"""add Skill provenance to platform files

Revision ID: 8f21a6d4c901
Revises: c5d9f3a8201b
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "8f21a6d4c901"
down_revision = "c5d9f3a8201b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("skill_id", sa.String(length=128), nullable=False, server_default=""),
    )
    op.add_column(
        "files",
        sa.Column("skill_name", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "files",
        sa.Column("skill_version", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "files",
        sa.Column("workflow_id", sa.String(length=36), nullable=False, server_default=""),
    )
    op.create_index("ix_files_skill_id", "files", ["skill_id"], unique=False)
    op.create_index("ix_files_workflow_id", "files", ["workflow_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_files_workflow_id", table_name="files")
    op.drop_index("ix_files_skill_id", table_name="files")
    op.drop_column("files", "workflow_id")
    op.drop_column("files", "skill_version")
    op.drop_column("files", "skill_name")
    op.drop_column("files", "skill_id")
