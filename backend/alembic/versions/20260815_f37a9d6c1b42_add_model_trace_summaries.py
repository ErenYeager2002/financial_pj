"""add model trace summaries

Revision ID: f37a9d6c1b42
Revises: e91b7c4a2d30
Create Date: 2026-08-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "f37a9d6c1b42"
down_revision = "e91b7c4a2d30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_trace_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("task_draft_id", sa.String(length=36), nullable=True),
        sa.Column("connection_id", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_code", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('succeeded', 'fallback', 'failed')",
            name="ck_model_trace_records_status",
        ),
        sa.CheckConstraint(
            "duration_ms >= 0 AND input_tokens >= 0 AND output_tokens >= 0",
            name="ck_model_trace_records_nonnegative_metrics",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.ForeignKeyConstraint(["task_draft_id"], ["task_drafts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_trace_records_owner_id", "model_trace_records", ["owner_id"]
    )
    op.create_index(
        "ix_model_trace_records_department_id", "model_trace_records", ["department_id"]
    )
    op.create_index(
        "ix_model_trace_records_run_id", "model_trace_records", ["run_id"]
    )
    op.create_index(
        "ix_model_trace_records_task_draft_id", "model_trace_records", ["task_draft_id"]
    )
    op.create_index(
        "ix_model_trace_records_connection_id", "model_trace_records", ["connection_id"]
    )
    op.create_index(
        "ix_model_trace_records_purpose", "model_trace_records", ["purpose"]
    )
    op.create_index(
        "ix_model_trace_records_provider", "model_trace_records", ["provider"]
    )
    op.create_index("ix_model_trace_records_model", "model_trace_records", ["model"])
    op.create_index("ix_model_trace_records_status", "model_trace_records", ["status"])
    op.create_index(
        "ix_model_trace_records_created_at", "model_trace_records", ["created_at"]
    )
    op.create_index(
        "ix_model_trace_records_department_created",
        "model_trace_records",
        ["department_id", "created_at"],
    )
    op.create_index(
        "ix_model_trace_records_provider_model",
        "model_trace_records",
        ["provider", "model"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_trace_records_provider_model", table_name="model_trace_records")
    op.drop_index(
        "ix_model_trace_records_department_created", table_name="model_trace_records"
    )
    op.drop_index("ix_model_trace_records_created_at", table_name="model_trace_records")
    op.drop_index("ix_model_trace_records_status", table_name="model_trace_records")
    op.drop_index("ix_model_trace_records_model", table_name="model_trace_records")
    op.drop_index("ix_model_trace_records_provider", table_name="model_trace_records")
    op.drop_index("ix_model_trace_records_purpose", table_name="model_trace_records")
    op.drop_index("ix_model_trace_records_connection_id", table_name="model_trace_records")
    op.drop_index("ix_model_trace_records_task_draft_id", table_name="model_trace_records")
    op.drop_index("ix_model_trace_records_run_id", table_name="model_trace_records")
    op.drop_index("ix_model_trace_records_department_id", table_name="model_trace_records")
    op.drop_index("ix_model_trace_records_owner_id", table_name="model_trace_records")
    op.drop_table("model_trace_records")
