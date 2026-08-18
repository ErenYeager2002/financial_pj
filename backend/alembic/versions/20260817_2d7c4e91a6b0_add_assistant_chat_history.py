"""persist AI assistant conversation history

Revision ID: 2d7c4e91a6b0
Revises: 8f21a6d4c901
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "2d7c4e91a6b0"
down_revision = "8f21a6d4c901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_assistant_messages_role",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assistant_messages_session_id", "assistant_messages", ["session_id"])
    op.create_index("ix_assistant_messages_owner_id", "assistant_messages", ["owner_id"])
    op.create_index(
        "ix_assistant_messages_department_id",
        "assistant_messages",
        ["department_id"],
    )
    op.create_index(
        "ix_assistant_messages_owner_session_created",
        "assistant_messages",
        ["owner_id", "session_id", "created_at"],
    )
    op.create_index(
        "ix_assistant_messages_department_created",
        "assistant_messages",
        ["department_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_messages_department_created", table_name="assistant_messages")
    op.drop_index("ix_assistant_messages_owner_session_created", table_name="assistant_messages")
    op.drop_index("ix_assistant_messages_department_id", table_name="assistant_messages")
    op.drop_index("ix_assistant_messages_owner_id", table_name="assistant_messages")
    op.drop_index("ix_assistant_messages_session_id", table_name="assistant_messages")
    op.drop_table("assistant_messages")
