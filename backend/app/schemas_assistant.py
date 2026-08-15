from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AdminAssistantProfileWrite(BaseModel):
    connection_id: str = Field(min_length=1, max_length=36)
    model: str = Field(min_length=1, max_length=255)


class AssistantPrepareRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    file_ids: list[str] = Field(default_factory=list, max_length=20)


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
