from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class InterpretRequest(BaseModel):
    message: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    model_connection_id: str | None = None
    model: str | None = None


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
    model_connection_id: str | None = None
    model: str | None = None


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
    model_provider: str
    model_name: str
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


class ModelConnectRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)


class ModelSelectRequest(BaseModel):
    selected_model: str = Field(min_length=1, max_length=255)


class ModelConnectionRead(BaseModel):
    id: str
    provider: str
    provider_name: str
    api_key_hint: str
    models: list[str]
    selected_model: str
    status: str
    last_checked_at: datetime
    created_at: datetime


class ServiceCredentialWrite(BaseModel):
    account: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=512)


class ServiceCredentialRead(BaseModel):
    service: str
    configured: bool
    account_hint: str
    updated_at: datetime | None


class WorkflowCreate(BaseModel):
    skill_id: str
    model_connection_id: str
    model: str | None = None


class WorkflowMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class WorkflowFilesUpdate(BaseModel):
    files: dict[str, list[str]] = Field(default_factory=dict)


class WorkflowMessageRead(BaseModel):
    id: int
    role: str
    content: str
    data: dict[str, Any]
    created_at: datetime


class WorkflowActionRead(BaseModel):
    id: str
    name: str
    state: str
    error_message: str
    created_at: datetime
    finished_at: datetime | None


class WorkflowRead(BaseModel):
    id: str
    owner_id: str
    skill_id: str
    skill_name: str
    skill_version: str
    model_provider: str
    model_name: str
    state: str
    stage: str
    reconciliation_date: str
    progress: int
    progress_message: str
    error_message: str
    files: dict[str, Any]
    artifacts: list[dict[str, Any]]
    messages: list[WorkflowMessageRead]
    actions: list[WorkflowActionRead]
    created_at: datetime
    updated_at: datetime
