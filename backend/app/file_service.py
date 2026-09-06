from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from .auth import UserContext
from .contracts import (
    PlatformFile,
    PlatformFileDetail,
    PlatformFileGroupSummary,
    PlatformFileOption,
)
from .models import (
    FileRecord,
    RunRecord,
    WorkflowMaterialSet,
    WorkflowMaterialSetFile,
    WorkflowSession,
)
from .resource_policy import assert_owner, owner_list_filter
from .storage import (
    file_delete_status,
    file_delete_statuses,
    file_expiry,
    file_references,
)


def _effective_skill_values(
    record: FileRecord,
    run_values: tuple[str, str, str] | None,
) -> tuple[str, str, str]:
    if record.skill_id:
        return record.skill_id, record.skill_name or "", record.skill_version or ""
    if run_values:
        run_skill_id, run_skill_name, run_skill_version = run_values
        return (
            run_skill_id or record.skill_id or "",
            run_skill_name or record.skill_name or "",
            run_skill_version or record.skill_version or "",
        )
    return record.skill_id or "", record.skill_name or "", record.skill_version or ""


@dataclass(frozen=True)
class FileProvenance:
    source_task_id: str = ""
    source_task_type: str = ""
    business_date: str = ""
    material_set_id: str | None = None
    material_version: int | None = None
    same_content_count: int = 1


