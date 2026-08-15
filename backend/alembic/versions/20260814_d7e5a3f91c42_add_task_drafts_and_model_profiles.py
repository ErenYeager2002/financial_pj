"""add task drafts and model profiles

Revision ID: d7e5a3f91c42
Revises: b1a76f93c2de
Create Date: 2026-08-14 15:00:00+08:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7e5a3f91c42"
down_revision: str | None = "b1a76f93c2de"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("configured_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["configured_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["connection_id"], ["model_connections.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "department_id", "purpose", name="uq_model_profile_department_purpose"
        ),
    )
    for column in ("department_id", "purpose", "connection_id", "configured_by"):
        op.create_index(f"ix_model_profiles_{column}", "model_profiles", [column])

    op.create_table(
        "task_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.Column("skill_id", sa.String(length=128), nullable=False),
        sa.Column("skill_name", sa.String(length=255), nullable=False),
        sa.Column("skill_version", sa.String(length=64), nullable=False),
        sa.Column("skill_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("candidates_json", sa.Text(), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("files_json", sa.Text(), nullable=False),
        sa.Column("file_hashes_json", sa.Text(), nullable=False),
        sa.Column("missing_inputs_json", sa.Text(), nullable=False),
        sa.Column("validation_warnings_json", sa.Text(), nullable=False),
        sa.Column("clarification", sa.Text(), nullable=False),
        sa.Column("confirmation_text", sa.Text(), nullable=False),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    for column in ("owner_id", "department_id", "skill_id", "state", "expires_at"):
        op.create_index(f"ix_task_drafts_{column}", "task_drafts", [column])


def downgrade() -> None:
    op.drop_table("task_drafts")
    op.drop_table("model_profiles")
