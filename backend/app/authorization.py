from __future__ import annotations

import uuid
from dataclasses import replace
from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .auth import UserContext
from .auth_models import User, UserSkillPermission

PERMISSION_CAPABILITIES = {"can_run", "can_upload", "can_create_draft"}


def refresh_active_user(db: Session, user: UserContext) -> UserContext:
    """Recheck an authenticated caller after waiting for a mutation/claim lock."""
    stored = db.get(User, user.user_id, populate_existing=True)
    if stored is None or stored.status != "active" or stored.department_id != user.department_id:
        raise HTTPException(status_code=403, detail="平台用户已停用，不能执行此操作。")
    return replace(user, role=stored.role, display_name=stored.display_name, username=stored.username)


def get_skill_permission(
    db: Session,
    user_id: str,
    skill_id: str,
) -> UserSkillPermission | None:
    return db.scalar(
        select(UserSkillPermission).where(
            UserSkillPermission.user_id == user_id,
            UserSkillPermission.skill_id == skill_id,
        )
    )


def allowed_skill_ids(
    db: Session,
    user: UserContext,
    capability: str = "can_run",
) -> set[str]:
    if user.is_admin:
        return set()
    if capability not in PERMISSION_CAPABILITIES:
        raise ValueError(f"未知 Skill 权限能力：{capability}")
    column = getattr(UserSkillPermission, capability)
    return set(
        db.scalars(
            select(UserSkillPermission.skill_id).where(
                UserSkillPermission.user_id == user.user_id,
                column.is_(True),
            )
        ).all()
    )


def assert_skill_permission(
    db: Session,
    user: UserContext,
    skill_id: str,
    capability: str = "can_run",
) -> UserSkillPermission | None:
    if user.is_admin:
        return None
    if capability not in PERMISSION_CAPABILITIES:
        raise ValueError(f"未知 Skill 权限能力：{capability}")
    permission = get_skill_permission(db, user.user_id, skill_id)
    if not permission or not bool(getattr(permission, capability)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号没有使用该财务工具的权限。",
        )
    return permission


def list_user_permissions(db: Session, user_id: str) -> list[UserSkillPermission]:
    return list(
        db.scalars(
            select(UserSkillPermission)
            .where(UserSkillPermission.user_id == user_id)
            .order_by(UserSkillPermission.skill_id)
        ).all()
    )


def replace_user_permissions(
    db: Session,
    user: User,
    permissions: Iterable[dict[str, object]],
) -> list[UserSkillPermission]:
    db.execute(delete(UserSkillPermission).where(UserSkillPermission.user_id == user.id))
    for item in permissions:
        db.add(
            UserSkillPermission(
                id=str(uuid.uuid4()),
                user_id=user.id,
                skill_id=str(item["skill_id"]),
                can_run=bool(item.get("can_run", False)),
                can_upload=bool(item.get("can_upload", False)),
                can_create_draft=bool(item.get("can_create_draft", False)),
                requires_approval=bool(item.get("requires_approval", False)),
            )
        )
    db.commit()
    return list_user_permissions(db, user.id)
