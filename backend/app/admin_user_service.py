from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit_service import record_audit
from .auth import UserContext
from .auth_models import User, UserSkillPermission
from .auth_service import create_user, revoke_all_user_sessions
from .authorization import list_user_permissions, replace_user_permissions
from .registry import registry
from .schemas_auth import (
    AdminUserCreate,
    AdminUserRead,
    AdminUserUpdate,
    SkillPermissionRead,
    SkillPermissionsReplace,
)


def _permission_read(item: UserSkillPermission) -> SkillPermissionRead:
    return SkillPermissionRead(
        skill_id=item.skill_id,
        can_run=item.can_run,
        can_upload=item.can_upload,
        can_create_draft=item.can_create_draft,
        requires_approval=item.requires_approval,
    )


def user_read(db: Session, user: User) -> AdminUserRead:
    return AdminUserRead(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        department_id=user.department_id,
        status=user.status,
        must_change_password=user.must_change_password,
        clerk_user_id=user.clerk_user_id,
        clerk_organization_id=user.clerk_organization_id,
        permissions=[_permission_read(item) for item in list_user_permissions(db, user.id)],
        created_at=user.created_at,
    )


def _department_user(db: Session, actor: UserContext, user_id: str) -> User:
    stored = db.scalar(
        select(User).where(
            User.id == user_id,
            User.department_id == actor.department_id,
        )
    )
    if not stored:
        raise HTTPException(status_code=404, detail="用户不存在。")
    return stored


def list_department_users(db: Session, actor: UserContext) -> list[AdminUserRead]:
    users = db.scalars(
        select(User)
        .where(User.department_id == actor.department_id)
        .order_by(User.created_at, User.username)
    ).all()
    record_audit(
        db,
        actor=actor,
        action="admin.users.read",
        resource_type="user",
        details={"result_count": len(users)},
    )
    db.commit()
    return [user_read(db, item) for item in users]


def create_department_user(
    db: Session,
    actor: UserContext,
    body: AdminUserCreate,
) -> AdminUserRead:
    if body.department_id != actor.department_id:
        raise HTTPException(status_code=403, detail="不能在其他部门创建平台用户。")
    try:
        user = create_user(
            db,
            username=body.username,
            password=body.initial_password,
            display_name=body.display_name,
            role=body.role,
            department_id=actor.department_id,
            must_change_password=True,
        )
        record_audit(
            db,
            actor=actor,
            action="user.create",
            resource_type="user",
            resource_id=user.id,
            details={"role": user.role, "department_id": actor.department_id},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户名已经存在。") from exc
    db.refresh(user)
    return user_read(db, user)


def update_department_user(
    db: Session,
    actor: UserContext,
    user_id: str,
    body: AdminUserUpdate,
) -> AdminUserRead:
    user = _department_user(db, actor, user_id)
    if user.id == actor.user_id:
        if body.status == "disabled":
            raise HTTPException(status_code=409, detail="不能禁用当前登录的管理员。")
        if body.role and body.role != "skill_admin":
            raise HTTPException(status_code=409, detail="不能移除当前登录账号的管理员角色。")
    if body.display_name is not None:
        user.display_name = body.display_name.strip() or user.username
    if body.role is not None:
        user.role = body.role
        if body.role == "skill_admin":
            db.execute(
                delete(UserSkillPermission).where(UserSkillPermission.user_id == user.id)
            )
    if body.status is not None:
        user.status = body.status
    if "clerk_user_id" in body.model_fields_set:
        user.clerk_user_id = body.clerk_user_id.strip() if body.clerk_user_id else None
    if "clerk_organization_id" in body.model_fields_set:
        user.clerk_organization_id = (
            body.clerk_organization_id.strip() if body.clerk_organization_id else None
        )
    record_audit(
        db,
        actor=actor,
        action="user.update",
        resource_type="user",
        resource_id=user.id,
        details={
            "display_name_changed": body.display_name is not None,
            "role": body.role,
            "status": body.status,
            "clerk_identity_changed": bool(
                {"clerk_user_id", "clerk_organization_id"} & body.model_fields_set
            ),
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Clerk 用户标识已经绑定其他账号。") from exc
    if body.status == "disabled":
        revoke_all_user_sessions(db, user.id)
    db.refresh(user)
    return user_read(db, user)


def replace_department_user_permissions(
    db: Session,
    actor: UserContext,
    user_id: str,
    body: SkillPermissionsReplace,
) -> list[SkillPermissionRead]:
    user = _department_user(db, actor, user_id)
    if user.role == "skill_admin" and body.permissions:
        raise HTTPException(status_code=422, detail="管理员默认拥有全部 Skill，无需单独授权。")
    published = {
        item.manifest.id
        for item in registry.list(include_disabled=False)
        if item.manifest.status == "published"
    }
    requested_ids = [item.skill_id for item in body.permissions]
    if len(requested_ids) != len(set(requested_ids)):
        raise HTTPException(status_code=422, detail="同一 Skill 不能重复授权。")
    unknown = sorted(set(requested_ids) - published)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Skill 未发布或不存在：{unknown}")
    record_audit(
        db,
        actor=actor,
        action="permission.replace",
        resource_type="user",
        resource_id=user.id,
        details={
            "permission_count": len(body.permissions),
            "skill_ids": sorted(item.skill_id for item in body.permissions),
        },
    )
    items = replace_user_permissions(
        db,
        user,
        [item.model_dump() for item in body.permissions],
    )
    return [_permission_read(item) for item in items]
