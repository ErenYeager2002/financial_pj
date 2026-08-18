from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .registry import (
    FileInputSpec,
    HandlerSpec,
    PermissionSpec,
    ProgressStageSpec,
    ResultPresentationSpec,
    RiskSpec,
    RuntimeSpec,
    SafetyConstraintSpec,
    SkillManifest,
    SkillUiSpec,
)

CONTRACT_VERSION = "2026-08-15-stage10"


class PlatformUser(BaseModel):
    user_id: str
    username: str
    display_name: str
    role: Literal["finance_user", "skill_admin"]
    department_id: str
    must_change_password: bool = False
    auth_provider: Literal["session", "clerk"] = "session"


class SkillRiskSummary(BaseModel):
    level: Literal["read_only", "write", "external_action"] = "read_only"
    requires_confirmation: bool = False
    requires_approval: bool = False
    modifies_uploaded_files: bool = False


class SkillSummary(BaseModel):
    id: str
    name: str
    version: str
    status: Literal["draft", "published", "disabled"]
    description: str
    categories: list[str]
    tags: list[str] = Field(default_factory=list)
    estimated_minutes: int
    output_summary: str
    action_label: str
    popular: bool = False
    execution_mode: Literal["standard", "guided_workflow"] = "standard"
    risk: SkillRiskSummary


class SkillDetail(SkillSummary):
    file_inputs: list[FileInputSpec] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    progress_stages: list[ProgressStageSpec] = Field(default_factory=list)
    result_presentation: ResultPresentationSpec = Field(
        default_factory=ResultPresentationSpec
    )


class AdminSkillDetail(SkillManifest):
    """管理员 Skill DTO；员工接口不得返回这些执行和来源字段。"""

    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    file_inputs: list[FileInputSpec] = Field(default_factory=list)
    handler: HandlerSpec
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)
    risk: RiskSpec = Field(default_factory=RiskSpec)
    permissions: PermissionSpec = Field(default_factory=PermissionSpec)
    ui: SkillUiSpec | None = None
    safety_constraints: dict[str, SafetyConstraintSpec] = Field(default_factory=dict)
    skill_hash: str
    commit_sha: str = ""
    source: str


class SkillReleaseInboxItem(BaseModel):
    package_name: str
    size_bytes: int
    sha256: str


class SkillReleaseImportRequest(BaseModel):
    package_name: str = Field(
        min_length=5,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*\.zip$",
    )


class SkillReleaseMetadataUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=4000)
    category: str | None = Field(default=None, min_length=1, max_length=128)
    tags: list[str] | None = Field(default=None, max_length=20)
    ui: SkillUiSpec | None = None
    progress_stages: list[ProgressStageSpec] | None = Field(default=None, max_length=30)
    result_presentation: ResultPresentationSpec | None = None


class SkillReleaseReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    notes: str = Field(min_length=2, max_length=2000)


class SkillReleasePublishRequest(BaseModel):
    confirmation: str = Field(min_length=4, max_length=255)


class SkillReleaseRead(BaseModel):
    id: str
    skill_id: str
    version: str
    state: Literal[
        "validated",
        "reviewed",
        "rejected",
        "published",
        "superseded",
        "rolled_back",
    ]
    package_sha256: str
    source_repository: str
    source_commit: str
    source_tree_hash: str
    manifest: AdminSkillDetail
    validation: dict[str, Any] = Field(default_factory=dict)
    tests: dict[str, Any] = Field(default_factory=dict)
    review_notes: str
    imported_by: str
    reviewed_by: str
    published_by: str
    published_skill_hash: str
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None
    published_at: datetime | None


class RunSummary(BaseModel):
    id: str
    owner_id: str
    owner_name: str
    skill_id: str
    skill_name: str
    skill_version: str
    state: str
    progress: int
    progress_message: str
    files: dict[str, Any] = Field(default_factory=dict)
    error_message: str
    confirmation_required: bool
    confirmed_by: str
    cancel_requested: bool
    attempt_count: int = 0
    can_retry: bool = False
    retry_block_reason: str = ""
    created_at: datetime
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class RunDetail(RunSummary):
    skill_commit: str
    model_provider: str
    model_name: str
    message: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)


class RunPage(BaseModel):
    items: list[RunSummary] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    pages: int


class RunEventRead(BaseModel):
    id: int
    type: str
    state: str
    progress: int | None
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class StepRunRead(BaseModel):
    id: str
    step_key: str
    name: str
    step_type: str
    position: int
    state: str
    attempt_count: int
    can_retry: bool
    retry_block_reason: str
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    error_code: str
    error_message: str
    created_at: datetime
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class StepDefinitionRead(BaseModel):
    id: str
    step_key: str
    name: str
    step_type: str
    position: int
    timeout_seconds: int
    max_attempts: int
    risk_level: str
    worker_pool: str
    is_idempotent: bool
    retryable: bool


