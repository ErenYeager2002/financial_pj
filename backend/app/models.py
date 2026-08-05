from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class FileRecord(Base):
    __tablename__ = "files"

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


class RunRecord(Base):
    __tablename__ = "runs"

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


class WorkflowBatch(Base):
    __tablename__ = "workflow_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
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

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
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
