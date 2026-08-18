from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .contracts import PlatformFile, RunDetail


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


class RunRead(RunDetail):
    """兼容旧服务代码；公开契约名称为 RunDetail。"""


class FileRead(PlatformFile):
    """兼容旧服务代码；公开契约名称为 PlatformFile。"""


class ModelConnectRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)
    provider_id: str | None = Field(default=None, max_length=64)
    base_url: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=255)


class ModelProviderRead(BaseModel):
    id: str
    name: str
    discovery_mode: str
    allow_manual_model: bool
    admin_only: bool = False


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


class WorkflowStart(BaseModel):
    skill_id: str
    model_connection_id: str | None = None
    model: str | None = None
    reconciliation_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    files: dict[str, list[str]] = Field(default_factory=dict)


class WorkflowBatchStart(BaseModel):
    skill_id: str
    model_connection_id: str | None = None
    model: str | None = None
    reconciliation_dates: list[str] = Field(min_length=1, max_length=31)
    files: dict[str, list[str]] = Field(default_factory=dict)


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
    batch_id: str | None = None
    batch_sequence: int = 0
    requires_confirmation: bool = True
    progress: int
    progress_message: str
    error_message: str
    current_step: str = ""
    current_step_label: str = ""
    step_error: str = ""
    step_error_detail: dict[str, str] = Field(default_factory=dict)
    files: dict[str, Any]
    artifacts: list[dict[str, Any]]
    messages: list[WorkflowMessageRead]
    actions: list[WorkflowActionRead]
    created_at: datetime
    updated_at: datetime


class WorkflowAgentEmptyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowAgentSetDateArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class WorkflowAgentRegenerationArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=1000)


class WorkflowAgentConfirmationArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["date", "apply"]
    message: str = Field(default="", max_length=1000)


class WorkflowAgentSetDateRequest(BaseModel):
    action: Literal["set_reconciliation_date"]
    arguments: WorkflowAgentSetDateArguments


class WorkflowAgentStageRequest(BaseModel):
    action: Literal["get_workflow_stage", "prepare_daily_reconciliation"]
    arguments: WorkflowAgentEmptyArguments


class WorkflowAgentRegenerationRequest(BaseModel):
    action: Literal["request_regeneration"]
    arguments: WorkflowAgentRegenerationArguments


class WorkflowAgentConfirmationRequest(BaseModel):
    action: Literal["request_user_confirmation"]
    arguments: WorkflowAgentConfirmationArguments


WorkflowAgentActionRequest = Annotated[
    WorkflowAgentSetDateRequest
    | WorkflowAgentStageRequest
    | WorkflowAgentRegenerationRequest
    | WorkflowAgentConfirmationRequest,
    Field(discriminator="action"),
]


class WorkflowAgentActionResponse(BaseModel):
    workflow: WorkflowRead
    action: str
    await_confirmation: bool
    confirmation_kind: Literal["", "date", "apply"] = ""
    message: str


class WorkflowAgentContext(BaseModel):
    workflow: WorkflowRead
    connection_id: str | None = None
    model: str = ""


class WorkflowBatchRead(BaseModel):
    id: str
    owner_id: str
    skill_id: str
    skill_name: str
    skill_version: str
    model_provider: str
    model_name: str
    reconciliation_dates: list[str]
    state: str
    progress: int
    progress_message: str
    error_message: str
    workflows: list[WorkflowRead]
    created_at: datetime
    updated_at: datetime
