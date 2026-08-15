from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .model_providers import build_extra_body, chat_completion_request
from .registry import RegisteredSkill
from .settings import settings

PROTECTED_PAYLOAD_KEYS = frozenset({"model", "messages", "tools", "tool_choice"})


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    connection_id: str
    base_url: str
    api_key: str
    model: str
    protocol: str = "chat_completions"
    extra_body: dict[str, Any] = field(default_factory=dict)


def config_extra_body(config: LlmConfig) -> dict[str, Any]:
    """按供应商与模型生成请求附加参数，且不允许覆盖受保护字段。"""
    extra = dict(getattr(config, "extra_body", None) or {})
    if extra:
        return {key: value for key, value in extra.items() if key not in PROTECTED_PAYLOAD_KEYS}
    if config.provider == "environment":
        provider_id = getattr(settings, "llm_provider", "") or (
            "qwen" if config.model.startswith("qwen") else ""
        )
    else:
        provider_id = config.provider
    return {
        key: value
        for key, value in build_extra_body(provider_id, config.model).items()
        if key not in PROTECTED_PAYLOAD_KEYS
    }


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
    llm_config: LlmConfig | None = None,
    trace: dict[str, int | str] | None = None,
) -> tuple[dict[str, Any], list[str], str, list[str]]:
    schema = skill.manifest.input_schema
    config = llm_config
    if not config and settings.llm_base_url and settings.llm_api_key and settings.llm_model:
        config = LlmConfig(
            provider="environment",
            connection_id="",
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        )
    if config and message.strip():
        started = time.perf_counter()
        tool = {
            "type": "function",
            "function": {
                "name": skill.manifest.id.replace("-", "_"),
                "description": skill.manifest.description,
                "parameters": schema,
            },
        }
        payload = {
            "model": config.model,
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
        payload.update(config_extra_body(config))
        try:
            response = chat_completion_request(
                config.provider,
                config.base_url,
                config.api_key,
                payload,
            )
            response.raise_for_status()
            response_data = response.json()
            usage = response_data.get("usage") or {}
            calls = response_data["choices"][0]["message"].get("tool_calls") or []
            if calls:
                extracted = json.loads(calls[0]["function"]["arguments"])
                values = _apply_defaults(schema, {**current, **extracted})
                if trace is not None:
                    trace.update(
                        status="succeeded",
                        duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
                        input_tokens=max(0, int(usage.get("prompt_tokens") or 0)),
                        output_tokens=max(0, int(usage.get("completion_tokens") or 0)),
                        failure_code="",
                    )
                return values, _required_missing(schema, values), "llm", []
        except (
            httpx.HTTPError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            notes = [f"模型参数解析失败，已回退本地规则：{type(exc).__name__}"]
            failure_code = type(exc).__name__
        else:
            notes = ["模型没有返回工具调用，已回退本地规则。"]
            failure_code = "no_tool_call"
        if trace is not None:
            trace.update(
                status="fallback",
                duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
                input_tokens=0,
                output_tokens=0,
                failure_code=failure_code,
            )
    else:
        notes = ["未配置模型，使用表单默认值和本地参数规则。"]
        if config and trace is not None:
            trace.update(
                status="fallback",
                duration_ms=0,
                input_tokens=0,
                output_tokens=0,
                failure_code="empty_message",
            )
    values = _local_extract(skill, message, current)
    return values, _required_missing(schema, values), "local", notes
