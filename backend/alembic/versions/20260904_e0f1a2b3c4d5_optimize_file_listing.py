"""optimize file center listing queries

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-09-04
"""

from __future__ import annotations

from alembic import op

revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_files_latest_lookup",
        "files",
        [
            "owner_id",
            "department_id",
            "kind",
            "skill_id",
            "original_name",
            "created_at",
            "id",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_files_latest_lookup", table_name="files")
