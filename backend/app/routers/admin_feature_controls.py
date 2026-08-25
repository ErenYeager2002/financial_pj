from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import UserContext, get_current_user, require_admin
from ..contracts import FeatureControlRead, FeatureControlUpdateRequest
from ..database import get_db
from ..feature_control_service import list_feature_controls, update_feature_control

router = APIRouter(prefix="/api/admin/feature-controls", tags=["admin-feature-controls"])


@router.get("", response_model=list[FeatureControlRead])
def admin_list_feature_controls(
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> list[FeatureControlRead]:
    require_admin(current)
    return list_feature_controls(db)


@router.put("/{key}", response_model=FeatureControlRead)
def admin_update_feature_control(
    key: str,
    body: FeatureControlUpdateRequest,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> FeatureControlRead:
    require_admin(current)
    return update_feature_control(db, current, key, body.enabled)
