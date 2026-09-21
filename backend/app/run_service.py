from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from jsonschema import Draft202012Validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import UserContext
from .authorization import assert_skill_permission, refresh_active_user
from .events import append_run_event
from .model_service import resolve_runtime_config
from .modules.execution.prepared_payload import ModelAuditSelection
from .modules.execution.authorization import execution_actor, execution_owner, ExecutionPhase, ExecutionAuthorizationRevoked
from .modules.execution.input_snapshot import input_snapshot_hash
from .modules.execution.preconditions import assert_run_input_snapshot, ExecutionInputChanged
from .models import FileRecord, ModelTraceRecord, RunModelAudit, RunRecord
from .orchestrator import LlmConfig, interpret_parameters
from .redaction import sanitize_text
from .registry import RegisteredSkill, hash_skill_directory, registry
from .resource_policy import assert_owner, owner_list_filter, run_root
from .schemas import RunCreate, RunRead
from .skill_availability_service import assert_skill_accepting_new_work
from .step_runtime_service import initialize_run_steps, queue_run_execution_step
from .storage import sha256_file
from .task_errors import classify_task_error

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


def get_run_or_404(db: Session, run_id: str, user: UserContext, *, lock: bool = False) -> RunRecord:
    run = db.scalar(select(RunRecord).where(RunRecord.id == run_id).with_for_update()
                    .execution_options(populate_existing=True)) if lock else db.get(RunRecord, run_id)
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
    safe_error = sanitize_text(run.error_message, error=True)
    snapshot = _load(run.manifest_snapshot)
    risk = snapshot.get("risk") if isinstance(snapshot, dict) else None
    read_only = (
        isinstance(risk, dict) and risk.get("level") == "read_only"
        and risk.get("modifies_uploaded_files") is False
    )
    failure_detail: dict[str, Any] = {}
    if run.state in {"failed", "timed_out"} or safe_error:
        error_code, category = classify_task_error(safe_error, stage=run.progress_message)
        failure_detail = {
            "error_code": error_code,
            "category": category,
            "failed_stage": sanitize_text(
                run.progress_message or "执行阶段待核实",
                error=True,
                max_length=255,
            ),
            "write_status": "not_applicable" if read_only else "unknown",
            "published_material_version": "",
            "recovery_allowed": can_retry,
            "recovery_reason": sanitize_text(retry_block_reason, error=True, max_length=500),
            "failed_at": (
                run.finished_at or run.started_at or run.queued_at or run.created_at
            ).isoformat(),
        }
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
        error_message=safe_error,
        confirmation_required=run.confirmation_required,
        confirmed_by=run.confirmed_by,
        cancel_requested=run.cancel_requested,
        attempt_count=run.attempt_count,
        can_retry=can_retry,
        retry_block_reason=retry_block_reason,
        failure_detail=failure_detail,
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


def prepare_retry_request(db: Session, run: RunRecord, user: UserContext) -> RunCreate:
    allowed, reason = retry_status(db, run, user, verify_file_hash=True)
    if not allowed:
        raise HTTPException(status_code=409, detail=reason)
    raw_files: dict[str, str | list[str]] = {}
    for role, value in _load(run.files_json).items():
        items = value if isinstance(value, list) else ([value] if value else [])
        ids = [item["file_id"] for item in items]
        raw_files[role] = ids if isinstance(value, list) else (ids[0] if ids else "")
    return RunCreate(
            skill_id=run.skill_id,
            message=run.message,
            parameters=_load(run.parameters_json),
            files=raw_files,
            idempotency_key=f"retry:{run.id}",
            model_connection_id=run.model_audit.connection_id if run.model_audit else None,
            model=run.model_audit.model if run.model_audit else None,
        )


