"""add skill dedicated users

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "a6b7c8d9e0f1"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_dedicated_users",
        sa.Column("department_id", sa.String(128), nullable=False),
        sa.Column("skill_id", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("department_id", "skill_id"),
        sa.UniqueConstraint(
            "department_id",
            "skill_id",
            name="uq_skill_dedicated_users_department_skill",
        ),
    )
    op.create_index(
        "ix_skill_dedicated_users_department_user",
        "skill_dedicated_users",
        ["department_id", "user_id"],
        unique=False,
    )
    op.create_index(
        "ix_skill_dedicated_users_user_id",
        "skill_dedicated_users",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_skill_dedicated_users_user_id", table_name="skill_dedicated_users")
    op.drop_index(
        "ix_skill_dedicated_users_department_user",
        table_name="skill_dedicated_users",
    )
    op.drop_table("skill_dedicated_users")
