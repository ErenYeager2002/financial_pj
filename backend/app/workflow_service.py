from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .auth import UserContext
from .leases import LeaseHeartbeat, lease_deadline
from .model_service import resolve_runtime_config
from .models import (
    FileRecord,
    WorkflowAction,
    WorkflowBatch,
    WorkflowMessage,
    WorkflowSession,
)
from .registry import RegisteredSkill, registry
from .scheduler import (
    acquire_claim_lock,
    active_workflow_count,
    recover_expired_jobs,
)
from .schemas import (
    WorkflowBatchRead,
    WorkflowBatchStart,
    WorkflowCreate,
    WorkflowRead,
    WorkflowStart,
)
from .service_credential_service import (
    has_service_credential,
    resolve_service_credential,
)
from .settings import settings
from .storage import safe_filename, sha256_file
from .workflow_orchestrator import WorkflowDecision, decide_workflow_turn

WEEKDAYS = "一二三四五六日"
CONFIRM_STAGES = {"awaiting_date_confirmation", "awaiting_apply_confirmation"}
BUSY_STAGES = {"preparing", "applying"}
FILE_ROLES = {
    "finance_workbooks": "02_我的表副本",
}
CONFIRM_REPLIES = {"确认", "可以", "可以写", "按这个写", "没问题写吧", "写吧", "对", "是"}


