from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .models import RunRecord, StepDefinition, StepRun, WorkflowDefinition


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _execution_shape(run: RunRecord) -> tuple[str, str]:
    if run.adapter == "http":
        return "read_only_http", "http"
    if run.adapter == "rpa":
        return "rpa", "workflow"
    return "python", "python"


def _definition_version(run: RunRecord) -> str:
    return f"{run.skill_version}+{run.skill_hash[:12]}"


def _definition(db: Session, run: RunRecord) -> WorkflowDefinition:
    workflow_key = f"standard-run:{run.skill_id}"
    version = _definition_version(run)
    existing = db.scalar(
        select(WorkflowDefinition).where(
            WorkflowDefinition.department_id == run.department_id,
            WorkflowDefinition.workflow_key == workflow_key,
            WorkflowDefinition.version == version,
        )
    )
    if existing:
        return existing

    definition_id = str(uuid.uuid4())
    values = {
        "id": definition_id,
        "department_id": run.department_id,
        "workflow_key": workflow_key,
        "name": f"{run.skill_name}标准执行流程",
        "description": "平台根据已发布 Skill 快照生成的只读标准执行流程。",
        "version": version,
        "status": "published",
        "skill_id": run.skill_id,
        "skill_version": run.skill_version,
        "skill_hash": run.skill_hash,
        "created_by": run.owner_id,
    }
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(WorkflowDefinition).values(**values)
        statement = statement.on_conflict_do_nothing(
            index_elements=["department_id", "workflow_key", "version"]
        ).returning(WorkflowDefinition.id)
    elif dialect == "sqlite":
        statement = sqlite_insert(WorkflowDefinition).values(**values)
        statement = statement.on_conflict_do_nothing(
            index_elements=["department_id", "workflow_key", "version"]
        ).returning(WorkflowDefinition.id)
    else:
        statement = insert(WorkflowDefinition).values(**values).returning(
            WorkflowDefinition.id
        )
    inserted = db.scalar(statement) is not None
    definition = db.scalar(
        select(WorkflowDefinition).where(
            WorkflowDefinition.department_id == run.department_id,
            WorkflowDefinition.workflow_key == workflow_key,
            WorkflowDefinition.version == version,
        )
    )
    if definition is None:
        raise RuntimeError("标准任务步骤定义创建失败。")
    if not inserted:
        return definition

    execution_type, execution_pool = _execution_shape(run)
    shapes = (
        ("validate-parameters", "校验任务参数", "parameter_validation", 10, "python", False),
        ("validate-files", "校验平台文件", "file_validation", 20, "python", False),
        ("execute", "执行 Skill", execution_type, 30, execution_pool, True),
        ("preview-result", "整理结果摘要", "result_preview", 40, "python", False),
        ("archive-artifacts", "归档结果文件", "artifact_archive", 50, "python", False),
    )
    for key, name, step_type, position, pool, retryable in shapes:
        db.add(
            StepDefinition(
                id=str(uuid.uuid4()),
                workflow_definition_id=definition.id,
                department_id=run.department_id,
                step_key=key,
                name=name,
                step_type=step_type,
                position=position,
                timeout_seconds=3600 if key == "execute" else 300,
                max_attempts=2 if retryable else 1,
                risk_level="read_only",
                worker_pool=pool,
                is_idempotent=retryable,
                retryable=retryable,
            )
        )
    db.flush()
    db.expire(definition, ["steps"])
    return definition


