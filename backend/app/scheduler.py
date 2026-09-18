from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from .models import (
    RunEvent,
    RunRecord,
    SchedulerLock,
    TaskDiscoveryCheck,
    WorkflowAction,
    WorkflowBatch,
    WorkflowMessage,
    WorkflowSession,
)
from .reconciliation_runner import PI_HARNESS_ACTION
from .ar_execution_contract import publication_needs_completion
from .settings import settings
from .step_runtime_service import finish_run_execution_step, queue_run_execution_step
from .task_reminder_workflow_service import sync_reminder_from_workflow


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
            ).with_for_update()
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
            queue_run_execution_step(db, run)
        else:
            run.state = "failed"
            run.error_message = "Worker 中断且执行租约已过期，请人工检查后重新提交。"
            run.progress_message = "Worker 中断，任务未自动重试"
            run.finished_at = current
            event_state = "failed"
            event_message = run.error_message
            finish_run_execution_step(
                db,
                run,
                state="failed",
                error_code="worker_lease_expired",
                error_message=run.error_message,
            )
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
            from .ar_execution_contract import INVESTIGATION_ACTION

            if action.name == INVESTIGATION_ACTION:
                action.error_message = "独立调查 Worker 租约已过期，调查结果未确认；原核销失败记录保留，未自动重试。"
                action.result_json = json.dumps({"error_type": "WorkerLeaseExpired", "process_exit_confirmed": False})
                continue
            context = json.loads(workflow.context_json or "{}")
            if action.name.startswith("ar_"):
                context["ar_failure"] = {
                    "action_id": action.id, "phase": action.name.removeprefix("ar_"),
                    "process_exit_confirmed": False, "error_type": "WorkerLeaseExpired",
                    "failed_at": current.isoformat(),
                }
                workflow.context_json = json.dumps(context, ensure_ascii=False)
            if action.name == "finalize_batch":
                from .ar_report_recovery import record_report_failure, uses_verified_reports

                if uses_verified_reports(workflow.batch):
                    record_report_failure(workflow, action, process_exit_confirmed=False, error_type="WorkerLeaseExpired")
                    context = json.loads(workflow.context_json or "{}")
            if action.name == PI_HARNESS_ACTION and (
                workflow.state in {"succeeded", "cancelled"}
                or publication_needs_completion(context)
                or ((context.get("ar_execution") or {}).get("publication") == "verified" and workflow.stage == "finalizing")
            ):
                context["ar_harness_failure"] = {"action_id": action.id, "message": action.error_message}
                workflow.context_json = json.dumps(context, ensure_ascii=False)
                sync_reminder_from_workflow(db, workflow)
                continue
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
            sync_reminder_from_workflow(db, workflow)


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
                WorkflowAction.name != PI_HARNESS_ACTION,
                or_(
                    WorkflowAction.lease_expires_at.is_(None),
                    WorkflowAction.lease_expires_at >= now,
                ),
            )
        )
        or 0
    )


def active_or_queued_workflow_count(db: Session, skill_id: str) -> int:
    action_count = int(
        db.scalar(
            select(func.count(WorkflowAction.id))
            .join(WorkflowSession, WorkflowSession.id == WorkflowAction.workflow_id)
            .where(
                WorkflowSession.skill_id == skill_id,
                WorkflowAction.state.in_(("queued", "running")),
            )
        )
        or 0
    )
    cancelling_count = int(
        db.scalar(
            select(func.count(WorkflowSession.id)).where(
                WorkflowSession.skill_id == skill_id,
                WorkflowSession.state == "cancelling",
            )
        )
        or 0
    )
    return action_count + cancelling_count


def active_task_discovery_count(db: Session, skill_id: str, now: datetime) -> int:
    return int(
        db.scalar(
            select(func.count(TaskDiscoveryCheck.id)).where(
                TaskDiscoveryCheck.skill_id == skill_id,
                TaskDiscoveryCheck.state == "running",
                or_(
                    TaskDiscoveryCheck.lease_expires_at.is_(None),
                    TaskDiscoveryCheck.lease_expires_at >= now,
                ),
            )
        )
        or 0
    )