class PostWriteVerificationError(RuntimeError):
    """The deterministic write completed, but its final baseline could not be verified."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _assert_visible(workflow: WorkflowSession, user: UserContext) -> None:
    if workflow.department_id != user.department_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="无权查看其他部门的对话任务。")


def get_workflow_or_404(
    db: Session,
    workflow_id: str,
    user: UserContext,
) -> WorkflowSession:
    workflow = db.get(WorkflowSession, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="对话任务不存在。")
    _assert_visible(workflow, user)
    return workflow


def _message(
    db: Session,
    workflow: WorkflowSession,
    role: str,
    content: str,
    data: dict[str, Any] | None = None,
) -> WorkflowMessage:
    item = WorkflowMessage(
        workflow_id=workflow.id,
        role=role,
        content=content,
        data_json=_json(data or {}),
    )
    db.add(item)
    workflow.updated_at = datetime.now(UTC)
    return item


def serialize_workflow(workflow: WorkflowSession) -> WorkflowRead:
    messages = sorted(workflow.messages, key=lambda item: item.id)
    actions = sorted(workflow.actions, key=lambda item: item.queued_at)
    context = _load(workflow.context_json, {})
    return WorkflowRead(
        id=workflow.id,
        owner_id=workflow.owner_id,
        skill_id=workflow.skill_id,
        skill_name=workflow.skill_name,
        skill_version=workflow.skill_version,
        model_provider=workflow.model_provider,
        model_name=workflow.model_name,
        state=workflow.state,
        stage=workflow.stage,
        reconciliation_date=workflow.reconciliation_date,
        batch_id=workflow.batch_id,
        batch_sequence=workflow.batch_sequence,
        requires_confirmation=bool(context.get("requires_confirmation", True)),
        progress=workflow.progress,
        progress_message=workflow.progress_message,
        error_message=workflow.error_message,
        files=_load(workflow.files_json, {}),
        artifacts=_load(workflow.artifacts_json, []),
        messages=[
            {
                "id": item.id,
                "role": item.role,
                "content": item.content,
                "data": _load(item.data_json, {}),
                "created_at": item.created_at,
            }
            for item in messages
        ],
        actions=[
            {
                "id": item.id,
                "name": item.name,
                "state": item.state,
                "error_message": item.error_message,
                "created_at": item.queued_at,
                "finished_at": item.finished_at,
            }
            for item in actions
        ],
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def serialize_workflow_batch(batch: WorkflowBatch) -> WorkflowBatchRead:
    workflows = sorted(batch.workflows, key=lambda item: item.batch_sequence)
    progress = (
        int(sum(item.progress for item in workflows) / len(workflows))
        if workflows
        else batch.progress
    )
    active = next((item for item in workflows if item.state == "running"), None)
    progress_message = batch.progress_message
    if active:
        progress_message = (
            f"第 {active.batch_sequence}/{len(workflows)} 天 · {active.progress_message}"
        )
    return WorkflowBatchRead(
        id=batch.id,
        owner_id=batch.owner_id,
        skill_id=batch.skill_id,
        skill_name=batch.skill_name,
        skill_version=batch.skill_version,
        model_provider=batch.model_provider,
        model_name=batch.model_name,
        reconciliation_dates=_load(batch.reconciliation_dates_json, []),
        state=batch.state,
        progress=progress,
        progress_message=progress_message,
        error_message=batch.error_message,
        workflows=[serialize_workflow(item) for item in workflows],
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


def _assert_batch_visible(batch: WorkflowBatch, user: UserContext) -> None:
    if batch.department_id != user.department_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="无权查看其他部门的批次任务。")


def get_workflow_batch_or_404(
    db: Session,
    batch_id: str,
    user: UserContext,
) -> WorkflowBatch:
    batch = db.get(WorkflowBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="核销批次不存在。")
    _assert_batch_visible(batch, user)
    return batch


def _snapshot_skill(skill: RegisteredSkill, workflow_id: str) -> Path:
    root = (settings.workflow_dir / workflow_id).resolve()
    destination = root / "skill"
    root.mkdir(parents=True, exist_ok=False)
    for path in skill.directory.rglob("*"):
        if path.is_symlink():
            raise HTTPException(status_code=422, detail="Skill 包不能包含符号链接。")
    shutil.copytree(
        skill.directory,
        destination,
        ignore=shutil.ignore_patterns(
            "__pycache__", ".pytest_cache", ".ruff_cache", "工作区", "output"
        ),
    )
    return destination


def create_workflow(
    db: Session,
    request: WorkflowCreate,
    user: UserContext,
) -> WorkflowSession:
    skill = registry.get(request.skill_id)
    if not skill or skill.manifest.handler.adapter != "workflow":
        raise HTTPException(status_code=404, detail="对话式 Skill 不存在或尚未发布。")
    llm = resolve_runtime_config(db, user, request.model_connection_id, request.model)
    if not llm:
        raise HTTPException(status_code=422, detail="对话式 Skill 必须选择一个大模型连接。")
    workflow_id = str(uuid.uuid4())
    _snapshot_skill(skill, workflow_id)
    workflow = WorkflowSession(
        id=workflow_id,
        owner_id=user.user_id,
        owner_name=user.display_name,
        department_id=user.department_id,
        skill_id=skill.manifest.id,
        skill_name=skill.manifest.name,
        skill_version=skill.manifest.version,
        skill_hash=skill.skill_hash,
        skill_commit=skill.commit_sha,
        concurrency_limit=skill.manifest.runtime.concurrency_limit,
        model_connection_id=llm.connection_id,
        model_provider=llm.provider,
        model_name=llm.model,
        state="active",
        stage="awaiting_date",
        progress_message="等待确认核销日期",
    )
    db.add(workflow)
    _message(
        db,
        workflow,
        "assistant",
        "先告诉我要跑的核销日期。可以说“昨天”或直接说“2026-07-24”。",
        {"kind": "date_request"},
    )
    db.commit()
    db.refresh(workflow)
    return workflow


def start_workflow(
    db: Session,
    request: WorkflowStart,
    user: UserContext,
) -> WorkflowSession:
    """Start a workflow from a completed prerequisite form.

    The web form supplies the date, model and uploaded file IDs in one request.
    The worker still performs the deterministic financial processing and keeps
    the existing human confirmation gate before any workbook write.
    """
    skill = registry.get(request.skill_id)
    if not skill or skill.manifest.handler.adapter != "workflow":
        raise HTTPException(status_code=404, detail="对话式 Skill 不存在或尚未发布。")
    parsed_date = _parse_date(request.reconciliation_date)
    if not parsed_date:
        raise HTTPException(status_code=422, detail="核销日期无效，不能晚于今天。")
    llm = resolve_runtime_config(db, user, request.model_connection_id, request.model)
    if not llm:
        raise HTTPException(status_code=422, detail="开始核销前必须选择一个大模型连接。")
    if not has_service_credential(db, user.user_id, user.department_id, "zhiyun"):
        raise HTTPException(status_code=422, detail="尚未配置智云登录凭据，请先安全保存账号密码。")

    workflow_id = str(uuid.uuid4())
    _snapshot_skill(skill, workflow_id)
    workflow = WorkflowSession(
        id=workflow_id,
        owner_id=user.user_id,
        owner_name=user.display_name,
        department_id=user.department_id,
        skill_id=skill.manifest.id,
        skill_name=skill.manifest.name,
        skill_version=skill.manifest.version,
        skill_hash=skill.skill_hash,
        skill_commit=skill.commit_sha,
        concurrency_limit=skill.manifest.runtime.concurrency_limit,
        model_connection_id=llm.connection_id,
        model_provider=llm.provider,
        model_name=llm.model,
        state="active",
        stage="awaiting_files",
        reconciliation_date=parsed_date.isoformat(),
        context_json=_json(
            {
                "started_from_form": True,
                "requires_confirmation": skill.manifest.risk.requires_confirmation,
            }
        ),
        progress_message="正在核验前置条件",
    )
    db.add(workflow)
    db.flush()
    # Reuse the same role, extension, ownership and minimum-count validation
    # used by the legacy workflow form.
    update_workflow_files(db, workflow, request.files, user)
    ready, missing = _has_required_files(workflow)
    if not ready:
        raise HTTPException(
            status_code=422,
            detail=f"前置文件未上传完整：{'、'.join(missing)}。",
        )
    workflow.state = "running"
    workflow.stage = "preparing"
    workflow.progress = 5
    workflow.progress_message = (
        f"前置条件已核验，开始生成 {_date_label(workflow.reconciliation_date)} 的核销日清"
    )
    workflow.error_message = ""
    _queue_action(db, workflow, "prepare_worklist")
    _message(
        db,
        workflow,
        "assistant",
        f"前置条件已核验，已使用 {workflow.model_name} 开始执行"
        f" {_date_label(workflow.reconciliation_date)} 的核销日清。",
        {"kind": "direct_start", "reconciliation_date": workflow.reconciliation_date},
    )
    db.commit()
    db.refresh(workflow)
    return workflow


def start_workflow_batch(
    db: Session,
    request: WorkflowBatchStart,
    user: UserContext,
) -> WorkflowBatch:
    """Create an ordered multi-date batch without widening a child's write scope."""
    skill = registry.get(request.skill_id)
    if not skill or skill.manifest.handler.adapter != "workflow":
        raise HTTPException(status_code=404, detail="对话式 Skill 不存在或尚未发布。")
    if len(request.reconciliation_dates) > 7:
        raise HTTPException(status_code=422, detail="单个批次最多选择 7 个核销日期。")

    parsed_dates: list[str] = []
    for value in request.reconciliation_dates:
        parsed = _parse_date(value)
        if not parsed:
            raise HTTPException(status_code=422, detail=f"核销日期无效或晚于今天：{value}")
        parsed_dates.append(parsed.isoformat())
    parsed_dates = sorted(set(parsed_dates))
    if not parsed_dates:
        raise HTTPException(status_code=422, detail="请至少选择一个核销日期。")

    llm = resolve_runtime_config(db, user, request.model_connection_id, request.model)
    if not llm:
        raise HTTPException(status_code=422, detail="开始核销前必须选择一个大模型连接。")
    if not has_service_credential(db, user.user_id, user.department_id, "zhiyun"):
        raise HTTPException(status_code=422, detail="尚未配置智云登录凭据，请先安全保存账号密码。")

    normalized_files = _validate_file_bindings(db, skill, request.files, user)
    missing = [
        spec.name
        for spec in skill.manifest.file_inputs
        if spec.required and len(normalized_files.get(spec.role, [])) < spec.min_files
    ]
    if missing:
        raise HTTPException(status_code=422, detail=f"前置文件未上传完整：{'、'.join(missing)}。")

    batch_id = f"BAT-{date.today():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
    batch = WorkflowBatch(
        id=batch_id,
        owner_id=user.user_id,
        owner_name=user.display_name,
        department_id=user.department_id,
        skill_id=skill.manifest.id,
        skill_name=skill.manifest.name,
        skill_version=skill.manifest.version,
        model_connection_id=llm.connection_id,
        model_provider=llm.provider,
        model_name=llm.model,
        reconciliation_dates_json=_json(parsed_dates),
        files_json=_json(normalized_files),
        state="running",
        progress=0,
        progress_message=f"已创建 {len(parsed_dates)} 天核销批次，等待第 1 天执行",
    )
    db.add(batch)
    created_roots: list[Path] = []
    previous_workflow_id = ""
    try:
        for sequence, reconciliation_date in enumerate(parsed_dates, start=1):
            workflow_id = str(uuid.uuid4())
            _snapshot_skill(skill, workflow_id)
            created_roots.append((settings.workflow_dir / workflow_id).resolve())
            is_first = sequence == 1
            context = {
                "started_from_form": True,
                "batch_id": batch_id,
                "requires_confirmation": skill.manifest.risk.requires_confirmation,
            }
            workflow = WorkflowSession(
                id=workflow_id,
                owner_id=user.user_id,
                owner_name=user.display_name,
                department_id=user.department_id,
                skill_id=skill.manifest.id,
                skill_name=skill.manifest.name,
                skill_version=skill.manifest.version,
                skill_hash=skill.skill_hash,
                skill_commit=skill.commit_sha,
                concurrency_limit=skill.manifest.runtime.concurrency_limit,
                model_connection_id=llm.connection_id,
                model_provider=llm.provider,
                model_name=llm.model,
                state="running" if is_first else "queued",
                stage="preparing" if is_first else "queued",
                reconciliation_date=reconciliation_date,
                batch_id=batch_id,
                batch_sequence=sequence,
                previous_workflow_id=previous_workflow_id,
                context_json=_json(context),
                files_json=_json(normalized_files if is_first else {}),
                progress=5 if is_first else 0,
                progress_message=(
                    f"正在执行第 {sequence}/{len(parsed_dates)} 天核销"
                    if is_first
                    else f"等待前一天完成后执行（{sequence}/{len(parsed_dates)}）"
                ),
            )
            db.add(workflow)
            db.flush()
            if is_first:
                _queue_action(db, workflow, "prepare_worklist")
            _message(
                db,
                workflow,
                "assistant",
                (
                    f"批次 {batch_id} 的第 {sequence}/{len(parsed_dates)} 个单日任务已创建："
                    f"{_date_label(reconciliation_date)}。"
                ),
                {"kind": "batch_child_created", "batch_id": batch_id, "sequence": sequence},
            )
            previous_workflow_id = workflow_id
        db.commit()
    except Exception:
        db.rollback()
        for root in created_roots:
            shutil.rmtree(root, ignore_errors=True)
        raise
    db.refresh(batch)
    return batch