def _file_summary(run: RunRecord) -> dict[str, Any]:
    try:
        files = json.loads(run.files_json or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(files, dict):
        return {}
    count = 0
    for value in files.values():
        count += len(value) if isinstance(value, list) else int(bool(value))
    return {"file_count": count, "roles": sorted(str(key) for key in files)[:50]}


def initialize_run_steps(db: Session, run: RunRecord) -> list[StepRun]:
    existing = list(db.scalars(select(StepRun).where(StepRun.run_id == run.id)).all())
    if existing:
        return existing
    definition = _definition(db, run)
    now = datetime.now(UTC)
    execution_state = "waiting_confirmation" if run.state == "waiting_confirmation" else "queued"
    result: list[StepRun] = []
    for step in definition.steps:
        state = "pending"
        started_at = None
        finished_at = None
        queued_at = None
        input_summary: dict[str, Any] = {}
        output_summary: dict[str, Any] = {}
        if step.step_key == "validate-parameters":
            state = "succeeded"
            started_at = finished_at = now
            try:
                parameters = json.loads(run.parameters_json or "{}")
            except json.JSONDecodeError:
                parameters = {}
            output_summary = {
                "parameter_count": len(parameters) if isinstance(parameters, dict) else 0
            }
        elif step.step_key == "validate-files":
            state = "succeeded"
            started_at = finished_at = now
            output_summary = _file_summary(run)
        elif step.step_key == "execute":
            state = execution_state
            queued_at = run.queued_at
            input_summary = _file_summary(run)
        item = StepRun(
            id=str(uuid.uuid4()),
            step_definition_id=step.id,
            run_id=run.id,
            owner_id=run.owner_id,
            department_id=run.department_id,
            state=state,
            input_summary_json=_json(input_summary),
            output_summary_json=_json(output_summary),
            queued_at=queued_at,
            started_at=started_at,
            finished_at=finished_at,
        )
        db.add(item)
        result.append(item)
    db.flush()
    return result


def _step(db: Session, run: RunRecord, step_key: str) -> tuple[StepRun, StepDefinition]:
    row = db.execute(
        select(StepRun, StepDefinition)
        .join(StepDefinition, StepDefinition.id == StepRun.step_definition_id)
        .where(StepRun.run_id == run.id, StepDefinition.step_key == step_key)
    ).one_or_none()
    if row is None:
        initialize_run_steps(db, run)
        row = db.execute(
            select(StepRun, StepDefinition)
            .join(StepDefinition, StepDefinition.id == StepRun.step_definition_id)
            .where(StepRun.run_id == run.id, StepDefinition.step_key == step_key)
        ).one()
    return row[0], row[1]


def queue_run_execution_step(db: Session, run: RunRecord) -> None:
    step, _ = _step(db, run, "execute")
    step.state = "queued"
    step.queued_at = run.queued_at or datetime.now(UTC)
    step.started_at = None
    step.finished_at = None
    step.worker_id = ""
    step.error_code = ""
    step.error_message = ""
    step.can_retry = False
    step.retry_block_reason = ""
    db.flush()


def start_run_execution_step(db: Session, run: RunRecord, worker_id: str) -> None:
    step, _ = _step(db, run, "execute")
    step.state = "running"
    step.worker_id = worker_id
    step.attempt_count += 1
    step.started_at = datetime.now(UTC)
    step.error_code = ""
    step.error_message = ""
    step.can_retry = False
    step.retry_block_reason = ""
    db.flush()


def finish_run_execution_step(
    db: Session,
    run: RunRecord,
    *,
    state: str,
    result: dict[str, Any] | None = None,
    error_code: str = "",
    error_message: str = "",
) -> None:
    if state not in {"succeeded", "failed", "timed_out", "cancelled"}:
        raise ValueError("不支持的步骤终态。")
    now = datetime.now(UTC)
    execution, definition = _step(db, run, "execute")
    execution.state = state
    execution.finished_at = now
    execution.error_code = error_code[:64]
    execution.error_message = error_message
    summary = (result or {}).get("summary", {})
    execution.output_summary_json = _json(summary if isinstance(summary, dict) else {})
    execution.can_retry = state in {"failed", "timed_out"} and definition.retryable
    execution.retry_block_reason = "" if execution.can_retry else (
        "该步骤不是可安全重试的幂等步骤。" if state in {"failed", "timed_out"} else ""
    )

    for key in ("preview-result", "archive-artifacts"):
        downstream, _ = _step(db, run, key)
        if state == "succeeded":
            downstream.state = "succeeded"
            downstream.started_at = now
            downstream.finished_at = now
            downstream.output_summary_json = execution.output_summary_json
        elif downstream.state == "pending":
            downstream.state = "skipped"
            downstream.finished_at = now
            downstream.retry_block_reason = "前置执行步骤未成功。"
    db.flush()
