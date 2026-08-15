from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..audit_service import query_audit_events, record_audit
from ..auth import UserContext, get_current_user, require_admin
from ..contracts import AuditEventRead
from ..database import get_db

router = APIRouter(prefix="/api/admin/audit-events", tags=["admin-audit"])


@router.get("", response_model=list[AuditEventRead])
def list_audit_events(
    action: str = Query(default="", max_length=128),
    actor_id: str = Query(default="", max_length=128),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> list[AuditEventRead]:
    require_admin(user)
    rows = [
        AuditEventRead(
            id=item.id,
            actor_id=item.actor_id,
            actor_role=item.actor_role,
            action=item.action,
            resource_type=item.resource_type,
            resource_id=item.resource_id,
            outcome=item.outcome,
            details=json.loads(item.details_json or "{}"),
            created_at=item.created_at,
        )
        for item in query_audit_events(
            db, user, action=action, actor_id=actor_id, limit=limit
        )
    ]
    record_audit(
        db,
        actor=user,
        action="admin.audit.read",
        resource_type="audit_event",
        details={"action_filter": action, "actor_filter_used": bool(actor_id), "limit": limit},
    )
    db.commit()
    return rows
