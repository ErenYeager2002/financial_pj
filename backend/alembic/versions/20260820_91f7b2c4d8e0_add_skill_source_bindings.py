"""add skill source bindings

Revision ID: 91f7b2c4d8e0
Revises: 8e31b7c4d2a9
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "91f7b2c4d8e0"
down_revision = "8e31b7c4d2a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_source_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("repository_url", sa.Text(), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=False),
        sa.Column("tracking_ref", sa.String(length=255), nullable=False),
        sa.Column("binding_status", sa.String(length=32), nullable=False),
        sa.Column("packager_profile", sa.String(length=128), nullable=False),
        sa.Column("last_seen_commit", sa.String(length=64), nullable=False),
        sa.Column("last_seen_tree_hash", sa.String(length=64), nullable=False),
        sa.Column("published_commit", sa.String(length=64), nullable=False),
        sa.Column("published_tree_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("updated_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "binding_status IN ('candidate', 'bound', 'broken', 'excluded')",
            name="ck_skill_source_bindings_status",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id", name="uq_skill_source_bindings_skill_id"),
        sa.UniqueConstraint(
            "repository_url",
            "source_path",
            name="uq_skill_source_bindings_repository_path",
        ),
    )
    for column in (
        "skill_id",
        "binding_status",
        "last_seen_commit",
        "published_commit",
        "created_by",
        "updated_by",
    ):
        op.create_index(
            f"ix_skill_source_bindings_{column}", "skill_source_bindings", [column]
        )


def downgrade() -> None:
    op.drop_table("skill_source_bindings")
