from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import JSON, String, case, cast, func, literal, select, union_all
from sqlalchemy.orm import Session

from .auth import UserContext
from .contracts import (
    TaskCenterItem,
    TaskCenterPage,
    TaskCenterReferenceType,
    TaskCenterStateCounts,
    TaskCenterViewState,
)
from .models import RunRecord, WorkflowBatch, WorkflowSession
from .redaction import sanitize_text
from .resource_policy import owner_list_filter

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
VIEW_STATES: tuple[TaskCenterViewState, ...] = (
    "pending",
    "running",
    "failed",
    "succeeded",
    "cancelled",
)
FAILED_STATES = {"failed", "timed_out"}
CANCELLED_STATES = {"cancelled"}
SUCCEEDED_STATES = {"succeeded"}
RUNNING_STATES = {"running", "cancelling", "finalizing"}
FAILED_STAGES = {"failed"}
CANCELLED_STAGES = {"cancelled"}
SUCCEEDED_STAGES = {"completed"}
RUNNING_STAGES = {"applying", "finalizing", "supplementing_fetched_data"}


def _load_object(value: str) -> dict[str, Any]:
    try:
        loaded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _load_dates(value: str) -> list[str]:
    try:
        loaded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(loaded, list):
        return []
    return sorted({item for item in loaded if isinstance(item, str) and DATE.fullmatch(item)})


def _run_dates(run: RunRecord) -> list[str]:
    parameters = _load_object(run.parameters_json)
    for key in ("business_date", "reconciliation_date", "date"):
        value = parameters.get(key)
        if isinstance(value, str) and DATE.fullmatch(value):
            return [value]
    return []


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _run_updated_at(run: RunRecord) -> datetime:
    return run.finished_at or run.started_at or run.queued_at or run.created_at


def task_center_view_state(state: str, stage: str = "") -> TaskCenterViewState:
    if state in FAILED_STATES or stage in FAILED_STAGES:
        return "failed"
    if state in CANCELLED_STATES or stage in CANCELLED_STAGES:
        return "cancelled"
    if state in SUCCEEDED_STATES or stage in SUCCEEDED_STAGES:
        return "succeeded"
    if state in RUNNING_STATES or stage in RUNNING_STAGES:
        return "running"
    return "pending"


def _view_state_expression(state: Any, stage: Any | None = None) -> Any:
    failed = state.in_(FAILED_STATES)
    cancelled = state.in_(CANCELLED_STATES)
    succeeded = state.in_(SUCCEEDED_STATES)
    running = state.in_(RUNNING_STATES)
    if stage is not None:
        failed = failed | stage.in_(FAILED_STAGES)
        cancelled = cancelled | stage.in_(CANCELLED_STAGES)
        succeeded = succeeded | stage.in_(SUCCEEDED_STAGES)
        running = running | stage.in_(RUNNING_STAGES)
    return case(
        (failed, "failed"),
        (cancelled, "cancelled"),
        (succeeded, "succeeded"),
        (running, "running"),
        else_="pending",
    )


def _business_task_id(display_id: str | None, reference_id: str) -> str:
    candidate = (display_id or "").strip()
    if not candidate or candidate == reference_id or UUID.fullmatch(candidate):
        return ""
    return candidate[:192]


def _safe_failure_summary(view_state: TaskCenterViewState) -> str:
    if view_state != "failed":
        return ""
    # The compact query deliberately never reads raw failure detail into its response.
    return "任务未完成，请进入详情查看失败步骤。"


def _dates_fields(dates: list[str]) -> tuple[str, str, int]:
    return (dates[0], dates[-1], len(dates)) if dates else ("", "", 0)


def _run_item(run: RunRecord) -> TaskCenterItem:
    dates = _run_dates(run)
    start, end, count = _dates_fields(dates)
    view_state = task_center_view_state(run.state)
    return TaskCenterItem(
        reference_type="run",
        reference_id=run.id,
        detail_href=f"/dashboard/runs/{quote(run.id, safe='')}",
        business_task_id="",
        skill_id=run.skill_id,
        skill_name=run.skill_name,
        business_date_start=start,
        business_date_end=end,
        business_date_count=count,
        view_state=view_state,
        original_state=run.state,
        progress=min(max(run.progress, 0), 100),
        progress_message=sanitize_text(run.progress_message, max_length=160),
        error_summary=_safe_failure_summary(view_state),
        created_at=run.created_at,
        updated_at=_run_updated_at(run),
    )


