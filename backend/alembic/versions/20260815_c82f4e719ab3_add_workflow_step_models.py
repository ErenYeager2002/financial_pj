"""add versioned workflow definitions and step execution records

Revision ID: c82f4e719ab3
Revises: a8b6d1c904fe
Create Date: 2026-08-15 12:00:00+08:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c82f4e719ab3"
down_revision: str | None = "a8b6d1c904fe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_integrity_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        immutable_keys = {
            "artifact_bindings": (
                "id = NEW.id OR (step_run_id = NEW.step_run_id AND "
                "file_id = NEW.file_id AND direction = NEW.direction AND role = NEW.role)"
            ),
            "approval_bindings": "id = NEW.id OR approval_record_id = NEW.approval_record_id",
        }
        for table_name, duplicate_key in immutable_keys.items():
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_immutable_update
                BEFORE UPDATE ON {table_name}
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} rows are immutable after insert');
                END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_immutable_delete
                BEFORE DELETE ON {table_name}
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} rows cannot be deleted');
                END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_immutable_replace
                BEFORE INSERT ON {table_name}
                FOR EACH ROW WHEN EXISTS (
                    SELECT 1 FROM {table_name} WHERE {duplicate_key}
                )
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} rows cannot be replaced');
                END
                """
            )
        op.execute(
            """
            CREATE TRIGGER trg_step_runs_retry_requires_idempotence_insert
            BEFORE INSERT ON step_runs
            FOR EACH ROW WHEN NEW.can_retry = 1 AND NOT EXISTS (
                SELECT 1 FROM step_definitions
                WHERE id = NEW.step_definition_id AND is_idempotent = 1 AND retryable = 1
            )
            BEGIN
                SELECT RAISE(ABORT, 'only explicitly idempotent steps can be retried');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_step_runs_retry_requires_idempotence_update
            BEFORE UPDATE OF can_retry, step_definition_id ON step_runs
            FOR EACH ROW WHEN NEW.can_retry = 1 AND NOT EXISTS (
                SELECT 1 FROM step_definitions
                WHERE id = NEW.step_definition_id AND is_idempotent = 1 AND retryable = 1
            )
            BEGIN
                SELECT RAISE(ABORT, 'only explicitly idempotent steps can be retried');
            END
            """
        )
        return
    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION p3_02_reject_binding_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '% rows are immutable after insert', TG_TABLE_NAME
                    USING ERRCODE = '23000';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table_name in ("artifact_bindings", "approval_bindings"):
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_immutable
                BEFORE UPDATE OR DELETE ON {table_name}
                FOR EACH ROW EXECUTE FUNCTION p3_02_reject_binding_mutation()
                """
            )
        op.execute(
            """
            CREATE FUNCTION p3_02_validate_step_run_retry() RETURNS trigger AS $$
            BEGIN
                IF NEW.can_retry AND NOT EXISTS (
                    SELECT 1 FROM step_definitions
                    WHERE id = NEW.step_definition_id AND is_idempotent AND retryable
                ) THEN
                    RAISE EXCEPTION 'only explicitly idempotent steps can be retried'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_step_runs_retry_requires_idempotence
            BEFORE INSERT OR UPDATE OF can_retry, step_definition_id ON step_runs
            FOR EACH ROW EXECUTE FUNCTION p3_02_validate_step_run_retry()
            """
        )


def _drop_integrity_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table_name in ("artifact_bindings", "approval_bindings"):
            for suffix in ("update", "delete", "replace"):
                op.execute(
                    f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable_{suffix}"
                )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_step_runs_retry_requires_idempotence_insert"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_step_runs_retry_requires_idempotence_update"
        )
        return
    if dialect == "postgresql":
        for table_name in ("artifact_bindings", "approval_bindings"):
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}"
            )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_step_runs_retry_requires_idempotence ON step_runs"
        )
        op.execute("DROP FUNCTION IF EXISTS p3_02_validate_step_run_retry()")
        op.execute("DROP FUNCTION IF EXISTS p3_02_reject_binding_mutation()")


def upgrade() -> None:
    op.create_index(
        "ux_users_id_department",
        "users",
        ["id", "department_id"],
        unique=True,
    )
    op.create_index(
        "ux_runs_id_owner_department",
        "runs",
        ["id", "owner_id", "department_id"],
        unique=True,
    )
    op.create_index(
        "ux_workflow_sessions_id_owner_department",
        "workflow_sessions",
        ["id", "owner_id", "department_id"],
        unique=True,
    )
    op.create_index(
        "ux_files_id_owner_department",
        "files",
        ["id", "owner_id", "department_id"],
        unique=True,
    )
    op.create_index(
        "ux_approval_records_id_requester_department",
        "approval_records",
        ["id", "requested_by", "department_id"],
        unique=True,
    )

    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.Column("workflow_key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("skill_id", sa.String(length=128), nullable=False),
        sa.Column("skill_version", sa.String(length=64), nullable=False),
        sa.Column("skill_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'disabled', 'superseded', 'archived')",
            name="ck_workflow_definitions_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by", "department_id"],
            ["users.id", "users.department_id"],
            name="fk_workflow_definitions_creator_department",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "department_id",
            "workflow_key",
            "version",
            name="uq_workflow_definitions_department_key_version",
        ),
    )
    for column in ("department_id", "workflow_key", "status", "skill_id", "created_by"):
        op.create_index(
            f"ix_workflow_definitions_{column}",
            "workflow_definitions",
            [column],
        )
    op.create_index(
        "ix_workflow_definitions_department_status",
        "workflow_definitions",
        ["department_id", "status"],
    )
    op.create_index(
        "ix_workflow_definitions_skill_version",
        "workflow_definitions",
        ["skill_id", "skill_version"],
    )
    op.create_index(
        "ux_workflow_definitions_id_department",
        "workflow_definitions",
        ["id", "department_id"],
        unique=True,
    )

    op.create_table(
        "step_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_definition_id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.Column("step_key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("step_type", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("input_schema_json", sa.Text(), nullable=False),
        sa.Column("output_schema_json", sa.Text(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("retry_backoff_seconds", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(length=24), nullable=False),
        sa.Column("worker_pool", sa.String(length=64), nullable=False),
        sa.Column("is_idempotent", sa.Boolean(), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "max_attempts > 0",
            name="ck_step_definitions_attempts_positive",
        ),
        sa.CheckConstraint(
            "is_idempotent OR (max_attempts = 1 AND NOT retryable)",
            name="ck_step_definitions_non_idempotent_no_retry",
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_step_definitions_position_nonnegative",
        ),
        sa.CheckConstraint(
            "timeout_seconds > 0",
            name="ck_step_definitions_timeout_positive",
        ),
        sa.CheckConstraint(
            "step_type IN ("
            "'parameter_validation', 'file_validation', 'read_only_http', 'python', 'rpa', "
            "'result_preview', 'human_confirmation', 'admin_approval', 'controlled_write', "
            "'post_write_verification', 'artifact_archive'"
            ")",
            name="ck_step_definitions_controlled_type",
        ),
        sa.CheckConstraint(
            "risk_level IN ('read_only', 'write', 'external_action')",
            name="ck_step_definitions_risk_level",
        ),
        sa.CheckConstraint(
            "worker_pool IN ('python', 'http', 'workflow')",
            name="ck_step_definitions_worker_pool",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_definition_id", "department_id"],
            ["workflow_definitions.id", "workflow_definitions.department_id"],
            name="fk_step_definitions_workflow_department",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_definition_id",
            "step_key",
            name="uq_step_definitions_workflow_key",
        ),
        sa.UniqueConstraint(
            "workflow_definition_id",
            "position",
            name="uq_step_definitions_workflow_position",
        ),
    )
    for column in (
        "workflow_definition_id",
        "department_id",
        "step_type",
        "risk_level",
        "worker_pool",
    ):
        op.create_index(f"ix_step_definitions_{column}", "step_definitions", [column])
    op.create_index(
        "ix_step_definitions_workflow_type",
        "step_definitions",
        ["workflow_definition_id", "step_type"],
    )
    op.create_index(
        "ux_step_definitions_id_department",
        "step_definitions",
        ["id", "department_id"],
        unique=True,
    )

    op.create_table(
        "step_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("step_definition_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("workflow_session_id", sa.String(length=36), nullable=True),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("input_summary_json", sa.Text(), nullable=False),
        sa.Column("output_summary_json", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("can_retry", sa.Boolean(), nullable=False),
        sa.Column("retry_block_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_step_runs_attempts_nonnegative",
        ),
        sa.CheckConstraint(
            "state IN ("
            "'pending', 'queued', 'running', 'waiting_confirmation', "
            "'waiting_approval', 'succeeded', 'failed', 'timed_out', "
            "'cancelled', 'skipped'"
            ")",
            name="ck_step_runs_state",
        ),
        sa.CheckConstraint(
            "(run_id IS NOT NULL AND workflow_session_id IS NULL) OR "
            "(run_id IS NULL AND workflow_session_id IS NOT NULL)",
            name="ck_step_runs_single_task_parent",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "owner_id", "department_id"],
            ["runs.id", "runs.owner_id", "runs.department_id"],
            name="fk_step_runs_run_scope",
        ),
        sa.ForeignKeyConstraint(
            ["step_definition_id", "department_id"],
            ["step_definitions.id", "step_definitions.department_id"],
            name="fk_step_runs_step_department",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_session_id", "owner_id", "department_id"],
            [
                "workflow_sessions.id",
                "workflow_sessions.owner_id",
                "workflow_sessions.department_id",
            ],
            name="fk_step_runs_workflow_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "step_definition_id", name="uq_step_runs_run_step"),
        sa.UniqueConstraint(
            "workflow_session_id",
            "step_definition_id",
            name="uq_step_runs_workflow_step",
        ),
    )
    for column in (
        "step_definition_id",
        "run_id",
        "workflow_session_id",
        "owner_id",
        "department_id",
        "state",
        "worker_id",
    ):
        op.create_index(f"ix_step_runs_{column}", "step_runs", [column])
    op.create_index("ix_step_runs_owner_state", "step_runs", ["owner_id", "state"])
    op.create_index(
        "ix_step_runs_department_state",
        "step_runs",
        ["department_id", "state"],
    )
    op.create_index(
        "ux_step_runs_id_owner_department",
        "step_runs",
        ["id", "owner_id", "department_id"],
        unique=True,
    )

    op.create_table(
        "artifact_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("step_run_id", sa.String(length=36), nullable=False),
        sa.Column("file_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "direction IN ('input', 'output')",
            name="ck_artifact_bindings_direction",
        ),
        sa.ForeignKeyConstraint(
            ["file_id", "owner_id", "department_id"],
            ["files.id", "files.owner_id", "files.department_id"],
            name="fk_artifact_bindings_file_scope",
        ),
        sa.ForeignKeyConstraint(
            ["step_run_id", "owner_id", "department_id"],
            ["step_runs.id", "step_runs.owner_id", "step_runs.department_id"],
            name="fk_artifact_bindings_step_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "step_run_id",
            "file_id",
            "direction",
            "role",
            name="uq_artifact_bindings_step_file_direction_role",
        ),
    )
    for column in (
        "step_run_id",
        "file_id",
        "owner_id",
        "department_id",
        "direction",
        "role",
        "sha256",
    ):
        op.create_index(f"ix_artifact_bindings_{column}", "artifact_bindings", [column])
    op.create_index(
        "ix_artifact_bindings_owner_direction",
        "artifact_bindings",
        ["owner_id", "direction"],
    )

    op.create_table(
        "approval_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("step_run_id", sa.String(length=36), nullable=False),
        sa.Column("approval_record_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["approval_record_id", "owner_id", "department_id"],
            [
                "approval_records.id",
                "approval_records.requested_by",
                "approval_records.department_id",
            ],
            name="fk_approval_bindings_approval_scope",
        ),
        sa.ForeignKeyConstraint(
            ["step_run_id", "owner_id", "department_id"],
            ["step_runs.id", "step_runs.owner_id", "step_runs.department_id"],
            name="fk_approval_bindings_step_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "approval_record_id",
            name="uq_approval_bindings_approval_record",
        ),
    )
    for column in (
        "step_run_id",
        "approval_record_id",
        "owner_id",
        "department_id",
        "snapshot_sha256",
    ):
        op.create_index(f"ix_approval_bindings_{column}", "approval_bindings", [column])
    op.create_index(
        "ix_approval_bindings_owner_step",
        "approval_bindings",
        ["owner_id", "step_run_id"],
    )
    _create_integrity_guards()


def downgrade() -> None:
    _drop_integrity_guards()
    op.drop_table("approval_bindings")
    op.drop_table("artifact_bindings")
    op.drop_table("step_runs")
    op.drop_table("step_definitions")
    op.drop_table("workflow_definitions")
    op.drop_index(
        "ux_approval_records_id_requester_department",
        table_name="approval_records",
    )
    op.drop_index("ux_files_id_owner_department", table_name="files")
    op.drop_index(
        "ux_workflow_sessions_id_owner_department",
        table_name="workflow_sessions",
    )
    op.drop_index("ux_runs_id_owner_department", table_name="runs")
    op.drop_index("ux_users_id_department", table_name="users")