def list_workflows(db: Session, user: UserContext, limit: int = 50) -> list[WorkflowSession]:
    query = (
        select(WorkflowSession)
        .where(
            WorkflowSession.department_id == user.department_id,
            # Only sessions created by the completed prerequisite form belong
            # in the task list. The legacy conversational bootstrap remains
            # available for API compatibility/tests, but must not create a
            # visible dashboard task before the user clicks 开始核销.
            WorkflowSession.context_json.like('%"started_from_form": true%'),
            WorkflowSession.batch_id.is_(None),
        )
        .order_by(WorkflowSession.updated_at.desc())
        .limit(min(max(limit, 1), 200))
    )
    return list(db.scalars(query).all())


def list_workflow_batches(
    db: Session,
    user: UserContext,
    limit: int = 50,
) -> list[WorkflowBatch]:
    query = (
        select(WorkflowBatch)
        .where(WorkflowBatch.department_id == user.department_id)
        .order_by(WorkflowBatch.updated_at.desc())
        .limit(min(max(limit, 1), 200))
    )
    return list(db.scalars(query).all())


def _validate_file_bindings(
    db: Session,
    skill: RegisteredSkill,
    bindings: dict[str, list[str]],
    user: UserContext,
) -> dict[str, list[dict[str, Any]]]:
    specs = {item.role: item for item in skill.manifest.file_inputs}
    unknown = set(bindings) - set(specs)
    if unknown:
        raise HTTPException(status_code=422, detail=f"未知文件角色：{sorted(unknown)}")
    normalized: dict[str, list[dict[str, Any]]] = {}
    for role, ids in bindings.items():
        spec = specs[role]
        if not spec.multiple and len(ids) > 1:
            raise HTTPException(status_code=422, detail=f"{spec.name}只能上传一个文件。")
        records: list[dict[str, Any]] = []
        for file_id in ids:
            record = db.get(FileRecord, file_id)
            if not record or record.kind != "input":
                raise HTTPException(status_code=422, detail=f"输入文件不存在：{file_id}")
            if record.department_id != user.department_id and not user.is_admin:
                raise HTTPException(status_code=403, detail="无权使用其他部门文件。")
            suffix = Path(record.original_name).suffix.lower().lstrip(".")
            allowed = [item.lower().lstrip(".") for item in spec.extensions]
            if allowed and suffix not in allowed:
                raise HTTPException(
                    status_code=422,
                    detail=f"{spec.name}不支持 .{suffix}，允许：{', '.join(allowed)}",
                )
            records.append(
                {
                    "file_id": record.id,
                    "name": record.original_name,
                    "size_bytes": record.size_bytes,
                    "sha256": record.sha256,
                }
            )
        normalized[role] = records
    return normalized


def update_workflow_files(
    db: Session,
    workflow: WorkflowSession,
    bindings: dict[str, list[str]],
    user: UserContext,
) -> WorkflowSession:
    editable_stages = {
        "awaiting_date",
        "awaiting_date_confirmation",
        "awaiting_files",
        "failed",
    }
    if workflow.stage not in editable_stages:
        raise HTTPException(status_code=409, detail="当前阶段不能更换输入文件。")
    skill = registry.get(workflow.skill_id)
    if not skill:
        raise HTTPException(status_code=409, detail="Skill 当前不可用。")
    normalized = _load(workflow.files_json, {})
    normalized.update(_validate_file_bindings(db, skill, bindings, user))
    workflow.files_json = _json(normalized)
    workflow.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(workflow)
    return workflow


def reset_workflow(
    db: Session,
    workflow: WorkflowSession,
) -> WorkflowSession:
    pending = db.scalar(
        select(WorkflowAction.id).where(
            WorkflowAction.workflow_id == workflow.id,
            WorkflowAction.state.in_(("queued", "running")),
        )
    )
    if pending or workflow.stage in BUSY_STAGES:
        raise HTTPException(status_code=409, detail="当前动作正在执行，完成后才能重置任务。")

    workflow.state = "active"
    workflow.stage = "awaiting_date"
    workflow.reconciliation_date = ""
    workflow.context_json = "{}"
    workflow.files_json = "{}"
    workflow.artifacts_json = "[]"
    workflow.progress = 0
    workflow.progress_message = "任务已重置，等待确认核销日期"
    workflow.error_message = ""
    _message(
        db,
        workflow,
        "assistant",
        "任务已重置。已清空核销日期、文件绑定和本次输出列表；"
        "历史记录及已经完成的写入不会撤销。请重新告诉我要跑的核销日期。",
        {"kind": "workflow_reset"},
    )
    db.commit()
    db.refresh(workflow)
    return workflow


