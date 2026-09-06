"""Explicit, bounded recovery of an unfinished v2 phase, never an apply retry."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .ar_execution_contract import CONTRACT_VERSION, next_phase
from .auth import UserContext
from .models import WorkflowSession
from .reconciliation_runner import PI_HARNESS_ACTION

MAX_RECOVERIES = 2
RECOVERABLE = {
    "inspect_materials", "classify_receipts", "review_order_evidence", "validate_reconciliation",
    "build_initial_report", "stage_reconciliation", "verify_reconciliation", "rescan_holds",
    "build_final_report", "review_final_report", "publish_reconciliation", "complete_reconciliation",
}


class ArRecoveryRequest(BaseModel):
    failed_action_id: str
    checkpoint_fingerprint: str


def _unstarted_queued_phase(workflow: WorkflowSession, phase) -> tuple[list, str]:
    """Identify an unclaimed request, never infer non-execution from queue state alone."""
    from .resource_policy import workflow_root

    queued = [item for item in workflow.actions if item.state == "queued"]
    if not queued:
        return [], ""
    if len(queued) != 1 or queued[0].name != f"ar_{phase.name}":
        return [], "排队动作与当前未完成阶段不唯一对应，不能撤销后重新派发。"
    action = queued[0]
    if (action.workflow_id != workflow.id or action.attempt_count != 0 or action.started_at
            or action.finished_at or action.worker_id or action.heartbeat_at or action.lease_expires_at
            or action.error_message):
        return [], "排队动作已有领取、执行或结束痕迹，须先核查原执行，不能按未启动处理。"
    try:
        request = json.loads(action.input_json or "{}")
        result = json.loads(action.result_json or "{}")
        if not isinstance(request, dict) or request.get("cancel_requested") or result != {}:
            return [], "排队动作已有取消请求或执行结果，不能按未启动处理。"
        root = workflow_root(workflow.owner_id, workflow.id)
        journal_root = root / "execution-processes"
        journal = journal_root / action.id
        if (not root.is_dir() or root.is_symlink() or journal_root.is_symlink() or journal.is_symlink()
                or (journal_root.exists() and not journal_root.is_dir())
                or not journal.resolve().is_relative_to(root.resolve()) or journal.exists()):
            return [], "排队动作存在进程证据或证据目录异常，不能确认从未启动。"
    except (OSError, ValueError, TypeError):
        return [], "排队动作的请求、结果或进程证据无法核查，不能恢复派发。"
    return queued, ""


def recovery_status(workflow: WorkflowSession, *, include_write_inspection: bool = False) -> dict:
    context = json.loads(workflow.context_json or "{}")
    state = context.get("ar_execution") or {}
    encoded = json.dumps(state, ensure_ascii=False, sort_keys=True).encode("utf-8")
    result = {"allowed": False, "reason": "当前任务没有可恢复的执行阶段。",
              "failed_action_id": "", "checkpoint_fingerprint": hashlib.sha256(encoded).hexdigest(),
              "recovery_kind": "phase"}
    if state.get("schema_version") != CONTRACT_VERSION or workflow.state != "failed":
        return result
    if any(action.state == "running" for action in workflow.actions):
        return {**result, "reason": "仍有执行动作正在运行，不能恢复或重新派发。"}
    try:
        phase = next_phase(state.get("completed") or [])
    except ValueError:
        return {**result, "reason": "阶段检查点不完整，不能推测应该恢复的步骤。"}
    if phase is None:
        return {**result, "reason": "业务阶段已结束，需核查正式完成登记或范围报告，不能重新派发核销。"}
    failure = context.get("ar_failure") or {}
    action = next((item for item in workflow.actions if item.id == failure.get("action_id")), None)
    phase_failed = (action is not None and action.name == f"ar_{phase.name}"
                    and action.state == "failed" and action.finished_at)
    queued = [item for item in workflow.actions if item.state == "queued"]
    if queued and phase_failed:
        return {**result, "reason": "业务阶段失败后仍有排队动作，须核查两者关系，不能重复派发失败阶段。"}
    if not phase_failed:
        completed_names = {f"ar_{name}" for name in state.get("completed", [])}
        uncertain = [item for item in workflow.actions if item.name.startswith("ar_")
                     and item.name not in completed_names
                     and (item.started_at or item.attempt_count or item.state in {"failed", "succeeded"})]
        if uncertain:
            return {**result, "reason": "存在尚未核清的业务阶段执行记录，不能只恢复 Agent 后继续写入。"}
        if workflow.execution_mode != "pi_harness":
            return {**result, "reason": "当前任务未使用 Agent 执行方式，不能通过恢复 Agent 继续。"}
        if queued and context.get("stop_after_action"):
            return {**result, "reason": "任务已要求停止后续动作，不能通过 Agent 恢复重新派发排队阶段。"}
        queued, queue_reason = _unstarted_queued_phase(workflow, phase)
        if queue_reason:
            return {**result, "reason": queue_reason}
        harnesses = [item for item in workflow.actions if item.name == PI_HARNESS_ACTION
                     and item.state == "failed" and item.finished_at]
        if not harnesses:
            return {**result, "reason": "缺少已停止的 Agent 执行记录，不能恢复调查。"}
        harness = max(harnesses, key=lambda item: item.queued_at)
        attempts = sum(item.name == PI_HARNESS_ACTION
                       and json.loads(item.input_json or "{}").get("recovery_kind") == "harness"
                       for item in workflow.actions)
        if attempts >= MAX_RECOVERIES:
            return {**result, "reason": "本任务的 Agent 调查恢复已达到两次上限，需核查原因并使用关联恢复任务。"}
        queue_binding = [{"id": item.id, "name": item.name, "input_json": item.input_json,
                          "queued_at": item.queued_at.isoformat()} for item in queued]
        fingerprint = hashlib.sha256(encoded + json.dumps(queue_binding, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        return {**result, "allowed": True, "failed_action_id": harness.id, "recovery_kind": "harness",
                "checkpoint_fingerprint": fingerprint,
                "superseded_queued_action_ids": [item.id for item in queued],
                "reason": (f"已核对排队的{phase.label}尚未被领取且没有启动记录；恢复时撤销原排队请求，再由 Agent 继续该阶段。"
                           if queued else f"可恢复 Agent 调查，继续至{phase.label}；保留已完成阶段和已读证据，不重做核销。")}
    from .ar_process_inspection import inspect_process_evidence

    inspection = inspect_process_evidence(workflow, action, failure)
    result.update(failed_action_id=action.id, process_inspection=inspection)
    write_fingerprint = ""
    if include_write_inspection and phase.name in {"write_ledger", "write_receipt_flow"}:
        from .ar_write_inspection import inspect_write_evidence

        write_inspection = inspect_write_evidence(workflow, action)
        result["write_inspection"] = write_inspection
        write_fingerprint = write_inspection["fingerprint"]
    result["checkpoint_fingerprint"] = hashlib.sha256(
        encoded + inspection["fingerprint"].encode("ascii") + write_fingerprint.encode("ascii")
    ).hexdigest()
    if not inspection["verified"]:
        return {**result, "reason": inspection["message"]}
    if failure.get("process_exit_confirmed") is not True:
        return {**result, "reason": "脚本进程证据已读取，但原 Worker 未确认执行已停止；仍须核查外部应用及阶段结果，不能重新派发。"}
    if phase.name != failure.get("phase"):
        return {**result, "reason": "失败动作与当前未完成步骤不一致，需核查执行记录。"}
    if phase.name not in RECOVERABLE:
        return {**result, "reason": "盈亏或流转写入失败，不提供重复写入；需先核查实际结果并通过关联恢复任务处理。"}
    attempts = sum(item.name == action.name and bool(json.loads(item.input_json or "{}").get("recovered_from"))
                   for item in workflow.actions)
    if attempts >= MAX_RECOVERIES:
        return {**result, "reason": "本阶段恢复次数已达到上限，需修复原因后使用关联的新版本任务。"}
    return {**result, "allowed": True, "failed_action_id": action.id,
            "reason": f"可恢复{phase.label}；将重新核对材料版本和暂存指纹，不重做已完成阶段。"}


def recover_execution(db: Session, workflow: WorkflowSession, request: ArRecoveryRequest, actor: UserContext) -> None:
    from . import workflow_service as service
    from .ar_execution_runner import ArExecution
    from .ar_agent_budget import initial_budget
    from .reconciliation_runner import PI_HARNESS_ACTION
    from .scheduler import acquire_claim_lock

    db.commit()
    acquire_claim_lock(db)
    db.refresh(workflow)
    db.expire(workflow, ["actions"])
    service.workflow_owner_context(db, workflow)
    service._assert_single_flight_available(db, workflow.skill_id, exclude_workflow_id=workflow.id,
                                            exclude_batch_id=workflow.batch_id or "")
    status = recovery_status(workflow)
    if (not status["allowed"] or request.failed_action_id != status["failed_action_id"]
            or request.checkpoint_fingerprint != status["checkpoint_fingerprint"]):
        raise HTTPException(status_code=409, detail=status["reason"] if not status["allowed"] else "执行检查点已变化，请刷新任务。")
    failed = next(action for action in workflow.actions if action.id == request.failed_action_id)
    execution = ArExecution(db, failed, workflow)
    try:
        execution.verify_input_binding()
        if "stage_reconciliation" in execution.execution.get("completed", []):
            stage, _ = execution.staging()
            for name in reversed(execution.execution["completed"]):
                previous = execution.execution["steps"][name]
                if previous.get("files") or previous.get("manifest", {}).get("files"):
                    execution._require_staged_fingerprints(stage, name)
                    break
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    context = json.loads(workflow.context_json or "{}")
    context.pop("step_error", None)
    context.pop("error_detail", None)
    context["ar_recovery"] = {"failed_action_id": failed.id, "checkpoint_fingerprint": request.checkpoint_fingerprint}
    superseded = status.get("superseded_queued_action_ids", [])
    for pending in workflow.actions:
        if pending.id in superseded:
            pending.state, pending.finished_at = "cancelled", datetime.now(UTC)
            pending.error_message = "Agent 中断后显式恢复：本请求尚未被领取，已撤销原排队；历史请求保留。"
            pending.result_json = service._json({"recovery_disposition": "superseded_before_claim",
                                                 "recovered_from_harness": failed.id,
                                                 "checkpoint_fingerprint": request.checkpoint_fingerprint})
    context["ar_recovery"]["superseded_queued_action_ids"] = superseded
    if workflow.execution_mode == "pi_harness":
        context.setdefault("ar_agent_budget_history", []).append({
            "recovered_from": failed.id, "budget": context.get("ar_agent_budget"),
            "stop": context.pop("ar_agent_stop", None),
        })
        context["ar_agent_budget"] = initial_budget()
    workflow.context_json = service._json(context)
    workflow.state = "running"
    workflow.stage = "applying" if "stage_reconciliation" in execution.execution["completed"] else "preparing"
    workflow.error_message = ""
    workflow.progress_message = status["reason"]
    service._new_action(db, workflow, failed.name, {"recovered_from": failed.id,
                                                  "recovery_kind": status["recovery_kind"],
                                                  "superseded_queued_action_ids": superseded})
    if workflow.execution_mode == "pi_harness" and status["recovery_kind"] != "harness":
        service._new_action(db, workflow, PI_HARNESS_ACTION, {"recovered_from": failed.id})
    if workflow.batch_id:
        batch = workflow.batch
        if batch.state != "failed":
            raise HTTPException(status_code=409, detail="所属批次当前状态不允许恢复失败日期。")
        batch.state = "cancelling" if context.get("stop_after_action") else "running"
        batch.error_message = ""
        batch.progress_message = f"恢复第 {workflow.batch_sequence} 天的未完成阶段"
    service.record_audit(db, actor=actor,
                         action="workflow.ar_execution.recover", resource_type="workflow", resource_id=workflow.id,
                         details={"failed_action_id": failed.id, "phase": failed.name,
                                  "recovery_kind": status["recovery_kind"],
                                  "superseded_queued_action_ids": superseded})
    db.commit()
