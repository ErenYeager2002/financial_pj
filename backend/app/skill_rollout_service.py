from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit_service import record_audit
from .auth import UserContext
from .contracts import SkillRolloutRead
from .database import SessionLocal
from .models import (
    SkillAvailability,
    SkillRelease,
    SkillRollout,
    SkillSourceBinding,
)
from .redaction import sanitize_text
from .registry import registry
from .scheduler import acquire_claim_lock
from .settings import settings
from .skill_availability_service import (
    disable_after_drain,
    get_availability,
    transition_availability,
)
from .skill_release_service import activate_reviewed_release

ACTIVE_ROLLOUT_STATES = {"queued", "draining", "activating", "verifying"}
INTERRUPTED_ROLLOUT_AFTER = timedelta(minutes=15)


def rollout_read(record: SkillRollout) -> SkillRolloutRead:
    return SkillRolloutRead.model_validate(record, from_attributes=True)


def get_rollout(db: Session, rollout_id: str) -> SkillRolloutRead:
    record = db.get(SkillRollout, rollout_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Skill 发布任务不存在。")
    return rollout_read(record)


def start_rollout(
    db: Session,
    actor: UserContext,
    release_id: str,
    confirmation: str,
) -> SkillRolloutRead:
    release = db.get(SkillRelease, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="Skill 发布记录不存在。")
    expected = f"停用并发布 {release.skill_id} {release.version}"
    if confirmation != expected:
        raise HTTPException(status_code=422, detail=f"发布确认文字必须为：{expected}")
    if release.state != "reviewed":
        raise HTTPException(status_code=409, detail="只有审核通过的版本可以创建发布任务。")
    existing = db.scalar(select(SkillRollout).where(SkillRollout.release_id == release.id))
    if existing is not None:
        return rollout_read(existing)
    active = db.scalar(
        select(SkillRollout).where(
            SkillRollout.skill_id == release.skill_id,
            SkillRollout.state.in_(ACTIVE_ROLLOUT_STATES),
        )
    )
    if active is not None:
        raise HTTPException(status_code=409, detail="该 Skill 已有发布任务正在执行。")
    current = registry.get(release.skill_id, include_unpublished=True)
    if current is not None and current.manifest.version == release.version:
        raise HTTPException(status_code=409, detail="新版本号必须与当前线上版本不同。")
    now = datetime.now(UTC)
    record = SkillRollout(
        id=str(uuid.uuid4()),
        release_id=release.id,
        skill_id=release.skill_id,
        state="queued",
        requested_by=actor.user_id,
        target_commit=release.source_commit,
        target_tree_hash=release.source_tree_hash,
        next_attempt_at=now,
    )
    db.add(record)
    record_audit(
        db,
        actor=actor,
        action="admin.skill_rollout.start",
        resource_type="skill_rollout",
        resource_id=record.id,
        details={
            "skill_id": record.skill_id,
            "release_id": record.release_id,
            "target_commit": record.target_commit,
            "target_tree_hash": record.target_tree_hash,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(SkillRollout).where(SkillRollout.release_id == release.id)
        )
        if existing is not None:
            return rollout_read(existing)
        raise HTTPException(status_code=409, detail="Skill 发布任务发生并发冲突。") from exc
    db.refresh(record)
    return rollout_read(record)


def _claim_rollout(db: Session, *, force: bool) -> SkillRollout | None:
    acquire_claim_lock(db)
    now = datetime.now(UTC)
    pending = SkillRollout.state.in_(("queued", "draining"))
    interrupted = (
        SkillRollout.state.in_(("activating", "verifying"))
        & (SkillRollout.updated_at <= now - INTERRUPTED_ROLLOUT_AFTER)
    )
    query = select(SkillRollout).where(pending | interrupted)
    if not force:
        query = query.where(
            interrupted
            | (
                SkillRollout.state.in_(("queued", "draining"))
                & (SkillRollout.next_attempt_at <= now)
            )
        )
    record = db.scalar(query.order_by(SkillRollout.created_at).limit(1))
    if record is None:
        db.commit()
        return None
    actor = _actor(record)
    availability = get_availability(db, record.skill_id)
    if availability.state == "enabled":
        transition_availability(
            db,
            actor,
            record.skill_id,
            "draining",
            "发布任务等待排空",
            acquire_lock=False,
        )
        record = db.get(SkillRollout, record.id)
        assert record is not None
    elif availability.state not in {"draining", "disabled"}:
        record.state = "failed_disabled"
        record.error_message = f"Skill 当前可用状态不能发布：{availability.state}"
        record.finished_at = datetime.now(UTC)
        db.commit()
        return None
    record.attempt_count += 1
    record.started_at = record.started_at or datetime.now(UTC)
    db.commit()
    db.refresh(record)
    return record


def _finish_interrupted_rollout(db: Session, record: SkillRollout) -> None:
    actor = _actor(record)
    release = db.get(SkillRelease, record.release_id)
    registry.refresh()
    active = registry.get(record.skill_id, include_unpublished=True)
    if (
        release is not None
        and release.state == "published"
        and active is not None
        and active.manifest.version == release.version
        and active.skill_hash == release.published_skill_hash
    ):
        binding = db.scalar(
            select(SkillSourceBinding).where(
                SkillSourceBinding.skill_id == record.skill_id
            )
        )
        if binding is not None:
            binding.published_commit = release.source_commit
            binding.published_tree_hash = release.source_tree_hash
            binding.updated_by = actor.user_id
        availability = db.get(SkillAvailability, record.skill_id)
        if availability is not None and availability.state in {"draining", "disabled"}:
            transition_availability(
                db, actor, record.skill_id, "enabled", "中断发布验证通过"
            )
            record = db.get(SkillRollout, record.id)
            assert record is not None
        record.state = "succeeded"
        record.error_message = ""
        record.finished_at = datetime.now(UTC)
        db.commit()
        return
    if active is not None and record.previous_skill_hash == active.skill_hash:
        availability = db.get(SkillAvailability, record.skill_id)
        if availability is not None and availability.state in {"draining", "disabled"}:
            transition_availability(
                db, actor, record.skill_id, "enabled", "中断发布已恢复原版本"
            )
            record = db.get(SkillRollout, record.id)
            assert record is not None
        record.state = "failed"
        record.error_message = "发布进程中断，已核对并恢复原版本。"
        record.finished_at = datetime.now(UTC)
        db.commit()
        return
    _set_failed_disabled(
        db,
        record,
        actor,
        "发布进程中断，当前目录无法与目标版本或原版本核对。",
    )


def _actor(record: SkillRollout) -> UserContext:
    return UserContext(
        user_id=record.requested_by,
        display_name="Skill 管理员",
        role="skill_admin",
        department_id="finance",
    )


def _set_failed_disabled(
    db: Session, record: SkillRollout, actor: UserContext, message: str
) -> None:
    availability = db.get(SkillAvailability, record.skill_id)
    if availability is None:
        availability = SkillAvailability(skill_id=record.skill_id)
        db.add(availability)
    availability.state = "failed_disabled"
    availability.generation = (availability.generation or 0) + 1
    availability.reason = "发布失败且原版本恢复验证未通过"
    availability.changed_by = actor.user_id
    availability.changed_at = datetime.now(UTC)
    record.state = "failed_disabled"
    record.error_message = message
    record.finished_at = datetime.now(UTC)
    db.commit()


def _execute_rollout(db: Session, record: SkillRollout) -> None:
    actor = _actor(record)
    release = db.get(SkillRelease, record.release_id)
    if release is None or release.state != "reviewed":
        raise RuntimeError("待发布版本已经不存在或不再处于审核通过状态。")
    current = registry.get(record.skill_id, include_unpublished=True)
    previous_hash = current.skill_hash if current else ""
    record.previous_skill_hash = previous_hash
    db.commit()
    count = disable_after_drain(db, actor, record.skill_id, "发布任务开始激活")
    if count:
        record = db.get(SkillRollout, record.id)
        assert record is not None
        record.state = "draining"
        record.next_attempt_at = datetime.now(UTC) + timedelta(
            seconds=max(settings.queue_poll_seconds, 0.5)
        )
        db.commit()
        return
    record = db.get(SkillRollout, record.id)
    assert record is not None
    record.state = "activating"
    db.commit()
    activate_reviewed_release(db, actor, release)
    record = db.get(SkillRollout, record.id)
    assert record is not None
    record.state = "verifying"
    db.commit()
    active = registry.get(record.skill_id, include_unpublished=True)
    if active is None or active.manifest.version != release.version:
        raise RuntimeError("Registry 没有加载目标 Skill 版本。")
    binding = db.scalar(
        select(SkillSourceBinding).where(SkillSourceBinding.skill_id == record.skill_id)
    )
    if binding is not None:
        binding.published_commit = release.source_commit
        binding.published_tree_hash = release.source_tree_hash
        binding.updated_by = actor.user_id
        db.commit()
    transition_availability(db, actor, record.skill_id, "enabled", "发布验证通过")
    record = db.get(SkillRollout, record.id)
    assert record is not None
    record.state = "succeeded"
    record.error_message = ""
    record.finished_at = datetime.now(UTC)
    record_audit(
        db,
        actor=actor,
        action="admin.skill_rollout.succeeded",
        resource_type="skill_rollout",
        resource_id=record.id,
        details={
            "skill_id": record.skill_id,
            "release_id": record.release_id,
            "target_commit": record.target_commit,
            "target_tree_hash": record.target_tree_hash,
        },
    )
    db.commit()


def _handle_rollout_failure(db: Session, rollout_id: str, exc: Exception) -> None:
    db.rollback()
    record = db.get(SkillRollout, rollout_id)
    if record is None:
        return
    actor = _actor(record)
    message = sanitize_text(str(exc), error=True)[:2000]
    registry.refresh()
    active = registry.get(record.skill_id, include_unpublished=True)
    restored = bool(
        active
        and record.previous_skill_hash
        and active.skill_hash == record.previous_skill_hash
    )
    availability = db.get(SkillAvailability, record.skill_id)
    if restored and availability is not None and availability.state in {"draining", "disabled"}:
        transition_availability(db, actor, record.skill_id, "enabled", "发布失败，原版本已恢复")
        record = db.get(SkillRollout, rollout_id)
        assert record is not None
        record.state = "failed"
        record.error_message = message
        record.finished_at = datetime.now(UTC)
        db.commit()
        return
    _set_failed_disabled(db, record, actor, message)


def run_rollout_once(*, force: bool = False) -> bool:
    with SessionLocal() as db:
        record = _claim_rollout(db, force=force)
        if record is None:
            return False
        rollout_id = record.id
        try:
            if record.state in {"activating", "verifying"}:
                _finish_interrupted_rollout(db, record)
                return True
            _execute_rollout(db, record)
        except Exception as exc:
            _handle_rollout_failure(db, rollout_id, exc)
        return True
