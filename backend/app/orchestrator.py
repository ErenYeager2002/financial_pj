from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .registry import RegisteredSkill
from .settings import settings


def _apply_defaults(schema: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    merged = dict(values)
    for key, prop in schema.get("properties", {}).items():
        if key not in merged and "default" in prop:
            merged[key] = prop["default"]
    return merged


def _local_extract(skill: RegisteredSkill, message: str, current: dict[str, Any]) -> dict[str, Any]:
    values = _apply_defaults(skill.manifest.input_schema, current)
    text = message.strip()
    properties = skill.manifest.input_schema.get("properties", {})
    if "amount_tolerance" in properties:
        match = re.search(r"(?:金额|差异|容差)[^\d]{0,8}(\d+(?:\.\d+)?)\s*元?", text)
        if match:
            values["amount_tolerance"] = float(match.group(1))
    if "date_tolerance_days" in properties:
        match = re.search(r"(?:日期|相差|前后)[^\d]{0,8}(\d+)\s*天", text)
        if match:
            values["date_tolerance_days"] = int(match.group(1))
    return values


def _required_missing(schema: dict[str, Any], values: dict[str, Any]) -> list[str]:
    return [
        key
        for key in schema.get("required", [])
        if key not in values or values[key] in (None, "", [])
    ]


def interpret_parameters(
    skill: RegisteredSkill,
    message: str,
    current: dict[str, Any],
) -> tuple[dict[str, Any], list[str], str, list[str]]:
    schema = skill.manifest.input_schema
    if settings.llm_base_url and settings.llm_api_key and settings.llm_model and message.strip():
        tool = {
            "type": "function",
            "function": {
                "name": skill.manifest.id.replace("-", "_"),
                "description": skill.manifest.description,
                "parameters": schema,
            },
        }
        payload = {
            "model": settings.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你只负责从用户要求中提取工具参数。不得生成文件ID、本地路径、命令或SQL。"
                        "如果用户未提供参数，使用工具Schema默认值。"
                    ),
                },
                {"role": "user", "content": message},
            ],
            "tools": [tool],
            "tool_choice": {"type": "function", "function": {"name": tool["function"]["name"]}},
            "temperature": 0,
        }
        try:
            response = httpx.post(
                f"{settings.llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            calls = response.json()["choices"][0]["message"].get("tool_calls") or []
            if calls:
                extracted = json.loads(calls[0]["function"]["arguments"])
                values = _apply_defaults(schema, {**current, **extracted})
                return values, _required_missing(schema, values), "llm", []
        except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            notes = [f"模型参数解析失败，已回退本地规则：{type(exc).__name__}"]
        else:
            notes = ["模型没有返回工具调用，已回退本地规则。"]
    else:
        notes = ["未配置模型，使用表单默认值和本地参数规则。"]
    values = _local_extract(skill, message, current)
    return values, _required_missing(schema, values), "local", notes
