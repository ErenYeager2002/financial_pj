"""Add durable scoped submission reservations and Native command identity.

Revision ID: f3a4b5c6d7e8
Revises: f2a3b4c5d6e7
"""
from alembic import op
import sqlalchemy as sa

revision = "f3a4b5c6d7e8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("task_drafts", sa.Column("content_revision", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "idempotency_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("department_id", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(200), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("canonical_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reservation_token", sa.String(36), nullable=False),
        sa.Column("reservation_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pinned_revision_json", sa.Text(), nullable=False),
        sa.Column("prepared_payload_json", sa.Text(), nullable=True),
        sa.Column("execution_kind", sa.String(32), nullable=True),
        sa.Column("execution_id", sa.String(128), nullable=True),
        sa.Column("response_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "department_id", "operation", "request_key", name="uq_idempotency_requests_scope_key"),
        sa.CheckConstraint("status IN ('preparing', 'prepared', 'bound', 'rejected')", name="ck_idempotency_requests_status"),
        sa.CheckConstraint("(status = 'bound' AND execution_kind IS NOT NULL AND execution_id IS NOT NULL) OR (status <> 'bound' AND execution_kind IS NULL AND execution_id IS NULL)", name="ck_idempotency_requests_binding"),
    )
    op.add_column("runs", sa.Column("source_session_key", sa.String(128), nullable=True))
    op.add_column("runs", sa.Column("source_command_id", sa.String(128), nullable=True))
    op.create_index("ix_runs_source_session_scope", "runs", ["owner_id", "department_id", "adapter", "source_session_key"])


def downgrade():
    raise RuntimeError("Forward-only: preserve submission bindings and Native command identities")
