from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AdminAssistantProfileWrite(BaseModel):
    connection_id: str = Field(min_length=1, max_length=36)
    model: str = Field(min_length=1, max_length=255)


class AssistantPrepareRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    file_ids: list[str] = Field(default_factory=list, max_length=20)


class AssistantMessageWrite(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=20000)
    data: dict[str, Any] = Field(default_factory=dict)


class TaskDraftUpdate(BaseModel):
    parameters: dict[str, Any] | None = None
    files: dict[str, str | list[str]] | None = None


class AssistantRecommendation(BaseModel):
    skill_id: str = Field(min_length=1, max_length=128)
    confidence: float = Field(ge=0, le=1)
    candidates: list[str] = Field(default_factory=list, max_length=3)
    parameters: dict[str, Any] = Field(default_factory=dict)
    file_roles: dict[str, str | list[str]] = Field(default_factory=dict)
    clarification: str = Field(default="", max_length=1000)
    confirmation_text: str = Field(default="", max_length=1000)


class AgentModelRequest(BaseModel):
    """Pi 的 OpenAI Chat Completions 请求白名单。"""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=255)
    connection_id: str | None = Field(default=None, max_length=36)
    messages: list[dict[str, Any]] = Field(min_length=1, max_length=64)
    tools: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    tool_choice: str | dict[str, Any] | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=32768)
    reasoning_effort: str | None = Field(default=None, max_length=32)
    parallel_tool_calls: bool | None = None
    response_format: dict[str, Any] | None = None
    stream: bool = True
    stream_options: dict[str, Any] | None = None


class AgentPrepareRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    file_ids: list[str] = Field(default_factory=list, max_length=20)
    recommendation: AssistantRecommendation
