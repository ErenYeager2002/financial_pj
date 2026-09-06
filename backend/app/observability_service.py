from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import UserContext
from .contracts import ModelUsageRead, ObservabilitySummary, StepMetricRead
from .models import (
    ApprovalRecord,
    ModelTraceRecord,
    RunModelAudit,
    RunRecord,
    StepDefinition,
    StepRun,
)
from .task_center_service import task_center_overview, task_center_scope


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return max(0.0, (end - start).total_seconds())


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def observability_summary(
    db: Session, user: UserContext, hours: int
) -> ObservabilitySummary:
    since = datetime.now(UTC) - timedelta(hours=hours)
    task_overview = task_center_overview(db, user, limit=1, since=since)
    runs = list(
        db.scalars(
            select(RunRecord).where(
                RunRecord.department_id == user.department_id,
                RunRecord.created_at >= since,
            )
        ).all()
    )
    run_ids = [item.id for item in runs]
    steps: list[tuple[StepRun, StepDefinition]] = []
    approvals: list[ApprovalRecord] = []
    model_rows: list[RunModelAudit] = []
    trace_rows = list(
        db.scalars(
            select(ModelTraceRecord).where(
                ModelTraceRecord.department_id == user.department_id,
                ModelTraceRecord.created_at >= since,
            )
        ).all()
    )
    if run_ids:
        steps = list(
            db.execute(
                select(StepRun, StepDefinition)
                .join(StepDefinition, StepDefinition.id == StepRun.step_definition_id)
                .where(StepRun.run_id.in_(run_ids))
            ).all()
        )
        approvals = list(
            db.scalars(
                select(ApprovalRecord).where(
                    ApprovalRecord.run_id.in_(run_ids),
                    ApprovalRecord.department_id == user.department_id,
                )
            ).all()
        )
        model_rows = list(
            db.scalars(select(RunModelAudit).where(RunModelAudit.run_id.in_(run_ids))).all()
        )

    task_count = sum(
        (
            task_overview.state_counts.pending,
            task_overview.state_counts.running,
            task_overview.state_counts.failed,
            task_overview.state_counts.succeeded,
            task_overview.state_counts.cancelled,
        )
    )
    failed_task_count = task_overview.state_counts.failed
    failed_run_count = failed_task_count
    queue_seconds = [
        value
        for item in runs
        if (value := _seconds(item.queued_at, item.started_at)) is not None
    ]
    run_seconds = [
        value
        for item in runs
        if (value := _seconds(item.started_at, item.finished_at)) is not None
    ]

    step_counts: Counter[str] = Counter()
    step_failures: Counter[str] = Counter()
    step_durations: dict[str, list[float]] = defaultdict(list)
    retry_count = 0
    manual_step_count = 0
    for step, definition in steps:
        step_counts[definition.step_type] += 1
        if step.state in {"failed", "timed_out"}:
            step_failures[definition.step_type] += 1
        if (duration := _seconds(step.started_at, step.finished_at)) is not None:
            step_durations[definition.step_type].append(duration)
        retry_count += max(0, step.attempt_count - 1)
        if definition.step_type in {"human_confirmation", "admin_approval"}:
            manual_step_count += 1

    model_counts: Counter[tuple[str, str]] = Counter()
    model_failures: Counter[tuple[str, str]] = Counter()
    model_fallbacks: Counter[tuple[str, str]] = Counter()
    model_durations: dict[tuple[str, str], list[float]] = defaultdict(list)
    model_input_tokens: Counter[tuple[str, str]] = Counter()
    model_output_tokens: Counter[tuple[str, str]] = Counter()
    traced_run_ids: set[str] = set()
    for trace in trace_rows:
        key = (trace.provider, trace.model)
        model_counts[key] += 1
        model_failures[key] += trace.status == "failed"
        model_fallbacks[key] += trace.status == "fallback"
        model_durations[key].append(float(trace.duration_ms))
        model_input_tokens[key] += trace.input_tokens
        model_output_tokens[key] += trace.output_tokens
        if trace.run_id:
            traced_run_ids.add(trace.run_id)
    for audit in model_rows:
        if audit.run_id not in traced_run_ids:
            model_counts[(audit.provider, audit.model)] += 1
    return ObservabilitySummary(
        window_hours=hours,
        run_count=task_count,
        failed_run_count=failed_run_count,
        failure_rate=round(failed_run_count / task_count, 4) if task_count else 0.0,
        average_queue_seconds=_average(queue_seconds),
        average_run_seconds=_average(run_seconds),
        retry_count=retry_count,
        approval_count=len(approvals),
        manual_intervention_count=len(approvals) + manual_step_count,
        task_count=task_count,
        failed_task_count=failed_task_count,
        task_scope=task_center_scope(user, f"最近 {hours} 小时内创建"),
        step_metrics=[
            StepMetricRead(
                step_type=step_type,
                run_count=count,
                failed_count=step_failures[step_type],
                average_duration_seconds=_average(step_durations[step_type]),
            )
            for step_type, count in sorted(step_counts.items())
        ],
        model_usage=[
            ModelUsageRead(
                provider=provider,
                model=model,
                request_count=count,
                failed_count=model_failures[(provider, model)],
                fallback_count=model_fallbacks[(provider, model)],
                average_duration_ms=_average(model_durations[(provider, model)]),
                input_tokens=model_input_tokens[(provider, model)],
                output_tokens=model_output_tokens[(provider, model)],
            )
            for (provider, model), count in sorted(model_counts.items())
        ],
    )
