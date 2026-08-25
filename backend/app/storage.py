from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import UserContext
from .models import (
    FileRecord,
    RunRecord,
    WorkflowAction,
    WorkflowMaterialSetFile,
    WorkflowSession,
)
from .resource_policy import assert_owner, run_root, upload_root
from .settings import settings

SAFE_NAME_PATTERN = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._()（）-]+")
def safe_filename(name: str) -> str:
    clean = SAFE_NAME_PATTERN.sub("_", Path(name).name).strip("._")
    return clean[:180] or "uploaded-file"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_expiry(created_at: datetime | None) -> datetime | None:
    if created_at is None:
        return None
    return created_at + timedelta(days=settings.file_retention_days)


async def save_upload(
    db: Session,
    upload: UploadFile,
    user: UserContext,
    *,
    skill_id: str = "",
    skill_name: str = "",
    skill_version: str = "",
) -> FileRecord:
    file_id = str(uuid.uuid4())
    folder = upload_root(user.user_id, file_id)
    folder.mkdir(parents=True, exist_ok=False)
    target = folder / safe_filename(upload.filename or "uploaded-file")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0
    digest = hashlib.sha256()
    try:
        with target.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"文件超过 {settings.max_upload_mb} MB 限制。",
                    )
                digest.update(chunk)
                handle.write(chunk)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    record = FileRecord(
        id=file_id,
        owner_id=user.user_id,
        department_id=user.department_id,
        kind="input",
        original_name=upload.filename or target.name,
        stored_path=str(target.resolve()),
        content_type=upload.content_type or "application/octet-stream",
        size_bytes=size,
        sha256=digest.hexdigest(),
        skill_id=skill_id,
        skill_name=skill_name,
        skill_version=skill_version,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def register_output(
    db: Session,
    path: Path,
    run_id: str,
    owner: UserContext,
    display_name: str | None = None,
    skill_id: str = "",
    skill_name: str = "",
    skill_version: str = "",
    workflow_id: str = "",
) -> FileRecord:
    resolved = path.resolve()
    expected_run_root = run_root(owner.user_id, run_id)
    if not resolved.is_file() or not resolved.is_relative_to(expected_run_root):
        raise ValueError("输出文件必须位于本次运行目录内")
    record = FileRecord(
        id=str(uuid.uuid4()),
        owner_id=owner.user_id,
        department_id=owner.department_id,
        kind="output",
        original_name=display_name or path.name,
        stored_path=str(resolved),
        content_type="application/octet-stream",
        size_bytes=resolved.stat().st_size,
        sha256=sha256_file(resolved),
        run_id=run_id,
        skill_id=skill_id,
        skill_name=skill_name,
        skill_version=skill_version,
        workflow_id=workflow_id,
    )
    db.add(record)
    db.flush()
    return record


def copy_input_to_workspace(source: Path, target_dir: Path, role: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()
    target = target_dir / f"{safe_filename(role)}{suffix}"
    shutil.copy2(source, target)
    return target.resolve()


def _contains_file_id(value: str, file_id: str) -> bool:
    try:
        payload = json.loads(value or "{}")
    except json.JSONDecodeError:
        return False

    def contains(item: object) -> bool:
        if isinstance(item, dict):
            return any(contains(value) for value in item.values())
        if isinstance(item, list):
            return any(contains(value) for value in item)
        return item == file_id

    return contains(payload)


def file_references(
    db: Session,
    record: FileRecord,
) -> tuple[list[str], list[str]]:
    runs = db.scalars(
        select(RunRecord).where(RunRecord.owner_id == record.owner_id)
    ).all()
    workflows = db.scalars(
        select(WorkflowSession).where(WorkflowSession.owner_id == record.owner_id)
    ).all()
    actions = db.scalars(
        select(WorkflowAction)
        .join(WorkflowSession, WorkflowSession.id == WorkflowAction.workflow_id)
        .where(WorkflowSession.owner_id == record.owner_id)
    ).all()
    run_ids = [item.id for item in runs if _contains_file_id(item.files_json, record.id)]
    workflow_ids = {
        item.id for item in workflows if _contains_file_id(item.files_json, record.id)
    }
    workflow_ids.update(
        item.workflow_id for item in actions if _contains_file_id(item.input_json, record.id)
    )
    if record.run_id:
        run_ids.append(record.run_id)
    return sorted(set(run_ids)), sorted(workflow_ids)


def file_delete_status(db: Session, record: FileRecord) -> tuple[bool, str]:
    if record.kind != "input":
        return False, "结果文件随任务记录保留，不能单独删除。"
    material_reference = db.scalar(
        select(WorkflowMaterialSetFile.id).where(
            WorkflowMaterialSetFile.file_id == record.id
        )
    )
    if material_reference:
        return False, "文件属于业务材料版本；为保留当前版本和历史版本，不能删除。"
    run_ids, workflow_ids = file_references(db, record)
    if run_ids or workflow_ids:
        return False, "文件仍被任务使用；为保留审计和重试证据，不能删除。"
    return True, ""


def delete_upload(
    db: Session,
    file_id: str,
    user: UserContext,
) -> None:
    record = db.get(FileRecord, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="上传文件不存在。")
    assert_owner(record.owner_id, user, "上传文件", record.department_id)
    can_delete, reason = file_delete_status(db, record)
    if not can_delete:
        raise HTTPException(status_code=409, detail=reason)

    path = Path(record.stored_path).resolve()
    uploads_root = settings.upload_dir.resolve()
    expected_folders = {
        upload_root(record.owner_id, record.id),
        (uploads_root / record.id).resolve(),  # P0-07 搬迁前兼容旧目录。
    }
    if not path.is_relative_to(uploads_root) or path.parent not in expected_folders:
        raise HTTPException(status_code=409, detail="上传文件存储路径异常，已拒绝删除。")
    if path.exists():
        path.unlink()
    if path.parent.exists():
        path.parent.rmdir()
    db.delete(record)
    db.commit()