def _business_date_from_run(run: RunRecord | None) -> str:
    if not run:
        return ""
    try:
        parameters = json.loads(run.parameters_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return ""
    if not isinstance(parameters, dict):
        return ""
    for key in ("business_date", "reconciliation_date", "date"):
        value = parameters.get(key)
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return value
    return ""


def _scope_expression(model: type[object], records: Sequence[FileRecord]) -> object:
    return or_(
        *(
            and_(
                getattr(model, "owner_id") == record.owner_id,
                getattr(model, "department_id") == record.department_id,
            )
            for record in records
        )
    )


def _file_provenance(
    db: Session,
    records: Sequence[FileRecord],
) -> dict[str, FileProvenance]:
    if not records:
        return {}
    metadata = {record.id: FileProvenance() for record in records}
    record_ids = set(metadata)
    run_ids = {record.run_id for record in records if record.run_id}
    workflow_ids = {record.workflow_id for record in records if record.workflow_id}
    workflow_ids.update(
        source_id
        for source_id, in db.execute(
            select(WorkflowMaterialSet.source_workflow_id)
            .join(
                WorkflowMaterialSetFile,
                WorkflowMaterialSetFile.material_set_id == WorkflowMaterialSet.id,
            )
            .where(
                WorkflowMaterialSetFile.file_id.in_(record_ids),
                _scope_expression(WorkflowMaterialSet, records),
                WorkflowMaterialSet.source_workflow_id != "",
            )
        ).all()
        if source_id
    )

    workflow_rows = db.execute(
        select(
            WorkflowSession.id,
            WorkflowSession.display_id,
            WorkflowSession.reconciliation_date,
            WorkflowSession.material_set_id,
        ).where(
            WorkflowSession.id.in_(workflow_ids),
            _scope_expression(WorkflowSession, records),
        )
    ).all()
    workflow_metadata = {
        workflow_id: (display_id or workflow_id, reconciliation_date or "", material_set_id)
        for workflow_id, display_id, reconciliation_date, material_set_id in workflow_rows
    }

    run_rows = db.scalars(
        select(RunRecord).where(
            RunRecord.id.in_(run_ids),
            _scope_expression(RunRecord, records),
        )
    ).all()
    run_metadata = {run.id: run for run in run_rows}
    for record in records:
        if record.workflow_id and record.workflow_id in workflow_metadata:
            source_id, business_date, material_set_id = workflow_metadata[record.workflow_id]
            metadata[record.id] = FileProvenance(
                source_task_id=source_id,
                source_task_type="workflow",
                business_date=business_date,
                material_set_id=material_set_id,
            )
        elif record.run_id and record.run_id in run_metadata:
            run = run_metadata[record.run_id]
            metadata[record.id] = FileProvenance(
                source_task_id=run.id,
                source_task_type="run",
                business_date=_business_date_from_run(run),
            )

    material_rows = db.execute(
        select(
            WorkflowMaterialSetFile.file_id,
            WorkflowMaterialSet.id,
            WorkflowMaterialSet.version,
            WorkflowMaterialSet.source_workflow_id,
            WorkflowMaterialSet.state,
        )
        .join(
            WorkflowMaterialSet,
            WorkflowMaterialSet.id == WorkflowMaterialSetFile.material_set_id,
        )
        .where(
            WorkflowMaterialSetFile.file_id.in_(record_ids),
            _scope_expression(WorkflowMaterialSet, records),
        )
        .order_by(
            case((WorkflowMaterialSet.state == "current", 0), else_=1),
            WorkflowMaterialSet.version.desc(),
        )
    ).all()
    seen_material_files: set[str] = set()
    for file_id, material_set_id, version, source_workflow_id, _ in material_rows:
        if file_id not in metadata:
            continue
        # The query orders current material first and then the newest version.
        # Keep that first match so an older historical binding cannot replace
        # the provenance shown for the file.
        if file_id in seen_material_files:
            continue
        seen_material_files.add(file_id)
        current = metadata[file_id]
        source = workflow_metadata.get(source_workflow_id)
        metadata[file_id] = FileProvenance(
            source_task_id=source[0] if source else current.source_task_id,
            source_task_type="workflow" if source else current.source_task_type,
            business_date=source[1] if source else current.business_date,
            material_set_id=material_set_id,
            material_version=version,
            same_content_count=current.same_content_count,
        )

    sha_values = {record.sha256 for record in records}
    count_rows = db.execute(
        select(
            FileRecord.owner_id,
            FileRecord.department_id,
            FileRecord.kind,
            FileRecord.sha256,
            func.count(),
        )
        .where(
            _scope_expression(FileRecord, records),
            FileRecord.kind.in_({record.kind for record in records}),
            FileRecord.sha256.in_(sha_values),
        )
        .group_by(
            FileRecord.owner_id,
            FileRecord.department_id,
            FileRecord.kind,
            FileRecord.sha256,
        )
    ).all()
    counts = {
        (owner_id, department_id, kind, sha256): int(count)
        for owner_id, department_id, kind, sha256, count in count_rows
    }
    for record in records:
        current = metadata[record.id]
        metadata[record.id] = FileProvenance(
            source_task_id=current.source_task_id,
            source_task_type=current.source_task_type,
            business_date=current.business_date,
            material_set_id=current.material_set_id,
            material_version=current.material_version,
            same_content_count=max(
                1,
                counts.get(
                    (record.owner_id, record.department_id, record.kind, record.sha256),
                    1,
                ),
            ),
        )
    return metadata


def serialize_file(
    db: Session,
    record: FileRecord,
    *,
    delete_status: tuple[bool, str] | None = None,
    include_delete_status: bool = True,
    run_metadata: dict[str, tuple[str, str, str]] | None = None,
    provenance: FileProvenance | None = None,
) -> PlatformFile:
    if not include_delete_status:
        can_delete, delete_block_reason = False, ""
    elif delete_status is None:
        can_delete, delete_block_reason = file_delete_status(db, record)
    else:
        can_delete, delete_block_reason = delete_status
    run_values = None
    if record.run_id:
        if run_metadata is None:
            run = db.get(RunRecord, record.run_id)
            if run and (
                run.owner_id == record.owner_id
                and run.department_id == record.department_id
            ):
                run_values = (run.skill_id, run.skill_name, run.skill_version)
        else:
            run_values = run_metadata.get(record.run_id)
    skill_id, skill_name, skill_version = _effective_skill_values(record, run_values)
    provenance = provenance or _file_provenance(db, [record]).get(record.id, FileProvenance())
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
        source_task_id=provenance.source_task_id,
        source_task_type=provenance.source_task_type,
        business_date=provenance.business_date,
        material_set_id=provenance.material_set_id,
        material_version=provenance.material_version,
        same_content_count=provenance.same_content_count,
        created_at=record.created_at,
        expires_at=file_expiry(record.created_at),
        can_delete=can_delete,
        delete_block_reason=delete_block_reason,
        download_url=f"/api/files/{record.id}/download",
    )