def _parse_date(value: str) -> date | None:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed <= date.today() else None


def _date_label(value: str) -> str:
    parsed = _parse_date(value)
    if not parsed:
        return "未确认"
    return f"{value}（周{WEEKDAYS[parsed.weekday()]}）"


def _has_required_files(workflow: WorkflowSession) -> tuple[bool, list[str]]:
    files = _load(workflow.files_json, {})
    skill = registry.get(workflow.skill_id)
    if not skill:
        return False, list(FILE_ROLES)
    missing = [
        spec.role
        for spec in skill.manifest.file_inputs
        if spec.required and len(files.get(spec.role, [])) < spec.min_files
    ]
    return not missing, missing


def _queue_action(
    db: Session,
    workflow: WorkflowSession,
    name: str,
) -> WorkflowAction:
    pending = db.scalar(
        select(WorkflowAction.id).where(
            WorkflowAction.workflow_id == workflow.id,
            WorkflowAction.state.in_(("queued", "running")),
        )
    )
    if pending:
        raise HTTPException(status_code=409, detail="当前已有动作正在执行。")
    return _new_action(db, workflow, name)


def _new_action(
    db: Session,
    workflow: WorkflowSession,
    name: str,
) -> WorkflowAction:
    action = WorkflowAction(
        id=str(uuid.uuid4()),
        workflow_id=workflow.id,
        name=name,
        input_json=_json(
            {
                "reconciliation_date": workflow.reconciliation_date,
                "files": _load(workflow.files_json, {}),
                "context": _load(workflow.context_json, {}),
            }
        ),
    )
    db.add(action)
    return action


def _status_reply(workflow: WorkflowSession) -> str:
    if workflow.stage == "awaiting_date_confirmation":
        return f"当前核销日期是 {_date_label(workflow.reconciliation_date)}，请回复“确认”。"
    if workflow.stage == "preparing":
        return f"正在生成 {_date_label(workflow.reconciliation_date)} 的《核销日清》。"
    labels = {
        "awaiting_date": "请先告诉我核销日期。",
        "awaiting_files": (
            "请安全保存智云账号，并上传盈亏表和到账流转表副本，"
            "传好后回复“上传好了”。智云核销数据由平台自动获取。"
        ),
        "awaiting_apply_confirmation": "《核销日清》已生成；请打开检查，确认后回复“确认”。",
        "applying": "正在执行确认后的写入和回读校验，请不要修改相关表格。",
        "completed": "本次核销已完成，结果文件可以下载。",
        "failed": "上一步没有完成。请根据错误提示补齐材料后回复“重出日清”。",
        "cancelled": "本次对话任务已经取消。",
    }
    return labels.get(workflow.stage, workflow.progress_message or "正在处理。")


def _is_explicit_confirmation(content: str, *, apply: bool) -> bool:
    normalized = content.lower().replace(" ", "").strip("。！!，,")
    if normalized in CONFIRM_REPLIES:
        return True
    if apply:
        return normalized in {
            "确认写入",
            "确认回填",
            "可以写入",
            "同意写入",
            "我已检查核销日清，确认写入",
        }
    return normalized in {"确认日期", "日期确认"}


def _apply_decision(
    db: Session,
    workflow: WorkflowSession,
    decision: WorkflowDecision,
) -> None:
    action = decision.action
    source = {"decision_source": decision.source, "action": action}
    if action == "reply":
        content = str(decision.arguments.get("content", "")).strip()
        _message(
            db,
            workflow,
            "assistant",
            content[:8000] if content else _status_reply(workflow),
            source,
        )
        return
    if action == "set_date":
        value = str(decision.arguments.get("date", ""))
        parsed = _parse_date(value)
        if not parsed:
            _message(
                db,
                workflow,
                "assistant",
                "这个日期无法使用。请给出不晚于今天的有效核销日期，例如 2026-07-24。",
                source,
            )
            return
        workflow.reconciliation_date = parsed.isoformat()
        workflow.stage = "awaiting_date_confirmation"
        workflow.state = "active"
        workflow.progress_message = "等待确认核销日期"
        _message(
            db,
            workflow,
            "assistant",
            f"我按核销日期 {_date_label(workflow.reconciliation_date)} 来跑——"
            "就是销售在这一天核销的到账，对吗？请回复“确认”，日期不对就直接告诉我新日期。",
            source,
        )
        return
    if action == "confirm_date":
        if workflow.stage != "awaiting_date_confirmation" or not workflow.reconciliation_date:
            _message(db, workflow, "assistant", _status_reply(workflow), source)
            return
        workflow.stage = "awaiting_files"
        workflow.state = "active"
        workflow.progress_message = "等待智云凭据和财务工作簿"
        _message(
            db,
            workflow,
            "assistant",
            "日期已确认。请在右侧安全保存智云账号，并上传盈亏表和到账流转表副本。"
            "智云回款、核销和订单数据会自动获取；准备好后回复“上传好了”。",
            source,
        )
        return
    if action == "prepare_worklist":
        if workflow.stage not in {"awaiting_files", "failed"}:
            _message(db, workflow, "assistant", _status_reply(workflow), source)
            return
        ready, missing = _has_required_files(workflow)
        if not ready:
            labels = {"finance_workbooks": "盈亏/流转表副本"}
            _message(
                db,
                workflow,
                "assistant",
                "还缺：" + "、".join(labels[item] for item in missing) + "。上传后再说“上传好了”。",
                source,
            )
            return
        if not has_service_credential(
            db,
            workflow.owner_id,
            workflow.department_id,
            "zhiyun",
        ):
            _message(
                db,
                workflow,
                "assistant",
                "还缺智云账号。请先在右侧“智云自动取数”中安全保存账号和密码，再回复“上传好了”。",
                source,
            )
            return
        _queue_action(db, workflow, "prepare_worklist")
        workflow.context_json = "{}"
        workflow.artifacts_json = "[]"
        workflow.stage = "preparing"
        workflow.state = "running"
        workflow.progress = 5
        workflow.progress_message = "已排队，准备生成核销日清"
        workflow.error_message = ""
        _message(
            db,
            workflow,
            "assistant",
            f"材料已收到，开始生成 {_date_label(workflow.reconciliation_date)} 的《核销日清》。"
            "在我明确说清单已生成前，不会写盈亏表或流转表。",
            source,
        )
        return
    if action == "confirm_apply":
        if workflow.stage != "awaiting_apply_confirmation":
            _message(db, workflow, "assistant", _status_reply(workflow), source)
            return
        _queue_action(db, workflow, "apply_confirmed")
        workflow.stage = "applying"
        workflow.state = "running"
        workflow.progress = 5
        workflow.progress_message = "已确认，等待执行写入"
        workflow.error_message = ""
        _message(
            db,
            workflow,
            "assistant",
            "已收到写入确认。现在执行：先写盈亏明细，再写流转安全子集，随后回读校验。",
            source,
        )
        return
    if action == "rebuild_worklist":
        if workflow.stage in BUSY_STAGES:
            _message(db, workflow, "assistant", "当前动作还在执行，完成后才能重出清单。", source)
            return
        ready, _ = _has_required_files(workflow)
        has_credential = has_service_credential(
            db,
            workflow.owner_id,
            workflow.department_id,
            "zhiyun",
        )
        if not ready or not has_credential or not workflow.reconciliation_date:
            workflow.stage = "awaiting_files" if workflow.reconciliation_date else "awaiting_date"
            workflow.state = "active"
            _message(db, workflow, "assistant", _status_reply(workflow), source)
            return
        _queue_action(db, workflow, "prepare_worklist")
        workflow.context_json = "{}"
        workflow.artifacts_json = "[]"
        workflow.stage = "preparing"
        workflow.state = "running"
        workflow.progress = 5
        workflow.progress_message = "正在重新生成核销日清"
        workflow.error_message = ""
        _message(db, workflow, "assistant", "旧清单作废，正在基于当前文件重新生成日清。", source)
        return
    if action == "cancel":
        if workflow.stage in BUSY_STAGES:
            context = _load(workflow.context_json, {})
            context["stop_after_action"] = True
            workflow.context_json = _json(context)
            _message(
                db,
                workflow,
                "assistant",
                "当前原子动作正在执行，不能从中间截断；完成后我会停止，不会继续下一阶段。",
                source,
            )
        else:
            workflow.stage = "cancelled"
            workflow.state = "cancelled"
            workflow.progress_message = "对话任务已取消"
            db.execute(
                update(WorkflowAction)
                .where(
                    WorkflowAction.workflow_id == workflow.id,
                    WorkflowAction.state == "queued",
                )
                .values(state="cancelled", finished_at=datetime.now(UTC))
            )
            _message(db, workflow, "assistant", "本次核销已取消，没有继续执行写入。", source)
        return
    _message(db, workflow, "assistant", _status_reply(workflow), source)


