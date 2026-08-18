from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import UserContext
from .contracts import PlatformFile, PlatformFileDetail
from .models import FileRecord, RunRecord
from .resource_policy import assert_owner, owner_list_filter
from .storage import file_delete_status, file_expiry, file_references


def serialize_file(db: Session, record: FileRecord) -> PlatformFile:
    can_delete, delete_block_reason = file_delete_status(db, record)
    skill_id = record.skill_id
    skill_name = record.skill_name
    skill_version = record.skill_version
    if not skill_id and record.run_id:
        run = db.get(RunRecord, record.run_id)
        if run:
            skill_id = run.skill_id
            skill_name = run.skill_name
            skill_version = run.skill_version
    return PlatformFile(
        id=record.id,
        name=record.original_name,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        kind=record.kind,
        skill_id=skill_id,
        skill_name=skill_name,
        skill_version=skill_version,
        workflow_id=record.workflow_id or None,
        content_type=record.content_type,
        run_id=record.run_id,
        created_at=record.created_at,
        expires_at=file_expiry(record.created_at),
        can_delete=can_delete,
        delete_block_reason=delete_block_reason,
        download_url=f"/api/files/{record.id}/download",
    )


def get_file_detail(
    db: Session,
    file_id: str,
    user: UserContext,
) -> PlatformFileDetail:
    record = db.get(FileRecord, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在。")
    assert_owner(record.owner_id, user, "文件", record.department_id)
    summary = serialize_file(db, record)
    run_ids, workflow_ids = file_references(db, record)
    return PlatformFileDetail(
        **summary.model_dump(),
        referenced_run_ids=run_ids,
        referenced_workflow_ids=workflow_ids,
    )


def list_files_page(
    db: Session,
    user: UserContext,
    *,
    page: int,
    page_size: int,
    kind: str = "",
    query: str = "",
) -> tuple[list[PlatformFile], int]:
    filters = [owner_list_filter(FileRecord, user)]
    if kind:
        filters.append(FileRecord.kind == kind)
    if query:
        filters.append(FileRecord.original_name.ilike(f"%{query}%"))
    total = int(db.scalar(select(func.count()).select_from(FileRecord).where(*filters)) or 0)
    records = db.scalars(
        select(FileRecord)
        .where(*filters)
        .order_by(FileRecord.created_at.desc(), FileRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [serialize_file(db, item) for item in records], total
