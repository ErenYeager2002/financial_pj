"""add skill rollouts

Revision ID: b7e3f9a1c5d2
Revises: a4c8d2e6f1b9
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b7e3f9a1c5d2"
down_revision = "a4c8d2e6f1b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_rollouts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("release_id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.String(length=36), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("previous_skill_hash", sa.String(length=64), nullable=False),
        sa.Column("target_commit", sa.String(length=64), nullable=False),
        sa.Column("target_tree_hash", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('queued', 'draining', 'activating', 'verifying', "
            "'succeeded', 'failed', 'failed_disabled')",
            name="ck_skill_rollouts_state",
        ),
        sa.ForeignKeyConstraint(["release_id"], ["skill_releases.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("release_id", name="uq_skill_rollouts_release_id"),
    )
    for column in ("release_id", "skill_id", "state", "requested_by"):
        op.create_index(f"ix_skill_rollouts_{column}", "skill_rollouts", [column])


def downgrade() -> None:
    op.drop_table("skill_rollouts")
