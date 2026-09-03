from __future__ import annotations

import json
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..agent_model_gateway import (
    AgentModelStreamStats,
    build_agent_model_payload,
    iter_agent_model_stream,
    open_agent_model_stream,
    resolve_agent_model_config,
    save_agent_model_trace,
)
from ..approval_service import load_workflow_manifest
from ..audit_service import record_audit
from ..authorization import assert_skill_permission
from ..database import SessionLocal, get_db
from ..leases import lease_deadline
from ..models import (
    WorkflowAction,
    WorkflowFetchedDataPreview,
    WorkflowFetchedDataPreviewArGroup,
    WorkflowSession,
)
from ..redaction import sanitize_text
from ..reconciliation_runner import PI_HARNESS_ACTION
from ..resource_policy import workflow_root
from ..scheduler import acquire_claim_lock, recover_expired_jobs
from ..schemas_assistant import AgentModelRequest
from ..settings import settings
from ..workflow_service import (
    finalize_requested_batch_cancellation,
    pi_harness_task_context,
    pi_harness_visible_value,
    queue_pi_harness_tool,
    workflow_owner_context,
)

router = APIRouter(prefix="/api/internal/pi-harness", tags=["pi-harness"])


class PiHarnessClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=128)


class PiHarnessToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arguments: dict[str, Any] = Field(default_factory=dict)
    worker_id: str = Field(min_length=1, max_length=128)


class PiHarnessFinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=128)
    outcome: Literal["succeeded", "failed"]
    message: str = Field(default="", max_length=1000)


class PiHarnessModelRequest(AgentModelRequest):
    workflow_id: str = Field(min_length=36, max_length=36)
    harness_action_id: str = Field(min_length=36, max_length=36)
    worker_id: str = Field(min_length=1, max_length=128)


def require_pi_harness_token(authorization: str | None = Header(default=None)) -> None:
    configured = settings.pi_harness_token
    if len(configured) < 32:
        raise HTTPException(status_code=503, detail="Pi Harness Worker 尚未配置。")
    supplied = ""
    if authorization:
        scheme, separator, token = authorization.partition(" ")
        if separator and scheme.lower() == "bearer":
            supplied = token.strip()
    if not supplied or not secrets.compare_digest(supplied, configured):
        raise HTTPException(status_code=401, detail="Pi Harness Worker 认证失败。")


def _owned_snapshot_file(workflow: WorkflowSession, relative: str) -> Path:
    skill_dir = (workflow_root(workflow.owner_id, workflow.id) / "skill").resolve()
    path = (skill_dir / relative).resolve()
    if not path.is_relative_to(skill_dir) or not path.is_file() or path.is_symlink():
        raise RuntimeError("任务固定的 Skill 执行文件不存在或不安全。")
    return path


def _declared_tools(workflow: WorkflowSession) -> list[dict[str, Any]]:
    manifest = load_workflow_manifest(workflow)
    execution = manifest.execution
    if execution is None or "pi_harness" not in execution.modes:
        raise RuntimeError("任务固定的 Skill 快照没有声明 Pi Harness 执行模式。")
    mode = execution.modes["pi_harness"]
    tool_payload = yaml.safe_load(
        _owned_snapshot_file(workflow, str(mode.tools)).read_text(encoding="utf-8")
    )
    if not isinstance(tool_payload, dict) or not isinstance(tool_payload.get("tools"), list):
        raise RuntimeError("任务固定的 Pi Harness 工具清单无效。")
    declared_tools = []
    for item in tool_payload["tools"]:
        if not isinstance(item, dict):
            raise RuntimeError("任务固定的 Pi Harness 工具清单无效。")
        name = str(item.get("name") or "")
        description = str(item.get("description") or "")
        if not name or not description:
            raise RuntimeError("任务固定的 Pi Harness 工具声明不完整。")
        declared_tools.append(
            {
                "name": name,
                "description": description,
                "required_arguments": [
                    str(value) for value in item.get("required_arguments", [])
                ],
            }
        )
    return declared_tools


def _claim_payload(db: Session, workflow: WorkflowSession, action: WorkflowAction) -> dict[str, Any]:
    manifest = load_workflow_manifest(workflow)
    execution = manifest.execution
    if execution is None or "pi_harness" not in execution.modes:
        raise RuntimeError("任务固定的 Skill 快照没有声明 Pi Harness 执行模式。")
    mode = execution.modes["pi_harness"]
    instructions = _owned_snapshot_file(workflow, str(mode.instructions)).read_text(
        encoding="utf-8"
    )
    declared_tools = _declared_tools(workflow)
    owner = workflow_owner_context(db, workflow)
    model = resolve_agent_model_config(
        db,
        owner,
        workflow.model_connection_id,
        workflow.model_name,
    )
    return {
        "action_id": action.id,
        "workflow": pi_harness_task_context(workflow),
        "skill": {
            "id": workflow.skill_id,
            "version": workflow.skill_version,
            "hash": workflow.skill_hash,
            "instructions": instructions,
            "tools": declared_tools,
        },
        "model": model.model,
    }


