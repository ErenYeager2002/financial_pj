from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .audit_service import record_audit
from .auth import UserContext
from .contracts import SkillActiveWorkRead, SkillAvailabilityRead
from .models import RunRecord, SkillAvailability, WorkflowBatch, WorkflowSession
from .registry import registry
from .scheduler import acquire_claim_lock

RUN_TERMINAL_STATES = {"succeeded", "failed", "timed_out", "cancelled"}
WORKFLOW_TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
ACTIVE_WORK_DETAIL_LIMIT = 200


def _work_state(state: str, stage: str = "") -> tuple[str, str]:
    if state in {"queued", "created", "validating"}:
        return "queued", ""
    if state in {"waiting_confirmation", "waiting_approval"} or stage in {
        "awaiting_apply_confirmation",
        "awaiting_date_confirmation",
        "awaiting_fetched_data_confirmation",
        "waiting_approval",
    }:
        return "waiting_confirmation", "等待人工确认后继续。"
    if stage in {
        "awaiting_date",
        "awaiting_files",
        "supplementing_fetched_data",
        "awaiting_fetched_data",
    }:
        return "waiting_material", "等待业务日期或材料。"
    if state in {"running", "active", "cancelling"}:
        return "running", ""
    return "unknown", "当前状态需要核实。"


def _active_work_details(
    db: Session, skill_id: str
) -> tuple[list[SkillActiveWorkRead], bool]:
    items: list[SkillActiveWorkRead] = []
    runs = list(
        db.scalars(
            select(RunRecord)
            .where(
                RunRecord.skill_id == skill_id,
                RunRecord.state.not_in(RUN_TERMINAL_STATES),
            )
            .order_by(
                func.coalesce(
                    RunRecord.finished_at, RunRecord.started_at,
                    RunRecord.queued_at, RunRecord.created_at,
                ).desc(),
                RunRecord.id.desc(),
            )
            .limit(ACTIVE_WORK_DETAIL_LIMIT + 1)
        ).all()
    )
    for run in runs:
        state, reason = _work_state(run.state)
        items.append(
            SkillActiveWorkRead(
                reference_type="run",
                reference_id=run.id,
                display_id=run.id,
                state=state,
                original_state=run.state,
                progress=run.progress,
                progress_message=run.progress_message,
                queued_at=run.queued_at,
                started_at=run.started_at,
                updated_at=run.finished_at or run.started_at or run.queued_at or run.created_at,
                waiting_reason=reason,
            )
        )

    workflows = list(
        db.scalars(
            select(WorkflowSession)
            .where(
                WorkflowSession.skill_id == skill_id,
                WorkflowSession.batch_id.is_(None),
                WorkflowSession.state.not_in(WORKFLOW_TERMINAL_STATES),
            )
            .order_by(WorkflowSession.updated_at.desc())
            .limit(ACTIVE_WORK_DETAIL_LIMIT + 1)
        ).all()
    )
    for workflow in workflows:
        state, reason = _work_state(workflow.state, workflow.stage)
        items.append(
            SkillActiveWorkRead(
                reference_type="workflow",
                reference_id=workflow.id,
                display_id=workflow.display_id or workflow.id,
                state=state,
                original_state=workflow.state,
                stage=workflow.stage,
                progress=workflow.progress,
                progress_message=workflow.progress_message,
                queued_at=workflow.created_at,
                started_at=workflow.created_at if workflow.state == "running" else None,
                updated_at=workflow.updated_at,
                waiting_reason=reason,
            )
        )

    batches = list(
        db.scalars(
            select(WorkflowBatch)
            .where(
                WorkflowBatch.skill_id == skill_id,
                WorkflowBatch.state.not_in(WORKFLOW_TERMINAL_STATES),
            )
            .order_by(WorkflowBatch.updated_at.desc())
            .limit(ACTIVE_WORK_DETAIL_LIMIT + 1)
        ).all()
    )
    batch_ids = [batch.id for batch in batches]
    batch_children: dict[str, list[WorkflowSession]] = {}
    if batch_ids:
        children = list(
            db.scalars(
                select(WorkflowSession)
                .where(
                    WorkflowSession.batch_id.in_(batch_ids),
                    WorkflowSession.state.not_in(WORKFLOW_TERMINAL_STATES),
                )
                .order_by(WorkflowSession.updated_at.desc())
            ).all()
        )
        for child in children:
            if child.batch_id:
                batch_children.setdefault(child.batch_id, []).append(child)
    for batch in batches:
        state, reason = _work_state(batch.state)
        stage = ""
        progress_message = batch.progress_message
        representative = None
        candidates = batch_children.get(batch.id, [])
        if candidates:
            representative = min(
                candidates,
                key=lambda child: (
                    0
                    if _work_state(child.state, child.stage)[0]
                    in {"waiting_material", "waiting_confirmation"}
                    else 1
                    if _work_state(child.state, child.stage)[0] == "running"
                    else 2,
                    -(child.updated_at.timestamp() if child.updated_at else 0),
                ),
            )
            child_state, child_reason = _work_state(
                representative.state, representative.stage
            )
            if child_state != "unknown":
                state = child_state
                reason = child_reason
                stage = representative.stage
                progress_message = representative.progress_message or batch.progress_message
        items.append(
            SkillActiveWorkRead(
                reference_type="workflow_batch",
                reference_id=batch.id,
                display_id=batch.display_id or batch.id,
                state=state,
                original_state=batch.state,
                stage=stage,
                progress=batch.progress,
                progress_message=progress_message,
                queued_at=batch.created_at,
                started_at=batch.created_at if batch.state == "running" else None,
                updated_at=batch.updated_at,
                waiting_reason=reason,
            )
        )

    items.sort(key=lambda item: item.updated_at, reverse=True)
    return items[:ACTIVE_WORK_DETAIL_LIMIT], len(items) > ACTIVE_WORK_DETAIL_LIMIT


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
                WorkflowSession.batch_id.is_(None),
                WorkflowSession.state.not_in(WORKFLOW_TERMINAL_STATES),
            )
        )
        or 0
    )
    batches = (
        db.scalar(
            select(func.count())
            .select_from(WorkflowBatch)
            .where(
                WorkflowBatch.skill_id == skill_id,
                WorkflowBatch.state.not_in(WORKFLOW_TERMINAL_STATES),
            )
        )
        or 0
    )
    return int(runs + workflows + batches)