def send_workflow_message(
    db: Session,
    workflow: WorkflowSession,
    content: str,
    user: UserContext,
) -> WorkflowSession:
    _message(db, workflow, "user", content)
    db.flush()
    recent = list(
        db.scalars(
            select(WorkflowMessage)
            .where(WorkflowMessage.workflow_id == workflow.id)
            .order_by(WorkflowMessage.id.desc())
            .limit(20)
        ).all()
    )
    history = [
        {"role": item.role, "content": item.content}
        for item in reversed(recent)
        if item.role in {"user", "assistant"}
    ]
    llm = resolve_runtime_config(
        db,
        user,
        workflow.model_connection_id,
        workflow.model_name,
    )
    decision = decide_workflow_turn(
        llm,
        workflow.stage,
        content,
        workflow.reconciliation_date,
        history,
    )
    if decision.action == "confirm_date" and not _is_explicit_confirmation(
        content,
        apply=False,
    ):
        decision = WorkflowDecision("show_status", {}, "backend_guard")
    if decision.action == "confirm_apply" and not _is_explicit_confirmation(
        content,
        apply=True,
    ):
        decision = WorkflowDecision("show_status", {}, "backend_guard")
    _apply_decision(db, workflow, decision)
    db.commit()
    db.refresh(workflow)
    return workflow


def claim_next_workflow_action(
    db: Session,
    pools: tuple[str, ...],
    worker_id: str = "workflow-worker",
) -> WorkflowAction | None:
    if "workflow" not in pools:
        return None
    acquire_claim_lock(db)
    now = datetime.now(UTC)
    recover_expired_jobs(db, now)
    candidates = list(
        db.scalars(
            select(WorkflowAction)
            .where(WorkflowAction.state == "queued")
            .order_by(WorkflowAction.queued_at.asc())
            .limit(100)
        ).all()
    )
    selected: WorkflowAction | None = None
    for action in candidates:
        workflow = db.get(WorkflowSession, action.workflow_id)
        if not workflow:
            action.state = "failed"
            action.error_message = "对话任务不存在。"
            action.finished_at = now
            continue
        if active_workflow_count(db, workflow.skill_id, now) >= max(1, workflow.concurrency_limit):
            continue
        action.state = "running"
        action.started_at = now
        action.worker_id = worker_id
        action.attempt_count += 1
        action.heartbeat_at = now
        action.lease_expires_at = lease_deadline(now)
        selected = action
        break
    db.commit()
    return selected


def _copy_inputs(db: Session, action: WorkflowAction, business: Path) -> None:
    payload = _load(action.input_json, {})
    for role, folder_name in FILE_ROLES.items():
        target_dir = business / folder_name
        target_dir.mkdir(parents=True, exist_ok=True)
        for item in payload.get("files", {}).get(role, []):
            record = db.get(FileRecord, item["file_id"])
            if not record:
                raise RuntimeError(f"输入记录不存在：{item['file_id']}")
            source = Path(record.stored_path).resolve()
            if not source.is_file() or sha256_file(source) != record.sha256:
                raise RuntimeError(f"输入文件完整性校验失败：{record.id}")
            target = target_dir / safe_filename(record.original_name)
            if target.exists():
                target = target_dir / f"{target.stem}_{record.id[:8]}{target.suffix}"
            shutil.copy2(source, target)
    for folder_name in ("03_台账", "04_产出"):
        (business / folder_name).mkdir(parents=True, exist_ok=True)


