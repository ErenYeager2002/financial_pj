"""Durable submission reservations, separate from execution leases."""
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ...database import Base


class IdempotencyRequest(Base):
    __tablename__ = "idempotency_requests"
    __table_args__ = (
        UniqueConstraint("owner_id", "department_id", "operation", "request_key", name="uq_idempotency_requests_scope_key"),
        CheckConstraint("status IN ('preparing', 'prepared', 'bound', 'rejected')", name="ck_idempotency_requests_status"),
        CheckConstraint("(status = 'bound' AND execution_kind IS NOT NULL AND execution_id IS NOT NULL) OR (status <> 'bound' AND execution_kind IS NULL AND execution_id IS NULL)", name="ck_idempotency_requests_binding"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128))
    department_id: Mapped[str] = mapped_column(String(128))
    operation: Mapped[str] = mapped_column(String(64))
    request_key: Mapped[str] = mapped_column(String(200))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    canonical_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    reservation_token: Mapped[str] = mapped_column(String(36))
    reservation_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pinned_revision_json: Mapped[str] = mapped_column(Text)
    prepared_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    response_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
