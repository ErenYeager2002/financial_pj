"""Versioned, credential-free storage for an ordinary prepared submission.

Loading is not authorization or validation. The caller must recheck identity,
permissions, immutable snapshot and files before atomically persisting and binding.
Only pre-execution fields are serializable; worker leases/results never restore.
"""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ModelAuditSelection(StrictPayload):
    connection_id: str
    provider: str
    model: str


class TraceSummary(StrictPayload):
    status: str = "fallback"
    duration_ms: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    failure_code: str = Field(default="unknown", max_length=64)


class PreparedTask(StrictPayload):
    id: str = Field(min_length=1, max_length=36)
    owner_id: str
    owner_name: str
    department_id: str
    skill_id: str
    skill_name: str
    skill_version: str
    skill_commit: str
    skill_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_path: str
    manifest_snapshot: str
    adapter: str
    worker_pool: str
    concurrency_limit: int = Field(ge=1)
    state: Literal["queued", "waiting_confirmation"]
    progress: Literal[0]
    progress_message: str
    message: str
    parameters_json: str
    files_json: str
    input_hash: str
    idempotency_key: str
    confirmation_required: bool
    queued_at: datetime | None

    @field_validator("queued_at")
    @classmethod
    def require_timezone(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("Prepared timestamps require timezone")
        return value


class PreparedPayload(StrictPayload):
    version: Literal[1] = 1
    run: PreparedTask
    model_selection: ModelAuditSelection | None
    trace: TraceSummary


def freeze_prepared(prepared) -> dict:
    """Whitelist fields: never serialize LlmConfig or ORM __dict__."""
    run = prepared.run
    values = {field: getattr(run, field) for field in PreparedTask.model_fields}
    selection = prepared.llm_config
    model = None if selection is None else ModelAuditSelection(
        connection_id=selection.connection_id, provider=selection.provider, model=selection.model)
    # No arbitrary model response or exception text is retained in the trace.
    trace = TraceSummary(**{key: prepared.model_trace[key] for key in TraceSummary.model_fields if key in prepared.model_trace})
    return PreparedPayload(run=PreparedTask(**values), model_selection=model, trace=trace).model_dump(mode="json")


def restore_prepared(payload: dict):
    from ...models import RunRecord
    from ...run_service import PreparedRun
    # JSON-mode validation accepts ISO datetime, while strict fields forbid coercion.
    import json
    value = PreparedPayload.model_validate_json(json.dumps(payload, allow_nan=False))
    return PreparedRun(RunRecord(**value.run.model_dump()), value.model_selection,
                       value.trace.model_dump())