def _run_script(
    script_dir: Path,
    script_name: str,
    arguments: list[str],
    timeout: int = 900,
    stdin_data: str | None = None,
    sensitive_values: tuple[str, ...] = (),
) -> str:
    command = [sys.executable, str(script_dir / script_name), *arguments]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        command,
        cwd=script_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=stdin_data,
        timeout=timeout,
        env=env,
        check=False,
    )
    if completed.returncode:
        details = (completed.stderr or completed.stdout).strip()
        for value in sensitive_values:
            if value:
                details = details.replace(value, "[已隐藏]")
        suffix = f"：{details[-1200:]}" if details else ""
        raise RuntimeError(f"{script_name} 执行失败（退出码 {completed.returncode}）{suffix}")
    return completed.stdout


def _register_artifact(
    db: Session,
    workflow: WorkflowSession,
    source: Path,
    action_id: str,
) -> dict[str, Any]:
    root = (settings.workflow_dir / workflow.id).resolve()
    source = source.resolve()
    if not source.is_file() or not source.is_relative_to(root):
        raise RuntimeError("工作流产物必须位于当前会话目录。")
    delivery = root / "outputs" / action_id
    delivery.mkdir(parents=True, exist_ok=True)
    target = delivery / safe_filename(source.name)
    if target.exists() and source != target:
        digest = sha256_file(source)[:8]
        target = delivery / f"{target.stem}_{digest}{target.suffix}"
    if source != target:
        shutil.copy2(source, target)
    record = FileRecord(
        id=str(uuid.uuid4()),
        owner_id=workflow.owner_id,
        department_id=workflow.department_id,
        kind="output",
        original_name=target.name,
        stored_path=str(target.resolve()),
        content_type="application/octet-stream",
        size_bytes=target.stat().st_size,
        sha256=sha256_file(target),
    )
    db.add(record)
    db.flush()
    return {
        "name": record.original_name,
        "file_id": record.id,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "download_url": f"/api/files/{record.id}/download",
        "action_id": action_id,
    }


def _worklist_summary(stdout: str) -> dict[str, int]:
    summary: dict[str, int] = {}
    line = next((item for item in stdout.splitlines() if "《核销日清》已生成：" in item), "")
    for label in ("今天要填", "已填过·跳过", "冲突·需你定", "挂账待办", "异常"):
        match = re.search(rf"{re.escape(label)}\s+(\d+)", line)
        if match:
            summary[label] = int(match.group(1))
    flow = next((item for item in stdout.splitlines() if item.startswith("流转：")), "")
    for label in ("确认后自动写", "须手填", "跳过"):
        match = re.search(rf"{label}\s+(\d+)", flow)
        if match:
            summary[f"流转{label}"] = int(match.group(1))
    return summary


def _prepare_worklist(
    db: Session,
    action: WorkflowAction,
    workflow: WorkflowSession,
) -> dict[str, Any]:
    root = (settings.workflow_dir / workflow.id).resolve()
    business = root / "actions" / action.id / "工作区"
    business.mkdir(parents=True, exist_ok=False)
    _copy_inputs(db, action, business)
    script_dir = root / "skill" / "vendor" / "scripts"
    if not (script_dir / "classify_hexiao.py").is_file():
        raise RuntimeError("应收核销脚本包不完整。")
    workspace = str(business.resolve())
    hexiao_date = workflow.reconciliation_date
    account, password = resolve_service_credential(
        db,
        workflow.owner_id,
        workflow.department_id,
        "zhiyun",
    )
    workflow.progress = 10
    workflow.progress_message = "正在登录智云并按核销日期自动取数"
    db.commit()
    try:
        _run_script(
            script_dir,
            "fetch_secure.py",
            [],
            timeout=600,
            stdin_data=_json(
                {
                    "account": account,
                    "password": password,
                    "reconciliation_date": hexiao_date,
                    "workspace": workspace,
                }
            ),
            sensitive_values=(account, password),
        )
    finally:
        password = ""
    steps = [
        ("inspect_inputs.py", ["--workspace", workspace]),
        ("verify_sources.py", ["snapshot", "--workspace", workspace]),
        (
            "classify_hexiao.py",
            ["--workspace", workspace, "--hexiao-date", hexiao_date],
        ),
        (
            "validate_plan.py",
            ["--workspace", workspace, "--hexiao-date", hexiao_date],
        ),
        (
            "build_flow_plan.py",
            ["--workspace", workspace, "--hexiao-date", hexiao_date],
        ),
    ]
    for index, (script, arguments) in enumerate(steps, start=1):
        workflow.progress = 20 + index * 11
        workflow.progress_message = f"正在执行日清准备步骤 {index}/{len(steps) + 1}"
        db.commit()
        _run_script(script_dir, script, arguments)
    stdout = _run_script(
        script_dir,
        "build_worklist.py",
        ["--workspace", workspace, "--hexiao-date", hexiao_date],
    )
    worklists = sorted(
        (business / "04_产出").glob("核销日清_*.xlsx"),
        key=lambda path: path.stat().st_mtime,
    )
    if not worklists:
        raise RuntimeError("build_worklist.py 未生成核销日清。")
    artifact = _register_artifact(db, workflow, worklists[-1], action.id)
    checked = sorted(
        (business / "04_产出").glob("写入计划_校验后*.json"),
        key=lambda path: path.stat().st_mtime,
    )
    ledgers = sorted((business / "02_我的表副本").glob("*盈亏*.xls*"))
    if not checked or not ledgers:
        raise RuntimeError("日清已生成，但没有找到校验后计划或盈亏副本。")
    summary = _worklist_summary(stdout)
    return {
        "workspace": str(business),
        "checked_plan": str(checked[-1]),
        "ledger": str(ledgers[0]),
        "summary": summary,
        "artifacts": [artifact],
    }


