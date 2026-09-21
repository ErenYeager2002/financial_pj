"""Move historical SQLite runtime column repair into a versioned migration.

Revision ID: f2a3b4c5d6e7
Revises: f1a2b3c4d5e6
"""
from alembic import context, op
import sqlalchemy as sa

revision = "f2a3b4c5d6e7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def definitions():
    def integer(name, default):
        return sa.Column(name, sa.Integer(), nullable=False, server_default=sa.text(str(default)))
    def string(name, length, default=""):
        return sa.Column(name, sa.String(length), nullable=False, server_default=sa.text("'" + default + "'"))
    def lease_columns():
        return [string("worker_id", 128), integer("attempt_count", 0),
                sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
                sa.Column("lease_expires_at", sa.DateTime(timezone=True))]
    return {
        "runs": [integer("concurrency_limit", 1), *lease_columns()],
        "workflow_sessions": [integer("concurrency_limit", 1), string("execution_mode", 32, "workflow"),
                              sa.Column("batch_id", sa.String(36)), integer("batch_sequence", 0),
                              string("previous_workflow_id", 36)],
        "workflow_batches": [string("execution_mode", 32, "workflow")],
        "workflow_actions": lease_columns(),
    }


def upgrade():
    if context.is_offline_mode():
        if context.get_context().dialect.name == "sqlite":
            raise RuntimeError("SQLITE_LEGACY_COLUMN_REPAIR_REQUIRES_ONLINE_INSPECTION")
        # PostgreSQL baseline already declares all columns; no repair DDL there.
        return
    inspector = sa.inspect(op.get_bind())
    expected = definitions()
    if not set(expected).issubset(inspector.get_table_names()):
        raise RuntimeError("RUNTIME_COLUMN_REPAIR_REQUIRED_TABLE_MISSING")
    missing = [(table, column) for table, columns in expected.items()
               for column in columns if column.name not in {c["name"] for c in inspector.get_columns(table)}]
    if missing and op.get_bind().dialect.name != "sqlite":
        raise RuntimeError("NON_SQLITE_RUNTIME_SCHEMA_INCOMPLETE")
    for table, column in missing:
        op.add_column(table, column)


def downgrade():
    raise RuntimeError("Forward-only repair: preserve runtime columns and application data")
