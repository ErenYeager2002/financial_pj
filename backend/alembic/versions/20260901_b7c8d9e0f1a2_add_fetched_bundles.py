"""add fetched bundles

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-09-01
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "b7c8d9e0f1a2"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def _backfill_historical_previews() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT
                workflow.id AS workflow_id,
                workflow.owner_id AS owner_id,
                workflow.department_id AS department_id,
                workflow.skill_id AS skill_id,
                workflow.batch_id AS batch_id,
                workflow.context_json AS context_json,
                MIN(preview.reconciliation_date) AS date_from,
                MAX(preview.reconciliation_date) AS date_to,
                MIN(preview.created_at) AS created_at
            FROM workflow_sessions AS workflow
            JOIN workflow_fetched_data_previews AS preview
              ON preview.workflow_id = workflow.id
            GROUP BY
                workflow.id,
                workflow.owner_id,
                workflow.department_id,
                workflow.skill_id,
                workflow.batch_id,
                workflow.context_json
            """
        )
    ).mappings()
    for row in rows:
        dates = list(
            connection.execute(
                sa.text(
                    """
                    SELECT DISTINCT reconciliation_date
                    FROM workflow_fetched_data_previews
                    WHERE workflow_id = :workflow_id
                    ORDER BY reconciliation_date
                    """
                ),
                {"workflow_id": row["workflow_id"]},
            ).scalars()
        )
        context: object
        try:
            context = json.loads(row["context_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            context = {}
        fetched_data = context.get("fetched_data", {}) if isinstance(context, dict) else {}
        source_type = (
            "replay"
            if isinstance(fetched_data, dict) and fetched_data.get("source") == "snapshot"
            else "live"
        )
        bundle_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"financial-pj:fetched-bundle:{row['workflow_id']}",
            )
        )
        created_at = row["created_at"] or datetime.now(UTC)
        dates_json = json.dumps(dates, ensure_ascii=False, separators=(",", ":"))
        connection.execute(
            sa.text(
                """
                INSERT INTO fetched_bundles (
                    id, owner_id, department_id, skill_id,
                    source_workflow_id, source_batch_id, source_type,
                    manifest_version, state, date_from, date_to, dates_json,
                    storage_key, raw_available, preview_available, replayable,
                    created_at, confirmed_at, consumed_at, purged_at,
                    retention_until, last_error
                ) VALUES (
                    :id, :owner_id, :department_id, :skill_id,
                    :source_workflow_id, :source_batch_id, :source_type,
                    :manifest_version, :state, :date_from, :date_to, :dates_json,
                    :storage_key, :raw_available, :preview_available, :replayable,
                    :created_at, :confirmed_at, :consumed_at, :purged_at,
                    :retention_until, :last_error
                )
                """
            ),
            {
                "id": bundle_id,
                "owner_id": row["owner_id"],
                "department_id": row["department_id"],
                "skill_id": row["skill_id"],
                "source_workflow_id": row["workflow_id"],
                "source_batch_id": row["batch_id"],
                "source_type": source_type,
                "manifest_version": "legacy-preview-v1",
                "state": "raw_purged",
                "date_from": row["date_from"],
                "date_to": row["date_to"],
                "dates_json": dates_json,
                "storage_key": "",
                "raw_available": False,
                "preview_available": True,
                "replayable": False,
                "created_at": created_at,
                "confirmed_at": created_at,
                "consumed_at": created_at,
                "purged_at": created_at,
                "retention_until": None,
                "last_error": "",
            },
        )
        connection.execute(
            sa.text(
                "UPDATE workflow_fetched_data_previews "
                "SET bundle_id = :bundle_id WHERE workflow_id = :workflow_id"
            ),
            {"bundle_id": bundle_id, "workflow_id": row["workflow_id"]},
        )
        connection.execute(
            sa.text(
                "UPDATE workflow_sessions SET fetched_bundle_id = :bundle_id "
                "WHERE id = :workflow_id"
            ),
            {"bundle_id": bundle_id, "workflow_id": row["workflow_id"]},
        )