def _apply_confirmed(
    db: Session,
    action: WorkflowAction,
    workflow: WorkflowSession,
) -> dict[str, Any]:
    context = _load(action.input_json, {}).get("context", {})
    business = Path(context.get("workspace", "")).resolve()
    root = (settings.workflow_dir / workflow.id).resolve()
    if not business.is_dir() or not business.is_relative_to(root):
        raise RuntimeError("上一次日清工作区不存在，请重新生成日清。")
    script_dir = root / "skill" / "vendor" / "scripts"
    checked = Path(context.get("checked_plan", "")).resolve()
    ledger = Path(context.get("ledger", "")).resolve()
    if not checked.is_file() or not ledger.is_file():
        raise RuntimeError("校验后计划或盈亏副本不存在，请重新生成日清。")
    workspace = str(business)
    # The preparation snapshot is a pre-write guard. Verify it immediately before
    # the confirmed mutation so a stale or externally changed workbook is rejected.
    _run_script(script_dir, "verify_sources.py", ["verify", "--workspace", workspace])
    _run_script(
        script_dir,
        "apply_all.py",
        [
            "--checked",
            str(checked),
            "--ledger",
            str(ledger),
            "--workspace",
            workspace,
            "--confirmed",
            "--in-place",
            "--flow-in-place",
        ],
    )
    try:
        # apply_all performs deterministic planned-cell writes and readback checks.
        # Commit both successful in-place writes as the new baseline; otherwise the
        # intermediate snapshot made after the ledger write treats the subsequent
        # flow write as an external modification.
        _run_script(script_dir, "verify_sources.py", ["snapshot", "--workspace", workspace])
        _run_script(script_dir, "verify_sources.py", ["verify", "--workspace", workspace])
    except Exception as exc:
        raise PostWriteVerificationError(
            f"计划内写入已完成，但写入后校验基线更新失败；请勿重复确认写入。原始错误：{exc}"
        ) from exc
    candidates = [
        path
        for folder in (business / "02_我的表副本", business / "04_产出")
        for path in folder.glob("*")
        if path.is_file()
        and path.suffix.lower() in {".xlsx", ".xlsm", ".xls", ".json", ".txt"}
        and ("备份" not in path.name)
    ]
    artifacts: list[dict[str, Any]] = []
    next_files: list[dict[str, Any]] = []
    for path in candidates:
        artifact = _register_artifact(db, workflow, path, action.id)
        artifacts.append(artifact)
        if (
            getattr(workflow, "batch_id", None)
            and path.parent.name == "02_我的表副本"
            and path.suffix.lower()
            in {
                ".xlsx",
                ".xlsm",
                ".xls",
            }
        ):
            next_files.append(
                {
                    "file_id": artifact["file_id"],
                    "name": artifact["name"],
                    "size_bytes": artifact["size_bytes"],
                    "sha256": artifact["sha256"],
                }
            )
    if getattr(workflow, "batch_id", None) and len(next_files) < 2:
        raise PostWriteVerificationError(
            "本日写入已完成，但没有找到可传递给下一日的两份工作副本；批次已暂停，"
            "请勿重复执行本日任务。"
        )
    return {
        "workspace": str(business),
        "artifacts": artifacts,
        "next_files": {"finance_workbooks": next_files},
    }


def _fail_batch(db: Session, workflow: WorkflowSession, message: str) -> None:
    if not workflow.batch_id:
        return
    batch = db.get(WorkflowBatch, workflow.batch_id)
    if not batch:
        return
    batch.state = "failed"
    batch.error_message = message[:500]
    batch.progress_message = (
        f"第 {workflow.batch_sequence} 天（{workflow.reconciliation_date}）失败，后续日期已暂停"
    )
    batch.updated_at = datetime.now(UTC)


def _advance_batch(
    db: Session,
    workflow: WorkflowSession,
    result: dict[str, Any],
) -> None:
    if not workflow.batch_id:
        return
    batch = db.get(WorkflowBatch, workflow.batch_id)
    if not batch:
        raise RuntimeError("所属核销批次不存在。")
    children = sorted(batch.workflows, key=lambda item: item.batch_sequence)
    total = len(children)
    completed = len([item for item in children if item.state == "succeeded"])
    batch.progress = int(completed * 100 / max(total, 1))
    batch.error_message = ""
    next_workflow = next(
        (item for item in children if item.batch_sequence == workflow.batch_sequence + 1),
        None,
    )
    if not next_workflow:
        batch.state = "succeeded"
        batch.progress = 100
        batch.progress_message = f"{total} 天核销全部完成"
        batch.updated_at = datetime.now(UTC)
        return

    next_files = result.get("next_files", {})
    if len(next_files.get("finance_workbooks", [])) < 2:
        raise PostWriteVerificationError(
            "本日写入已完成，但工作副本传递不完整；批次已暂停，请勿重复执行本日任务。"
        )
    next_workflow.files_json = _json(next_files)
    next_workflow.state = "running"
    next_workflow.stage = "preparing"
    next_workflow.progress = 5
    next_workflow.progress_message = (
        f"前一天已完成，正在执行第 {next_workflow.batch_sequence}/{total} 天核销"
    )
    next_workflow.error_message = ""
    _new_action(db, next_workflow, "prepare_worklist")
    _message(
        db,
        next_workflow,
        "assistant",
        (
            "已接收前一天核销完成后的工作副本，开始执行 "
            f"{_date_label(next_workflow.reconciliation_date)}。"
        ),
        {
            "kind": "batch_child_started",
            "batch_id": batch.id,
            "previous_workflow_id": workflow.id,
        },
    )
    batch.state = "running"
    batch.progress_message = (
        f"已完成 {completed}/{total} 天，正在执行 {next_workflow.reconciliation_date}"
    )
    batch.updated_at = datetime.now(UTC)


def retry_workflow_batch(
    db: Session,
    batch: WorkflowBatch,
) -> WorkflowBatch:
    if batch.state != "failed":
        raise HTTPException(status_code=409, detail="只有失败并暂停的批次可以继续。")
    children = sorted(batch.workflows, key=lambda item: item.batch_sequence)
    failed = next((item for item in children if item.state == "failed"), None)
    if not failed:
        raise HTTPException(status_code=409, detail="没有找到可继续的失败日期。")
    last_action = max(failed.actions, key=lambda item: item.queued_at, default=None)
    if not last_action or last_action.name != "prepare_worklist":
        raise HTTPException(
            status_code=409,
            detail="失败发生在写入阶段，不能自动重试；请先由管理员核对工作副本。",
        )
    pending = any(
        action.state in {"queued", "running"} for child in children for action in child.actions
    )
    if pending:
        raise HTTPException(status_code=409, detail="批次中仍有动作正在执行。")

    context = _load(failed.context_json, {})
    failed.context_json = _json(
        {
            "started_from_form": True,
            "batch_id": batch.id,
            "requires_confirmation": bool(context.get("requires_confirmation", False)),
        }
    )
    failed.artifacts_json = "[]"
    failed.state = "running"
    failed.stage = "preparing"
    failed.progress = 5
    failed.progress_message = f"正在重新执行 {failed.reconciliation_date}"
    failed.error_message = ""
    _queue_action(db, failed, "prepare_worklist")
    _message(
        db,
        failed,
        "assistant",
        "已从失败日期继续。之前成功的日期不会重复执行。",
        {"kind": "batch_retry", "batch_id": batch.id},
    )
    batch.state = "running"
    batch.error_message = ""
    batch.progress_message = f"正在重新执行失败日期 {failed.reconciliation_date}"
    batch.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(batch)
    return batch


