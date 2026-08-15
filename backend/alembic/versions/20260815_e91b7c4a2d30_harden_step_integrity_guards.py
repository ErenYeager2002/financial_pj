"""harden step integrity guards

Revision ID: e91b7c4a2d30
Revises: c82f4e719ab3
Create Date: 2026-08-15 14:30:00+08:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e91b7c4a2d30"
down_revision: str | None = "c82f4e719ab3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ensure_scope_constraints() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_indexes = {item["name"] for item in inspector.get_indexes("users")}
    if "ux_users_id_department" not in user_indexes:
        op.create_index(
            "ux_users_id_department",
            "users",
            ["id", "department_id"],
            unique=True,
        )

    workflow_fks = inspector.get_foreign_keys("workflow_definitions")
    has_creator_scope = any(
        item.get("constrained_columns") == ["created_by", "department_id"]
        and item.get("referred_table") == "users"
        for item in workflow_fks
    )
    if not has_creator_scope:
        with op.batch_alter_table("workflow_definitions") as batch:
            batch.create_foreign_key(
                "fk_workflow_definitions_creator_department",
                "users",
                ["created_by", "department_id"],
                ["id", "department_id"],
            )


def _sqlite_guards() -> None:
    for table_name in ("artifact_bindings", "approval_bindings"):
        for trigger_name in (
            f"trg_{table_name}_immutable",
            f"trg_{table_name}_immutable_update",
            f"trg_{table_name}_immutable_delete",
            f"trg_{table_name}_immutable_replace",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
    immutable_keys = {
        "artifact_bindings": (
            "id = NEW.id OR (step_run_id = NEW.step_run_id AND "
            "file_id = NEW.file_id AND direction = NEW.direction AND role = NEW.role)"
        ),
        "approval_bindings": "id = NEW.id OR approval_record_id = NEW.approval_record_id",
    }
    for table_name, duplicate_key in immutable_keys.items():
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_immutable_{action.lower()}
                BEFORE {action} ON {table_name}
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} rows are immutable after insert');
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
    for suffix in ("insert", "update"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_step_runs_retry_requires_idempotence_{suffix}"
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


def _postgres_guards() -> None:
    for table_name in ("artifact_bindings", "approval_bindings"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}")
    op.execute("DROP FUNCTION IF EXISTS p3_02_reject_binding_update()")
    op.execute("DROP FUNCTION IF EXISTS p3_02_reject_binding_mutation()")
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
        "DROP TRIGGER IF EXISTS trg_step_runs_retry_requires_idempotence ON step_runs"
    )
    op.execute("DROP FUNCTION IF EXISTS p3_02_validate_step_run_retry()")
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


def upgrade() -> None:
    _ensure_scope_constraints()
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_guards()
    elif op.get_bind().dialect.name == "postgresql":
        _postgres_guards()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table_name in ("artifact_bindings", "approval_bindings"):
            for suffix in ("update", "delete", "replace"):
                op.execute(
                    f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable_{suffix}"
                )
        for suffix in ("insert", "update"):
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_step_runs_retry_requires_idempotence_{suffix}"
            )
    elif dialect == "postgresql":
        for table_name in ("artifact_bindings", "approval_bindings"):
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}"
            )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_step_runs_retry_requires_idempotence ON step_runs"
        )
        op.execute("DROP FUNCTION IF EXISTS p3_02_validate_step_run_retry()")
        op.execute("DROP FUNCTION IF EXISTS p3_02_reject_binding_mutation()")
