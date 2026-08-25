"""add skill availability

Revision ID: a4c8d2e6f1b9
Revises: 91f7b2c4d8e0
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "a4c8d2e6f1b9"
down_revision = "91f7b2c4d8e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_availability",
        sa.Column("skill_id", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.String(length=36), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('enabled', 'draining', 'disabled', 'failed_disabled')",
            name="ck_skill_availability_state",
        ),
        sa.PrimaryKeyConstraint("skill_id"),
    )
    op.create_index("ix_skill_availability_state", "skill_availability", ["state"])
    op.create_index(
        "ix_skill_availability_changed_by", "skill_availability", ["changed_by"]
    )


def downgrade() -> None:
    op.drop_table("skill_availability")
