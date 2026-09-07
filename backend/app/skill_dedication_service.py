from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit_service import record_audit
from .auth import UserContext
from .auth_models import User
from .authorization import refresh_active_user
from .contracts import SkillDedicationRead
from .models import SkillDedicatedUser, utcnow
from .registry import registry
from .scheduler import acquire_claim_lock


def _require_admin(actor: UserContext) -> None:
    if not actor.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有 Skill 管理员可以管理专属员工标记。",
        )


def _require_skill(skill_id: str) -> None:
    if registry.get(skill_id, include_unpublished=True) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="平台不存在该 Skill。")


def _department_user(db: Session, actor: UserContext, user_id: str) -> User:
    user = db.scalar(
        select(User).where(
            User.id == user_id,
            User.department_id == actor.department_id,
        )
        .execution_options(populate_existing=True)
    )
    if user is None:
        # 跨部门用户与不存在的用户使用同一响应，避免泄露用户信息。
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="员工不存在。")
    if user.status != "active" or user.role != "finance_user":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="专属员工只能选择当前部门状态正常的财务员工。",
        )
    return user


def _dedication_read(row: SkillDedicatedUser, user: User) -> SkillDedicationRead:
    return SkillDedicationRead(
        skill_id=row.skill_id,
        user_id=row.user_id,
        user_display_name=user.display_name,
        user_status="active" if user.status == "active" else "disabled",
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


def _find_dedication(db: Session, actor: UserContext, skill_id: str) -> SkillDedicatedUser | None:
    return db.scalar(
        select(SkillDedicatedUser).where(
            SkillDedicatedUser.department_id == actor.department_id,
            SkillDedicatedUser.skill_id == skill_id,
        )
    )


def list_skill_dedications(db: Session, actor: UserContext) -> list[SkillDedicationRead]:
    _require_admin(actor)
    rows = db.execute(
        select(SkillDedicatedUser, User)
        .join(User, User.id == SkillDedicatedUser.user_id)
        .where(SkillDedicatedUser.department_id == actor.department_id)
        .order_by(SkillDedicatedUser.skill_id)
    ).all()
    result = [_dedication_read(row, user) for row, user in rows]
    record_audit(
        db,
        actor=actor,
        action="admin.skill_dedication.read",
        resource_type="skill_dedication",
        details={"skill_id": ""},
    )
    db.commit()
    return result


def set_skill_dedication(
    db: Session,
    actor: UserContext,
    skill_id: str,
    user_id: str,
) -> SkillDedicationRead:
    _require_admin(actor)
    _require_skill(skill_id)
    acquire_claim_lock(db)
    actor = refresh_active_user(db, actor)
    _require_admin(actor)
    target = _department_user(db, actor, user_id)
    row = _find_dedication(db, actor, skill_id)
    old_user_id = row.user_id if row is not None else ""
    if row is None:
        now = utcnow()
        row = SkillDedicatedUser(
            department_id=actor.department_id,
            skill_id=skill_id,
            user_id=target.id,
            created_by=actor.user_id,
            updated_by=actor.user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    elif row.user_id != target.id:
        row.user_id = target.id
        row.updated_by = actor.user_id
        row.updated_at = utcnow()

    try:
        db.flush()
        record_audit(
            db,
            actor=actor,
            action="admin.skill_dedication.set",
            resource_type="skill_dedication",
            resource_id=skill_id,
            details={
                "skill_id": skill_id,
                "old_user_id": old_user_id,
                "new_user_id": target.id,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该 Skill 的专属员工刚刚发生变化，请刷新后重试。",
        ) from exc
    return _dedication_read(row, target)


def clear_skill_dedication(db: Session, actor: UserContext, skill_id: str) -> None:
    _require_admin(actor)
    _require_skill(skill_id)
    row = _find_dedication(db, actor, skill_id)
    old_user_id = row.user_id if row is not None else ""
    if row is not None:
        db.delete(row)
    record_audit(
        db,
        actor=actor,
        action="admin.skill_dedication.clear",
        resource_type="skill_dedication",
        resource_id=skill_id,
        details={
            "skill_id": skill_id,
            "old_user_id": old_user_id,
            "new_user_id": "",
        },
    )
    db.commit()
