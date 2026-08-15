"""add audit events

Revision ID: c4d91f7b2e10
Revises: 8dd3d2f9a6c5
Create Date: 2026-08-13 20:30:00+08:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4d91f7b2e10"
down_revision: str | None = "8dd3d2f9a6c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("actor_role", sa.String(length=64), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "actor_id",
        "department_id",
        "action",
        "resource_type",
        "resource_id",
        "outcome",
        "created_at",
    ):
        op.create_index(f"ix_audit_events_{column}", "audit_events", [column])


def downgrade() -> None:
    op.drop_table("audit_events")
