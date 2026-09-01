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
    replace_roles: list[str] = Field(default_factory=list)
    fetched_bundle_id: str | None = Field(default=None, max_length=64)
    # Deprecated compatibility field. New callers identify the immutable
    # owner-scoped fetch bundle directly.
    snapshot_workflow_id: str | None = Field(
        default=None,
        max_length=64,
        json_schema_extra={"deprecated": True},
    )


class WorkflowBatchStart(BaseModel):
    skill_id: str
    model_connection_id: str | None = None
    model: str | None = None
    reconciliation_dates: list[str] = Field(min_length=1, max_length=31)
    files: dict[str, list[str]] = Field(default_factory=dict)
    replace_roles: list[str] = Field(default_factory=list)
    rerun_successful_dates: bool = False
    rerun_reason: str = Field(default="", max_length=500)
    fetched_bundle_id: str | None = Field(default=None, max_length=64)
    snapshot_workflow_id: str | None = Field(
        default=None,
        max_length=64,
        json_schema_extra={"deprecated": True},
    )


class WorkflowMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class WorkflowFilesUpdate(BaseModel):
    files: dict[str, list[str]] = Field(default_factory=dict)
    replace_roles: list[str] = Field(default_factory=list)


class WorkflowReusableFilesRead(BaseModel):
    skill_id: str
    files: dict[str, Any] = Field(default_factory=dict)
    ready: bool
    missing_roles: list[str] = Field(default_factory=list)
    material_set_id: str | None = None
    material_version: int | None = None
    source_workflow_id: str = ""
    published_at: datetime | None = None


class WorkflowMaterialFileRead(BaseModel):
    role: Literal["profit_loss_ledgers", "receipt_flow_table"]
    year: int | None = None
    file_id: str
    name: str
    size_bytes: int
    sha256: str


class WorkflowMaterialSetRead(BaseModel):
    id: str
    skill_id: str
    version: int
    parent_set_id: str | None = None
    source_workflow_id: str = ""
    source_workflow_display_id: str = ""
    state: Literal["current", "superseded"]
    published_at: datetime
    files: list[WorkflowMaterialFileRead] = Field(default_factory=list)


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


class FetchedBundleRead(BaseModel):
    id: str
    source_type: Literal["live", "replay"]
    state: Literal[
        "creating",
        "ready_for_review",
        "confirmed",
        "consumed",
        "purge_pending",
        "raw_purged",
        "invalid",
    ]
    dates: list[str]
    raw_available: bool
    preview_available: bool
    replayable: bool
    retention_until: datetime | None
    created_at: datetime


class WorkflowRead(BaseModel):
    id: str
    display_id: str
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
    material_set_id: str | None = None
    fetched_bundle: FetchedBundleRead | None = None
    material_version: int | None = None
    material_source_workflow_id: str = ""
    requires_confirmation: bool = True
    progress: int
    progress_message: str
    error_message: str
    current_step: str = ""
    current_step_label: str = ""
    step_error: str = ""
    step_error_detail: dict[str, str] = Field(default_factory=dict)
    fetched_data_available: bool = False
    # Optional for compatibility with task rows created before source tracking.
    fetched_data_source: Literal["live", "replay"] | None = None
    fetched_data_summary: dict[str, Any] = Field(default_factory=dict)
    fetched_data_review_status: str = ""
    fetched_data_supplement_history: list[dict[str, Any]] = Field(default_factory=list)
    result_summary: dict[str, Any] = Field(default_factory=dict)
    files: dict[str, Any]
    artifacts: list[dict[str, Any]]
    messages: list[WorkflowMessageRead]
    actions: list[WorkflowActionRead]
    created_at: datetime
    updated_at: datetime


class WorkflowFetchedDataSet(BaseModel):
    key: str
    label: str
    total: int


class WorkflowFetchedSnapshotRead(BaseModel):
    """A safe fetch history item; only replayable bundles are selectable."""

    bundle_id: str
    source_workflow_id: str
    source_display_id: str
    skill_version: str
    dates: list[str]
    summary_by_date: dict[str, dict[str, Any]] = Field(default_factory=dict)
    captured_at: datetime
    availability: Literal["replayable_bundle", "historical_preview"]
    state: str
    raw_available: bool
    preview_available: bool
    replayable: bool
    retention_until: datetime | None = None


class WorkflowFetchedPayment(BaseModel):
    ar_id: str
    reconciliation_date: str = ""
    arrival_date: str = ""
    amount_original: float | None = None
    amount_local: float | None = None
    total_amount_original: float | None = None
    total_amount_local: float | None = None
    fee_original: float | None = None
    tax_original: float | None = None
    tax_local: float | None = None
    currency: str = ""
    payment_type: str = ""
    writeoff_status: str = ""
    customer: str = ""
    salesperson: str = ""
    historical_parent_only: bool = False


class WorkflowFetchedDelivery(BaseModel):
    ar_id: str
    so_id: str
    written_off_original: float | None = None
    written_off_local: float | None = None
    delivery_amount_original: float | None = None
    exchange_rate: float | None = None
    currency: str = ""
    order_name: str = ""
    delivery_date: str = ""
    delivery_date_status: str = ""
    source: str = ""


class WorkflowFetchedWriteoff(BaseModel):
    writeoff_id: str
    ar_id: str
    so_id: str
    reconciliation_date: str = ""
    amount_original: float | None = None
    amount_local: float | None = None
    currency: str = ""
    exchange_rate: float | None = None
    order_name: str = ""
    revoked: bool = False


class WorkflowFetchedOrderDetail(BaseModel):
    so_id: str
    sod_id: str
    delivery_amount_original: float | None = None
    currency: str = ""
    project_status: str = ""


class WorkflowFetchedDataOrderGroup(BaseModel):
    so_id: str
    deliveries: list[WorkflowFetchedDelivery] = Field(default_factory=list)
    writeoffs: list[WorkflowFetchedWriteoff] = Field(default_factory=list)
    order_details: list[WorkflowFetchedOrderDetail] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class WorkflowFetchedDataArGroup(BaseModel):
    ar_id: str
    payments: list[WorkflowFetchedPayment] = Field(default_factory=list)
    orders: list[WorkflowFetchedDataOrderGroup] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class WorkflowFetchedDataRead(BaseModel):
    reconciliation_date: str
    dataset: str
    dataset_label: str
    headers: list[str]
    rows: list[list[Any]]
    total: int
    offset: int
    limit: int
    datasets: list[WorkflowFetchedDataSet]
    summary: dict[str, Any] = Field(default_factory=dict)
    ar_groups: list[WorkflowFetchedDataArGroup] = Field(default_factory=list)


class WorkflowFetchedDataSupplement(BaseModel):
    ar_ids: list[str] = Field(default_factory=list, max_length=50)
    so_ids: list[str] = Field(default_factory=list, max_length=50)


class WorkflowBatchFetchedDataSupplement(WorkflowFetchedDataSupplement):
    reconciliation_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


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
    display_id: str
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
    retryable: bool = False
    can_retry: bool = False
    retry_message: str = ""
    retry_block_reason: str = ""
    fetched_data_available: bool = False
    # Optional for compatibility with batch rows created before source tracking.
    fetched_data_source: Literal["live", "replay"] | None = None
    fetched_data_review_status: str = ""
    fetched_data_summary_by_date: dict[str, dict[str, Any]] = Field(default_factory=dict)
    fetched_data_supplement_history: list[dict[str, Any]] = Field(default_factory=list)
    workflows: list[WorkflowRead]
    created_at: datetime
    updated_at: datetime
