from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .assistant_profile_service import resolve_assistant_config
from .auth import UserContext
from .model_providers import chat_completion_stream_request
from .model_service import resolve_runtime_config
from .models import ModelTraceRecord
from .orchestrator import LlmConfig, config_extra_body
from .workflow_constants import is_background_model_connection

_FORWARDED_FIELDS = frozenset(
    {
        "messages",
        "tools",
        "tool_choice",
        "temperature",
        "top_p",
        "max_tokens",
        "max_completion_tokens",
        "reasoning_effort",
        "parallel_tool_calls",
        "response_format",
        "stream_options",
    }
)


def resolve_agent_model_config(
    db: Session,
    user: UserContext,
    connection_id: str | None,
    model: str,
) -> LlmConfig:
    """Resolve either the department assistant profile or a workflow snapshot model."""
    # 表单启动的确定性后台任务会把一个兼容标记写入工作流快照。它不是
    # model_connections 的 ID；这类工作流由 legacy action 处理，若仍有
    # 旧客户端调用 Agent 网关，则退回部门默认助手配置，不能去查这个标记。
    if connection_id and not is_background_model_connection(connection_id):
        config = resolve_runtime_config(db, user, connection_id, model)
        if config is None:
            raise ValueError("工作流 Agent 未提供有效模型连接。")
        return config
    return resolve_assistant_config(db, user)


@dataclass
class AgentModelStreamStats:
    started_at: float = field(default_factory=time.perf_counter)
    input_tokens: int = 0
    output_tokens: int = 0
    status: str = "running"
    failure_code: str = ""
    _buffer: bytes = field(default=b"", repr=False)

    def observe(self, chunk: bytes) -> None:
        """只读取流中的 usage 元数据，不记录消息正文。"""
        self._buffer += chunk
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            if not line.startswith(b"data:"):
                continue
            raw = line[5:].strip()
            if not raw or raw == b"[DONE]":
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            usage = payload.get("usage") if isinstance(payload, dict) else None
            if not isinstance(usage, dict):
                continue
            self.input_tokens = max(self.input_tokens, _token_value(usage, "prompt_tokens"))
            self.output_tokens = max(
                self.output_tokens,
                _token_value(usage, "completion_tokens"),
            )

    def succeed(self) -> None:
        if self._buffer:
            self.observe(b"\n")
        self.status = "succeeded"

    def fail(self, code: str) -> None:
        self.status = "failed"
        self.failure_code = code[:64]

    @property
    def duration_ms(self) -> int:
        return max(0, round((time.perf_counter() - self.started_at) * 1000))


def _token_value(usage: dict[str, Any], key: str) -> int:
    try:
        return max(0, int(usage.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def build_agent_model_payload(config: LlmConfig, incoming: dict[str, Any]) -> dict[str, Any]:
    """绑定平台选定模型，并移除客户端不能控制的连接字段。"""
    if incoming.get("stream") is not True:
        raise ValueError("Agent 模型网关只接受流式请求。")
    payload = {key: incoming[key] for key in _FORWARDED_FIELDS if key in incoming}
    payload["model"] = config.model
    payload["stream"] = True
    payload.update(config_extra_body(config))
    return payload


def open_agent_model_stream(
    config: LlmConfig,
    payload: dict[str, Any],
    *,
    session_id: str | None = None,
) -> AbstractContextManager[httpx.Response]:
    """打开已绑定部门配置的上游模型流。"""
    return chat_completion_stream_request(
        config.provider,
        config.base_url,
        config.api_key,
        payload,
        **({"session_id": session_id} if config.provider == "opencode_go" else {}),
    )


def iter_agent_model_stream(
    response: httpx.Response,
    stats: AgentModelStreamStats,
) -> Iterator[bytes]:
    try:
        for chunk in response.iter_bytes():
            stats.observe(chunk)
            yield chunk
        stats.succeed()
    except GeneratorExit:
        stats.fail("stream_cancelled")
        raise
    except Exception as exc:
        stats.fail(type(exc).__name__)
        raise


def save_agent_model_trace(
    db: Session,
    user: UserContext,
    config: LlmConfig,
    stats: AgentModelStreamStats,
) -> None:
    db.add(
        ModelTraceRecord(
            id=str(uuid.uuid4()),
            owner_id=user.user_id,
            department_id=user.department_id,
            connection_id=config.connection_id,
            purpose="agent_turn",
            provider=config.provider,
            model=config.model,
            status=stats.status,
            duration_ms=stats.duration_ms,
            input_tokens=stats.input_tokens,
            output_tokens=stats.output_tokens,
            failure_code=stats.failure_code,
        )
    )