class WorkflowDefinitionRead(BaseModel):
    id: str
    workflow_key: str
    name: str
    description: str
    version: str
    status: str
    skill_id: str
    skill_version: str
    steps: list[StepDefinitionRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class RunApprovalRead(BaseModel):
    id: str
    status: Literal["pending", "approved", "rejected", "expired", "revoked"]
    preview: dict[str, Any] = Field(default_factory=dict)
    requested_by_name: str = ""
    decided_by_name: str = ""
    reason: str = ""
    created_at: datetime
    decided_at: datetime | None = None
    expires_at: datetime | None = None


class StepMetricRead(BaseModel):
    step_type: str
    run_count: int
    failed_count: int
    average_duration_seconds: float


class ModelUsageRead(BaseModel):
    provider: str
    model: str
    request_count: int
    failed_count: int = 0
    fallback_count: int = 0
    average_duration_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


class ObservabilitySummary(BaseModel):
    window_hours: int
    run_count: int
    failed_run_count: int
    failure_rate: float
    average_queue_seconds: float
    average_run_seconds: float
    retry_count: int
    approval_count: int
    manual_intervention_count: int
    step_metrics: list[StepMetricRead] = Field(default_factory=list)
    model_usage: list[ModelUsageRead] = Field(default_factory=list)


class PlatformFile(BaseModel):
    id: str
    name: str
    role: str = ""
    size_bytes: int
    sha256: str
    kind: Literal["input", "output"] | str
    skill_id: str = ""
    skill_name: str = ""
    skill_version: str = ""
    workflow_id: str | None = None
    content_type: str = "application/octet-stream"
    run_id: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    can_delete: bool = False
    delete_block_reason: str = ""
    download_url: str


class PlatformFileDetail(PlatformFile):
    referenced_run_ids: list[str] = Field(default_factory=list)
    referenced_workflow_ids: list[str] = Field(default_factory=list)


class PlatformFilePage(BaseModel):
    items: list[PlatformFile] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    pages: int


class WorkbenchCounts(BaseModel):
    waiting_confirmation: int = 0
    active: int = 0
    succeeded: int = 0
    failed: int = 0
    files: int = 0


class WorkbenchSkillUsage(BaseModel):
    skill: SkillSummary
    run_count: int = 0
    last_run_at: datetime | None = None


class Workbench(BaseModel):
    counts: WorkbenchCounts
    common_skills: list[WorkbenchSkillUsage] = Field(default_factory=list)
    pending_runs: list[RunSummary] = Field(default_factory=list)
    recent_results: list[RunSummary] = Field(default_factory=list)
    recent_files: list[PlatformFile] = Field(default_factory=list)


class AuditEventRead(BaseModel):
    id: int
    actor_id: str
    actor_role: str
    action: str
    resource_type: str
    resource_id: str
    outcome: str
    details: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class TaskDraft(BaseModel):
    id: str
    owner_id: str
    skill_id: str
    skill_name: str
    skill_version: str
    state: Literal["draft", "ready", "expired", "consumed"] = "draft"
    source: Literal["manual", "assistant"] = "manual"
    message: str = ""
    confidence: float = 0
    candidates: list[SkillSummary] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    files: dict[str, str | list[str]] = Field(default_factory=dict)
    file_hashes: dict[str, str] = Field(default_factory=dict)
    missing_inputs: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    requires_approval: bool = False
    clarification: str = ""
    confirmation_text: str = ""
    run_id: str | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None


class AssistantStatus(BaseModel):
    configured: bool


class AssistantMessageRead(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AssistantConversationRead(BaseModel):
    session_id: str
    messages: list[AssistantMessageRead] = Field(default_factory=list)
    updated_at: datetime | None = None


class AdminAssistantProfile(BaseModel):
    configured: bool
    connection_id: str = ""
    provider_name: str = ""
    api_key_hint: str = ""
    model: str = ""
    updated_at: datetime | None = None


class ApprovalRecord(BaseModel):
    id: str
    resource_type: Literal["run", "workflow"]
    resource_id: str
    run_id: str | None = None
    workflow_id: str | None = None
    skill_id: str
    snapshot_sha256: str
    preview_sha256: str
    preview: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "approved", "rejected", "expired", "revoked"]
    requested_by: str
    requested_by_name: str = ""
    decided_by: str = ""
    decided_by_name: str = ""
    reason: str = ""
    execution_action_id: str = ""
    created_at: datetime
    decided_at: datetime | None = None
    expires_at: datetime | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=2, max_length=2000)


class RegistryError(BaseModel):
    path: str
    error: str


class PlatformHealth(BaseModel):
    status: str
    name: str
    environment: str
    skills: int
    registry_errors: list[RegistryError] = Field(default_factory=list)
    configured_workers: dict[str, int]
    configured_execution_capacity: int


class RegistryReloadResponse(BaseModel):
    skills: int
    errors: list[RegistryError] = Field(default_factory=list)


DOMAIN_CONTRACT_MODELS: tuple[type[BaseModel], ...] = (
    PlatformUser,
    SkillSummary,
    SkillDetail,
    AdminSkillDetail,
    SkillReleaseInboxItem,
    SkillReleaseRead,
    RunSummary,
    RunDetail,
    RunPage,
    RunEventRead,
    PlatformFile,
    PlatformFileDetail,
    PlatformFilePage,
    WorkbenchCounts,
    WorkbenchSkillUsage,
    Workbench,
    AuditEventRead,
    TaskDraft,
    AssistantStatus,
    AssistantMessageRead,
    AssistantConversationRead,
    AdminAssistantProfile,
    ApprovalRecord,
)


def domain_contract_schemas() -> dict[str, Any]:
    """生成可并入 OpenAPI components.schemas 的领域契约。"""

    schemas: dict[str, Any] = {}
    for model in DOMAIN_CONTRACT_MODELS:
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(schema.pop("$defs", {}))
        schemas[model.__name__] = schema
    return schemas
