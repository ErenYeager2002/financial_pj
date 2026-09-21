"""Add assistant turn persistence with validation of an existing deployed table.

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
"""
from alembic import context, op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None


def columns():
    return [
        sa.Column("owner_id", sa.String(128), primary_key=True),
        sa.Column("department_id", sa.String(128), primary_key=True),
        sa.Column("session_id", sa.String(128), primary_key=True),
        sa.Column("turn_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("partial_text", sa.Text(), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("stopped", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    offline = context.is_offline_mode()
    inspector = None if offline else sa.inspect(op.get_bind())
    exists = inspector is not None and inspector.has_table("assistant_turns")
    if exists:
        current = {column["name"]: column for column in inspector.get_columns("assistant_turns")}
        for expected in columns():
            actual = current.get(expected.name)
            if actual is None or actual["nullable"] != expected.nullable:
                raise RuntimeError("ASSISTANT_TURNS_EXISTING_SCHEMA_INCOMPATIBLE")
            if actual["type"]._type_affinity is not expected.type._type_affinity:
                raise RuntimeError("ASSISTANT_TURNS_EXISTING_TYPE_INCOMPATIBLE")
            if isinstance(expected.type, sa.String) and expected.type.length is not None and getattr(actual["type"], "length", None) != expected.type.length:
                raise RuntimeError("ASSISTANT_TURNS_EXISTING_LENGTH_INCOMPATIBLE")
            if op.get_bind().dialect.name == "postgresql" and isinstance(expected.type, sa.DateTime):
                if actual["type"].timezone != expected.type.timezone:
                    raise RuntimeError("ASSISTANT_TURNS_EXISTING_TIMEZONE_INCOMPATIBLE")
        if inspector.get_pk_constraint("assistant_turns")["constrained_columns"] != ["owner_id", "department_id", "session_id"]:
            raise RuntimeError("ASSISTANT_TURNS_EXISTING_PRIMARY_KEY_INCOMPATIBLE")
    else:
        op.create_table("assistant_turns", *columns())
    indices = inspector.get_indexes("assistant_turns") if exists else []
    present = next((item for item in indices if item["name"] == "ix_assistant_turns_state"), None)
    if present is not None:
        if present["column_names"] != ["state"] or present["unique"]:
            raise RuntimeError("ASSISTANT_TURNS_EXISTING_INDEX_INCOMPATIBLE")
    else:
        op.create_index("ix_assistant_turns_state", "assistant_turns", ["state"])


def downgrade():
    raise RuntimeError("Forward-only expansion: roll back application code, preserve assistant turn data")
