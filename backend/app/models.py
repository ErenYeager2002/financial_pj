from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .auth_models import User, UserSession, UserSkillPermission  # noqa: F401
from .database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


CONTROLLED_STEP_TYPES: tuple[str, ...] = (
    "parameter_validation",
    "file_validation",
    "read_only_http",
    "python",
    "rpa",
    "result_preview",
    "human_confirmation",
    "admin_approval",
    "controlled_write",
    "post_write_verification",
    "artifact_archive",
)
WORKFLOW_DEFINITION_STATUSES: tuple[str, ...] = (
    "draft",
    "published",
    "disabled",
    "superseded",
    "archived",
)
STEP_RISK_LEVELS: tuple[str, ...] = ("read_only", "write", "external_action")
STEP_WORKER_POOLS: tuple[str, ...] = ("python", "http", "workflow")
STEP_RUN_STATES: tuple[str, ...] = (
    "pending",
    "queued",
    "running",
    "waiting_confirmation",
    "waiting_approval",
    "succeeded",
    "failed",
    "timed_out",
    "cancelled",
    "skipped",
)
_CONTROLLED_STEP_TYPES_SQL = ", ".join(f"'{item}'" for item in CONTROLLED_STEP_TYPES)
_WORKFLOW_DEFINITION_STATUSES_SQL = ", ".join(
    f"'{item}'" for item in WORKFLOW_DEFINITION_STATUSES
)
_STEP_RISK_LEVELS_SQL = ", ".join(f"'{item}'" for item in STEP_RISK_LEVELS)
_STEP_WORKER_POOLS_SQL = ", ".join(f"'{item}'" for item in STEP_WORKER_POOLS)
_STEP_RUN_STATES_SQL = ", ".join(f"'{item}'" for item in STEP_RUN_STATES)


