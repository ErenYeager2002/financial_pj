"""add must_change_password

Revision ID: 8dd3d2f9a6c5
Revises: a2b6880a030c
Create Date: 2026-08-13 14:17:46.999700+08:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8dd3d2f9a6c5"
down_revision: str | None = "a2b6880a030c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
