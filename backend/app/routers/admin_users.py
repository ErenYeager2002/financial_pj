from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..admin_user_service import (
    create_department_user,
    list_department_users,
    replace_department_user_permissions,
    update_department_user,
)
from ..auth import UserContext, get_current_user, require_admin
from ..database import get_db
from ..schemas_auth import (
    AdminUserCreate,
    AdminUserRead,
    AdminUserUpdate,
    SkillPermissionRead,
    SkillPermissionsReplace,
)

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])


@router.get("", response_model=list[AdminUserRead])
def admin_list_users(
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> list[AdminUserRead]:
    require_admin(current)
    return list_department_users(db, current)


@router.post("", response_model=AdminUserRead, status_code=201)
def admin_create_user(
    body: AdminUserCreate,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> AdminUserRead:
    require_admin(current)
    return create_department_user(db, current, body)


@router.patch("/{user_id}", response_model=AdminUserRead)
def admin_update_user(
    user_id: str,
    body: AdminUserUpdate,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> AdminUserRead:
    require_admin(current)
    return update_department_user(db, current, user_id, body)


@router.put("/{user_id}/skill-permissions", response_model=list[SkillPermissionRead])
def admin_replace_skill_permissions(
    user_id: str,
    body: SkillPermissionsReplace,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> list[SkillPermissionRead]:
    require_admin(current)
    return replace_department_user_permissions(db, current, user_id, body)