def _workflow_item(workflow: WorkflowSession) -> TaskCenterItem:
    dates = [workflow.reconciliation_date] if DATE.fullmatch(workflow.reconciliation_date) else []
    start, end, count = _dates_fields(dates)
    view_state = task_center_view_state(workflow.state, workflow.stage)
    return TaskCenterItem(
        reference_type="workflow",
        reference_id=workflow.id,
        detail_href=f"/dashboard/workflows/{quote(workflow.id, safe='')}",
        business_task_id=_business_task_id(workflow.display_id, workflow.id),
        skill_id=workflow.skill_id,
        skill_name=workflow.skill_name,
        business_date_start=start,
        business_date_end=end,
        business_date_count=count,
        view_state=view_state,
        original_state=workflow.state,
        original_stage=workflow.stage,
        progress=min(max(workflow.progress, 0), 100),
        progress_message=sanitize_text(workflow.progress_message, max_length=160),
        error_summary=_safe_failure_summary(view_state),
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def _batch_item(batch: WorkflowBatch) -> TaskCenterItem:
    dates = _load_dates(batch.reconciliation_dates_json)
    start, end, count = _dates_fields(dates)
    view_state = task_center_view_state(batch.state)
    return TaskCenterItem(
        reference_type="workflow_batch",
        reference_id=batch.id,
        detail_href=f"/dashboard/workflows/batches/{quote(batch.id, safe='')}",
        business_task_id=_business_task_id(batch.display_id, batch.id),
        skill_id=batch.skill_id,
        skill_name=batch.skill_name,
        business_date_start=start,
        business_date_end=end,
        business_date_count=count,
        view_state=view_state,
        original_state=batch.state,
        progress=min(max(batch.progress, 0), 100),
        progress_message=sanitize_text(batch.progress_message, max_length=160),
        error_summary=_safe_failure_summary(view_state),
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


def _batch_date_expressions(dialect_name: str) -> tuple[Any, Any]:
    # Batch creation stores a sorted, unique, consecutive date list, so its
    # first and last JSON elements are the canonical range bounds.
    if dialect_name == "postgresql":
        payload = cast(WorkflowBatch.reconciliation_dates_json, JSON)
        start = payload[0].as_string()
        end = payload[-1].as_string()
    else:
        start = func.json_extract(WorkflowBatch.reconciliation_dates_json, "$[0]")
        last_path = (
            literal("$[")
            + cast(func.json_array_length(WorkflowBatch.reconciliation_dates_json) - 1, String)
            + literal("]")
        )
        end = func.json_extract(WorkflowBatch.reconciliation_dates_json, last_path)
    return start, end


def task_center_candidates_query(dialect_name: str, user: UserContext) -> Any:
    run_parameters = cast(RunRecord.parameters_json, JSON)
    run_date = func.coalesce(
        run_parameters["business_date"].as_string(),
        run_parameters["reconciliation_date"].as_string(),
        run_parameters["date"].as_string(),
        "",
    )
    run_updated = func.coalesce(
        RunRecord.finished_at,
        RunRecord.started_at,
        RunRecord.queued_at,
        RunRecord.created_at,
    )
    batch_start, batch_end = _batch_date_expressions(dialect_name)

    run_query = select(
        literal("run").label("reference_type"),
        RunRecord.id.label("reference_id"),
        RunRecord.skill_id.label("skill_id"),
        run_date.label("business_date_start"),
        run_date.label("business_date_end"),
        run_updated.label("updated_at"),
        _view_state_expression(RunRecord.state).label("view_state"),
    ).where(owner_list_filter(RunRecord, user))
    workflow_query = select(
        literal("workflow").label("reference_type"),
        WorkflowSession.id.label("reference_id"),
        WorkflowSession.skill_id.label("skill_id"),
        WorkflowSession.reconciliation_date.label("business_date_start"),
        WorkflowSession.reconciliation_date.label("business_date_end"),
        WorkflowSession.updated_at.label("updated_at"),
        _view_state_expression(WorkflowSession.state, WorkflowSession.stage).label("view_state"),
    ).where(
        owner_list_filter(WorkflowSession, user),
        WorkflowSession.context_json.like('%"started_from_form": true%'),
        WorkflowSession.batch_id.is_(None),
    )
    batch_query = select(
        literal("workflow_batch").label("reference_type"),
        WorkflowBatch.id.label("reference_id"),
        WorkflowBatch.skill_id.label("skill_id"),
        batch_start.label("business_date_start"),
        batch_end.label("business_date_end"),
        WorkflowBatch.updated_at.label("updated_at"),
        _view_state_expression(WorkflowBatch.state).label("view_state"),
    ).where(owner_list_filter(WorkflowBatch, user))
    return union_all(run_query, workflow_query, batch_query).subquery("task_center_candidates")


def query_task_center(
    db: Session,
    user: UserContext,
    *,
    page: int,
    page_size: int,
    view_state: TaskCenterViewState | None = None,
    item_type: TaskCenterReferenceType | None = None,
    skill_id: str = "",
    business_date_from: str = "",
    business_date_to: str = "",
    updated_from: datetime | None = None,
    updated_to: datetime | None = None,
) -> TaskCenterPage:
    if business_date_from and not DATE.fullmatch(business_date_from):
        raise HTTPException(status_code=422, detail="业务开始日期格式无效。")
    if business_date_to and not DATE.fullmatch(business_date_to):
        raise HTTPException(status_code=422, detail="业务结束日期格式无效。")
    if business_date_from and business_date_to and business_date_from > business_date_to:
        raise HTTPException(status_code=422, detail="业务日期范围无效。")
    if updated_from and updated_to and _aware(updated_from) > _aware(updated_to):
        raise HTTPException(status_code=422, detail="更新时间范围无效。")

    dialect_name = db.bind.dialect.name if db.bind is not None else ""
    candidates = task_center_candidates_query(dialect_name, user)
    filters = []
    if item_type:
        filters.append(candidates.c.reference_type == item_type)
    if skill_id:
        filters.append(candidates.c.skill_id == skill_id)
    if business_date_from:
        filters.extend(
            [
                candidates.c.business_date_end != "",
                candidates.c.business_date_end >= business_date_from,
            ]
        )
    if business_date_to:
        filters.extend(
            [
                candidates.c.business_date_start != "",
                candidates.c.business_date_start <= business_date_to,
            ]
        )
    if updated_from:
        filters.append(candidates.c.updated_at >= updated_from)
    if updated_to:
        filters.append(candidates.c.updated_at <= updated_to)

    count_rows = db.execute(
        select(candidates.c.view_state, func.count())
        .where(*filters)
        .group_by(candidates.c.view_state)
    ).all()
    counts = {state: 0 for state in VIEW_STATES}
    for state, count in count_rows:
        counts[state] = int(count)

    page_filters = list(filters)
    if view_state:
        page_filters.append(candidates.c.view_state == view_state)
    total = int(db.scalar(select(func.count()).select_from(candidates).where(*page_filters)) or 0)
    selected = db.execute(
        select(candidates.c.reference_type, candidates.c.reference_id)
        .where(*page_filters)
        .order_by(
            candidates.c.updated_at.desc(),
            candidates.c.reference_type.asc(),
            candidates.c.reference_id.asc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    ids_by_type: dict[str, list[str]] = {"run": [], "workflow": [], "workflow_batch": []}
    for reference_type, reference_id in selected:
        ids_by_type[reference_type].append(reference_id)
    records: dict[tuple[str, str], TaskCenterItem] = {}
    if ids_by_type["run"]:
        for record in db.scalars(
            select(RunRecord).where(RunRecord.id.in_(ids_by_type["run"]))
        ).all():
            records[("run", record.id)] = _run_item(record)
    if ids_by_type["workflow"]:
        for record in db.scalars(
            select(WorkflowSession).where(WorkflowSession.id.in_(ids_by_type["workflow"]))
        ).all():
            records[("workflow", record.id)] = _workflow_item(record)
    if ids_by_type["workflow_batch"]:
        for record in db.scalars(
            select(WorkflowBatch).where(WorkflowBatch.id.in_(ids_by_type["workflow_batch"]))
        ).all():
            records[("workflow_batch", record.id)] = _batch_item(record)
    page_items = [
        records[(reference_type, reference_id)] for reference_type, reference_id in selected
    ]
    return TaskCenterPage(
        items=page_items,
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
        state_counts=TaskCenterStateCounts(**counts),
    )