class FileRecord(Base):
    __tablename__ = "files"
    __table_args__ = (
        Index(
            "ux_files_id_owner_department",
            "id",
            "owner_id",
            "department_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    department_id: Mapped[str] = mapped_column(String(128), default="finance", index=True)
    kind: Mapped[str] = mapped_column(String(24), default="input", index=True)
    original_name: Mapped[str] = mapped_column(String(512))
    stored_path: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(255), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("runs.id"), nullable=True)
    # Keep provenance on each record so the file center can group inputs and
    # outputs by Skill without replacing historical files.
    skill_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    skill_name: Mapped[str] = mapped_column(String(255), default="")
    skill_version: Mapped[str] = mapped_column(String(64), default="")
    workflow_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkflowMaterialSet(Base):
    __tablename__ = "workflow_material_sets"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "department_id",
            "skill_id",
            "version",
            name="uq_workflow_material_sets_scope_version",
        ),
        CheckConstraint(
            "state IN ('current', 'superseded')",
            name="ck_workflow_material_sets_state",
        ),
        Index(
            "ux_workflow_material_sets_current_scope",
            "owner_id",
            "department_id",
            "skill_id",
            unique=True,
            sqlite_where=text("state = 'current'"),
            postgresql_where=text("state = 'current'"),
        ),
        Index(
            "ix_workflow_material_sets_scope_created",
            "owner_id",
            "department_id",
            "skill_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    department_id: Mapped[str] = mapped_column(String(128), index=True)
    skill_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer)
    parent_set_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflow_material_sets.id"), nullable=True, index=True
    )
    source_workflow_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    state: Mapped[str] = mapped_column(String(24), default="current", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    files: Mapped[list[WorkflowMaterialSetFile]] = relationship(
        back_populates="material_set",
        cascade="all, delete-orphan",
        order_by="WorkflowMaterialSetFile.role, WorkflowMaterialSetFile.year",
    )


class WorkflowMaterialSetFile(Base):
    __tablename__ = "workflow_material_set_files"
    __table_args__ = (
        UniqueConstraint(
            "material_set_id",
            "role",
            "year",
            name="uq_workflow_material_set_files_role_year",
        ),
        CheckConstraint(
            "role IN ('profit_loss_ledgers', 'receipt_flow_table')",
            name="ck_workflow_material_set_files_role",
        ),
        CheckConstraint(
            "(role = 'profit_loss_ledgers' AND year BETWEEN 1900 AND 2999) "
            "OR (role = 'receipt_flow_table' AND year = 0)",
            name="ck_workflow_material_set_files_year",
        ),
        Index("ix_workflow_material_set_files_file", "file_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    material_set_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_material_sets.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(64))
    year: Mapped[int] = mapped_column(Integer, default=0)
    file_id: Mapped[str] = mapped_column(String(36), ForeignKey("files.id"))
    sha256: Mapped[str] = mapped_column(String(64))

    material_set: Mapped[WorkflowMaterialSet] = relationship(back_populates="files")


class AssistantMessage(Base):
    __tablename__ = "assistant_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_assistant_messages_role",
        ),
        Index(
            "ix_assistant_messages_owner_session_created",
            "owner_id",
            "session_id",
            "created_at",
        ),
        Index(
            "ix_assistant_messages_department_created",
            "department_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    department_id: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelConnection(Base):
    __tablename__ = "model_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    department_id: Mapped[str] = mapped_column(String(128), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    provider_name: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[str] = mapped_column(Text)
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    api_key_hint: Mapped[str] = mapped_column(String(32))
    api_key_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    models_json: Mapped[str] = mapped_column(Text, default="[]")
    selected_model: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), default="connected")
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ModelProfile(Base):
    __tablename__ = "model_profiles"
    __table_args__ = (
        UniqueConstraint("department_id", "purpose", name="uq_model_profile_department_purpose"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    department_id: Mapped[str] = mapped_column(String(128), index=True)
    purpose: Mapped[str] = mapped_column(String(64), default="finance-assistant", index=True)
    connection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("model_connections.id"), index=True
    )
    model: Mapped[str] = mapped_column(String(255))
    configured_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TaskDraftRecord(Base):
    __tablename__ = "task_drafts"
    __table_args__ = (
        Index(
            "ux_task_drafts_id_owner_department",
            "id",
            "owner_id",
            "department_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    department_id: Mapped[str] = mapped_column(String(128), index=True)
    skill_id: Mapped[str] = mapped_column(String(128), index=True)
    skill_name: Mapped[str] = mapped_column(String(255))
    skill_version: Mapped[str] = mapped_column(String(64))
    skill_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    source: Mapped[str] = mapped_column(String(24), default="assistant")
    message: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    candidates_json: Mapped[str] = mapped_column(Text, default="[]")
    parameters_json: Mapped[str] = mapped_column(Text, default="{}")
    files_json: Mapped[str] = mapped_column(Text, default="{}")
    file_hashes_json: Mapped[str] = mapped_column(Text, default="{}")
    missing_inputs_json: Mapped[str] = mapped_column(Text, default="[]")
    validation_warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    clarification: Mapped[str] = mapped_column(Text, default="")
    confirmation_text: Mapped[str] = mapped_column(Text, default="")
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("runs.id"), nullable=True, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ServiceCredential(Base):
    __tablename__ = "service_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    department_id: Mapped[str] = mapped_column(String(128), index=True)
    service: Mapped[str] = mapped_column(String(64), index=True)
    account_encrypted: Mapped[str] = mapped_column(Text)
    password_encrypted: Mapped[str] = mapped_column(Text)
    account_hint: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(32), default="configured")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TaskReminderSubscription(Base):
    __tablename__ = "task_reminder_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "department_id",
            "skill_id",
            name="uq_task_reminder_subscriptions_department_skill",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    department_id: Mapped[str] = mapped_column(String(128), index=True)
    skill_id: Mapped[str] = mapped_column(String(128), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    schedule_time: Mapped[str] = mapped_column(String(5), default="09:10")
    last_successful_business_date: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )
    last_check_status: Mapped[str] = mapped_column(String(32), default="never")
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TaskDiscoveryCheck(Base):
    __tablename__ = "task_discovery_checks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subscription_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("task_reminder_subscriptions.id"), index=True
    )
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    department_id: Mapped[str] = mapped_column(String(128), index=True)
    skill_id: Mapped[str] = mapped_column(String(128), index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="scheduled")
    business_dates_json: Mapped[str] = mapped_column(Text, default="[]")
    state: Mapped[str] = mapped_column(String(32), default="running", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    error_message: Mapped[str] = mapped_column(Text, default="")
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    worker_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TaskReminder(Base):
    __tablename__ = "task_reminders"
    __table_args__ = (
        UniqueConstraint(
            "department_id",
            "skill_id",
            "business_date",
            name="uq_task_reminders_department_skill_date",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    department_id: Mapped[str] = mapped_column(String(128), index=True)
    skill_id: Mapped[str] = mapped_column(String(128), index=True)
    business_date: Mapped[str] = mapped_column(String(10), index=True)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    fingerprint: Mapped[str] = mapped_column(String(128), default="")
    state: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    first_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    actor_role: Mapped[str] = mapped_column(String(64), default="")
    department_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(64), default="", index=True)
    resource_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    outcome: Mapped[str] = mapped_column(String(32), default="success", index=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class SkillRelease(Base):
    __tablename__ = "skill_releases"
    __table_args__ = (
        UniqueConstraint("package_sha256", name="uq_skill_releases_package_sha256"),
        UniqueConstraint("skill_id", "version", name="uq_skill_releases_skill_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(32), default="validated", index=True)
    package_sha256: Mapped[str] = mapped_column(String(64))
    package_path: Mapped[str] = mapped_column(Text)
    source_repository: Mapped[str] = mapped_column(Text, default="")
    source_commit: Mapped[str] = mapped_column(String(64), default="", index=True)
    source_tree_hash: Mapped[str] = mapped_column(String(64), default="")
    manifest_json: Mapped[str] = mapped_column(Text)
    validation_json: Mapped[str] = mapped_column(Text, default="{}")
    test_json: Mapped[str] = mapped_column(Text, default="{}")
    review_notes: Mapped[str] = mapped_column(Text, default="")
    imported_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    reviewed_by: Mapped[str] = mapped_column(String(36), default="", index=True)
    published_by: Mapped[str] = mapped_column(String(36), default="", index=True)
    published_skill_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SkillSourceBinding(Base):
    __tablename__ = "skill_source_bindings"
    __table_args__ = (
        UniqueConstraint("skill_id", name="uq_skill_source_bindings_skill_id"),
        UniqueConstraint(
            "repository_url",
            "source_path",
            name="uq_skill_source_bindings_repository_path",
        ),
        CheckConstraint(
            "binding_status IN ('candidate', 'bound', 'broken', 'excluded')",
            name="ck_skill_source_bindings_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(128), index=True)
    source_type: Mapped[str] = mapped_column(String(32), default="git")
    provider: Mapped[str] = mapped_column(String(32), default="gitee")
    repository_url: Mapped[str] = mapped_column(Text)
    source_path: Mapped[str] = mapped_column(String(512))
    tracking_ref: Mapped[str] = mapped_column(String(255), default="main")
    binding_status: Mapped[str] = mapped_column(String(32), default="bound", index=True)
    packager_profile: Mapped[str] = mapped_column(
        String(128), default="finance-skills-v1"
    )
    last_seen_commit: Mapped[str] = mapped_column(String(64), default="", index=True)
    last_seen_tree_hash: Mapped[str] = mapped_column(String(64), default="")
    published_commit: Mapped[str] = mapped_column(String(64), default="", index=True)
    published_tree_hash: Mapped[str] = mapped_column(String(64), default="")
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    updated_by: Mapped[str] = mapped_column(String(36), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SkillAvailability(Base):
    __tablename__ = "skill_availability"
    __table_args__ = (
        CheckConstraint(
            "state IN ('enabled', 'draining', 'disabled', 'failed_disabled')",
            name="ck_skill_availability_state",
        ),
    )

    skill_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), default="enabled", index=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    changed_by: Mapped[str] = mapped_column(String(36), default="", index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlatformFeatureControl(Base):
    __tablename__ = "platform_feature_controls"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    changed_by: Mapped[str] = mapped_column(String(36), default="", index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SkillRollout(Base):
    __tablename__ = "skill_rollouts"
    __table_args__ = (
        UniqueConstraint("release_id", name="uq_skill_rollouts_release_id"),
        CheckConstraint(
            "state IN ('queued', 'draining', 'activating', 'verifying', "
            "'succeeded', 'failed', 'failed_disabled')",
            name="ck_skill_rollouts_state",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    release_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("skill_releases.id"), index=True
    )
    skill_id: Mapped[str] = mapped_column(String(128), index=True)
    state: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    requested_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    previous_skill_hash: Mapped[str] = mapped_column(String(64), default="")
    target_commit: Mapped[str] = mapped_column(String(64), default="")
    target_tree_hash: Mapped[str] = mapped_column(String(64), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalRecord(Base):
    __tablename__ = "approval_records"
    __table_args__ = (
        Index(
            "ux_approval_records_id_requester_department",
            "id",
            "requested_by",
            "department_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(24), index=True)
    resource_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("runs.id"), nullable=True, index=True
    )
    workflow_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflow_sessions.id"), nullable=True, index=True
    )
    department_id: Mapped[str] = mapped_column(String(128), index=True)
    skill_id: Mapped[str] = mapped_column(String(128), index=True)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    preview_sha256: Mapped[str] = mapped_column(String(64))
    snapshot_json: Mapped[str] = mapped_column(Text)
    preview_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    requested_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    decided_by: Mapped[str] = mapped_column(String(36), default="", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    execution_action_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint(
            "department_id",
            "workflow_key",
            "version",
            name="uq_workflow_definitions_department_key_version",
        ),
        CheckConstraint(
            f"status IN ({_WORKFLOW_DEFINITION_STATUSES_SQL})",
            name="ck_workflow_definitions_status",
        ),
        ForeignKeyConstraint(
            ["created_by", "department_id"],
            ["users.id", "users.department_id"],
            name="fk_workflow_definitions_creator_department",
        ),
        Index(
            "ix_workflow_definitions_department_status",
            "department_id",
            "status",
        ),
        Index(
            "ix_workflow_definitions_skill_version",
            "skill_id",
            "skill_version",
        ),
        Index(
            "ux_workflow_definitions_id_department",
            "id",
            "department_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    department_id: Mapped[str] = mapped_column(String(128), index=True)
    workflow_key: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    skill_id: Mapped[str] = mapped_column(String(128), index=True)
    skill_version: Mapped[str] = mapped_column(String(64))
    skill_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    steps: Mapped[list[StepDefinition]] = relationship(
        back_populates="workflow_definition",
        cascade="all, delete-orphan",
        order_by="StepDefinition.position",
    )


class StepDefinition(Base):
    __tablename__ = "step_definitions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_definition_id",
            "step_key",
            name="uq_step_definitions_workflow_key",
        ),
        UniqueConstraint(
            "workflow_definition_id",
            "position",
            name="uq_step_definitions_workflow_position",
        ),
        ForeignKeyConstraint(
            ["workflow_definition_id", "department_id"],
            ["workflow_definitions.id", "workflow_definitions.department_id"],
            name="fk_step_definitions_workflow_department",
        ),
        CheckConstraint("position >= 0", name="ck_step_definitions_position_nonnegative"),
        CheckConstraint("timeout_seconds > 0", name="ck_step_definitions_timeout_positive"),
        CheckConstraint("max_attempts > 0", name="ck_step_definitions_attempts_positive"),
        CheckConstraint(
            "is_idempotent OR (max_attempts = 1 AND NOT retryable)",
            name="ck_step_definitions_non_idempotent_no_retry",
        ),
        CheckConstraint(
            f"step_type IN ({_CONTROLLED_STEP_TYPES_SQL})",
            name="ck_step_definitions_controlled_type",
        ),
        CheckConstraint(
            f"risk_level IN ({_STEP_RISK_LEVELS_SQL})",
            name="ck_step_definitions_risk_level",
        ),
        CheckConstraint(
            f"worker_pool IN ({_STEP_WORKER_POOLS_SQL})",
            name="ck_step_definitions_worker_pool",
        ),
        Index(
            "ix_step_definitions_workflow_type",
            "workflow_definition_id",
            "step_type",
        ),
        Index(
            "ux_step_definitions_id_department",
            "id",
            "department_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_definition_id: Mapped[str] = mapped_column(String(36), index=True)
    department_id: Mapped[str] = mapped_column(String(128), default="finance", index=True)
    step_key: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(255))
    step_type: Mapped[str] = mapped_column(String(64), index=True)
    position: Mapped[int] = mapped_column(Integer)
    input_schema_json: Mapped[str] = mapped_column(Text, default="{}")
    output_schema_json: Mapped[str] = mapped_column(Text, default="{}")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    retry_backoff_seconds: Mapped[int] = mapped_column(Integer, default=0)
    risk_level: Mapped[str] = mapped_column(String(24), default="read_only", index=True)
    worker_pool: Mapped[str] = mapped_column(String(64), index=True)
    is_idempotent: Mapped[bool] = mapped_column(Boolean, default=False)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    workflow_definition: Mapped[WorkflowDefinition] = relationship(back_populates="steps")
    step_runs: Mapped[list[StepRun]] = relationship(back_populates="step_definition")


class StepRun(Base):
    __tablename__ = "step_runs"
    __table_args__ = (
        CheckConstraint(
            "(run_id IS NOT NULL AND workflow_session_id IS NULL) OR "
            "(run_id IS NULL AND workflow_session_id IS NOT NULL)",
            name="ck_step_runs_single_task_parent",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_step_runs_attempts_nonnegative"),
        CheckConstraint(
            f"state IN ({_STEP_RUN_STATES_SQL})",
            name="ck_step_runs_state",
        ),
        UniqueConstraint("run_id", "step_definition_id", name="uq_step_runs_run_step"),
        UniqueConstraint(
            "workflow_session_id",
            "step_definition_id",
            name="uq_step_runs_workflow_step",
        ),
        ForeignKeyConstraint(
            ["run_id", "owner_id", "department_id"],
            ["runs.id", "runs.owner_id", "runs.department_id"],
            name="fk_step_runs_run_scope",
        ),
        ForeignKeyConstraint(
            ["step_definition_id", "department_id"],
            ["step_definitions.id", "step_definitions.department_id"],
            name="fk_step_runs_step_department",
        ),
        ForeignKeyConstraint(
            ["workflow_session_id", "owner_id", "department_id"],
            [
                "workflow_sessions.id",
                "workflow_sessions.owner_id",
                "workflow_sessions.department_id",
            ],
            name="fk_step_runs_workflow_scope",
        ),
        Index("ix_step_runs_owner_state", "owner_id", "state"),
        Index("ix_step_runs_department_state", "department_id", "state"),
        Index(
            "ux_step_runs_id_owner_department",
            "id",
            "owner_id",
            "department_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    step_definition_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    workflow_session_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    department_id: Mapped[str] = mapped_column(String(128), index=True)
    state: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    worker_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    input_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    output_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    error_code: Mapped[str] = mapped_column(String(64), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    can_retry: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_block_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    step_definition: Mapped[StepDefinition] = relationship(back_populates="step_runs")
    artifacts: Mapped[list[ArtifactBinding]] = relationship(
        back_populates="step_run", cascade="all, delete-orphan"
    )
    approvals: Mapped[list[ApprovalBinding]] = relationship(
        back_populates="step_run", cascade="all, delete-orphan"
    )


class ArtifactBinding(Base):
    __tablename__ = "artifact_bindings"
    __table_args__ = (
        UniqueConstraint(
            "step_run_id",
            "file_id",
            "direction",
            "role",
            name="uq_artifact_bindings_step_file_direction_role",
        ),
        CheckConstraint(
            "direction IN ('input', 'output')",
            name="ck_artifact_bindings_direction",
        ),
        ForeignKeyConstraint(
            ["step_run_id", "owner_id", "department_id"],
            ["step_runs.id", "step_runs.owner_id", "step_runs.department_id"],
            name="fk_artifact_bindings_step_scope",
        ),
        ForeignKeyConstraint(
            ["file_id", "owner_id", "department_id"],
            ["files.id", "files.owner_id", "files.department_id"],
            name="fk_artifact_bindings_file_scope",
        ),
        Index("ix_artifact_bindings_owner_direction", "owner_id", "direction"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    step_run_id: Mapped[str] = mapped_column(String(36), index=True)
    file_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    department_id: Mapped[str] = mapped_column(String(128), index=True)
    direction: Mapped[str] = mapped_column(String(16), index=True)
    role: Mapped[str] = mapped_column(String(64), default="", index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    step_run: Mapped[StepRun] = relationship(back_populates="artifacts")


class ApprovalBinding(Base):
    __tablename__ = "approval_bindings"
    __table_args__ = (
        UniqueConstraint(
            "approval_record_id",
            name="uq_approval_bindings_approval_record",
        ),
        ForeignKeyConstraint(
            ["step_run_id", "owner_id", "department_id"],
            ["step_runs.id", "step_runs.owner_id", "step_runs.department_id"],
            name="fk_approval_bindings_step_scope",
        ),
        ForeignKeyConstraint(
            ["approval_record_id", "owner_id", "department_id"],
            [
                "approval_records.id",
                "approval_records.requested_by",
                "approval_records.department_id",
            ],
            name="fk_approval_bindings_approval_scope",
        ),
        Index("ix_approval_bindings_owner_step", "owner_id", "step_run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    step_run_id: Mapped[str] = mapped_column(String(36), index=True)
    approval_record_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    department_id: Mapped[str] = mapped_column(String(128), index=True)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    step_run: Mapped[StepRun] = relationship(back_populates="approvals")


def _reject_immutable_binding_update(_mapper, _connection, target) -> None:
    state = inspect(target)
    if any(attribute.history.has_changes() for attribute in state.attrs):
        raise ValueError(f"{target.__tablename__} rows are immutable after insert")


def _reject_immutable_binding_delete(_mapper, _connection, target) -> None:
    raise ValueError(f"{target.__tablename__} rows cannot be deleted")


def _validate_step_run_retry(_mapper, connection, target: StepRun) -> None:
    if not target.can_retry:
        return
    retryable = connection.execute(
        select(StepDefinition.is_idempotent, StepDefinition.retryable).where(
            StepDefinition.id == target.step_definition_id
        )
    ).one_or_none()
    if retryable is None or not retryable.is_idempotent or not retryable.retryable:
        raise ValueError("Only explicitly idempotent steps can be marked retryable")


event.listen(ArtifactBinding, "before_update", _reject_immutable_binding_update)
event.listen(ApprovalBinding, "before_update", _reject_immutable_binding_update)
event.listen(ArtifactBinding, "before_delete", _reject_immutable_binding_delete)
event.listen(ApprovalBinding, "before_delete", _reject_immutable_binding_delete)
event.listen(StepRun, "before_insert", _validate_step_run_retry)
event.listen(StepRun, "before_update", _validate_step_run_retry)


class RunRecord(Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index(
            "ux_runs_id_owner_department",
            "id",
            "owner_id",
            "department_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    owner_name: Mapped[str] = mapped_column(String(128), default="")
    department_id: Mapped[str] = mapped_column(String(128), default="finance", index=True)
    skill_id: Mapped[str] = mapped_column(String(128), index=True)
    skill_name: Mapped[str] = mapped_column(String(255))
    skill_version: Mapped[str] = mapped_column(String(64))
    skill_commit: Mapped[str] = mapped_column(String(64), default="")
    skill_hash: Mapped[str] = mapped_column(String(64))
    manifest_path: Mapped[str] = mapped_column(Text)
    manifest_snapshot: Mapped[str] = mapped_column(Text)
    adapter: Mapped[str] = mapped_column(String(32))
    worker_pool: Mapped[str] = mapped_column(String(64), index=True)
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=1)
    worker_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    state: Mapped[str] = mapped_column(String(40), default="created", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str] = mapped_column(Text, default="")
    message: Mapped[str] = mapped_column(Text, default="")
    parameters_json: Mapped[str] = mapped_column(Text, default="{}")
    files_json: Mapped[str] = mapped_column(Text, default="{}")
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    idempotency_key: Mapped[str] = mapped_column(String(128), default="", index=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")
    confirmation_required: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_by: Mapped[str] = mapped_column(String(128), default="")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list[RunEvent]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    model_audit: Mapped[RunModelAudit | None] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )


class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40), default="progress")
    state: Mapped[str] = mapped_column(String(40), default="")
    progress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[RunRecord] = relationship(back_populates="events")


class RunModelAudit(Base):
    __tablename__ = "run_model_audits"

    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"), primary_key=True)
    connection_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[RunRecord] = relationship(back_populates="model_audit")


class ModelTraceRecord(Base):
    __tablename__ = "model_trace_records"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'fallback', 'failed')",
            name="ck_model_trace_records_status",
        ),
        CheckConstraint(
            "NOT (run_id IS NOT NULL AND task_draft_id IS NOT NULL)",
            name="ck_model_trace_records_at_most_one_parent",
        ),
        CheckConstraint(
            "duration_ms >= 0 AND input_tokens >= 0 AND output_tokens >= 0",
            name="ck_model_trace_records_nonnegative_metrics",
        ),
        Index(
            "ix_model_trace_records_department_created",
            "department_id",
            "created_at",
        ),
        Index(
            "ix_model_trace_records_provider_model",
            "provider",
            "model",
        ),
        ForeignKeyConstraint(
            ["run_id", "owner_id", "department_id"],
            ["runs.id", "runs.owner_id", "runs.department_id"],
            name="fk_model_trace_records_run_scope",
        ),
        ForeignKeyConstraint(
            ["task_draft_id", "owner_id", "department_id"],
            ["task_drafts.id", "task_drafts.owner_id", "task_drafts.department_id"],
            name="fk_model_trace_records_draft_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    department_id: Mapped[str] = mapped_column(String(128), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    task_draft_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    connection_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    purpose: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    failure_code: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class WorkflowBatch(Base):
    __tablename__ = "workflow_batches"

    __table_args__ = (
        Index("ux_workflow_batches_display_id", "display_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_id: Mapped[str | None] = mapped_column(String(192), nullable=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    owner_name: Mapped[str] = mapped_column(String(128), default="")
    department_id: Mapped[str] = mapped_column(String(128), default="finance", index=True)
    skill_id: Mapped[str] = mapped_column(String(128), index=True)
    skill_name: Mapped[str] = mapped_column(String(255))
    skill_version: Mapped[str] = mapped_column(String(64))
    model_connection_id: Mapped[str] = mapped_column(String(36), index=True)
    model_provider: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(255))
    reconciliation_dates_json: Mapped[str] = mapped_column(Text, default="[]")
    files_json: Mapped[str] = mapped_column(Text, default="{}")
    material_set_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflow_material_sets.id"), nullable=True, index=True
    )
    state: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    workflows: Mapped[list[WorkflowSession]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class WorkflowSession(Base):
    __tablename__ = "workflow_sessions"
    __table_args__ = (
        Index(
            "ux_workflow_sessions_id_owner_department",
            "id",
            "owner_id",
            "department_id",
            unique=True,
        ),
        Index("ux_workflow_sessions_display_id", "display_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_id: Mapped[str | None] = mapped_column(String(192), nullable=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    owner_name: Mapped[str] = mapped_column(String(128), default="")
    department_id: Mapped[str] = mapped_column(String(128), default="finance", index=True)
    skill_id: Mapped[str] = mapped_column(String(128), index=True)
    skill_name: Mapped[str] = mapped_column(String(255))
    skill_version: Mapped[str] = mapped_column(String(64))
    skill_hash: Mapped[str] = mapped_column(String(64))
    skill_commit: Mapped[str] = mapped_column(String(64), default="")
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=1)
    model_connection_id: Mapped[str] = mapped_column(String(36), index=True)
    model_provider: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(40), default="active", index=True)
    stage: Mapped[str] = mapped_column(String(64), default="awaiting_date", index=True)
    reconciliation_date: Mapped[str] = mapped_column(String(10), default="")
    batch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflow_batches.id"), nullable=True, index=True
    )
    batch_sequence: Mapped[int] = mapped_column(Integer, default=0)
    previous_workflow_id: Mapped[str] = mapped_column(String(36), default="")
    material_set_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflow_material_sets.id"), nullable=True, index=True
    )
    context_json: Mapped[str] = mapped_column(Text, default="{}")
    files_json: Mapped[str] = mapped_column(Text, default="{}")
    artifacts_json: Mapped[str] = mapped_column(Text, default="[]")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    messages: Mapped[list[WorkflowMessage]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    actions: Mapped[list[WorkflowAction]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    batch: Mapped[WorkflowBatch | None] = relationship(back_populates="workflows")


class WorkflowMessage(Base):
    __tablename__ = "workflow_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_sessions.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(24))
    content: Mapped[str] = mapped_column(Text)
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    workflow: Mapped[WorkflowSession] = relationship(back_populates="messages")


class WorkflowAction(Base):
    __tablename__ = "workflow_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_sessions.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    worker_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workflow: Mapped[WorkflowSession] = relationship(back_populates="actions")


class SchedulerLock(Base):
    __tablename__ = "scheduler_locks"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
