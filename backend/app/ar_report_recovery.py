"""Recover only the range report after every financial date has finished."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import HTTPException

from .ar_execution_contract import CONTRACT_VERSION, next_phase


def uses_verified_reports(batch) -> bool:
    if not batch or not batch.workflows:
        return False
    contexts = [json.loads(child.context_json or "{}") for child in batch.workflows]
    if any((context.get("ar_execution") or {}).get("schema_version") == CONTRACT_VERSION for context in contexts):
        return True
    # Empty dates skip initialization. Identify an all-empty v2 batch using its
    # immutable primary Skill snapshot, without changing legacy empty batches.
    if all(context.get("empty_day_skipped") or (context.get("fetched_data") or {}).get("empty_day_skipped") for context in contexts):
        from .ar_execution_runner import execution_version

        primary = min(batch.workflows, key=lambda item: item.batch_sequence)
        try:
            return execution_version(primary) == CONTRACT_VERSION
        except (OSError, ValueError):
            # An unreadable empty-batch snapshot must not select legacy recovery.
            # The status endpoint below explains why recovery is unavailable.
            return True
    return False


def record_report_failure(workflow, action, *, process_exit_confirmed: bool, error_type: str) -> None:
    context = json.loads(workflow.context_json or "{}")
    context["ar_report_failure"] = {
        "action_id": action.id, "process_exit_confirmed": process_exit_confirmed,
        "error_type": error_type, "failed_at": datetime.now(UTC).isoformat(),
    }
    workflow.context_json = json.dumps(context, ensure_ascii=False)


def report_recovery_status(batch) -> dict | None:
    if not uses_verified_reports(batch):
        return None
    children = sorted(batch.workflows, key=lambda item: item.batch_sequence)
    last = children[-1]
    actions = [item for item in last.actions if item.name == "finalize_batch"]
    if not actions:
        return None
    latest = max(actions, key=lambda item: item.queued_at)
    result = {"allowed": False, "failed_action_id": latest.id, "workflow_id": last.id,
              "reason": "范围报告当前不处于可恢复的失败状态。"}
    from .ar_execution_runner import execution_version

    try:
        if execution_version(children[0]) != CONTRACT_VERSION:
            return {**result, "reason": "批次固定快照与已记录执行契约不一致，不能恢复范围报告。"}
    except (OSError, ValueError):
        return {**result, "reason": "批次固定 Skill 快照缺失或执行契约无效，须先核查原版本；不能按旧版恢复。"}
    if batch.state != "failed" or latest.state != "failed" or not latest.finished_at:
        return result
    if any(action.state in {"running", "queued"} for child in children for action in child.actions):
        return {**result, "reason": "批次仍有活动动作，须先确认原报告和 Agent 已停止。"}
    for child in children:
        if child.id != last.id and child.state != "succeeded":
            return {**result, "reason": "前置日期尚未全部完成，不能仅恢复范围报告。"}
        context = json.loads(child.context_json or "{}")
        fetched = context.get("fetched_data") or {}
        empty = context.get("empty_day_skipped") or fetched.get("empty_day_skipped")
        execution = context.get("ar_execution") or {}
        if empty and not execution:
            continue
        try:
            complete = (execution.get("schema_version") == CONTRACT_VERSION
                        and next_phase(execution.get("completed") or []) is None
                        and execution.get("publication") == "verified" and bool(context.get("formal_ledgers")))
        except ValueError:
            complete = False
        if not complete:
            return {**result, "reason": "存在未完成正式核销的日期，不能以范围报告恢复跳过业务步骤。"}
    failure = json.loads(last.context_json or "{}").get("ar_report_failure") or {}
    if failure.get("action_id") != latest.id or failure.get("process_exit_confirmed") is not True:
        return {**result, "reason": "原范围报告执行是否停止尚未核实；保留日核销结果，先核查原进程后再恢复。"}
    attempts = sum(json.loads(item.input_json or "{}").get("recovery_kind") == "range_report" for item in actions)
    if attempts >= 2:
        return {**result, "reason": "范围报告恢复已达到两次上限，需排查原因并使用关联恢复任务。"}
    return {**result, "allowed": True,
            "reason": "可单独恢复范围报告；重新核对各日已发布结果，不重做取数、核销或材料发布。"}


def recover_report(db, batch, actor) -> bool:
    """Called under the claim lock; return False for a non-report recovery."""
    from . import workflow_service as service

    if not uses_verified_reports(batch):
        return False
    for child in batch.workflows:
        db.refresh(child)
        db.expire(child, ["actions"])
    status = report_recovery_status(batch)
    if status is None:
        return False
    if not status["allowed"]:
        raise HTTPException(status_code=409, detail=status["reason"])
    last = next(child for child in batch.workflows if child.id == status["workflow_id"])
    owner = service.workflow_owner_context(db, last)
    if actor.user_id != owner.user_id and not actor.is_admin:
        raise HTTPException(status_code=403, detail="当前账号不能恢复该批次范围报告。")
    service.assert_workflow_execution_enabled(last)
    service._assert_single_flight_available(db, batch.skill_id, exclude_batch_id=batch.id)
    context = json.loads(last.context_json or "{}")
    for key in ("step_error", "error_detail"):
        context.pop(key, None)
    context.update(current_step="finalize_batch", current_step_label="正在恢复范围报告")
    last.context_json = service._json(context)
    last.state, last.stage = "running", "finalizing"
    last.error_message = ""
    last.progress, last.progress_message = 99, status["reason"]
    action = service._new_action(db, last, "finalize_batch", {
        "recovered_from": status["failed_action_id"], "recovery_kind": "range_report",
    })
    batch.state, batch.progress = "finalizing", 99
    batch.error_message = ""
    batch.progress_message = "仅恢复范围报告，各日核销及已发布材料保持不变"
    service.record_audit(db, actor=actor, action="workflow.batch.report.recover", resource_type="workflow_batch",
                         resource_id=batch.id, details={"failed_action_id": status["failed_action_id"], "action_id": action.id})
    db.commit()
    db.refresh(batch)
    return True
