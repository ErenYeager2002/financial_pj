"""add workflow execution modes

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("workflow_batches", "workflow_sessions"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "execution_mode",
                    sa.String(length=32),
                    server_default="workflow",
                    nullable=False,
                )
            )
            batch.create_index(
                f"ix_{table}_execution_mode",
                ["execution_mode"],
                unique=False,
            )
            batch.create_check_constraint(
                f"ck_{table}_execution_mode",
                "execution_mode IN ('workflow', 'pi_harness')",
            )


def downgrade() -> None:
    for table in ("workflow_sessions", "workflow_batches"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"ck_{table}_execution_mode", type_="check")
            batch.drop_index(f"ix_{table}_execution_mode")
            batch.drop_column("execution_mode")
