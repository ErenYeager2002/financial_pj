"""add workflow material version sets

Revision ID: 71d4e9c2a5f0
Revises: 2d7c4e91a6b0
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "71d4e9c2a5f0"
down_revision = "2d7c4e91a6b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_material_sets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("department_id", sa.String(length=128), nullable=False),
        sa.Column("skill_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_set_id", sa.String(length=36), nullable=True),
        sa.Column("source_workflow_id", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=24), nullable=False, server_default="current"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('current', 'superseded')",
            name="ck_workflow_material_sets_state",
        ),
        sa.ForeignKeyConstraint(
            ["parent_set_id"],
            ["workflow_material_sets.id"],
            name="fk_workflow_material_sets_parent",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "department_id",
            "skill_id",
            "version",
            name="uq_workflow_material_sets_scope_version",
        ),
    )
    op.create_index("ix_workflow_material_sets_owner_id", "workflow_material_sets", ["owner_id"])
    op.create_index(
        "ix_workflow_material_sets_department_id", "workflow_material_sets", ["department_id"]
    )
    op.create_index("ix_workflow_material_sets_skill_id", "workflow_material_sets", ["skill_id"])
    op.create_index(
        "ix_workflow_material_sets_parent_set_id", "workflow_material_sets", ["parent_set_id"]
    )
    op.create_index(
        "ix_workflow_material_sets_source_workflow_id",
        "workflow_material_sets",
        ["source_workflow_id"],
    )
    op.create_index("ix_workflow_material_sets_state", "workflow_material_sets", ["state"])
    op.create_index(
        "ix_workflow_material_sets_scope_created",
        "workflow_material_sets",
        ["owner_id", "department_id", "skill_id", "created_at"],
    )
    op.create_index(
        "ux_workflow_material_sets_current_scope",
        "workflow_material_sets",
        ["owner_id", "department_id", "skill_id"],
        unique=True,
        sqlite_where=sa.text("state = 'current'"),
        postgresql_where=sa.text("state = 'current'"),
    )

    op.create_table(
        "workflow_material_set_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("material_set_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_id", sa.String(length=36), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "role IN ('profit_loss_ledgers', 'receipt_flow_table')",
            name="ck_workflow_material_set_files_role",
        ),
        sa.CheckConstraint(
            "(role = 'profit_loss_ledgers' AND year BETWEEN 1900 AND 2999) "
            "OR (role = 'receipt_flow_table' AND year = 0)",
            name="ck_workflow_material_set_files_year",
        ),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.ForeignKeyConstraint(
            ["material_set_id"],
            ["workflow_material_sets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "material_set_id",
            "role",
            "year",
            name="uq_workflow_material_set_files_role_year",
        ),
    )
    op.create_index(
        "ix_workflow_material_set_files_material_set_id",
        "workflow_material_set_files",
        ["material_set_id"],
    )
    op.create_index(
        "ix_workflow_material_set_files_file",
        "workflow_material_set_files",
        ["file_id"],
    )

    with op.batch_alter_table("workflow_sessions") as batch:
        batch.add_column(sa.Column("material_set_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_workflow_sessions_material_set",
            "workflow_material_sets",
            ["material_set_id"],
            ["id"],
        )
        batch.create_index("ix_workflow_sessions_material_set_id", ["material_set_id"])
    with op.batch_alter_table("workflow_batches") as batch:
        batch.add_column(sa.Column("material_set_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_workflow_batches_material_set",
            "workflow_material_sets",
            ["material_set_id"],
            ["id"],
        )
        batch.create_index("ix_workflow_batches_material_set_id", ["material_set_id"])


def downgrade() -> None:
    with op.batch_alter_table("workflow_batches") as batch:
        batch.drop_index("ix_workflow_batches_material_set_id")
        batch.drop_constraint("fk_workflow_batches_material_set", type_="foreignkey")
        batch.drop_column("material_set_id")
    with op.batch_alter_table("workflow_sessions") as batch:
        batch.drop_index("ix_workflow_sessions_material_set_id")
        batch.drop_constraint("fk_workflow_sessions_material_set", type_="foreignkey")
        batch.drop_column("material_set_id")
    op.drop_index("ix_workflow_material_set_files_file", table_name="workflow_material_set_files")
    op.drop_index(
        "ix_workflow_material_set_files_material_set_id",
        table_name="workflow_material_set_files",
    )
    op.drop_table("workflow_material_set_files")
    op.drop_index(
        "ux_workflow_material_sets_current_scope", table_name="workflow_material_sets"
    )
    op.drop_index(
        "ix_workflow_material_sets_scope_created", table_name="workflow_material_sets"
    )
    op.drop_index("ix_workflow_material_sets_state", table_name="workflow_material_sets")
    op.drop_index(
        "ix_workflow_material_sets_source_workflow_id", table_name="workflow_material_sets"
    )
    op.drop_index("ix_workflow_material_sets_parent_set_id", table_name="workflow_material_sets")
    op.drop_index("ix_workflow_material_sets_skill_id", table_name="workflow_material_sets")
    op.drop_index("ix_workflow_material_sets_department_id", table_name="workflow_material_sets")
    op.drop_index("ix_workflow_material_sets_owner_id", table_name="workflow_material_sets")
    op.drop_table("workflow_material_sets")
