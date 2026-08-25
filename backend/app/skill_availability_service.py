from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .audit_service import record_audit
from .auth import UserContext
from .contracts import SkillAvailabilityRead
from .models import RunRecord, SkillAvailability, WorkflowSession
from .registry import registry
from .scheduler import acquire_claim_lock

RUN_TERMINAL_STATES = {"succeeded", "failed", "timed_out", "cancelled"}
WORKFLOW_TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


def active_work_count(db: Session, skill_id: str) -> int:
    runs = (
        db.scalar(
            select(func.count())
            .select_from(RunRecord)
            .where(
                RunRecord.skill_id == skill_id,
                RunRecord.state.not_in(RUN_TERMINAL_STATES),
            )
        )
        or 0
    )
    workflows = (
        db.scalar(
            select(func.count())
            .select_from(WorkflowSession)
            .where(
                WorkflowSession.skill_id == skill_id,
                WorkflowSession.state.not_in(WORKFLOW_TERMINAL_STATES),
            )
        )
        or 0
    )
    return int(runs + workflows)


def _read(db: Session, record: SkillAvailability) -> SkillAvailabilityRead:
    return SkillAvailabilityRead(
        skill_id=record.skill_id,
        state=record.state,
        generation=record.generation,
        reason=record.reason,
        changed_by=record.changed_by,
        changed_at=record.changed_at,
        active_work_count=active_work_count(db, record.skill_id),
    )


def get_availability(db: Session, skill_id: str) -> SkillAvailabilityRead:
    if registry.get(skill_id, include_unpublished=True) is None:
        raise HTTPException(status_code=404, detail="平台不存在该 Skill。")
    record = db.get(SkillAvailability, skill_id)
    if record is None:
        return SkillAvailabilityRead(
            skill_id=skill_id,
            state="enabled",
            generation=0,
            reason="",
            changed_by="",
            changed_at=None,
            active_work_count=active_work_count(db, skill_id),
        )
    return _read(db, record)


def list_availability(db: Session) -> list[SkillAvailabilityRead]:
    return [
        get_availability(db, skill.manifest.id) for skill in registry.list(include_disabled=True)
    ]


def assert_skill_accepting_new_work(
    db: Session, skill_id: str, *, acquire_lock: bool = True
) -> None:
    if acquire_lock:
        acquire_claim_lock(db)
    record = db.get(SkillAvailability, skill_id)
    if record is not None and record.state != "enabled":
        raise HTTPException(
            status_code=409,
            detail=f"Skill 当前为 {record.state}，暂停接收新任务。",
        )


def transition_availability(
    db: Session,
    actor: UserContext,
    skill_id: str,
    target_state: str,
    reason: str,
    *,
    acquire_lock: bool = True,
) -> SkillAvailabilityRead:
    if registry.get(skill_id, include_unpublished=True) is None:
        raise HTTPException(status_code=404, detail="平台不存在该 Skill。")
    if acquire_lock:
        acquire_claim_lock(db)
    record = db.get(SkillAvailability, skill_id)
    if record is None:
        record = SkillAvailability(skill_id=skill_id, state="enabled")
        db.add(record)
        db.flush()
    current = record.state
    if current == target_state:
        return _read(db, record)
    allowed = {
        "enabled": {"draining"},
        "draining": {"enabled", "disabled"},
        "disabled": {"enabled"},
        "failed_disabled": set(),
    }
    if target_state not in allowed[current]:
        raise HTTPException(
            status_code=409,
            detail=f"Skill 可用状态不能从 {current} 直接变为 {target_state}；必须先进入 draining。",
        )
    count = active_work_count(db, skill_id)
    if target_state == "disabled" and count:
        raise HTTPException(status_code=409, detail=f"Skill 仍有 {count} 个活动任务。")
    record.state = target_state
    record.generation += 1
    record.reason = reason.strip()
    record.changed_by = actor.user_id
    record.changed_at = datetime.now(UTC)
    record_audit(
        db,
        actor=actor,
        action="admin.skill_availability.transition",
        resource_type="skill_availability",
        resource_id=skill_id,
        details={
            "skill_id": skill_id,
            "from_state": current,
            "to_state": target_state,
            "generation": record.generation,
            "active_work_count": count,
        },
    )
    db.commit()
    db.refresh(record)
    return _read(db, record)


def disable_after_drain(db: Session, actor: UserContext, skill_id: str, reason: str) -> int:
    acquire_claim_lock(db)
    record = db.get(SkillAvailability, skill_id)
    if record is None or record.state != "draining":
        raise HTTPException(status_code=409, detail="Skill 尚未进入 draining。")
    count = active_work_count(db, skill_id)
    if count:
        db.commit()
        return count
    transition_availability(
        db,
        actor,
        skill_id,
        "disabled",
        reason,
        acquire_lock=False,
    )
    return 0
