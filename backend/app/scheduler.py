from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

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
from .task_reminder_workflow_service import sync_reminder_from_workflow


def acquire_claim_lock(db: Session) -> None:
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        connection = db.connection()
        if connection.connection.driver_connection.in_transaction:
            # Upgrade an existing caller/savepoint transaction to a write lock
            # without committing it or issuing an invalid nested BEGIN.
            db.execute(text("UPDATE scheduler_locks SET name = name WHERE name = 'global'"))
        else:
            db.execute(text("BEGIN IMMEDIATE"))
        return
    db.scalar(select(SchedulerLock).where(SchedulerLock.name == "global").with_for_update())


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
        # A lease timeout proves neither process exit nor absence of side effects.
        # Hold the original attempt until its process and outcome are investigated.
        # A null lease remains counted as active and cannot be claimed again.
        run.progress_message = "Worker 租约已过期，原执行结果未知；未重新入队，保留占用等待调查。"
        run.lease_expires_at = None
        db.add(
            RunEvent(
                run_id=run.id,
                event_type="state",
                state="running",
                progress=run.progress,
                message=run.progress_message,
                data_json=json.dumps({"code": "worker_lease_expired_unknown",
                                      "worker_id": run.worker_id,
                                      "attempt": run.attempt_count}),
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
        workflow = db.get(WorkflowSession, action.workflow_id)
        process_exit_confirmed = True
        if workflow and action.name.startswith("ar_"):
            from .ar_process_inspection import action_process_exit_confirmed

            process_exit_confirmed = action_process_exit_confirmed(workflow, action)
            if not process_exit_confirmed:
                # Missing exit evidence is unknown, even if the lease expired.
                # Keep this action unclaimable until process facts are audited.
                action.error_message = "Worker 租约已过期；原进程是否退出尚未证实，继续保留占用并等待调查。"
                action.heartbeat_at = current
                action.lease_expires_at = current + timedelta(
                    seconds=max(5, settings.worker_heartbeat_seconds * 2)
                )
                continue
        action.state = "failed"
        action.error_message = ("Worker 租约已过期，原脚本退出已核实；业务结果仍待核查，本动作未自动重试。"
                                if action.name.startswith("ar_") else
                                "Worker lease expired; the action was stopped without an automatic retry.")
        action.finished_at = current
        from .ar_execution_contract import INVESTIGATION_ACTION

        # A failed AR action is never auto-requeued. Retain the original worker
        # and attempt as immutable attribution for process/result investigation.
        if not (action.name.startswith("ar_") or action.name == INVESTIGATION_ACTION):
            action.worker_id = ""
        action.heartbeat_at = None
        action.lease_expires_at = None
        if workflow:
            if action.name == INVESTIGATION_ACTION:
                action.error_message = "独立调查 Worker 租约已过期，调查结果未确认；原核销失败记录保留，未自动重试。"
                action.result_json = json.dumps({"error_type": "WorkerLeaseExpired", "process_exit_confirmed": False})
                continue
            context = json.loads(workflow.context_json or "{}")
            if action.name.startswith("ar_"):
                context["ar_failure"] = {
                    "action_id": action.id, "phase": action.name.removeprefix("ar_"),
                    "process_exit_confirmed": process_exit_confirmed, "error_type": "WorkerLeaseExpired",
                    "worker_id": action.worker_id, "attempt": action.attempt_count,
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
                        "请先检查原执行和材料结果，再按允许的恢复入口处理。"
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
