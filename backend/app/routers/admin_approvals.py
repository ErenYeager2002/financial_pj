from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..approval_service import decide_approval, list_approvals
from ..auth import UserContext, get_current_user, require_admin
from ..contracts import ApprovalDecisionRequest, ApprovalRecord
from ..database import get_db

router = APIRouter(prefix="/api/admin/approvals", tags=["admin-approvals"])


@router.get("", response_model=list[ApprovalRecord])
def admin_list_approvals(
    status: str = Query(default="", max_length=24),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> list[ApprovalRecord]:
    require_admin(current)
    if status not in {"", "pending", "approved", "rejected", "expired", "revoked"}:
        status = ""
    return list_approvals(db, current, status=status, limit=limit)


@router.post("/{approval_id}/decision", response_model=ApprovalRecord)
def admin_decide_approval(
    approval_id: str,
    body: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> ApprovalRecord:
    require_admin(current)
    return decide_approval(
        db,
        current,
        approval_id,
        decision=body.decision,
        reason=body.reason,
    )
