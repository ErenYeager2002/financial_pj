from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .auth import UserContext
from .models import (
    FileRecord,
    RunRecord,
    WorkflowAction,
    WorkflowMaterialSet,
    WorkflowMaterialSetFile,
    WorkflowSession,
)
from .resource_policy import assert_owner, run_root, upload_root
from .settings import settings

SAFE_NAME_PATTERN = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._()（）-]+")
RESULT_FILE_DELETE_REASON = "结果文件随任务记录保留，不能单独删除。"
MATERIAL_FILE_DELETE_REASON = "文件属于业务材料版本；为保留当前版本和历史版本，不能删除。"
REFERENCED_FILE_DELETE_REASON = "文件仍被任务使用；为保留审计和重试证据，不能删除。"


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


def _file_ids_from_json(value: str, candidates: set[str] | None = None) -> set[str]:
    try:
        payload = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return set()

    def collect(item: object) -> set[str]:
        if isinstance(item, dict):
            result: set[str] = set()
            for child in item.values():
                result.update(collect(child))
            return result
        if isinstance(item, list):
            result = set()
            for child in item:
                result.update(collect(child))
            return result
        if not isinstance(item, str):
            return set()
        return {item} if candidates is None or item in candidates else set()

    return collect(payload)


def _file_delete_status(
    record: FileRecord,
    *,
    material_reference: bool,
    file_reference: bool,
) -> tuple[bool, str]:
    if record.kind != "input":
        return False, RESULT_FILE_DELETE_REASON
    if material_reference:
        return False, MATERIAL_FILE_DELETE_REASON
    if file_reference:
        return False, REFERENCED_FILE_DELETE_REASON
    return True, ""


def _reference_json_filter(column: object, file_ids: set[str]) -> object:
    """Select only legacy JSON rows that can contain one of the page's IDs."""
    return or_(*(column.like(f"%{file_id}%") for file_id in file_ids))  # type: ignore[attr-defined]


def _reference_scope(model: type[object], scopes: set[tuple[str, str]]) -> object:
    return or_(
        *(
            and_(
                getattr(model, "owner_id") == owner_id,
                getattr(model, "department_id") == department_id,
            )
            for owner_id, department_id in scopes
        )
    )


def _legacy_reference_maps(
    db: Session,
    records: Sequence[FileRecord],
) -> tuple[dict[str, set[str]], dict[str, set[str]], set[str]]:
    """Read only matching legacy references and keep malformed rows conservative.

    The relationship table is authoritative for material versions. Older task
    records still carry references in JSON, so the compatibility path searches
    for the current page's IDs in SQL and parses only matching rows. A matching
    malformed row blocks deletion for that file instead of treating a failed
    parse as proof that the file is unused.
    """
    file_ids = {record.id for record in records if record.kind == "input"}
    scopes = {(record.owner_id, record.department_id) for record in records}
    run_refs: dict[str, set[str]] = {}
    workflow_refs: dict[str, set[str]] = {}
    uncertain: set[str] = set()
    if not file_ids or not scopes:
        return run_refs, workflow_refs, uncertain

    def add_refs(
        rows: Sequence[tuple[str, str]],
        target: dict[str, set[str]],
    ) -> None:
        for source_id, value in rows:
            raw = value or ""
            matched = {file_id for file_id in file_ids if file_id in raw}
            if not matched:
                continue
            try:
                json.loads(raw or "{}")
            except (TypeError, json.JSONDecodeError):
                uncertain.update(matched)
                continue
            for file_id in _file_ids_from_json(raw, file_ids):
                target.setdefault(file_id, set()).add(source_id)

    run_rows = db.execute(
        select(RunRecord.id, RunRecord.files_json).where(
            _reference_scope(RunRecord, scopes),
            _reference_json_filter(RunRecord.files_json, file_ids),
        )
    ).all()
    add_refs(run_rows, run_refs)

    workflow_rows = db.execute(
        select(WorkflowSession.id, WorkflowSession.files_json).where(
            _reference_scope(WorkflowSession, scopes),
            _reference_json_filter(WorkflowSession.files_json, file_ids),
        )
    ).all()
    add_refs(workflow_rows, workflow_refs)

    action_rows = db.execute(
        select(WorkflowAction.workflow_id, WorkflowAction.input_json)
        .join(WorkflowSession, WorkflowSession.id == WorkflowAction.workflow_id)
        .where(
            _reference_scope(WorkflowSession, scopes),
            _reference_json_filter(WorkflowAction.input_json, file_ids),
        )
    ).all()
    add_refs(action_rows, workflow_refs)
    return run_refs, workflow_refs, uncertain


def file_references(
    db: Session,
    record: FileRecord,
) -> tuple[list[str], list[str]]:
    run_refs, workflow_refs, _ = _legacy_reference_maps(db, [record])
    run_ids = set(run_refs.get(record.id, set()))
    workflow_ids = set(workflow_refs.get(record.id, set()))
    if record.run_id:
        run_ids.add(record.run_id)
    if record.workflow_id:
        workflow_ids.add(record.workflow_id)
    return sorted(run_ids), sorted(workflow_ids)


def file_delete_status(db: Session, record: FileRecord) -> tuple[bool, str]:
    if record.kind != "input":
        return _file_delete_status(
            record,
            material_reference=False,
            file_reference=False,
        )
    material_reference = db.scalar(
        select(WorkflowMaterialSetFile.id).where(
            WorkflowMaterialSetFile.file_id == record.id
        )
    )
    run_refs, workflow_refs, uncertain = _legacy_reference_maps(db, [record])
    run_ids = set(run_refs.get(record.id, set()))
    workflow_ids = set(workflow_refs.get(record.id, set()))
    if record.run_id:
        run_ids.add(record.run_id)
    if record.workflow_id:
        workflow_ids.add(record.workflow_id)
    return _file_delete_status(
        record,
        material_reference=bool(material_reference),
        file_reference=bool(run_ids or workflow_ids or record.id in uncertain),
    )


def file_delete_statuses(
    db: Session,
    records: Sequence[FileRecord],
) -> dict[str, tuple[bool, str]]:
    """Build deletion statuses for a file page without per-file reference queries."""
    if not records:
        return {}

    statuses: dict[str, tuple[bool, str]] = {
        record.id: _file_delete_status(
            record,
            material_reference=False,
            file_reference=False,
        )
        for record in records
        if record.kind != "input"
    }
    input_records = [record for record in records if record.kind == "input"]
    if not input_records:
        return statuses

    record_ids = {record.id for record in input_records}
    material_file_ids = set(
        db.scalars(
            select(WorkflowMaterialSetFile.file_id)
            .join(
                WorkflowMaterialSet,
                WorkflowMaterialSet.id == WorkflowMaterialSetFile.material_set_id,
            )
            .where(
                WorkflowMaterialSetFile.file_id.in_(record_ids),
                _reference_scope(
                    WorkflowMaterialSet,
                    {(record.owner_id, record.department_id) for record in input_records},
                ),
            )
        ).all()
    )
    run_refs, workflow_refs, uncertain = _legacy_reference_maps(db, input_records)

    for record in input_records:
        statuses[record.id] = _file_delete_status(
            record,
            material_reference=record.id in material_file_ids,
            file_reference=bool(
                record.run_id
                or record.workflow_id
                or run_refs.get(record.id)
                or workflow_refs.get(record.id)
                or record.id in uncertain
            ),
        )
    return statuses


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
