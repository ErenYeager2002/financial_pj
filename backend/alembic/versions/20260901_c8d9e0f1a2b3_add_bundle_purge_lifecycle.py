"""add fetched bundle purge lifecycle

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-09-01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic recreates the table automatically on SQLite for constraint
    # changes, while PostgreSQL must alter it in place because three foreign
    # keys depend on the primary key.
    with op.batch_alter_table("fetched_bundles") as batch_op:
        batch_op.add_column(
            sa.Column("purge_attempts", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(sa.Column("purge_retry_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.drop_constraint("ck_fetched_bundles_state", type_="check")
        batch_op.create_check_constraint(
            "ck_fetched_bundles_state",
            "state IN ('creating', 'ready_for_review', 'confirmed', 'consumed', "
            "'purge_pending', 'raw_purged', 'invalid')",
        )
        batch_op.create_check_constraint(
            "ck_fetched_bundles_purge_attempts",
            "purge_attempts >= 0",
        )


def downgrade() -> None:
    op.execute(
        "UPDATE fetched_bundles SET state = 'invalid' "
        "WHERE state = 'purge_pending'"
    )
    with op.batch_alter_table("fetched_bundles") as batch_op:
        batch_op.drop_constraint("ck_fetched_bundles_purge_attempts", type_="check")
        batch_op.drop_constraint("ck_fetched_bundles_state", type_="check")
        batch_op.create_check_constraint(
            "ck_fetched_bundles_state",
            "state IN ('creating', 'ready_for_review', 'confirmed', 'consumed', "
            "'raw_purged', 'invalid')",
        )
        batch_op.drop_column("purge_retry_at")
        batch_op.drop_column("purge_attempts")
