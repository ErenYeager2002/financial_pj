"""add user-facing workflow display ids

Revision ID: 8e31b7c4d2a9
Revises: 71d4e9c2a5f0
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from alembic import op

revision = "8e31b7c4d2a9"
down_revision = "71d4e9c2a5f0"
branch_labels = None
depends_on = None

LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _backfill() -> None:
    connection = op.get_bind()
    rows: list[tuple[datetime, str, str, str]] = []
    for table in ("workflow_batches", "workflow_sessions"):
        statement = sa.text(f"SELECT id, skill_id, created_at FROM {table}")
        for item in connection.execute(statement).mappings():
            rows.append((_as_datetime(item["created_at"]), table, item["id"], item["skill_id"]))
    counters: dict[tuple[str, str], int] = defaultdict(int)
    for created_at, table, row_id, skill_id in sorted(rows, key=lambda item: (item[0], item[2])):
        local = created_at.astimezone(LOCAL_TIMEZONE)
        day_key = local.strftime("%Y-%m-%d")
        counters[(skill_id, day_key)] += 1
        display_id = f"{skill_id}_{local.month}.{local.day}_{counters[(skill_id, day_key)]}"
        connection.execute(
            sa.text(f"UPDATE {table} SET display_id = :display_id WHERE id = :id"),
            {"display_id": display_id, "id": row_id},
        )


def upgrade() -> None:
    with op.batch_alter_table("workflow_batches") as batch:
        batch.add_column(sa.Column("display_id", sa.String(length=192), nullable=True))
    with op.batch_alter_table("workflow_sessions") as batch:
        batch.add_column(sa.Column("display_id", sa.String(length=192), nullable=True))

    _backfill()

    with op.batch_alter_table("workflow_batches") as batch:
        batch.create_index("ux_workflow_batches_display_id", ["display_id"], unique=True)
    with op.batch_alter_table("workflow_sessions") as batch:
        batch.create_index("ux_workflow_sessions_display_id", ["display_id"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("workflow_sessions") as batch:
        batch.drop_index("ux_workflow_sessions_display_id")
        batch.drop_column("display_id")
    with op.batch_alter_table("workflow_batches") as batch:
        batch.drop_index("ux_workflow_batches_display_id")
        batch.drop_column("display_id")
