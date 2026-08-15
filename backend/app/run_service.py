from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from jsonschema import Draft202012Validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .approval_service import manifest_requires_approval
from .auth import UserContext
from .authorization import assert_skill_permission
from .events import emit_event
from .model_service import resolve_runtime_config
from .models import FileRecord, ModelTraceRecord, RunModelAudit, RunRecord
from .orchestrator import interpret_parameters
from .redaction import sanitize_text
from .registry import RegisteredSkill, registry
from .resource_policy import assert_owner, owner_list_filter, run_root
from .schemas import RunCreate, RunRead
from .step_runtime_service import initialize_run_steps, queue_run_execution_step
from .storage import sha256_file

TERMINAL_STATES = {"succeeded", "failed", "timed_out", "cancelled"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}


def _assert_visible(run: RunRecord, user: UserContext) -> None:
    assert_owner(run.owner_id, user, "任务", run.department_id)


def get_run_or_404(db: Session, run_id: str, user: UserContext) -> RunRecord:
    run = db.get(RunRecord, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="任务不存在。")
    _assert_visible(run, user)
    return run


def serialize_run(
    run: RunRecord,
    *,
    can_retry: bool = False,
    retry_block_reason: str = "",
) -> RunRead:
    return RunRead(
        id=run.id,
        owner_id=run.owner_id,
        owner_name=run.owner_name,
        skill_id=run.skill_id,
        skill_name=run.skill_name,
        skill_version=run.skill_version,
        skill_commit=run.skill_commit,
        model_provider=run.model_audit.provider if run.model_audit else "",
        model_name=run.model_audit.model if run.model_audit else "",
        state=run.state,
        progress=run.progress,
        progress_message=sanitize_text(
            run.progress_message,
            error=run.state in {"failed", "timed_out"},
        ),
        message=run.message,
        parameters=_load(run.parameters_json),
        files=_load(run.files_json),
        result=_load(run.result_json),
        error_message=sanitize_text(run.error_message, error=True),
        confirmation_required=run.confirmation_required,
        confirmed_by=run.confirmed_by,
        cancel_requested=run.cancel_requested,
        attempt_count=run.attempt_count,
        can_retry=can_retry,
        retry_block_reason=retry_block_reason,
        created_at=run.created_at,
        queued_at=run.queued_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def retry_status(
    db: Session,
    run: RunRecord,
    user: UserContext,
    *,
    verify_file_hash: bool = False,
) -> tuple[bool, str]:
    if run.state not in {"failed", "timed_out"}:
        return False, "只有失败或超时的任务可以重试。"
    skill = registry.get(run.skill_id)
    if not skill:
        return False, "该 Skill 当前不可用。"
    try:
        assert_skill_permission(db, user, run.skill_id)
    except HTTPException:
        return False, "当前账号已没有使用该 Skill 的权限。"
    if skill.skill_hash != run.skill_hash or skill.manifest.version != run.skill_version:
        return False, "Skill 版本已经变化，请从目录重新创建任务。"
    if skill.manifest.risk.level != "read_only" or skill.manifest.risk.modifies_uploaded_files:
        return False, "写入型或会修改上传文件的任务不能直接重试。"
    for value in _load(run.files_json).values():
        items = value if isinstance(value, list) else ([value] if value else [])
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("file_id"), str):
                return False, "原任务的文件记录不完整。"
            record = db.get(FileRecord, item["file_id"])
            if not record or record.kind != "input":
                return False, "原任务的输入文件已经不存在。"
            try:
                assert_owner(record.owner_id, user, "输入文件", record.department_id)
            except HTTPException:
                return False, "原任务的输入文件已经不可访问。"
            path = Path(record.stored_path).resolve()
            if not path.is_file():
                return False, "原任务的输入文件已经不存在。"
            if verify_file_hash and sha256_file(path) != item.get("sha256"):
                return False, "原任务的输入文件缺失或内容已经变化。"
    return True, ""