def retry_run(db: Session, run: RunRecord, user: UserContext) -> RunRecord:
    return create_run(db, prepare_retry_request(db, run, user), user)


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
    if destination.exists():
        raise FileExistsError("Task Skill snapshot already exists")

    def verify(directory):
        if directory.is_symlink() or any(path.is_symlink() for path in directory.rglob("*")):
            raise HTTPException(status_code=422, detail="Skill 包不能包含符号链接。")
        if hash_skill_directory(directory) != skill.skill_hash:
            raise HTTPException(status_code=409, detail="Skill 内容在任务准备期间发生变化，请重新提交。")

    verify(skill.directory)
    staging = destination.parent / ("skill.staging-" + uuid.uuid4().hex)
    shutil.copytree(
        skill.directory,
        staging,
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "output", "工作区"),
    )
    # A link introduced during copy is copied as a link, never dereferenced, and
    # rejected below. Both the final source and copied bytes must match the pin.
    verify(staging)
    verify(skill.directory)
    # Keep orphan staging for recovery; never delete a potentially shared snapshot.
    if destination.exists():
        raise FileExistsError("Task Skill snapshot already exists")
    staging.rename(destination)
    return destination


@dataclass(frozen=True)
class PreparedRun:
    run: RunRecord
    llm_config: LlmConfig | ModelAuditSelection | None
    model_trace: dict[str, int | str]

