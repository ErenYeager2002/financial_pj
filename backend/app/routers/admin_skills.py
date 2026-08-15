from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import UserContext, get_current_user, require_admin
from ..contracts import (
    SkillReleaseImportRequest,
    SkillReleaseInboxItem,
    SkillReleaseMetadataUpdate,
    SkillReleasePublishRequest,
    SkillReleaseRead,
    SkillReleaseReviewRequest,
)
from ..database import get_db
from ..skill_release_service import (
    import_release,
    list_inbox_packages,
    list_releases,
    publish_release,
    review_release,
    update_release_metadata,
)

router = APIRouter(prefix="/api/admin/skill-releases", tags=["admin-skill-releases"])


@router.get("/inbox", response_model=list[SkillReleaseInboxItem])
def admin_list_release_inbox(
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> list[SkillReleaseInboxItem]:
    require_admin(current)
    return list_inbox_packages(db, current)


@router.get("", response_model=list[SkillReleaseRead])
def admin_list_skill_releases(
    skill_id: str = Query(default="", max_length=128),
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> list[SkillReleaseRead]:
    require_admin(current)
    return list_releases(db, current, skill_id)


@router.post("/import", response_model=SkillReleaseRead, status_code=201)
def admin_import_skill_release(
    body: SkillReleaseImportRequest,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillReleaseRead:
    require_admin(current)
    return import_release(db, current, body.package_name)


@router.patch("/{release_id}", response_model=SkillReleaseRead)
def admin_update_skill_release(
    release_id: str,
    body: SkillReleaseMetadataUpdate,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillReleaseRead:
    require_admin(current)
    return update_release_metadata(db, current, release_id, body)


@router.post("/{release_id}/review", response_model=SkillReleaseRead)
def admin_review_skill_release(
    release_id: str,
    body: SkillReleaseReviewRequest,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillReleaseRead:
    require_admin(current)
    return review_release(db, current, release_id, body)


@router.post("/{release_id}/publish", response_model=SkillReleaseRead)
def admin_publish_skill_release(
    release_id: str,
    body: SkillReleasePublishRequest,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillReleaseRead:
    require_admin(current)
    return publish_release(db, current, release_id, body.confirmation)