def serialize_files(
    db: Session,
    records: Sequence[FileRecord],
    *,
    include_delete_status: bool = True,
) -> list[PlatformFile]:
    delete_statuses = (
        file_delete_statuses(db, records) if include_delete_status else {}
    )
    provenance = _file_provenance(db, records)
    run_ids = {
        record.run_id
        for record in records
        if not record.skill_id and record.run_id
    }
    run_metadata: dict[str, tuple[str, str, str]] = {}
    if run_ids:
        records_by_run_id = {record.run_id: record for record in records if record.run_id}
        for (
            run_id,
            owner_id,
            department_id,
            skill_id,
            skill_name,
            skill_version,
        ) in db.execute(
            select(
                RunRecord.id,
                RunRecord.owner_id,
                RunRecord.department_id,
                RunRecord.skill_id,
                RunRecord.skill_name,
                RunRecord.skill_version,
            ).where(RunRecord.id.in_(run_ids))
        ).all():
            record = records_by_run_id.get(run_id)
            if record and record.owner_id == owner_id and record.department_id == department_id:
                run_metadata[run_id] = (skill_id, skill_name, skill_version)
    return [
        serialize_file(
            db,
            item,
            delete_status=delete_statuses.get(item.id),
            include_delete_status=include_delete_status,
            run_metadata=run_metadata,
            provenance=provenance.get(item.id),
        )
        for item in records
    ]


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
        audit_href=(
            f"/dashboard/users?tab=audit&audit_resource_type=file&audit_resource_id={record.id}"
        ),
    )


def _effective_skill_expressions() -> tuple[Any, Any, Any]:
    raw_skill_id = func.coalesce(FileRecord.skill_id, "")
    raw_skill_name = func.coalesce(FileRecord.skill_name, "")
    raw_skill_version = func.coalesce(FileRecord.skill_version, "")
    linked_run = aliased(RunRecord)
    run_scope = (
        linked_run.id == FileRecord.run_id,
        linked_run.owner_id == FileRecord.owner_id,
        linked_run.department_id == FileRecord.department_id,
    )
    run_skill_id = select(linked_run.skill_id).where(*run_scope).scalar_subquery()
    run_skill_name = select(linked_run.skill_name).where(*run_scope).scalar_subquery()
    run_skill_version = select(linked_run.skill_version).where(*run_scope).scalar_subquery()
    effective_skill_id = case(
        (raw_skill_id != "", raw_skill_id),
        else_=func.coalesce(run_skill_id, ""),
    )
    effective_skill_name = case(
        (raw_skill_id != "", raw_skill_name),
        else_=func.coalesce(func.nullif(run_skill_name, ""), raw_skill_name),
    )
    effective_skill_version = case(
        (raw_skill_id != "", raw_skill_version),
        else_=func.coalesce(func.nullif(run_skill_version, ""), raw_skill_version),
    )
    return effective_skill_id, effective_skill_name, effective_skill_version


def _current_material_visibility_filter(effective_skill_id: Any | None = None) -> Any:
    if effective_skill_id is None:
        effective_skill_id = _effective_skill_expressions()[0]
    material_set = aliased(WorkflowMaterialSet)
    material_file = aliased(WorkflowMaterialSetFile)
    has_current_material_set = exists(
        select(material_set.id).where(
            material_set.owner_id == FileRecord.owner_id,
            material_set.department_id == FileRecord.department_id,
            material_set.skill_id == effective_skill_id,
            material_set.state == "current",
        )
    )
    belongs_to_current_material_set = exists(
        select(material_file.id)
        .join(material_set, material_set.id == material_file.material_set_id)
        .where(
            material_file.file_id == FileRecord.id,
            material_set.owner_id == FileRecord.owner_id,
            material_set.department_id == FileRecord.department_id,
            material_set.skill_id == effective_skill_id,
            material_set.state == "current",
        )
    )
    return or_(
        FileRecord.kind != "input",
        effective_skill_id == "",
        ~has_current_material_set,
        belongs_to_current_material_set,
    )


