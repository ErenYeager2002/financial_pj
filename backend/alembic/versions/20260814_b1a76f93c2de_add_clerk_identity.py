"""add Clerk identity mapping

Revision ID: b1a76f93c2de
Revises: c4d91f7b2e10
Create Date: 2026-08-14 10:00:00+08:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1a76f93c2de"
down_revision: str | None = "c4d91f7b2e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("clerk_user_id", sa.String(length=128), nullable=True))
    op.add_column(
        "users",
        sa.Column("clerk_organization_id", sa.String(length=128), nullable=True),
    )
    op.create_index("ix_users_clerk_user_id", "users", ["clerk_user_id"], unique=True)
    op.create_index(
        "ix_users_clerk_organization_id",
        "users",
        ["clerk_organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_users_clerk_organization_id", table_name="users")
    op.drop_index("ix_users_clerk_user_id", table_name="users")
    op.drop_column("users", "clerk_organization_id")
    op.drop_column("users", "clerk_user_id")
