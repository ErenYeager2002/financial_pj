"""add controlled skill releases

Revision ID: f4a9c2e71b30
Revises: d7e5a3f91c42
Create Date: 2026-08-14 16:00:00+08:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4a9c2e71b30"
down_revision: str | None = "d7e5a3f91c42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_releases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("package_path", sa.Text(), nullable=False),
        sa.Column("source_repository", sa.Text(), nullable=False),
        sa.Column("source_commit", sa.String(length=64), nullable=False),
        sa.Column("source_tree_hash", sa.String(length=64), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("validation_json", sa.Text(), nullable=False),
        sa.Column("test_json", sa.Text(), nullable=False),
        sa.Column("review_notes", sa.Text(), nullable=False),
        sa.Column("imported_by", sa.String(length=36), nullable=False),
        sa.Column("reviewed_by", sa.String(length=36), nullable=False),
        sa.Column("published_by", sa.String(length=36), nullable=False),
        sa.Column("published_skill_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["imported_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("package_sha256", name="uq_skill_releases_package_sha256"),
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_releases_skill_version"),
    )
    for column in (
        "skill_id",
        "version",
        "state",
        "source_commit",
        "imported_by",
        "reviewed_by",
        "published_by",
    ):
        op.create_index(f"ix_skill_releases_{column}", "skill_releases", [column])


def downgrade() -> None:
    op.drop_table("skill_releases")
