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