def list_runs_page(
    db: Session,
    user: UserContext,
    *,
    page: int,
    page_size: int,
    state: str = "",
) -> tuple[list[RunRead], int]:
    filters = [owner_list_filter(RunRecord, user)]
    if state:
        filters.append(RunRecord.state == state)
    total = int(db.scalar(select(func.count()).select_from(RunRecord).where(*filters)) or 0)
    records = db.scalars(
        select(RunRecord)
        .where(*filters)
        .order_by(RunRecord.created_at.desc(), RunRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    result: list[RunRead] = []
    for item in records:
        allowed, reason = retry_status(db, item, user)
        result.append(
            serialize_run(item, can_retry=allowed, retry_block_reason=reason)
        )
    return result, total


def retry_run(db: Session, run: RunRecord, user: UserContext) -> RunRecord:
    allowed, reason = retry_status(db, run, user, verify_file_hash=True)
    if not allowed:
        raise HTTPException(status_code=409, detail=reason)
    raw_files: dict[str, str | list[str]] = {}
    for role, value in _load(run.files_json).items():
        items = value if isinstance(value, list) else ([value] if value else [])
        ids = [item["file_id"] for item in items]
        raw_files[role] = ids if isinstance(value, list) else (ids[0] if ids else "")
    return create_run(
        db,
        RunCreate(
            skill_id=run.skill_id,
            message=run.message,
            parameters=_load(run.parameters_json),
            files=raw_files,
            idempotency_key=f"retry:{run.id}",
            model_connection_id=run.model_audit.connection_id if run.model_audit else None,
            model=run.model_audit.model if run.model_audit else None,
        ),
        user,
    )


def validate_files(
    db: Session,
    skill: RegisteredSkill,
    bindings: dict[str, str | list[str]],
    user: UserContext,
) -> tuple[dict[str, Any], str]:
    normalized: dict[str, Any] = {}
    hash_parts: list[str] = []
    specs = {item.role: item for item in skill.manifest.file_inputs}
    unknown_roles = set(bindings) - set(specs)
    if unknown_roles:
        raise HTTPException(status_code=422, detail=f"未知文件角色：{sorted(unknown_roles)}")
    for role, spec in specs.items():
        raw_ids = bindings.get(role)
        ids = raw_ids if isinstance(raw_ids, list) else ([raw_ids] if raw_ids else [])
        if spec.required and not ids:
            raise HTTPException(status_code=422, detail=f"缺少文件：{spec.name}")
        if ids and len(ids) < spec.min_files:
            raise HTTPException(
                status_code=422,
                detail=f"{spec.name} 至少需要上传 {spec.min_files} 个文件。",
            )
        if not spec.multiple and len(ids) > 1:
            raise HTTPException(status_code=422, detail=f"{spec.name} 只能上传一个文件。")
        records: list[dict[str, Any]] = []
        for file_id in ids:
            record = db.get(FileRecord, file_id)
            if not record or record.kind != "input":
                raise HTTPException(status_code=422, detail=f"输入文件不存在：{file_id}")
            assert_owner(record.owner_id, user, "输入文件", record.department_id)
            suffix = Path(record.original_name).suffix.lower().lstrip(".")
            allowed = [item.lower().lstrip(".") for item in spec.extensions]
            if allowed and suffix not in allowed:
                raise HTTPException(
                    status_code=422,
                    detail=f"{spec.name} 不支持 .{suffix}，允许：{', '.join(allowed)}",
                )
            max_mb = spec.max_size_mb or 0
            if max_mb and record.size_bytes > max_mb * 1024 * 1024:
                raise HTTPException(status_code=422, detail=f"{spec.name} 超过 {max_mb} MB。")
            records.append(
                {
                    "file_id": record.id,
                    "name": record.original_name,
                    "sha256": record.sha256,
                    "size_bytes": record.size_bytes,
                }
            )
            hash_parts.append(f"{role}:{record.sha256}")
        normalized[role] = records if spec.multiple else (records[0] if records else None)
    return normalized, hashlib.sha256("|".join(sorted(hash_parts)).encode()).hexdigest()


def _snapshot_skill(skill: RegisteredSkill, owner_id: str, run_id: str) -> Path:
    destination = run_root(owner_id, run_id) / "skill"
    destination.parent.mkdir(parents=True, exist_ok=True)
    for path in skill.directory.rglob("*"):
        if path.is_symlink():
            raise HTTPException(status_code=422, detail="Skill 包不能包含符号链接。")
    shutil.copytree(
        skill.directory,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "output", "工作区"),
    )
    return destination


def create_run(db: Session, request: RunCreate, user: UserContext) -> RunRecord:
    skill = registry.get(request.skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在或尚未发布。")
    permission = assert_skill_permission(db, user, request.skill_id)
    if request.files:
        assert_skill_permission(db, user, request.skill_id, "can_upload")
    if skill.manifest.handler.adapter == "workflow":
        raise HTTPException(
            status_code=422,
            detail="该 Skill 需要通过对话式工作流创建任务。",
        )
    if manifest_requires_approval(skill.manifest) or bool(
        permission and permission.requires_approval
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "写入型、外部动作型或额外审批型标准任务尚未接入变更预览，"
                "不能直接创建；请使用已接入审批的工作流。"
            ),
        )
    if request.idempotency_key:
        existing = db.scalar(
            select(RunRecord).where(
                RunRecord.owner_id == user.user_id,
                RunRecord.idempotency_key == request.idempotency_key,
            )
        )
        if existing:
            return existing

    llm_config = resolve_runtime_config(
        db,
        user,
        request.model_connection_id,
        request.model,
    )
    model_trace: dict[str, int | str] = {}
    parameters, missing, _, _ = interpret_parameters(
        skill,
        request.message,
        request.parameters,
        llm_config,
        model_trace,
    )
    if missing:
        raise HTTPException(status_code=422, detail={"message": "缺少必要参数", "missing": missing})
    errors = sorted(
        Draft202012Validator(skill.manifest.input_schema).iter_errors(parameters),
        key=str,
    )
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[error.message for error in errors],
        )
    files, file_hash = validate_files(db, skill, request.files, user)
    payload_hash = hashlib.sha256(
        (_json(parameters) + _json(files) + skill.skill_hash).encode("utf-8")
    ).hexdigest()
    input_hash = hashlib.sha256(f"{file_hash}:{payload_hash}".encode()).hexdigest()
    confirmation = skill.manifest.risk.requires_confirmation
    now = datetime.now(UTC)
    run_id = str(uuid.uuid4())
    snapshot_dir = _snapshot_skill(skill, user.user_id, run_id)
    run = RunRecord(
        id=run_id,
        owner_id=user.user_id,
        owner_name=user.display_name,
        department_id=user.department_id,
        skill_id=skill.manifest.id,
        skill_name=skill.manifest.name,
        skill_version=skill.manifest.version,
        skill_commit=skill.commit_sha,
        skill_hash=skill.skill_hash,
        manifest_path=str((snapshot_dir / "tool.yaml").resolve()),
        manifest_snapshot=registry.snapshot(skill),
        adapter=skill.manifest.handler.adapter,
        worker_pool=skill.manifest.handler.worker_pool
        or ("rpa" if skill.manifest.handler.adapter == "rpa" else skill.manifest.handler.adapter),
        concurrency_limit=skill.manifest.runtime.concurrency_limit,
        state="waiting_confirmation" if confirmation else "queued",
        progress=0,
        progress_message="等待员工确认" if confirmation else "任务已进入队列",
        message=request.message,
        parameters_json=_json(parameters),
        files_json=_json(files),
        input_hash=input_hash,
        idempotency_key=request.idempotency_key or "",
        confirmation_required=confirmation,
        queued_at=None if confirmation else now,
    )
    db.add(run)
    db.flush()
    initialize_run_steps(db, run)
    if llm_config:
        db.add(
            RunModelAudit(
                run_id=run.id,
                connection_id=llm_config.connection_id,
                provider=llm_config.provider,
                model=llm_config.model,
            )
        )
        db.add(
            ModelTraceRecord(
                id=str(uuid.uuid4()),
                owner_id=user.user_id,
                department_id=user.department_id,
                run_id=run.id,
                connection_id=llm_config.connection_id,
                purpose="parameter_interpretation",
                provider=llm_config.provider,
                model=llm_config.model,
                status=str(model_trace.get("status", "fallback")),
                duration_ms=int(model_trace.get("duration_ms", 0)),
                input_tokens=int(model_trace.get("input_tokens", 0)),
                output_tokens=int(model_trace.get("output_tokens", 0)),
                failure_code=str(model_trace.get("failure_code", "unknown"))[:64],
            )
        )
    emit_event(
        db,
        run,
        event_type="state",
        state=run.state,
        progress=0,
        message=run.progress_message,
        data={
            "model_provider": llm_config.provider if llm_config else "",
            "model_name": llm_config.model if llm_config else "",
        },
    )
    return run


def confirm_run(db: Session, run: RunRecord, user: UserContext) -> RunRecord:
    if run.state != "waiting_confirmation":
        raise HTTPException(status_code=409, detail="当前任务不在等待确认状态。")
    run.confirmed_by = user.user_id
    run.confirmed_at = datetime.now(UTC)
    run.queued_at = datetime.now(UTC)
    queue_run_execution_step(db, run)
    emit_event(
        db,
        run,
        event_type="state",
        state="queued",
        progress=0,
        message="已确认，任务进入队列",
    )
    return run


def cancel_run(db: Session, run: RunRecord) -> RunRecord:
    if run.state in TERMINAL_STATES:
        raise HTTPException(status_code=409, detail="任务已经结束。")
    if run.state in {"created", "validating", "queued", "waiting_confirmation"}:
        run.cancel_requested = True
        run.finished_at = datetime.now(UTC)
        from .step_runtime_service import finish_run_execution_step

        finish_run_execution_step(db, run, state="cancelled", error_code="cancelled")
        emit_event(
            db,
            run,
            event_type="state",
            state="cancelled",
            message="任务已取消",
        )
    else:
        run.cancel_requested = True
        emit_event(db, run, event_type="notice", message="已提交取消请求")
    return run
