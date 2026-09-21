"""Store original ordinary-task execution intent without rewriting legacy rows."""
from alembic import op
import sqlalchemy as sa
revision = "f4b5c6d7e8f9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("run_execution_snapshots",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    raise RuntimeError("Forward-only: preserve original execution confirmation evidence")
