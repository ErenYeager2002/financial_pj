"""add platform feature controls

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_feature_controls",
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("changed_by", sa.String(36), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(
        "ix_platform_feature_controls_changed_by",
        "platform_feature_controls",
        ["changed_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_platform_feature_controls_changed_by",
        table_name="platform_feature_controls",
    )
    op.drop_table("platform_feature_controls")
