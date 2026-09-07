"""Keep legacy whole-task rebuilding away from staged AR execution facts."""
from __future__ import annotations

from .ar_skill_identity import is_ar_skill

import json


def legacy_rebuild_block_reason(workflow) -> str:
    if not is_ar_skill(workflow.skill_id):
        return ""
    context = json.loads(workflow.context_json or "{}")
    if (context.get("ar_execution") or context.get("ar_failure")
            or any(item.name.startswith("ar_") for item in workflow.actions)):
        return "本任务已有分阶段执行记录；请在核销执行与最终结果中查看恢复或调查条件，不能从头新建日清。"
    from .ar_execution_runner import execution_version

    try:
        if execution_version(workflow):
            return "本任务使用分阶段核销流程；旧的新建日清入口会重新取数并从头执行，不能用于恢复本任务。"
    except (OSError, ValueError, TypeError):
        return "原任务固定执行契约缺失或不一致，无法确认可安全新建日清；请先核查固定快照。"
    return ""
