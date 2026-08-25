"""add task discovery checks and reminders

Revision ID: c2d3e4f5a6b7
Revises: c1d2e3f4a5b6
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "c2d3e4f5a6b7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_discovery_checks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.Column("skill_id", sa.String(length=128), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("business_dates_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["subscription_id"], ["task_reminder_subscriptions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "subscription_id",
        "owner_id",
        "department_id",
        "skill_id",
        "state",
        "next_retry_at",
        "worker_id",
        "lease_expires_at",
    ):
        op.create_index(
            f"ix_task_discovery_checks_{column}",
            "task_discovery_checks",
            [column],
        )

    op.create_table(
        "task_reminders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.Column("skill_id", sa.String(length=128), nullable=False),
        sa.Column("business_date", sa.String(length=10), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=True),
        sa.Column("batch_id", sa.String(length=36), nullable=True),
        sa.Column("first_discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "department_id",
            "skill_id",
            "business_date",
            name="uq_task_reminders_department_skill_date",
        ),
    )
    for column in (
        "owner_id",
        "department_id",
        "skill_id",
        "business_date",
        "state",
        "workflow_id",
        "batch_id",
    ):
        op.create_index(f"ix_task_reminders_{column}", "task_reminders", [column])


def downgrade() -> None:
    op.drop_table("task_reminders")
    op.drop_table("task_discovery_checks")