def upgrade() -> None:
    op.create_table(
        "fetched_bundles",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("department_id", sa.String(128), nullable=False),
        sa.Column("skill_id", sa.String(128), nullable=False),
        sa.Column("source_workflow_id", sa.String(36), nullable=False),
        sa.Column("source_batch_id", sa.String(36), nullable=True),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("manifest_version", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("date_from", sa.String(10), nullable=False),
        sa.Column("date_to", sa.String(10), nullable=False),
        sa.Column("dates_json", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("raw_available", sa.Boolean(), nullable=False),
        sa.Column("preview_available", sa.Boolean(), nullable=False),
        sa.Column("replayable", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('live', 'replay')",
            name="ck_fetched_bundles_source_type",
        ),
        sa.CheckConstraint(
            "state IN ('creating', 'ready_for_review', 'confirmed', 'consumed', "
            "'raw_purged', 'invalid')",
            name="ck_fetched_bundles_state",
        ),
        sa.CheckConstraint(
            "raw_available OR NOT replayable",
            name="ck_fetched_bundles_raw_replayable",
        ),
        sa.CheckConstraint(
            "state != 'raw_purged' OR (NOT raw_available AND NOT replayable)",
            name="ck_fetched_bundles_purged_flags",
        ),
        sa.CheckConstraint("date_from <= date_to", name="ck_fetched_bundles_date_range"),
        sa.ForeignKeyConstraint(
            ["source_workflow_id"],
            ["workflow_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_batch_id"],
            ["workflow_batches.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_workflow_id",
            "manifest_version",
            "dates_json",
            name="uq_fetched_bundles_source_manifest_dates",
        ),
    )
    op.create_index(
        "ix_fetched_bundles_owner_skill_state",
        "fetched_bundles",
        ["owner_id", "skill_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_fetched_bundles_retention_until",
        "fetched_bundles",
        ["retention_until"],
        unique=False,
    )
    op.create_index(
        "ix_fetched_bundles_source_batch_id",
        "fetched_bundles",
        ["source_batch_id"],
        unique=False,
    )
    op.create_table(
        "fetched_bundle_files",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("bundle_id", sa.String(36), nullable=False),
        sa.Column("reconciliation_date", sa.String(10), nullable=False),
        sa.Column("dataset", sa.String(32), nullable=False),
        sa.Column("relative_name", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "dataset IN ('payments', 'orders', 'writeoffs', 'order_details', 'summary')",
            name="ck_fetched_bundle_files_dataset",
        ),
        sa.CheckConstraint("length(sha256) = 64", name="ck_fetched_bundle_files_sha256"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_fetched_bundle_files_size"),
        sa.ForeignKeyConstraint(["bundle_id"], ["fetched_bundles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bundle_id",
            "reconciliation_date",
            "dataset",
            name="uq_fetched_bundle_files_bundle_date_dataset",
        ),
    )
    op.create_index(
        "ix_fetched_bundle_files_bundle_id",
        "fetched_bundle_files",
        ["bundle_id"],
        unique=False,
    )
    with op.batch_alter_table("workflow_sessions") as batch_op:
        batch_op.add_column(sa.Column("fetched_bundle_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            "fk_workflow_sessions_fetched_bundle_id",
            "fetched_bundles",
            ["fetched_bundle_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_workflow_sessions_fetched_bundle_id",
            ["fetched_bundle_id"],
            unique=False,
        )
    with op.batch_alter_table("workflow_fetched_data_previews") as batch_op:
        batch_op.add_column(sa.Column("bundle_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            "fk_workflow_fetched_data_previews_bundle_id",
            "fetched_bundles",
            ["bundle_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index(
            "ix_workflow_fetched_data_previews_bundle_id",
            ["bundle_id"],
            unique=False,
        )
    _backfill_historical_previews()


def downgrade() -> None:
    with op.batch_alter_table("workflow_fetched_data_previews") as batch_op:
        batch_op.drop_index("ix_workflow_fetched_data_previews_bundle_id")
        batch_op.drop_constraint(
            "fk_workflow_fetched_data_previews_bundle_id",
            type_="foreignkey",
        )
        batch_op.drop_column("bundle_id")
    with op.batch_alter_table("workflow_sessions") as batch_op:
        batch_op.drop_index("ix_workflow_sessions_fetched_bundle_id")
        batch_op.drop_constraint("fk_workflow_sessions_fetched_bundle_id", type_="foreignkey")
        batch_op.drop_column("fetched_bundle_id")
    op.drop_index("ix_fetched_bundle_files_bundle_id", table_name="fetched_bundle_files")
    op.drop_table("fetched_bundle_files")
    op.drop_index("ix_fetched_bundles_source_batch_id", table_name="fetched_bundles")
    op.drop_index("ix_fetched_bundles_retention_until", table_name="fetched_bundles")
    op.drop_index("ix_fetched_bundles_owner_skill_state", table_name="fetched_bundles")
    op.drop_table("fetched_bundles")
