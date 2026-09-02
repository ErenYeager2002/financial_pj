from __future__ import annotations

import json
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
    if before_id is not None:
        query = query.where(AuditEvent.id < before_id)
    return list(
        db.scalars(
            query.order_by(AuditEvent.id.desc())
            .offset(max(offset, 0))
            .limit(min(max(limit, 1), 500))
        ).all()
    )
