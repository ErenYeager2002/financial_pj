"""add task reminder subscriptions

Revision ID: c1d2e3f4a5b6
Revises: b7e3f9a1c5d2
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "b7e3f9a1c5d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_reminder_subscriptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.Column("skill_id", sa.String(length=128), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("schedule_time", sa.String(length=5), nullable=False),
        sa.Column("last_successful_business_date", sa.String(length=10), nullable=True),
        sa.Column("last_check_status", sa.String(length=32), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "department_id",
            "skill_id",
            name="uq_task_reminder_subscriptions_department_skill",
        ),
    )
    for column in ("department_id", "skill_id", "owner_id"):
        op.create_index(
            f"ix_task_reminder_subscriptions_{column}",
            "task_reminder_subscriptions",
            [column],
        )


def downgrade() -> None:
    op.drop_table("task_reminder_subscriptions")