def _file_filters(
    user: UserContext,
    *,
    kind: str = "",
    query: str = "",
    latest_only: bool = False,
    skill_id: str = "",
    unassigned: bool = False,
) -> list[Any]:
    effective_skill_id, _, _ = _effective_skill_expressions()
    filters = [owner_list_filter(FileRecord, user)]
    if kind:
        filters.append(FileRecord.kind == kind)
    if query:
        filters.append(FileRecord.original_name.ilike(f"%{query}%"))
    if skill_id:
        filters.append(effective_skill_id == skill_id)
    elif unassigned:
        filters.append(effective_skill_id == "")

    # Inputs are visible only when they are part of the current material set.
    # Outputs remain visible, so this is shared by the list and group queries.
    filters.append(_current_material_visibility_filter(effective_skill_id))

    if latest_only:
        latest_outputs = (
            select(
                FileRecord.id.label("file_id"),
                func.row_number()
                .over(
                    partition_by=(
                        FileRecord.owner_id,
                        FileRecord.department_id,
                        FileRecord.kind,
                        effective_skill_id,
                        FileRecord.original_name,
                    ),
                    order_by=(FileRecord.created_at.desc(), FileRecord.id.desc()),
                )
                .label("latest_rank"),
            )
            .where(*filters, FileRecord.kind == "output")
            .subquery()
        )
        filters.append(
            or_(
                FileRecord.kind != "output",
                FileRecord.id.in_(
                    select(latest_outputs.c.file_id).where(
                        latest_outputs.c.latest_rank == 1
                    )
                ),
            )
        )
    return filters


def list_files_page(
    db: Session,
    user: UserContext,
    *,
    page: int,
    page_size: int,
    kind: str = "",
    query: str = "",
    latest_only: bool = False,
    include_delete_status: bool = True,
    skill_id: str = "",
    unassigned: bool = False,
) -> tuple[list[PlatformFile], int]:
    filters = _file_filters(
        user,
        kind=kind,
        query=query,
        latest_only=latest_only,
        skill_id=skill_id,
        unassigned=unassigned,
    )
    total = int(db.scalar(select(func.count()).select_from(FileRecord).where(*filters)) or 0)
    records = db.scalars(
        select(FileRecord)
        .where(*filters)
        .order_by(FileRecord.created_at.desc(), FileRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return serialize_files(
        db,
        records,
        include_delete_status=include_delete_status,
    ), total


def list_file_groups(
    db: Session,
    user: UserContext,
    *,
    kind: str = "",
    query: str = "",
    latest_only: bool = False,
) -> tuple[list[PlatformFileGroupSummary], int, int]:
    filters = _file_filters(
        user,
        kind=kind,
        query=query,
        latest_only=latest_only,
    )
    effective_skill_id, effective_skill_name, _ = _effective_skill_expressions()
    rows = db.execute(
        select(
            effective_skill_id.label("skill_id"),
            func.max(func.nullif(effective_skill_name, "")).label("skill_name"),
            func.count(FileRecord.id).label("file_count"),
            func.max(FileRecord.created_at).label("latest_created_at"),
        )
        .where(*filters)
        .group_by(effective_skill_id)
        .order_by(func.max(FileRecord.created_at).desc(), effective_skill_id.asc())
    ).all()
    items = []
    total_files = 0
    for skill_id, skill_name, file_count, latest_created_at in rows:
        normalized_skill_id = skill_id or ""
        count = int(file_count or 0)
        total_files += count
        is_unassigned = not normalized_skill_id
        items.append(
            PlatformFileGroupSummary(
                skill_id=normalized_skill_id,
                skill_name="未归类文件" if is_unassigned else (skill_name or normalized_skill_id),
                unassigned=is_unassigned,
                file_count=count,
                latest_created_at=latest_created_at,
            )
        )
    return items, total_files, len(items)


def list_selectable_input_files_page(
    db: Session,
    user: UserContext,
    *,
    page: int,
    page_size: int,
    query: str = "",
    file_ids: Sequence[str] | None = None,
) -> tuple[list[PlatformFileOption], int]:
    filters = _file_filters(user, kind="input", query=query)
    if file_ids is not None:
        filters.append(FileRecord.id.in_(file_ids))
    total = int(db.scalar(select(func.count()).select_from(FileRecord).where(*filters)) or 0)
    records = db.scalars(
        select(FileRecord)
        .where(*filters)
        .order_by(FileRecord.created_at.desc(), FileRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    summaries = serialize_files(db, records, include_delete_status=False)
    return [
        PlatformFileOption(
            id=file.id,
            name=file.name,
            kind="input",
            size_bytes=file.size_bytes,
            skill_id=file.skill_id,
            skill_name=file.skill_name,
            skill_version=file.skill_version,
            created_at=file.created_at,
            source_task_id=file.source_task_id,
            source_task_type=file.source_task_type,
            business_date=file.business_date,
            same_content_count=file.same_content_count,
        )
        for file in summaries
    ], total
