"""harden model trace scope

Revision ID: b4c8e2f7190a
Revises: f37a9d6c1b42
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b4c8e2f7190a"
down_revision = "f37a9d6c1b42"
branch_labels = None
depends_on = None


_SQLITE_INSERT_TRIGGER = """
CREATE TRIGGER trg_model_trace_records_scope_insert
BEFORE INSERT ON model_trace_records
FOR EACH ROW
WHEN
    NOT (
        (NEW.run_id IS NOT NULL AND NEW.task_draft_id IS NULL) OR
        (NEW.run_id IS NULL AND NEW.task_draft_id IS NOT NULL)
    ) OR
    (
        NEW.run_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM runs
            WHERE id = NEW.run_id
              AND owner_id = NEW.owner_id
              AND department_id = NEW.department_id
        )
    ) OR
    (
        NEW.task_draft_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM task_drafts
            WHERE id = NEW.task_draft_id
              AND owner_id = NEW.owner_id
              AND department_id = NEW.department_id
        )
    )
BEGIN
    SELECT RAISE(ABORT, 'model trace scope mismatch');
END
"""

_SQLITE_UPDATE_TRIGGER = _SQLITE_INSERT_TRIGGER.replace(
    "trg_model_trace_records_scope_insert\nBEFORE INSERT",
    "trg_model_trace_records_scope_update\nBEFORE UPDATE",
)


def upgrade() -> None:
    op.create_index(
        "ux_task_drafts_id_owner_department",
        "task_drafts",
        ["id", "owner_id", "department_id"],
        unique=True,
    )
    if op.get_bind().dialect.name == "sqlite":
        op.execute(sa.text(_SQLITE_INSERT_TRIGGER))
        op.execute(sa.text(_SQLITE_UPDATE_TRIGGER))
        return

    op.execute(
        sa.text(
            "ALTER TABLE model_trace_records "
            "DROP CONSTRAINT IF EXISTS model_trace_records_run_id_fkey"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE model_trace_records "
            "DROP CONSTRAINT IF EXISTS model_trace_records_task_draft_id_fkey"
        )
    )
    op.create_check_constraint(
        "ck_model_trace_records_single_parent",
        "model_trace_records",
        "(run_id IS NOT NULL AND task_draft_id IS NULL) OR "
        "(run_id IS NULL AND task_draft_id IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_model_trace_records_run_scope",
        "model_trace_records",
        "runs",
        ["run_id", "owner_id", "department_id"],
        ["id", "owner_id", "department_id"],
    )
    op.create_foreign_key(
        "fk_model_trace_records_draft_scope",
        "model_trace_records",
        "task_drafts",
        ["task_draft_id", "owner_id", "department_id"],
        ["id", "owner_id", "department_id"],
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_model_trace_records_scope_update"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_model_trace_records_scope_insert"))
    else:
        op.drop_constraint(
            "fk_model_trace_records_draft_scope",
            "model_trace_records",
            type_="foreignkey",
        )
        op.drop_constraint(
            "fk_model_trace_records_run_scope",
            "model_trace_records",
            type_="foreignkey",
        )
        op.drop_constraint(
            "ck_model_trace_records_single_parent",
            "model_trace_records",
            type_="check",
        )
        op.create_foreign_key(
            "model_trace_records_run_id_fkey",
            "model_trace_records",
            "runs",
            ["run_id"],
            ["id"],
        )
        op.create_foreign_key(
            "model_trace_records_task_draft_id_fkey",
            "model_trace_records",
            "task_drafts",
            ["task_draft_id"],
            ["id"],
        )
    op.drop_index("ux_task_drafts_id_owner_department", table_name="task_drafts")
