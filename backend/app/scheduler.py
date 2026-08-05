from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from .models import (
    RunEvent,
    RunRecord,
    SchedulerLock,
    WorkflowAction,
    WorkflowBatch,
    WorkflowMessage,
    WorkflowSession,
)
from .settings import settings


def acquire_claim_lock(db: Session) -> None:
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
        return
    db.scalar(select(SchedulerLock).where(SchedulerLock.name == "global").with_for_update())


def _run_is_retryable(run: RunRecord) -> bool:
    try:
        manifest = json.loads(run.manifest_snapshot)
    except (TypeError, json.JSONDecodeError):
        return False
    risk = manifest.get("risk", {})
    return (
        run.adapter != "rpa"
        and risk.get("level", "read_only") == "read_only"
        and run.attempt_count < settings.worker_max_attempts
    )


def recover_expired_jobs(db: Session, now: datetime | None = None) -> None:
    current = now or datetime.now(UTC)
    expired_runs = list(
        db.scalars(
            select(RunRecord).where(
                RunRecord.state == "running",
                RunRecord.lease_expires_at.is_not(None),
                RunRecord.lease_expires_at < current,
            )
        ).all()
    )
    for run in expired_runs:
        if _run_is_retryable(run):
            run.state = "queued"
            run.progress = 0
            run.progress_message = "上一个 Worker 租约过期，任务已重新排队"
            run.started_at = None
            event_state = "queued"
            event_message = run.progress_message
        else:
            run.state = "failed"
            run.error_message = "Worker 中断且执行租约已过期，请人工检查后重新提交。"
            run.progress_message = "Worker 中断，任务未自动重试"
            run.finished_at = current
            event_state = "failed"
            event_message = run.error_message
        run.worker_id = ""
        run.heartbeat_at = None
        run.lease_expires_at = None
        db.add(
            RunEvent(
                run_id=run.id,
                event_type="state",
                state=event_state,
                progress=run.progress,
                message=event_message,
                data_json="{}",
            )
        )

    expired_actions = list(
        db.scalars(
            select(WorkflowAction).where(
                WorkflowAction.state == "running",
                WorkflowAction.lease_expires_at.is_not(None),
                WorkflowAction.lease_expires_at < current,
            )
        ).all()
    )
    for action in expired_actions:
        action.state = "failed"
        action.error_message = "Worker 中断且执行租约已过期，请人工检查后重试。"
        action.finished_at = current
        action.worker_id = ""
        action.heartbeat_at = None
        action.lease_expires_at = None
        workflow = db.get(WorkflowSession, action.workflow_id)
        if workflow:
            workflow.state = "failed"
            workflow.stage = "failed"
            workflow.error_message = action.error_message
            workflow.progress_message = "Worker 中断，等待人工恢复"
            if workflow.batch_id:
                batch = db.get(WorkflowBatch, workflow.batch_id)
                if batch:
                    batch.state = "failed"
                    batch.error_message = action.error_message
                    batch.progress_message = (
                        f"第 {workflow.batch_sequence} 天（{workflow.reconciliation_date}）"
                        "执行中断，后续日期已暂停"
                    )
                    batch.updated_at = current
            db.add(
                WorkflowMessage(
                    workflow_id=workflow.id,
                    role="assistant",
                    content=(
                        "执行 Worker 意外中断。为避免重复写入，本动作没有自动重试；"
                        "请先检查结果，再重新发起。"
                    ),
                    data_json='{"kind":"worker_lease_expired"}',
                )
            )


def active_run_count(db: Session, skill_id: str, now: datetime) -> int:
    return int(
        db.scalar(
            select(func.count(RunRecord.id)).where(
                RunRecord.skill_id == skill_id,
                RunRecord.state == "running",
                or_(
                    RunRecord.lease_expires_at.is_(None),
                    RunRecord.lease_expires_at >= now,
                ),
            )
        )
        or 0
    )


def active_workflow_count(db: Session, skill_id: str, now: datetime) -> int:
    return int(
        db.scalar(
            select(func.count(WorkflowAction.id))
            .join(
                WorkflowSession,
                WorkflowSession.id == WorkflowAction.workflow_id,
            )
            .where(
                WorkflowSession.skill_id == skill_id,
                WorkflowAction.state == "running",
                or_(
                    WorkflowAction.lease_expires_at.is_(None),
                    WorkflowAction.lease_expires_at >= now,
                ),
            )
        )
        or 0
    )