def _read(db: Session, record: SkillAvailability) -> SkillAvailabilityRead:
    active_work, active_work_truncated = _active_work_details(db, record.skill_id)
    current = registry.get(record.skill_id, include_unpublished=True)
    return SkillAvailabilityRead(
        skill_id=record.skill_id,
        state=record.state,
        generation=record.generation,
        reason=record.reason,
        changed_by=record.changed_by,
        changed_at=record.changed_at,
        active_work_count=active_work_count(db, record.skill_id),
        active_work=active_work,
        active_work_truncated=active_work_truncated,
        current_version=current.manifest.version if current else "",
        current_skill_hash=current.skill_hash if current else "",
    )


def get_availability(db: Session, skill_id: str) -> SkillAvailabilityRead:
    if registry.get(skill_id, include_unpublished=True) is None:
        raise HTTPException(status_code=404, detail="平台不存在该 Skill。")
    record = db.get(SkillAvailability, skill_id)
    if record is None:
        active_work, active_work_truncated = _active_work_details(db, skill_id)
        current = registry.get(skill_id, include_unpublished=True)
        return SkillAvailabilityRead(
            skill_id=skill_id,
            state="enabled",
            generation=0,
            reason="",
            changed_by="",
            changed_at=None,
            active_work_count=active_work_count(db, skill_id),
            active_work=active_work,
            active_work_truncated=active_work_truncated,
            current_version=current.manifest.version if current else "",
            current_skill_hash=current.skill_hash if current else "",
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
