from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import UserContext
from .auth_models import User
from .contracts import RunApprovalRead
from .models import ApprovalRecord
from .redaction import sanitize_text, sanitize_value
from .run_service import get_run_or_404


def _safe_preview(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    sanitized = sanitize_value(parsed)
    return sanitized if isinstance(sanitized, dict) else {}


def _user_names(
    db: Session,
    ids: set[str],
    department_id: str,
) -> dict[str, str]:
    if not ids:
        return {}
    users = db.scalars(
        select(User).where(
            User.id.in_(ids),
            User.department_id == department_id,
        )
    ).all()
    return {item.id: item.display_name for item in users}


def list_run_approvals(
    db: Session, run_id: str, user: UserContext
) -> list[RunApprovalRead]:
    run = get_run_or_404(db, run_id, user)
    records = db.scalars(
        select(ApprovalRecord)
        .where(
            ApprovalRecord.run_id == run.id,
            ApprovalRecord.department_id == run.department_id,
        )
        .order_by(ApprovalRecord.created_at.asc(), ApprovalRecord.id.asc())
    ).all()
    names = _user_names(
        db,
        {
            item
            for record in records
            for item in (record.requested_by, record.decided_by)
            if item
        },
        run.department_id,
    )
    return [
        RunApprovalRead(
            id=record.id,
            status=record.status,
            preview=_safe_preview(record.preview_json),
            requested_by_name=names.get(record.requested_by, ""),
            decided_by_name=names.get(record.decided_by, ""),
            reason=sanitize_text(
                record.reason,
                error=True,
                hidden_message="步骤执行失败，技术详情已隐藏。",
            ),
            created_at=record.created_at,
            decided_at=record.decided_at,
            expires_at=record.expires_at,
        )
        for record in records
    ]