def _assert_active_harness(
    db: Session,
    workflow_id: str,
    action_id: str | None,
    worker_id: str,
) -> WorkflowAction:
    action = (
        db.get(WorkflowAction, action_id)
        if action_id
        else db.scalar(
            select(WorkflowAction)
            .where(
                WorkflowAction.workflow_id == workflow_id,
                WorkflowAction.name == PI_HARNESS_ACTION,
                WorkflowAction.state == "running",
                WorkflowAction.worker_id == worker_id,
            )
            .order_by(WorkflowAction.queued_at.desc())
        )
    )
    if (
        action is None
        or action.workflow_id != workflow_id
        or action.name != PI_HARNESS_ACTION
        or action.state != "running"
        or action.worker_id != worker_id
    ):
        raise HTTPException(status_code=409, detail="Pi Harness 租约已经失效。")
    return action


def _fetched_preview_page(
    db: Session,
    workflow: WorkflowSession,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    raw_offset = arguments.get("offset", 0)
    raw_limit = arguments.get("limit", 50)
    if (
        isinstance(raw_offset, bool)
        or not isinstance(raw_offset, int)
        or raw_offset < 0
        or isinstance(raw_limit, bool)
        or not isinstance(raw_limit, int)
        or raw_limit < 1
        or raw_limit > 100
    ):
        raise HTTPException(status_code=422, detail="取数明细分页参数无效。")
    preview_owners = [WorkflowFetchedDataPreview.workflow_id == workflow.id]
    if workflow.fetched_bundle_id:
        preview_owners.append(
            WorkflowFetchedDataPreview.bundle_id == workflow.fetched_bundle_id
        )
    preview = db.scalar(
        select(WorkflowFetchedDataPreview)
        .where(
            WorkflowFetchedDataPreview.reconciliation_date == workflow.reconciliation_date,
            or_(*preview_owners),
        )
        .order_by(WorkflowFetchedDataPreview.created_at.desc())
        .limit(1)
    )
    if preview is None:
        return {
            "reconciliation_date": workflow.reconciliation_date,
            "revision": "",
            "summary": {},
            "total": 0,
            "offset": raw_offset,
            "limit": raw_limit,
            "groups": [],
        }
    filters = [WorkflowFetchedDataPreviewArGroup.preview_id == preview.id]
    total = int(
        db.scalar(
            select(func.count())
            .select_from(WorkflowFetchedDataPreviewArGroup)
            .where(*filters)
        )
        or 0
    )
    rows = list(
        db.scalars(
            select(WorkflowFetchedDataPreviewArGroup.payload_json)
            .where(*filters)
            .order_by(WorkflowFetchedDataPreviewArGroup.position.asc())
            .offset(raw_offset)
            .limit(raw_limit)
        ).all()
    )
    return {
        "reconciliation_date": preview.reconciliation_date,
        "revision": preview.revision,
        "summary": pi_harness_visible_value(json.loads(preview.summary_json)),
        "total": total,
        "offset": raw_offset,
        "limit": raw_limit,
        "groups": [pi_harness_visible_value(json.loads(payload)) for payload in rows],
    }


def _task_text_file_page(
    workflow: WorkflowSession,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    raw_path = arguments.get("path")
    raw_offset = arguments.get("offset", 0)
    raw_limit = arguments.get("limit", 20_000)
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise HTTPException(status_code=422, detail="任务文件路径不能为空。")
    if (
        isinstance(raw_offset, bool)
        or not isinstance(raw_offset, int)
        or raw_offset < 0
        or isinstance(raw_limit, bool)
        or not isinstance(raw_limit, int)
        or raw_limit < 1
        or raw_limit > 50_000
    ):
        raise HTTPException(status_code=422, detail="任务文件分页参数无效。")
    root = workflow_root(workflow.owner_id, workflow.id).resolve()
    requested = Path(raw_path)
    path = (requested if requested.is_absolute() else root / requested).resolve()
    normalized_parts = [part.casefold() for part in path.parts]
    blocked_path = any(
        part.startswith(".env")
        or part in {".secrets", "credentials", "secrets"}
        or part.endswith((".key", ".pem"))
        or any(
            marker in part
            for marker in (
                "api_key",
                "apikey",
                "cookie",
                "credential",
                "password",
                "secret",
                "token",
            )
        )
        for part in normalized_parts
    )
    if (
        not path.is_file()
        or path.is_symlink()
        or not path.is_relative_to(root)
        or blocked_path
        or path.suffix.casefold() not in {".csv", ".json", ".md", ".txt", ".yaml", ".yml"}
    ):
        raise HTTPException(status_code=409, detail="该文件不属于任务可读取的文本资料。")
    total_bytes = path.stat().st_size
    with path.open("rb") as source:
        source.seek(min(raw_offset, total_bytes))
        chunk = source.read(raw_limit)
    visible = pi_harness_visible_value(chunk.decode("utf-8", errors="replace"))
    return {
        "path": path.relative_to(root).as_posix(),
        "total_bytes": total_bytes,
        "offset": raw_offset,
        "limit": raw_limit,
        "next_offset": min(raw_offset + len(chunk), total_bytes),
        "content": visible,
    }


@router.post("/claim", include_in_schema=False)
def claim_pi_harness_work(
    body: PiHarnessClaimRequest,
    _: None = Depends(require_pi_harness_token),
    db: Session = Depends(get_db),
) -> dict[str, Any] | None:
    acquire_claim_lock(db)
    now = datetime.now(UTC)
    recover_expired_jobs(db, now)
    action = db.scalar(
        select(WorkflowAction)
        .join(WorkflowSession, WorkflowSession.id == WorkflowAction.workflow_id)
        .where(
            WorkflowAction.name == PI_HARNESS_ACTION,
            WorkflowAction.state == "queued",
            WorkflowSession.execution_mode == "pi_harness",
            WorkflowSession.state == "running",
        )
        .order_by(WorkflowAction.queued_at.asc())
        .limit(1)
    )
    if action is None:
        db.commit()
        return None
    workflow = db.get(WorkflowSession, action.workflow_id)
    if workflow is None:
        action.state = "failed"
        action.error_message = "任务不存在。"
        action.finished_at = now
        db.commit()
        return None
    action.state = "running"
    action.worker_id = body.worker_id
    action.attempt_count += 1
    action.started_at = now
    action.heartbeat_at = now
    action.lease_expires_at = lease_deadline(now)
    workflow.progress_message = "Pi Harness 已领取任务，正在读取 Skill"
    try:
        payload = _claim_payload(db, workflow, action)
    except Exception as exc:
        action.state = "failed"
        action.error_message = sanitize_text(str(exc), error=True)
        action.finished_at = now
        workflow.state = "failed"
        workflow.stage = "failed"
        workflow.error_message = action.error_message
        workflow.progress_message = "Pi Harness 启动失败"
        db.commit()
        return None
    record_audit(
        db,
        actor=workflow_owner_context(db, workflow),
        action="workflow.pi_harness.claimed",
        resource_type="workflow",
        resource_id=workflow.id,
        details={"skill_id": workflow.skill_id},
    )
    db.commit()
    return payload


@router.post("/actions/{action_id}/heartbeat", include_in_schema=False)
def heartbeat_pi_harness_work(
    action_id: str,
    body: PiHarnessClaimRequest,
    _: None = Depends(require_pi_harness_token),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    action = db.get(WorkflowAction, action_id)
    if (
        action is None
        or action.name != PI_HARNESS_ACTION
        or action.state != "running"
        or action.worker_id != body.worker_id
    ):
        raise HTTPException(status_code=409, detail="Pi Harness 租约已经失效。")
    now = datetime.now(UTC)
    action.heartbeat_at = now
    action.lease_expires_at = lease_deadline(now)
    db.commit()
    return {"state": "running"}


@router.post("/actions/{action_id}/finish", include_in_schema=False)
def finish_pi_harness_work(
    action_id: str,
    body: PiHarnessFinishRequest,
    _: None = Depends(require_pi_harness_token),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    action = db.get(WorkflowAction, action_id)
    if (
        action is None
        or action.name != PI_HARNESS_ACTION
        or action.state != "running"
        or action.worker_id != body.worker_id
    ):
        raise HTTPException(status_code=409, detail="Pi Harness 租约已经失效。")
    workflow = db.get(WorkflowSession, action.workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="任务不存在。")
    action.finished_at = datetime.now(UTC)
    action.heartbeat_at = None
    action.lease_expires_at = None
    if workflow.state == "cancelling":
        action.state = "cancelled"
        workflow.state = "cancelled"
        workflow.stage = "cancelled"
        workflow.progress_message = "Pi Harness 已按取消请求停止"
        finalize_requested_batch_cancellation(db, workflow.batch_id)
    elif workflow.state in {"succeeded", "cancelled"}:
        action.state = "succeeded"
        action.result_json = '{"orchestration":"completed"}'
    else:
        action.state = "failed"
        action.error_message = sanitize_text(
            body.message or "Pi Harness 未完成 Skill 要求的全部步骤。",
            error=True,
        )
        if workflow.state not in {"succeeded", "cancelled"}:
            workflow.state = "failed"
            workflow.stage = "failed"
            workflow.error_message = action.error_message
            workflow.progress_message = "Pi Harness 执行中止，未自动重试"
    db.commit()
    return {"state": action.state}


@router.post("/workflows/{workflow_id}/tools/{tool_name}", include_in_schema=False)
def request_pi_harness_tool(
    workflow_id: str,
    tool_name: str,
    body: PiHarnessToolRequest,
    _: None = Depends(require_pi_harness_token),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    workflow = db.get(WorkflowSession, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="任务不存在。")
    _assert_active_harness(db, workflow.id, None, body.worker_id)
    if tool_name not in {item["name"] for item in _declared_tools(workflow)}:
        raise HTTPException(status_code=422, detail="任务固定的 Skill 没有声明该工具。")
    if tool_name in {"inspect_fetched_data", "read_task_file"}:
        actor = workflow_owner_context(db, workflow)
        assert_skill_permission(db, actor, workflow.skill_id)
        data = (
            _fetched_preview_page(db, workflow, body.arguments)
            if tool_name == "inspect_fetched_data"
            else _task_text_file_page(workflow, body.arguments)
        )
        record_audit(
            db,
            actor=actor,
            action="workflow.pi_harness.data.inspected",
            resource_type="workflow",
            resource_id=workflow.id,
            details={
                "skill_id": workflow.skill_id,
                "source": tool_name,
                "offset": data["offset"],
                "limit": data["limit"],
            },
        )
        db.commit()
        return {
            "action_id": None,
            "state": "succeeded",
            "workflow": pi_harness_task_context(workflow),
            "data": data,
        }
    action = queue_pi_harness_tool(db, workflow, tool_name, body.arguments)
    db.refresh(workflow)
    return {
        "action_id": action.id if action else None,
        "state": action.state if action else "succeeded",
        "workflow": pi_harness_task_context(workflow),
    }


@router.get("/workflows/{workflow_id}/actions/{action_id}", include_in_schema=False)
def read_pi_harness_tool(
    workflow_id: str,
    action_id: str,
    worker_id: str,
    _: None = Depends(require_pi_harness_token),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    workflow = db.get(WorkflowSession, workflow_id)
    action = db.get(WorkflowAction, action_id)
    if workflow is None or action is None or action.workflow_id != workflow.id:
        raise HTTPException(status_code=404, detail="工具动作不存在。")
    _assert_active_harness(db, workflow.id, None, worker_id)
    return {
        "action_id": action.id,
        "state": action.state,
        "error_message": sanitize_text(action.error_message, error=True),
        "workflow": pi_harness_task_context(workflow),
    }


@router.post("/model/chat/completions", include_in_schema=False)
def stream_pi_harness_model(
    body: PiHarnessModelRequest,
    _: None = Depends(require_pi_harness_token),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    workflow = db.get(WorkflowSession, body.workflow_id)
    if workflow is None or workflow.execution_mode != "pi_harness":
        raise HTTPException(status_code=404, detail="Pi Harness 任务不存在。")
    _assert_active_harness(
        db,
        workflow.id,
        body.harness_action_id,
        body.worker_id,
    )
    owner = workflow_owner_context(db, workflow)
    config = resolve_agent_model_config(
        db,
        owner,
        workflow.model_connection_id,
        workflow.model_name,
    )
    try:
        payload = build_agent_model_payload(config, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    stream_context = open_agent_model_stream(config, payload)
    stats = AgentModelStreamStats()
    try:
        response = stream_context.__enter__()
        response.raise_for_status()
    except httpx.HTTPError as exc:
        stream_context.__exit__(*sys.exc_info())
        stats.fail(f"upstream_http_{getattr(exc.response, 'status_code', 'error')}")
        save_agent_model_trace(db, owner, config, stats)
        db.commit()
        raise HTTPException(status_code=502, detail="模型服务当前不可用。") from exc
    except Exception as exc:
        stream_context.__exit__(*sys.exc_info())
        stats.fail(type(exc).__name__)
        save_agent_model_trace(db, owner, config, stats)
        db.commit()
        raise HTTPException(status_code=502, detail="模型网关连接失败。") from exc

    def body_iterator():
        try:
            yield from iter_agent_model_stream(response, stats)
        finally:
            if stats.status == "running":
                stats.fail("stream_cancelled")
            with SessionLocal() as trace_db:
                save_agent_model_trace(trace_db, owner, config, stats)
                trace_db.commit()
            stream_context.__exit__(None, None, None)

    return StreamingResponse(
        body_iterator(),
        media_type=response.headers.get("content-type", "text/event-stream"),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
