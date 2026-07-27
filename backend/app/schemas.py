from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class InterpretRequest(BaseModel):
    message: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class InterpretResponse(BaseModel):
    parameters: dict[str, Any]
    missing: list[str]
    source: str
    notes: list[str] = Field(default_factory=list)


class RunCreate(BaseModel):
    skill_id: str
    message: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    files: dict[str, str | list[str]] = Field(default_factory=dict)
    idempotency_key: str | None = None


class RunActionResponse(BaseModel):
    id: str
    state: str
    message: str


class RunRead(BaseModel):
    id: str
    owner_id: str
    owner_name: str
    skill_id: str
    skill_name: str
    skill_version: str
    skill_commit: str
    state: str
    progress: int
    progress_message: str
    message: str
    parameters: dict[str, Any]
    files: dict[str, Any]
    result: dict[str, Any]
    error_message: str
    confirmation_required: bool
    confirmed_by: str
    cancel_requested: bool
    created_at: datetime
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class FileRead(BaseModel):
    id: str
    name: str
    size_bytes: int
    sha256: str
    kind: str
    download_url: str
