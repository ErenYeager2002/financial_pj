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
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import UserContext
from .events import emit_event
from .models import FileRecord, RunRecord
from .orchestrator import interpret_parameters
from .registry import RegisteredSkill, registry
from .schemas import RunCreate, RunRead
from .settings import settings

TERMINAL_STATES = {"succeeded", "failed", "timed_out", "cancelled"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}


def _assert_visible(run: RunRecord, user: UserContext) -> None:
    if run.department_id != user.department_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="无权查看其他部门的任务。")


def get_run_or_404(db: Session, run_id: str, user: UserContext) -> RunRecord:
    run = db.get(RunRecord, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="任务不存在。")
    _assert_visible(run, user)
    return run


def serialize_run(run: RunRecord) -> RunRead:
    return RunRead(
        id=run.id,
        owner_id=run.owner_id,
        owner_name=run.owner_name,
        skill_id=run.skill_id,
        skill_name=run.skill_name,
        skill_version=run.skill_version,
        skill_commit=run.skill_commit,
        state=run.state,
        progress=run.progress,
        progress_message=run.progress_message,
        message=run.message,
        parameters=_load(run.parameters_json),
        files=_load(run.files_json),
        result=_load(run.result_json),
        error_message=run.error_message,
        confirmation_required=run.confirmation_required,
        confirmed_by=run.confirmed_by,
        cancel_requested=run.cancel_requested,
        created_at=run.created_at,
        queued_at=run.queued_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _validate_files(
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
        if not spec.multiple and len(ids) > 1:
            raise HTTPException(status_code=422, detail=f"{spec.name} 只能上传一个文件。")
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


def _snapshot_skill(skill: RegisteredSkill, run_id: str) -> Path:
    destination = settings.run_dir / run_id / "skill"
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
    if request.idempotency_key:
        existing = db.scalar(
            select(RunRecord).where(
                RunRecord.owner_id == user.user_id,
                RunRecord.idempotency_key == request.idempotency_key,
            )
        )
        if existing:
            return existing

    parameters, missing, _, _ = interpret_parameters(skill, request.message, request.parameters)
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
    files, file_hash = _validate_files(db, skill, request.files, user)
    payload_hash = hashlib.sha256(
        (_json(parameters) + _json(files) + skill.skill_hash).encode("utf-8")
    ).hexdigest()
    input_hash = hashlib.sha256(f"{file_hash}:{payload_hash}".encode()).hexdigest()
    confirmation = skill.manifest.risk.requires_confirmation
    now = datetime.now(UTC)
    run_id = str(uuid.uuid4())
    snapshot_dir = _snapshot_skill(skill, run_id)
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
    emit_event(
        db,
        run,
        event_type="state",
        state=run.state,
        progress=0,
        message=run.progress_message,
    )
    return run


def confirm_run(db: Session, run: RunRecord, user: UserContext) -> RunRecord:
    if run.state != "waiting_confirmation":
        raise HTTPException(status_code=409, detail="当前任务不在等待确认状态。")
    run.confirmed_by = user.user_id
    run.confirmed_at = datetime.now(UTC)
    run.queued_at = datetime.now(UTC)
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
