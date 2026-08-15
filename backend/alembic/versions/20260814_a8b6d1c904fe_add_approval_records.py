"""add approval records and execution snapshot evidence

Revision ID: a8b6d1c904fe
Revises: f4a9c2e71b30
Create Date: 2026-08-14 17:00:00+08:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8b6d1c904fe"
down_revision: str | None = "f4a9c2e71b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("resource_type", sa.String(length=24), nullable=False),
        sa.Column("resource_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("workflow_id", sa.String(length=36), nullable=True),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.Column("skill_id", sa.String(length=128), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("preview_sha256", sa.String(length=64), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("preview_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("requested_by", sa.String(length=36), nullable=False),
        sa.Column("decided_by", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("execution_action_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "resource_type",
        "resource_id",
        "run_id",
        "workflow_id",
        "department_id",
        "skill_id",
        "status",
        "requested_by",
        "decided_by",
        "execution_action_id",
        "expires_at",
    ):
        op.create_index(f"ix_approval_records_{column}", "approval_records", [column])


def downgrade() -> None:
    op.drop_table("approval_records")
