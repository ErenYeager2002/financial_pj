"""Retention holds for unresolved AR executions, separate from replay permission."""
from __future__ import annotations

import json

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from .ar_execution_contract import CONTRACT_VERSION, PHASES, next_phase
from .models import WorkflowSession

MAX_BUNDLE_REFERENCES = 500


def _hold(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def workflow_retention_hold(workflow: WorkflowSession) -> dict | None:
    """A terminal workflow alone does not release its recovery evidence."""
    if workflow.skill_id != "ar-hexiao-daily":
        return None
    try:
        context = json.loads(workflow.context_json or "{}")
        if not isinstance(context, dict):
            raise ValueError("invalid execution context")
        state = context.get("ar_execution")
        if not state and not context.get("ar_failure") and not any(
            item.name.startswith("ar_") for item in workflow.actions
        ):
            from .ar_execution_runner import execution_version

            if not execution_version(workflow):
                return None
        if any(item.state in {"queued", "running"} for item in workflow.actions):
            return _hold("active_action", "仍有排队或运行中的执行、恢复或调查动作，保留原始取数与暂存材料。")
        if workflow.state not in {"succeeded", "failed", "cancelled"}:
            return _hold("active_workflow", "核销任务尚未结束，保留原始取数与暂存材料。")
        if workflow.batch_id:
            batch = workflow.batch
            if batch is None or batch.state != "succeeded":
                return _hold("unfinished_batch", "所属批次尚未全部完成，原始取数与暂存材料仍用于失败日期处理或范围报告恢复。")
        fetched = context.get("fetched_data") or {}
        if not state and (context.get("empty_day_skipped") is True or fetched.get("empty_day_skipped") is True):
            from .workflow_service import _is_confirmed_empty_reconciliation_date

            if (workflow.state == "succeeded" and workflow.stage == "completed"
                    and fetched.get("review_status") == "confirmed"
                    and _is_confirmed_empty_reconciliation_date(fetched, workflow.reconciliation_date)
                    and not context.get("ar_failure")
                    and not any(item.name.startswith("ar_") for item in workflow.actions)):
                # Empty dates neither execute the write phases nor publish a
                # new material version. Do not demand nonexistent receipts.
                return None
            return _hold("empty_day_unconfirmed", "空日标记与取数确认、逐项零记录或任务终态不一致，保留原始材料供核查。")
        if not isinstance(state, dict) or state.get("schema_version") != CONTRACT_VERSION:
            return _hold("execution_not_confirmed", "新版执行尚未初始化或执行记录无效，保留原始材料供核查，不能按普通终态清理。")
        phase = next_phase(state.get("completed") or [])
        if phase is not None:
            return _hold("unfinished_phase", f"{phase.label}尚未登记完成，保留原始取数与暂存材料供调查或恢复。")
        if state.get("publication") != "verified":
            return _hold("publication_unconfirmed", "材料发布状态尚未核实，保留原始取数与暂存材料，不能按超期删除。")
        formal = context.get("formal_ledgers")
        if not isinstance(formal, dict) or not formal.get("file_id") or not formal.get("sha256"):
            return _hold("formal_registration_missing", "正式辅助台账登记不完整，保留原始取数与暂存材料。")
        if workflow.state != "succeeded":
            return _hold("terminal_outcome_unconfirmed", "执行检查点与任务终态不一致，保留材料供核对；未将失败或取消视为完成。")
        for completed_phase in PHASES:
            actions = [item for item in workflow.actions if item.name == f"ar_{completed_phase.name}"]
            latest = max(actions, key=lambda item: item.queued_at, default=None)
            if latest is None or latest.state != "succeeded" or latest.finished_at is None:
                return _hold("phase_fact_missing", f"{completed_phase.label}缺少一致的完成动作，保留材料供核查。")
        return None
    except (OSError, ValueError, TypeError, AttributeError):
        return _hold("retention_evidence_unreadable", "固定执行契约或阶段事实无法核查，保留原始取数与暂存材料。")


def bundle_retention_hold(db, bundle) -> dict | None:
    """Check source, consumers and delayed batch/replay references before purging."""
    source = db.get(WorkflowSession, bundle.source_workflow_id)
    if source is None:
        return _hold("source_missing", "取数包来源任务缺失，保留原始文件供核查。")
    if bundle.source_batch_id and source.batch_id != bundle.source_batch_id:
        return _hold("source_batch_invalid", "取数包与来源任务的批次绑定不一致，保留原始文件供核查。")
    filters = [WorkflowSession.id == bundle.source_workflow_id,
               WorkflowSession.fetched_bundle_id == bundle.id,
               WorkflowSession.context_json.contains(bundle.id, autoescape=True)]
    if bundle.source_batch_id:
        filters.append(WorkflowSession.batch_id == bundle.source_batch_id)
    references = list(db.scalars(select(WorkflowSession).where(or_(*filters))
                                .options(selectinload(WorkflowSession.actions), selectinload(WorkflowSession.batch))
                                .execution_options(populate_existing=True)
                                .order_by(WorkflowSession.id).limit(MAX_BUNDLE_REFERENCES + 1)))
    if len(references) > MAX_BUNDLE_REFERENCES:
        return _hold("reference_limit", "取数包关联范围超过本次核查上限，保留文件，未忽略其余引用。")
    for workflow in references:
        try:
            context = json.loads(workflow.context_json or "{}")
            if not isinstance(context, dict):
                raise ValueError("invalid reference context")
            fetched = context.get("fetched_data") or {}
            if not isinstance(fetched, dict):
                raise ValueError("invalid fetch reference")
            direct = workflow.id == bundle.source_workflow_id or workflow.fetched_bundle_id == bundle.id
            shared = bool(bundle.source_batch_id and workflow.batch_id == bundle.source_batch_id)
            selected = context.get("replay_source_bundle_id") == bundle.id or fetched.get("bundle_id") == bundle.id
            if not (direct or shared or selected):
                continue
            if (workflow.owner_id, workflow.department_id, workflow.skill_id) != (
                bundle.owner_id, bundle.department_id, bundle.skill_id,
            ):
                return _hold("reference_binding_invalid", "取数包与引用任务的业务范围不一致，保留原始文件供核查。")
            if workflow.state not in {"succeeded", "failed", "cancelled"} or any(
                item.state in {"queued", "running"} for item in workflow.actions
            ):
                return _hold("active_reference", "仍有任务或排队动作引用此取数包，保留原始文件。")
            reason = workflow_retention_hold(workflow)
            if reason:
                return reason
        except (ValueError, TypeError):
            return _hold("reference_unreadable", "取数包引用关系无法完整核查，保留原始文件。")
    return None
