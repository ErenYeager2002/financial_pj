from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .auth import UserContext
from .models import AuditEvent

SENSITIVE_PARTS = ("password", "token", "secret", "api_key", "credential", "content")


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if any(part in str(key).lower() for part in SENSITIVE_PARTS)
                else _sanitize(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def record_audit(
    db: Session,
    *,
    action: str,
    actor: UserContext | None = None,
    actor_id: str = "",
    actor_role: str = "",
    department_id: str = "",
    resource_type: str = "",
    resource_id: str = "",
    outcome: str = "success",
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_id=actor.user_id if actor else actor_id,
        actor_role=actor.role if actor else actor_role,
        department_id=actor.department_id if actor else department_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        details_json=json.dumps(_sanitize(details or {}), ensure_ascii=False, sort_keys=True),
    )
    db.add(event)
    db.flush()
    return event


def query_audit_events(
    db: Session,
    user: UserContext,
    *,
    action: str = "",
    actor_id: str = "",
    limit: int = 100,
    offset: int = 0,
    before_id: int | None = None,
    resource_type: str = "",
    resource_id: str = "",
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> list[AuditEvent]:
    query = select(AuditEvent).where(
        or_(
            AuditEvent.department_id == user.department_id,
            AuditEvent.department_id == "",
        )
    )
    if action:
        query = query.where(AuditEvent.action == action)
    if actor_id:
        query = query.where(AuditEvent.actor_id == actor_id)
    if resource_type:
        query = query.where(AuditEvent.resource_type == resource_type)
    if resource_id:
        query = query.where(AuditEvent.resource_id == resource_id)
    if created_from:
        query = query.where(AuditEvent.created_at >= created_from)
    if created_to:
        query = query.where(AuditEvent.created_at <= created_to)
    if before_id is not None:
        query = query.where(AuditEvent.id < before_id)
    return list(
        db.scalars(
            query.order_by(AuditEvent.id.desc())
            .offset(max(offset, 0))
            .limit(min(max(limit, 1), 500))
        ).all()
    )


def query_audit_events_page(
    db: Session,
    user: UserContext,
    *,
    action: str = "",
    actor_id: str = "",
    resource_type: str = "",
    resource_id: str = "",
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = 20,
    before_id: int | None = None,
) -> tuple[list[AuditEvent], int | None, bool]:
    rows = query_audit_events(
        db,
        user,
        action=action,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        created_from=created_from,
        created_to=created_to,
        limit=min(max(limit, 1), 100) + 1,
        before_id=before_id,
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return rows, rows[-1].id if has_more and rows else None, has_more
