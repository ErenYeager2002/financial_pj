from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..audit_service import query_audit_events, query_audit_events_page, record_audit
from ..auth import UserContext, get_current_user, require_admin
from ..contracts import AuditEventPage, AuditEventRead
from ..database import get_db
from ..model_visible_data import visible_value

router = APIRouter(prefix="/api/admin/audit-events", tags=["admin-audit"])


def _serialize_event(item) -> AuditEventRead:
    try:
        details = json.loads(item.details_json or "{}")
    except (TypeError, ValueError):
        details = {"error": "审计详情格式待核实。"}
    if not isinstance(details, dict):
        details = {"value": "审计详情格式待核实。"}
    else:
        safe_details = visible_value(details)
        details = safe_details if isinstance(safe_details, dict) else {}
    return AuditEventRead(
        id=item.id,
        actor_id=item.actor_id,
        actor_role=item.actor_role,
        action=item.action,
        resource_type=item.resource_type,
        resource_id=item.resource_id,
        outcome=item.outcome,
        details=details,
        created_at=item.created_at,
    )


@router.get("", response_model=list[AuditEventRead])
def list_audit_events(
    action: str = Query(default="", max_length=128),
    actor_id: str = Query(default="", max_length=128),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    before_id: int | None = Query(default=None, ge=1),
    resource_type: str = Query(default="", max_length=64),
    resource_id: str = Query(default="", max_length=128),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[AuditEventRead]:
    require_admin(user)
    rows = [
        _serialize_event(item)
        for item in query_audit_events(
            db,
            user,
            action=action,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            created_from=created_from,
            created_to=created_to,
            limit=limit,
            offset=offset,
            before_id=before_id,
        )
    ]
    record_audit(
        db,
        actor=user,
        action="admin.audit.read",
        resource_type="audit_event",
        details={
            "action_filter": action,
            "actor_filter_used": bool(actor_id),
            "resource_type_filter": resource_type,
            "resource_id_filter_used": bool(resource_id),
            "limit": limit,
            "offset": offset,
            "cursor_used": before_id is not None,
        },
    )
    db.commit()
    return rows


@router.get("/page", response_model=AuditEventPage)
def list_audit_event_page(
    action: str = Query(default="", max_length=128),
    actor_id: str = Query(default="", max_length=128),
    resource_type: str = Query(default="", max_length=64),
    resource_id: str = Query(default="", max_length=128),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    before_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> AuditEventPage:
    require_admin(user)
    if created_from and created_to and created_from > created_to:
        raise HTTPException(status_code=422, detail="审计时间范围无效。")
    rows, next_before_id, has_more = query_audit_events_page(
        db,
        user,
        action=action,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        before_id=before_id,
    )
    record_audit(
        db,
        actor=user,
        action="admin.audit.read",
        resource_type="audit_event",
        details={
            "action_filter": action,
            "actor_filter_used": bool(actor_id),
            "resource_type_filter": resource_type,
            "resource_id_filter_used": bool(resource_id),
            "limit": limit,
            "cursor_used": before_id is not None,
        },
    )
    db.commit()
    return AuditEventPage(
        items=[_serialize_event(item) for item in rows],
        limit=limit,
        next_before_id=next_before_id,
        has_more=has_more,
    )
