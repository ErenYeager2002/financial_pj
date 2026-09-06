"""Persisted limits for Agent work after fetch; no financial execution here."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .ar_execution_contract import CONTRACT_VERSION
from .models import WorkflowAction, WorkflowSession

DEFAULT_LIMITS = {"model_calls": 4096, "tool_calls": 8192, "seconds": 14400}


def initial_budget() -> dict:
    return {"schema_version": "ar-agent-budget-v1", "limits": dict(DEFAULT_LIMITS),
            "started_at": datetime.now(UTC).isoformat(), "model_calls": 0, "tool_calls": 0}


def reserve_agent_call(db: Session, workflow: WorkflowSession, action: WorkflowAction,
                       worker_id: str, kind: str) -> None:
    """Reserve before a model/tool call; concurrent requests share one limit."""
    from .scheduler import acquire_claim_lock
    from .workflow_service import workflow_owner_context

    if (json.loads(workflow.context_json or "{}").get("ar_execution") or {}).get("schema_version") != CONTRACT_VERSION:
        return
    if kind not in {"model_calls", "tool_calls"}:
        raise ValueError("unsupported Agent budget counter")
    db.commit()
    acquire_claim_lock(db)
    db.refresh(workflow)
    db.refresh(action)
    now = datetime.now(UTC)
    deadline = action.lease_expires_at
    if deadline is not None and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if (action.workflow_id != workflow.id or action.name != "pi_harness_execute"
            or action.state != "running" or action.worker_id != worker_id
            or deadline is None or deadline <= now or workflow.state not in {"running", "active"}):
        raise HTTPException(status_code=409, detail="Agent 租约或任务状态已失效，未继续调用。")
    workflow_owner_context(db, workflow)
    context = json.loads(workflow.context_json or "{}")
    budget = context.get("ar_agent_budget") or {}
    if budget.get("schema_version") != "ar-agent-budget-v1":
        raise HTTPException(status_code=409, detail="任务缺少固定的 Agent 调用预算，不能继续执行。")
    limits = budget.get("limits") or {}
    try:
        started = datetime.fromisoformat(budget["started_at"])
        if started.tzinfo is None or any(type(limits.get(key)) is not int or limits[key] <= 0 for key in DEFAULT_LIMITS):
            raise ValueError("invalid budget")
        elapsed = (now - started).total_seconds()
        used = budget[kind]
        if type(used) is not int or used < 0 or elapsed < 0:
            raise ValueError("invalid budget counter")
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="任务 Agent 预算记录无效，不能推测剩余次数。") from exc
    stop = context.get("ar_agent_stop") or {}
    if stop or used >= limits[kind] or elapsed >= limits["seconds"]:
        reason = stop.get("reason") or (
            f"取数后的 Agent 执行已达到 {limits['seconds']} 秒时限。"
            if elapsed >= limits["seconds"] else
            f"{'模型' if kind == 'model_calls' else '工具'}调用已达到 {limits[kind]} 次上限。"
        )
        context["ar_agent_stop"] = {"reason": reason, "action_id": action.id,
                                    "stage": context.get("current_step", ""), "stopped_at": now.isoformat()}
        workflow.context_json = json.dumps(context, ensure_ascii=False)
        db.commit()
        raise HTTPException(status_code=429, detail=reason + " 已保留检查点，未完成的检查不能视为通过；需核查恢复条件。")
    budget[kind] = used + 1
    context["ar_agent_budget"] = budget
    workflow.context_json = json.dumps(context, ensure_ascii=False)
    db.commit()
