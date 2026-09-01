from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ..auth import UserContext, get_current_user, require_admin
from ..contracts import SkillDedicationRead, SkillDedicationWrite
from ..database import get_db
from ..skill_dedication_service import (
    clear_skill_dedication,
    list_skill_dedications,
    set_skill_dedication,
)

router = APIRouter(prefix="/api/admin/skill-dedications", tags=["admin-skill-dedications"])


@router.get("", response_model=list[SkillDedicationRead])
def admin_list_skill_dedications(
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> list[SkillDedicationRead]:
    require_admin(current)
    return list_skill_dedications(db, current)


@router.put("/{skill_id}", response_model=SkillDedicationRead)
def admin_set_skill_dedication(
    skill_id: str,
    body: SkillDedicationWrite,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> SkillDedicationRead:
    require_admin(current)
    return set_skill_dedication(db, current, skill_id, body.user_id)


@router.delete("/{skill_id}", status_code=204)
def admin_clear_skill_dedication(
    skill_id: str,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> Response:
    require_admin(current)
    clear_skill_dedication(db, current, skill_id)
    return Response(status_code=204)
