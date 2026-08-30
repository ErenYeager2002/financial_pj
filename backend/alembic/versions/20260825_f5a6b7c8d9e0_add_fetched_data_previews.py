"""add fetched data previews

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_fetched_data_previews",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("reconciliation_date", sa.String(10), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_id",
            "reconciliation_date",
            "revision",
            name="ux_workflow_fetched_data_previews_revision",
        ),
    )
    op.create_index(
        "ix_workflow_fetched_data_previews_workflow_id",
        "workflow_fetched_data_previews",
        ["workflow_id"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_fetched_data_previews_reconciliation_date",
        "workflow_fetched_data_previews",
        ["reconciliation_date"],
        unique=False,
    )
    op.create_table(
        "workflow_fetched_data_preview_ar_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("preview_id", sa.String(36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("ar_id", sa.String(255), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("has_issues", sa.Boolean(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["preview_id"], ["workflow_fetched_data_previews.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "preview_id",
            "position",
            name="ux_workflow_fetched_data_preview_ar_group_position",
        ),
    )
    op.create_index(
        "ix_workflow_fetched_data_preview_ar_groups_preview_id",
        "workflow_fetched_data_preview_ar_groups",
        ["preview_id"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_fetched_data_preview_ar_groups_ar_id",
        "workflow_fetched_data_preview_ar_groups",
        ["ar_id"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_fetched_data_preview_ar_groups_has_issues",
        "workflow_fetched_data_preview_ar_groups",
        ["has_issues"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_fetched_data_preview_ar_groups_query",
        "workflow_fetched_data_preview_ar_groups",
        ["preview_id", "has_issues", "position"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_fetched_data_preview_ar_groups_query",
        table_name="workflow_fetched_data_preview_ar_groups",
    )
    op.drop_index(
        "ix_workflow_fetched_data_preview_ar_groups_has_issues",
        table_name="workflow_fetched_data_preview_ar_groups",
    )
    op.drop_index(
        "ix_workflow_fetched_data_preview_ar_groups_ar_id",
        table_name="workflow_fetched_data_preview_ar_groups",
    )
    op.drop_index(
        "ix_workflow_fetched_data_preview_ar_groups_preview_id",
        table_name="workflow_fetched_data_preview_ar_groups",
    )
    op.drop_table("workflow_fetched_data_preview_ar_groups")
    op.drop_index(
        "ix_workflow_fetched_data_previews_reconciliation_date",
        table_name="workflow_fetched_data_previews",
    )
    op.drop_index(
        "ix_workflow_fetched_data_previews_workflow_id",
        table_name="workflow_fetched_data_previews",
    )
    op.drop_table("workflow_fetched_data_previews")
