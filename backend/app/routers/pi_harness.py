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
from ..ar_execution_service import read_evidence_page, record_evidence_read
from ..ar_agent_budget import reserve_agent_call
from ..audit_service import record_audit
from ..database import SessionLocal, get_db
from ..leases import lease_deadline
from ..model_visible_data import (
    MAX_MODEL_VISIBLE_BYTES,
    UNSAFE_CONTENT,
    read_safe_text_page,
)
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
    mark_workflow_action_execution_rejected,
    pi_harness_task_context,
    pi_harness_visible_value,
    queue_pi_harness_tool,
    workflow_owner_context,
)

router = APIRouter(prefix="/api/internal/pi-harness", tags=["pi-harness"])


class PiHarnessClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=128)
    execution_contracts: list[str] = Field(default_factory=list, max_length=8)


class PiHarnessToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arguments: dict[str, Any] = Field(default_factory=dict)
    worker_id: str = Field(min_length=1, max_length=128)
    harness_action_id: str = Field(default="", max_length=36)


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
    from ..ar_snapshot_contract import declared_tools
    from ..ar_execution_runner import execution_version

    manifest = load_workflow_manifest(workflow)
    execution = manifest.execution
    if execution is None or "pi_harness" not in execution.modes:
        raise RuntimeError("任务固定的 Skill 快照没有声明 Pi Harness 执行模式。")
    mode = execution.modes["pi_harness"]
    tools_path = _owned_snapshot_file(workflow, str(mode.tools))
    tools_page = read_safe_text_page(
        tools_path,
        offset=0,
        limit=MAX_MODEL_VISIBLE_BYTES,
        format_hint=tools_path.suffix,
    )
    if not tools_page.available or tools_page.next_offset < tools_page.total_bytes:
        raise RuntimeError("任务固定的 Pi Harness 工具清单无法安全读取。")
    try:
        tool_payload = yaml.safe_load(tools_page.content)
    except yaml.YAMLError as exc:
        raise RuntimeError("任务固定的 Pi Harness 工具清单无效。") from exc
    if not isinstance(tool_payload, dict) or not isinstance(tool_payload.get("tools"), list):
        raise RuntimeError("任务固定的 Pi Harness 工具清单无效。")
    try:
        contract = execution_version(workflow)
    except (OSError, ValueError) as exc:
        raise RuntimeError("任务固定的执行契约与当前平台不兼容。") from exc
    try:
        tools = declared_tools(tool_payload, contract)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    return [{**item, "description": pi_harness_visible_value(item["description"])} for item in tools]


def _claim_payload(db: Session, workflow: WorkflowSession, action: WorkflowAction) -> dict[str, Any]:
    from ..ar_execution_contract import CONTRACT_VERSION
    from ..ar_execution_runner import execution_version

    if bool(execution_version(workflow)) != action.is_contract_isolated:
        raise RuntimeError("Agent 动作队列与固定执行契约不一致，未启动模型或业务工具。")

    if execution_version(workflow) == CONTRACT_VERSION:
        from ..workflow_service import _ensure_workflow_skill_snapshot

        _ensure_workflow_skill_snapshot(db, workflow)
    manifest = load_workflow_manifest(workflow)
    execution = manifest.execution
    if execution is None or "pi_harness" not in execution.modes:
        raise RuntimeError("任务固定的 Skill 快照没有声明 Pi Harness 执行模式。")
    mode = execution.modes["pi_harness"]
    instruction_page = read_safe_text_page(
        _owned_snapshot_file(workflow, str(mode.instructions)),
        offset=0,
        limit=50_000,
        format_hint=Path(str(mode.instructions)).suffix,
    )
    if not instruction_page.available or instruction_page.next_offset < instruction_page.total_bytes:
        raise RuntimeError("任务固定的 Pi Harness 执行说明无法安全读取。")
    instructions = instruction_page.content
    declared_tools = _declared_tools(workflow)
    contract = execution_version(workflow)
    if contract == CONTRACT_VERSION:
        extra = read_safe_text_page(_owned_snapshot_file(workflow, "config/execution-v2.md"),
                                    offset=0, limit=50_000, format_hint="md")
        if not extra.available or extra.next_offset < extra.total_bytes:
            raise RuntimeError("新版核销执行说明无法完整读取。")
        instructions += "\n\n" + extra.content
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
            "execution_contract": contract,
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
        "summary": _safe_preview_json(preview.summary_json),
        "total": total,
        "offset": raw_offset,
        "limit": raw_limit,
        "groups": [_safe_preview_json(payload) for payload in rows],
    }


