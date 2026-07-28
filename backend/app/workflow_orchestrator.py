from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx

from .orchestrator import LlmConfig

CONFIRM_WORDS = {
    "确认",
    "ok",
    "可以",
    "可以写",
    "按这个写",
    "没问题写吧",
    "写吧",
    "对",
    "是",
    "开始",
    "继续",
}


@dataclass(frozen=True)
class WorkflowDecision:
    action: str
    arguments: dict[str, Any]
    source: str


STAGE_ACTIONS: dict[str, tuple[str, ...]] = {
    "awaiting_date": ("set_date", "show_status", "cancel"),
    "awaiting_date_confirmation": ("confirm_date", "set_date", "show_status", "cancel"),
    "awaiting_files": ("prepare_worklist", "set_date", "show_status", "cancel"),
    "preparing": ("show_status", "cancel"),
    "awaiting_apply_confirmation": (
        "confirm_apply",
        "rebuild_worklist",
        "show_status",
        "cancel",
    ),
    "applying": ("show_status", "cancel"),
    "completed": ("show_status",),
    "failed": ("show_status", "rebuild_worklist", "cancel"),
    "cancelled": ("show_status",),
}


def _tool(action: str) -> dict[str, Any]:
    descriptions = {
        "set_date": "设置或修改核销日期。必须返回 YYYY-MM-DD。",
        "confirm_date": "用户明确确认当前核销日期。",
        "prepare_worklist": "用户表示文件已上传并要求开始生成核销日清。",
        "confirm_apply": "用户在看到核销日清后明确同意写入。",
        "rebuild_worklist": "用户要求重出核销日清，不写表。",
        "show_status": "用户询问当前进度、缺什么或下一步。",
        "cancel": "用户明确要求停止或取消本次核销。",
    }
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    if action == "set_date":
        parameters = {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "核销日期，格式 YYYY-MM-DD",
                    "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
                }
            },
            "required": ["date"],
            "additionalProperties": False,
        }
    return {
        "type": "function",
        "function": {
            "name": action,
            "description": descriptions[action],
            "parameters": parameters,
        },
    }


def _llm_decision(
    config: LlmConfig,
    stage: str,
    message: str,
    reconciliation_date: str,
) -> WorkflowDecision | None:
    allowed = STAGE_ACTIONS.get(stage, ("show_status",))
    tools = [_tool(action) for action in allowed]
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是应收核销日清的对话路由器，只选择一个允许的工具。"
                    "不得计算金额，不得生成命令、文件路径、客户名或财务明细。"
                    f"今天是 {date.today().isoformat()}，当前阶段是 {stage}，"
                    f"当前核销日期是 {reconciliation_date or '未设置'}。"
                    "“确认写入”与“确认日期”必须按当前阶段区分。"
                ),
            },
            {"role": "user", "content": message},
        ],
        "tools": tools,
        "tool_choice": "required",
        "temperature": 0,
    }
    if config.provider == "qwen" or config.model.startswith("qwen"):
        payload["enable_thinking"] = False
    try:
        response = httpx.post(
            f"{config.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {config.api_key}"},
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        call = response.json()["choices"][0]["message"]["tool_calls"][0]["function"]
        action = str(call["name"])
        if action not in allowed:
            return None
        arguments = json.loads(call.get("arguments") or "{}")
        if not isinstance(arguments, dict):
            return None
        return WorkflowDecision(action=action, arguments=arguments, source="llm")
    except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None


def _extract_date(text: str) -> str:
    lowered = text.lower().strip()
    if "昨天" in lowered:
        return (date.today() - timedelta(days=1)).isoformat()
    full = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", text)
    if full:
        try:
            return date(int(full.group(1)), int(full.group(2)), int(full.group(3))).isoformat()
        except ValueError:
            return ""
    short = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})日?", text)
    if short:
        try:
            return date(date.today().year, int(short.group(1)), int(short.group(2))).isoformat()
        except ValueError:
            return ""
    return ""


def _fallback_decision(stage: str, message: str) -> WorkflowDecision:
    text = message.strip()
    lowered = text.lower().replace(" ", "")
    extracted_date = _extract_date(text)
    date_stages = {"awaiting_date", "awaiting_date_confirmation", "awaiting_files"}
    if extracted_date and stage in date_stages:
        return WorkflowDecision("set_date", {"date": extracted_date}, "local")
    if any(word in lowered for word in ("取消", "停止", "先不做", "不跑了")):
        return WorkflowDecision("cancel", {}, "local")
    if stage == "awaiting_date_confirmation" and lowered in CONFIRM_WORDS:
        return WorkflowDecision("confirm_date", {}, "local")
    if stage == "awaiting_files" and any(
        word in lowered for word in ("传好了", "上传好了", "开始", "继续", "生成日清")
    ):
        return WorkflowDecision("prepare_worklist", {}, "local")
    apply_confirmed = lowered in CONFIRM_WORDS or any(
        phrase in lowered for phrase in ("确认写入", "确认回填", "可以写入")
    )
    if stage == "awaiting_apply_confirmation" and apply_confirmed:
        return WorkflowDecision("confirm_apply", {}, "local")
    if stage in {"awaiting_apply_confirmation", "failed"} and any(
        word in lowered for word in ("重出", "重新生成", "重新跑", "清单作废")
    ):
        return WorkflowDecision("rebuild_worklist", {}, "local")
    return WorkflowDecision("show_status", {}, "local")


def decide_workflow_turn(
    config: LlmConfig | None,
    stage: str,
    message: str,
    reconciliation_date: str,
) -> WorkflowDecision:
    local = _fallback_decision(stage, message)
    if local.action != "show_status":
        return local
    if config:
        decision = _llm_decision(config, stage, message, reconciliation_date)
        if decision:
            return decision
    return local