def _resolve_preparation_context(db: Session, request: RunCreate, user: UserContext):
    skill = registry.get(request.skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在或尚未发布。")
    assert_skill_permission(db, user, request.skill_id)
    if request.files:
        assert_skill_permission(db, user, request.skill_id, "can_upload")
    if skill.manifest.handler.adapter == "workflow":
        raise HTTPException(
            status_code=422,
            detail="该 Skill 需要通过对话式工作流创建任务。",
        )
    if request.idempotency_key:
        existing = db.scalar(
            select(RunRecord).where(
                RunRecord.owner_id == user.user_id,
                RunRecord.idempotency_key == request.idempotency_key,
            )
        )
        if existing:
            return existing.id

    assert_skill_accepting_new_work(db, request.skill_id)
    user = refresh_active_user(db, user)
    assert_skill_permission(db, user, request.skill_id)
    if request.files:
        assert_skill_permission(db, user, request.skill_id, "can_upload")

    llm_config = resolve_runtime_config(
        db,
        user,
        request.model_connection_id,
        request.model,
    )
    return skill, user, llm_config


def prepare_run(db: Session, request: RunCreate, user: UserContext, *, context=None) -> PreparedRun | RunRecord:
    """Own only short read sessions; do not end or commit the caller's transaction."""
    bind = db.get_bind()
    if context is None:
        with Session(bind=getattr(bind, "engine", bind)) as read_db:
            context = _resolve_preparation_context(read_db, request, user)
    if isinstance(context, str):
        existing = db.get(RunRecord, context)
        if existing is None:
            raise HTTPException(status_code=409, detail="任务状态已变化，请重新查询。")
        return existing
    skill, user, llm_config = context
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
    with Session(bind=getattr(bind, "engine", bind)) as read_db:
        if request.skill_id == "consolidated-statements" and parameters.get("parent_run_id"):
            parent = get_run_or_404(read_db, parameters["parent_run_id"], user)
            if parent.owner_id != user.user_id or parent.skill_id != request.skill_id or _load(parent.parameters_json).get("period") != parameters.get("period"):
                raise HTTPException(status_code=422, detail="补充版本必须属于同一用户、月份和报表工具。")
        files, _ = validate_files(read_db, skill, request.files, user)
    input_hash = input_snapshot_hash(_json(parameters), files, skill.skill_hash)
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
    return PreparedRun(run, llm_config, model_trace)


def persist_run(db: Session, prepared: PreparedRun) -> RunRecord:
    """Persist the prepared task in the caller-owned transaction, without commit."""
    run = prepared.run
    llm_config = prepared.llm_config
    model_trace = prepared.model_trace
    db.add(run)
    db.flush()
    from .modules.execution.run_snapshot import persist_execution_snapshot
    persist_execution_snapshot(db, run)
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
                owner_id=run.owner_id,
                department_id=run.department_id,
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
    append_run_event(
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



def _revalidate_prepared_run(
    db: Session, prepared: PreparedRun, request: RunCreate, user: UserContext,
    *, pinned_skill: RegisteredSkill | None = None,
) -> None:
    """Recheck mutable facts in the transaction that will persist the task."""
    user = refresh_active_user(db, user)
    run = prepared.run
    skill = pinned_skill or registry.get(run.skill_id)
    if not skill or skill.skill_hash != run.skill_hash or skill.manifest.version != run.skill_version:
        raise HTTPException(status_code=409, detail="Skill 版本已经变化，请重新提交。")
    assert_skill_accepting_new_work(db, run.skill_id)
    assert_skill_permission(db, user, run.skill_id)
    if request.files:
        assert_skill_permission(db, user, run.skill_id, "can_upload")
    for value in request.files.values():
        for file_id in value if isinstance(value, list) else ([value] if value else []):
            record = db.get(FileRecord, file_id, populate_existing=True)
            if record is None or record.kind != "input":
                raise HTTPException(status_code=409, detail="输入文件已经变化，请重新提交。")
            assert_owner(record.owner_id, user, "输入文件", record.department_id)
            path = Path(record.stored_path).resolve()
            if not path.is_file() or sha256_file(path) != record.sha256:
                raise HTTPException(status_code=409, detail="输入文件内容已经变化，请重新提交。")
    files, _ = validate_files(db, skill, request.files, user)
    input_hash = input_snapshot_hash(run.parameters_json, files, run.skill_hash)
    if _json(files) != run.files_json or input_hash != run.input_hash:
        raise HTTPException(status_code=409, detail="输入文件绑定已经变化，请重新提交。")
    parameters = _load(run.parameters_json)
    if run.skill_id == "consolidated-statements" and parameters.get("parent_run_id"):
        parent = db.get(RunRecord, parameters["parent_run_id"], populate_existing=True)
        if (parent is None or parent.owner_id != user.user_id
            or parent.department_id != user.department_id or parent.skill_id != run.skill_id
            or _load(parent.parameters_json).get("period") != parameters.get("period")):
            raise HTTPException(status_code=409, detail="补充版本的父任务已经变化，请重新提交。")


def create_run(db: Session, request: RunCreate, user: UserContext) -> RunRecord:
    """Prepare and persist a task; the API or composing use case owns commit."""
    prepared = prepare_run(db, request, user)
    if isinstance(prepared, RunRecord):
        return prepared
    _revalidate_prepared_run(db, prepared, request, user)
    return persist_run(db, prepared)


def confirm_run(db: Session, run: RunRecord, user: UserContext) -> RunRecord:
    user = execution_actor(db, run, user, ExecutionPhase.CONFIRM)
    try:
        execution_owner(db, run, ExecutionPhase.CONFIRM)
    except ExecutionAuthorizationRevoked as error:
        raise HTTPException(403, str(error)) from None
    if run.state != "waiting_confirmation":
        raise HTTPException(status_code=409, detail="当前任务不在等待确认状态。")
    try:
        assert_run_input_snapshot(run, ExecutionPhase.CONFIRM)
        from .modules.execution.run_snapshot import assert_execution_snapshot
        assert_execution_snapshot(db, run, ExecutionPhase.CONFIRM)
    except ExecutionInputChanged as error:
        raise HTTPException(409, str(error)) from None
    run.confirmed_by = user.user_id
    run.confirmed_at = datetime.now(UTC)
    run.queued_at = datetime.now(UTC)
    queue_run_execution_step(db, run)
    append_run_event(
        db,
        run,
        event_type="state",
        state="queued",
        progress=0,
        message="已确认，任务进入队列",
    )
    return run


def cancel_run(db: Session, run: RunRecord, user: UserContext) -> RunRecord:
    user = execution_actor(db, run, user, ExecutionPhase.CANCEL)
    if run.state in TERMINAL_STATES:
        raise HTTPException(status_code=409, detail="任务已经结束。")
    if run.state in {"created", "validating", "queued", "waiting_confirmation"}:
        run.cancel_requested = True
        run.finished_at = datetime.now(UTC)
        from .step_runtime_service import finish_run_execution_step

        finish_run_execution_step(db, run, state="cancelled", error_code="cancelled")
        append_run_event(
            db,
            run,
            event_type="state",
            state="cancelled",
            message="任务已取消",
        )
    else:
        run.cancel_requested = True
        append_run_event(db, run, event_type="notice", message="已提交取消请求")
    from .audit_service import record_audit
    record_audit(db, actor=user, action="run.cancel", resource_type="run", resource_id=run.id,
                 details={"state":run.state,"on_behalf_of_owner":user.user_id != run.owner_id})
    return run
