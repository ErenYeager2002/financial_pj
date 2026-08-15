"""allow model traces before a run or draft exists

Revision ID: c5d9f3a8201b
Revises: b4c8e2f7190a
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c5d9f3a8201b"
down_revision = "b4c8e2f7190a"
branch_labels = None
depends_on = None


_SQLITE_INSERT_TRIGGER = """
CREATE TRIGGER trg_model_trace_records_scope_insert
BEFORE INSERT ON model_trace_records
FOR EACH ROW
WHEN
    (NEW.run_id IS NOT NULL AND NEW.task_draft_id IS NOT NULL) OR
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

_SQLITE_STRICT_INSERT_TRIGGER = _SQLITE_INSERT_TRIGGER.replace(
    "    (NEW.run_id IS NOT NULL AND NEW.task_draft_id IS NOT NULL) OR\n",
    "    NOT (\n"
    "        (NEW.run_id IS NOT NULL AND NEW.task_draft_id IS NULL) OR\n"
    "        (NEW.run_id IS NULL AND NEW.task_draft_id IS NOT NULL)\n"
    "    ) OR\n",
)
_SQLITE_STRICT_UPDATE_TRIGGER = _SQLITE_STRICT_INSERT_TRIGGER.replace(
    "trg_model_trace_records_scope_insert\nBEFORE INSERT",
    "trg_model_trace_records_scope_update\nBEFORE UPDATE",
)


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_model_trace_records_scope_update"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_model_trace_records_scope_insert"))
        op.execute(sa.text(_SQLITE_INSERT_TRIGGER))
        op.execute(sa.text(_SQLITE_UPDATE_TRIGGER))
        return

    op.drop_constraint(
        "ck_model_trace_records_single_parent",
        "model_trace_records",
        type_="check",
    )
    op.create_check_constraint(
        "ck_model_trace_records_at_most_one_parent",
        "model_trace_records",
        "NOT (run_id IS NOT NULL AND task_draft_id IS NOT NULL)",
    )


def downgrade() -> None:
    # b4 的旧约束不允许无父级记录；回退时移除仅由本版本支持的调用摘要。
    op.execute(
        sa.text(
            "DELETE FROM model_trace_records "
            "WHERE run_id IS NULL AND task_draft_id IS NULL"
        )
    )
    if op.get_bind().dialect.name == "sqlite":
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_model_trace_records_scope_update"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_model_trace_records_scope_insert"))
        op.execute(sa.text(_SQLITE_STRICT_INSERT_TRIGGER))
        op.execute(sa.text(_SQLITE_STRICT_UPDATE_TRIGGER))
        return

    op.drop_constraint(
        "ck_model_trace_records_at_most_one_parent",
        "model_trace_records",
        type_="check",
    )
    op.create_check_constraint(
        "ck_model_trace_records_single_parent",
        "model_trace_records",
        "(run_id IS NOT NULL AND task_draft_id IS NULL) OR "
        "(run_id IS NULL AND task_draft_id IS NOT NULL)",
    )