def execute_workflow_action(db: Session, action: WorkflowAction) -> None:
    workflow = db.get(WorkflowSession, action.workflow_id)
    if not workflow:
        action.state = "failed"
        action.error_message = "对话任务不存在。"
        action.finished_at = datetime.now(UTC)
        return
    try:
        if action.name == "prepare_worklist":
            result = _prepare_worklist(db, action, workflow)
            context = _load(workflow.context_json, {})
            context.update(result)
            workflow.context_json = _json(context)
            artifacts = _load(workflow.artifacts_json, [])
            artifacts.extend(result["artifacts"])
            workflow.artifacts_json = _json(artifacts)
            stop = bool(context.get("stop_after_action"))
            auto_apply = bool(context.get("started_from_form")) and not bool(
                context.get("requires_confirmation", True)
            )
            summary = result.get("summary", {})
            if stop:
                workflow.stage = "cancelled"
                workflow.state = "cancelled"
                workflow.progress = 100
                workflow.progress_message = "日清生成后按要求停止"
                reply = "《核销日清》已经生成，但按你的停止要求，本次不会进入写表阶段。"
            elif auto_apply:
                workflow.stage = "applying"
                workflow.state = "running"
                workflow.progress = 85
                workflow.progress_message = "日清与写前校验已通过，正在安全写入工作副本"
                _new_action(db, workflow, "apply_confirmed")
                reply = (
                    f"✅ 核销日期 {_date_label(workflow.reconciliation_date)} "
                    "的日清与写前校验已通过，"
                    "正在按 Skill 规则写入隔离工作副本并生成订单差异表。"
                )
            else:
                workflow.stage = "awaiting_apply_confirmation"
                workflow.state = "waiting_confirmation"
                workflow.progress = 100
                workflow.progress_message = "核销日清已生成，等待人工确认"
                reply = (
                    f"✅ 核销日期 {_date_label(workflow.reconciliation_date)} 的核销判定完了，"
                    "财务工作簿原件一个字节没动；智云只做了查询取数。\n"
                    f"盈亏：今天要填 {summary.get('今天要填', 0)} 行；"
                    f"已填过·跳过 {summary.get('已填过·跳过', 0)} 行；"
                    f"冲突·需你定 {summary.get('冲突·需你定', 0)} 行；"
                    f"挂账待办 {summary.get('挂账待办', 0)} 行；"
                    f"异常 {summary.get('异常', 0)} 行。\n"
                    f"流转：确认后自动写 {summary.get('流转确认后自动写', 0)} 笔；"
                    f"须你手填 {summary.get('流转须手填', 0)} 笔。\n"
                    "请下载并打开《核销日清》检查；没问题回复“确认”或“可以写”。"
                )
            _message(db, workflow, "assistant", reply, {"kind": "worklist_ready"})
        elif action.name == "apply_confirmed":
            result = _apply_confirmed(db, action, workflow)
            context = _load(workflow.context_json, {})
            context.update(result)
            workflow.context_json = _json(context)
            artifacts = _load(workflow.artifacts_json, [])
            artifacts.extend(result["artifacts"])
            workflow.artifacts_json = _json(artifacts)
            workflow.stage = "completed"
            workflow.state = "succeeded"
            workflow.progress = 100
            workflow.progress_message = "盈亏和流转写入完成，订单差异表已生成"
            _message(
                db,
                workflow,
                "assistant",
                "统一写入完成：先盈亏明细、生成《订单写入差异》，"
                "再写流转安全子集；回读校验已通过。结果文件已放到右侧下载区。",
                {"kind": "workflow_completed"},
            )
            _advance_batch(db, workflow, result)
        else:
            raise RuntimeError(f"不支持的工作流动作：{action.name}")
        action.result_json = _json(result)
        action.state = "succeeded"
        action.finished_at = datetime.now(UTC)
        workflow.error_message = ""
    except subprocess.TimeoutExpired:
        action.state = "failed"
        action.error_message = "脚本执行超时。"
        action.finished_at = datetime.now(UTC)
        workflow.state = "failed"
        workflow.stage = "failed"
        workflow.error_message = action.error_message
        workflow.progress_message = "动作执行超时"
        _fail_batch(db, workflow, action.error_message)
        _message(
            db,
            workflow,
            "assistant",
            "这一步执行超时，财务工作簿原件没有被修改。请检查材料后回复“重出日清”。",
            {"kind": "action_failed"},
        )
    except PostWriteVerificationError as exc:
        action.state = "failed"
        action.error_message = str(exc)[:500]
        action.finished_at = datetime.now(UTC)
        workflow.state = "failed"
        workflow.stage = "failed"
        workflow.error_message = action.error_message
        workflow.progress_message = "写入已完成，等待恢复写入后校验"
        _fail_batch(db, workflow, action.error_message)
        _message(
            db,
            workflow,
            "assistant",
            "计划内写入已经完成，但写入后校验基线更新失败。请勿再次确认或重出日清，"
            "以免重复写入；请联系管理员恢复本次校验。",
            {"kind": "post_write_verification_failed"},
        )
    except Exception as exc:
        action.state = "failed"
        action.error_message = str(exc)[:500]
        action.finished_at = datetime.now(UTC)
        workflow.state = "failed"
        workflow.stage = "failed"
        workflow.error_message = action.error_message
        workflow.progress_message = "动作没有完成"
        _fail_batch(db, workflow, action.error_message)
        _message(
            db,
            workflow,
            "assistant",
            f"这一步没有完成：{action.error_message}。财务工作簿原件没有被修改。"
            "请检查材料后回复“重出日清”。",
            {"kind": "action_failed"},
        )


def run_workflow_action_once(
    db: Session,
    pools: tuple[str, ...],
    worker_id: str = "workflow-worker",
) -> bool:
    action = claim_next_workflow_action(db, pools, worker_id)
    if not action:
        return False
    with LeaseHeartbeat("workflow_action", action.id, worker_id):
        execute_workflow_action(db, action)
    action.heartbeat_at = datetime.now(UTC)
    action.lease_expires_at = None
    db.commit()
    return True
