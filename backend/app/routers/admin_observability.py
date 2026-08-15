from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import UserContext, get_current_user, require_admin
from ..contracts import ObservabilitySummary
from ..database import get_db
from ..observability_service import observability_summary

router = APIRouter(tags=["admin-observability"])


@router.get("/api/admin/observability/summary", response_model=ObservabilitySummary)
def admin_observability_summary(
    hours: int = Query(default=24, ge=1, le=24 * 90),
    db: Session = Depends(get_db),
    user: UserContext = Depends(get_current_user),
) -> ObservabilitySummary:
    require_admin(user)
    return observability_summary(db, user, hours)
