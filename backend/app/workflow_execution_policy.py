from __future__ import annotations

import json

from fastapi import HTTPException

from .settings import settings

AR_HEXIAO_SKILL_ID = "ar-hexiao-daily"
AR_HEXIAO_AGENT_BLOCKED_ACTIONS = frozenset(
    {"prepare_daily_reconciliation", "request_regeneration"}
)


def workflow_execution_block_reason(skill_id: str) -> str | None:
    """Return the current execution gate reason for a workflow Skill."""
    if skill_id == AR_HEXIAO_SKILL_ID and not settings.ar_hexiao_execution_enabled:
        return (
            "当前部署已暂停 ar-hexiao-daily 的真实工作流执行；"
            "本阶段仅允许合成数据和只读检查。"
        )
    return None


def assert_workflow_skill_execution_enabled(skill_id: str) -> None:
    """Reject workflow creation or execution when a Skill is gated off."""
    reason = workflow_execution_block_reason(skill_id)
    if reason:
        raise HTTPException(status_code=409, detail=reason)


def snapshot_replay_block_reason(skill_id: str) -> str | None:
    """Return the development-only gate for replaying an existing fetch."""
    if skill_id == AR_HEXIAO_SKILL_ID and not settings.ar_hexiao_snapshot_replay_enabled:
        return "当前部署未启用 ar-hexiao-daily 的取数快照回放。"
    if skill_id != AR_HEXIAO_SKILL_ID:
        return "只有 ar-hexiao-daily 支持取数快照回放。"
    return None


def assert_snapshot_replay_enabled(skill_id: str) -> None:
    reason = snapshot_replay_block_reason(skill_id)
    if reason:
        raise HTTPException(status_code=409, detail=reason)


def assert_workflow_execution_enabled(workflow: object) -> None:
    """Reject direct Worker execution using the same server-side policy."""
    skill_id = getattr(workflow, "skill_id", "")
    if str(skill_id) == AR_HEXIAO_SKILL_ID and not settings.ar_hexiao_execution_enabled:
        try:
            context = json.loads(str(getattr(workflow, "context_json", "{}")))
        except json.JSONDecodeError:
            context = {}
        snapshot_workflow_id = (
            str(context.get("snapshot_workflow_id") or "").strip()
            if isinstance(context, dict)
            else ""
        )
        if snapshot_workflow_id:
            assert_snapshot_replay_enabled(str(skill_id))
            return
    assert_workflow_skill_execution_enabled(str(skill_id))


def assert_workflow_agent_action_enabled(skill_id: str, action: str) -> None:
    """Apply the same deployment gate to direct Agent action requests."""
    if (
        skill_id == AR_HEXIAO_SKILL_ID
        and not settings.ar_hexiao_execution_enabled
        and action in AR_HEXIAO_AGENT_BLOCKED_ACTIONS
    ):
        raise HTTPException(
            status_code=409,
            detail="当前部署未启用 ar-hexiao-daily 的真实工作流执行。",
        )