def _safe_preview_json(value: object) -> Any:
    """Parse stored preview JSON before applying the shared visible-data filter."""
    if not isinstance(value, str):
        return UNSAFE_CONTENT
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return UNSAFE_CONTENT
    return pi_harness_visible_value(parsed)


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
    safe_page = read_safe_text_page(
        path,
        offset=raw_offset,
        limit=raw_limit,
        format_hint=path.suffix,
    )
    return {
        "path": path.relative_to(root).as_posix(),
        "total_bytes": safe_page.total_bytes,
        "offset": safe_page.offset,
        "limit": safe_page.limit,
        "next_offset": safe_page.next_offset,
        "content": safe_page.content,
        "available": safe_page.available,
    }


@router.post("/claim", include_in_schema=False)
def claim_pi_harness_work(
    body: PiHarnessClaimRequest,
    _: None = Depends(require_pi_harness_token),
    db: Session = Depends(get_db),
) -> dict[str, Any] | None:
    from ..ar_execution_runner import execution_version
    from ..workflow_action_state import action_storage_states

    acquire_claim_lock(db)
    now = datetime.now(UTC)
    recover_expired_jobs(db, now)
    candidates = db.scalars(
        select(WorkflowAction)
        .join(WorkflowSession, WorkflowSession.id == WorkflowAction.workflow_id)
        .where(
            WorkflowAction.name == PI_HARNESS_ACTION,
            WorkflowAction._stored_state.in_(action_storage_states("queued")),
            WorkflowSession.execution_mode == "pi_harness",
            WorkflowSession.state == "running",
        )
        .order_by(WorkflowAction.queued_at.asc())
        .execution_options(yield_per=50)
    )
    action = None
    try:
        for candidate in candidates:
            task = db.get(WorkflowSession, candidate.workflow_id)
            if task is not None:
                try:
                    contract = execution_version(task)
                except (OSError, ValueError):
                    # Let the normal claim error path report an invalid fixed snapshot.
                    contract = ""
                if contract and contract not in body.execution_contracts:
                    continue
            action = candidate
            break
    finally:
        candidates.close()
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
    try:
        workflow_owner_context(db, workflow)
    except HTTPException:
        mark_workflow_action_execution_rejected(db, workflow, action)
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
        required_contract = payload["skill"].get("execution_contract")
        if required_contract and required_contract not in body.execution_contracts:
            raise RuntimeError("当前 Agent Worker 不支持任务的分阶段执行契约，需使用匹配版本并核查任务恢复条件；不会退回旧流程。")
    except HTTPException as exc:
        if exc.status_code == 403:
            mark_workflow_action_execution_rejected(db, workflow, action)
        else:
            action.state = "failed"
            action.error_message = sanitize_text(
                str(exc.detail),
                error=True,
                hidden_message="Pi Harness 读取任务配置失败。",
            )
            action.finished_at = now
            workflow.state = "failed"
            workflow.stage = "failed"
            workflow.error_message = action.error_message
            workflow.progress_message = "Pi Harness 读取任务配置失败"
        db.commit()
        return None
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
    from ..ar_execution_contract import publication_needs_completion

    acquire_claim_lock(db)
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
    context = json.loads(workflow.context_json or "{}")
    if (publication_needs_completion(context)
            or ((context.get("ar_execution") or {}).get("publication") == "verified" and workflow.stage == "finalizing")):
        action.state = "failed"
        action.error_message = sanitize_text(body.message or "Agent 在材料发布后停止。", error=True)
        context["ar_harness_failure"] = {"action_id": action.id, "message": action.error_message}
        workflow.context_json = json.dumps(context, ensure_ascii=False)
        # Publication already committed. The separately queued deterministic
        # completion must retain its execution rights even if the Agent stops.
    elif workflow.state == "cancelling":
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
            previous_error = workflow.error_message if workflow.state == "failed" else ""
            workflow.state = "failed"
            workflow.stage = "failed"
            workflow.error_message = previous_error or action.error_message
            workflow.progress_message = "Pi Harness 执行中止，未自动重试"
            if context.get("ar_execution") and workflow.batch_id and workflow.batch:
                workflow.batch.state = "failed"
                workflow.batch.error_message = workflow.error_message
                workflow.batch.progress_message = f"第 {workflow.batch_sequence} 天的 Agent 已停止，后续日期暂停"
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
    active_action = _assert_active_harness(db, workflow.id, body.harness_action_id or None, body.worker_id)
    if (json.loads(workflow.context_json or "{}").get("ar_execution") and not body.harness_action_id):
        raise HTTPException(status_code=422, detail="新版工具请求必须绑定本次 Agent 动作，旧会话不能借用恢复后的租约。")
    try:
        workflow_owner_context(db, workflow)
    except HTTPException:
        mark_workflow_action_execution_rejected(db, workflow, active_action)
        db.commit()
        raise
    try:
        declared_tools = _declared_tools(workflow)
    except RuntimeError as exc:
        active_action.state = "failed"
        active_action.error_message = "任务固定的 Pi Harness 工具清单无法安全读取。"
        active_action.finished_at = datetime.now(UTC)
        workflow.state = "failed"
        workflow.stage = "failed"
        workflow.error_message = active_action.error_message
        workflow.progress_message = "Pi Harness 工具配置读取失败"
        db.commit()
        raise HTTPException(
            status_code=409,
            detail="任务固定的 Pi Harness 工具清单无法安全读取，任务已停止；平台不会自动重试。",
        ) from exc
    if tool_name not in {item["name"] for item in declared_tools}:
        raise HTTPException(status_code=422, detail="任务固定的 Skill 没有声明该工具。")
    reserve_agent_call(db, workflow, active_action, body.worker_id, "tool_calls")
    if tool_name == "inspect_order_evidence":
        allowed = {"offset", "limit", "query", "record_id", "detail_offset", "fingerprint"}
        args = body.arguments
        if set(args) - allowed or any(
            isinstance(args.get(key, default), bool) or not isinstance(args.get(key, default), int)
            for key, default in (("offset", 0), ("limit", 20), ("detail_offset", 0))
        ) or any(not isinstance(args.get(key, ""), str) for key in ("query", "record_id", "fingerprint")):
            raise HTTPException(status_code=422, detail="逐单证据查询参数无效。")
        snapshot = json.loads(workflow.context_json or "{}")
        binding_keys = ("workspace", "ar_evidence", "final_result")
        binding = {key: snapshot.get(key) for key in binding_keys}
        # Parsing/indexing a large order must not hold the global claim lock.
        page = read_evidence_page(db, workflow, **args)
        db.commit()
        acquire_claim_lock(db)
        db.refresh(workflow)
        db.refresh(active_action)
        _assert_active_harness(db, workflow.id, active_action.id, body.worker_id)
        deadline = active_action.lease_expires_at
        if deadline is not None and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        if deadline is None or deadline <= datetime.now(UTC) or workflow.state not in {"active", "running"}:
            raise HTTPException(status_code=409, detail="逐单检查的 Agent 租约或任务执行状态已失效。")
        current = json.loads(workflow.context_json or "{}")
        if (binding != {key: current.get(key) for key in binding_keys}
                or workflow.reconciliation_date != page.reconciliation_date):
            raise HTTPException(status_code=409, detail="读取期间任务证据版本发生变化，本页未计入检查，请重新读取。")
        record_evidence_read(workflow, page)
        record_audit(
            db, actor=workflow_owner_context(db, workflow),
            action="workflow.pi_harness.order_evidence.inspected",
            resource_type="workflow", resource_id=workflow.id,
            details={"fingerprint": page.fingerprint, "offset": page.offset, "count": len(page.records),
                     "detail_offset": page.detail.offset if page.detail else None,
                     "detail_next_offset": page.detail.next_offset if page.detail else None},
        )
        db.commit()
        return {"action_id": None, "state": "succeeded",
                "workflow": pi_harness_task_context(workflow), "data": page.model_dump()}
    if tool_name in {"inspect_fetched_data", "read_task_file"}:
        actor = workflow_owner_context(db, workflow)
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
    try:
        action = queue_pi_harness_tool(db, workflow, tool_name, body.arguments,
                                       harness_action_id=active_action.id, worker_id=body.worker_id)
    except HTTPException as exc:
        # The harness action is already running. A permission change must end
        # that action explicitly instead of leaving the task in a false
        # running state; the tool itself is never retried automatically.
        if exc.status_code == 403 and active_action.state == "running":
            mark_workflow_action_execution_rejected(db, workflow, active_action)
            db.commit()
        raise
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
    active_action = _assert_active_harness(db, workflow.id, None, worker_id)
    try:
        workflow_owner_context(db, workflow)
    except HTTPException:
        mark_workflow_action_execution_rejected(db, workflow, active_action)
        db.commit()
        raise
    return {
        "action_id": action.id,
        "state": action.state,
        "error_message": pi_harness_visible_value(
            sanitize_text(action.error_message, error=True)
        ),
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
    active_action = _assert_active_harness(
        db,
        workflow.id,
        body.harness_action_id,
        body.worker_id,
    )
    try:
        owner = workflow_owner_context(db, workflow)
    except HTTPException:
        mark_workflow_action_execution_rejected(db, workflow, active_action)
        db.commit()
        raise
    config = resolve_agent_model_config(
        db,
        owner,
        workflow.model_connection_id,
        workflow.model_name,
    )
    safe_model_request = pi_harness_visible_value(body.model_dump(exclude_none=True))
    try:
        payload = build_agent_model_payload(config, safe_model_request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    reserve_agent_call(db, workflow, active_action, body.worker_id, "model_calls")
    stream_context = open_agent_model_stream(
        config,
        payload,
        **({"session_id": f"workflow:{workflow.id}"} if config.provider == "opencode_go" else {}),
    )
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
