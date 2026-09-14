from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .auth import UserContext
from .models import (
    FileRecord,
    WorkflowMaterialSet,
    WorkflowMaterialSetFile,
    WorkflowSession,
)

ANNUAL_LEDGER_ROLE = "profit_loss_ledgers"
RECEIPT_FLOW_ROLE = "receipt_flow_table"
MATERIAL_ROLES = {ANNUAL_LEDGER_ROLE, RECEIPT_FLOW_ROLE}


class MaterialVersionConflict(RuntimeError):
    """Raised when a workflow tries to publish from a superseded material version."""


def current_material_set(
    db: Session,
    owner_id: str,
    department_id: str,
    skill_id: str,
) -> WorkflowMaterialSet | None:
    return db.scalar(
        select(WorkflowMaterialSet).where(
            WorkflowMaterialSet.owner_id == owner_id,
            WorkflowMaterialSet.department_id == department_id,
            WorkflowMaterialSet.skill_id == skill_id,
            WorkflowMaterialSet.state == "current",
        )
    )


def successful_reconciliation_dates_for_material_lineage(
    db: Session,
    *,
    owner_id: str,
    department_id: str,
    skill_id: str,
    material_set_id: str | None,
    reconciliation_dates: Iterable[str],
) -> set[str]:
    """Find successful dates whose fixed or published version reaches the current set."""
    return set(
        successful_reconciliation_workflows_for_material_lineage(
            db,
            owner_id=owner_id,
            department_id=department_id,
            skill_id=skill_id,
            material_set_id=material_set_id,
            reconciliation_dates=reconciliation_dates,
        )
    )


def successful_reconciliation_workflows_for_material_lineage(
    db: Session,
    *,
    owner_id: str,
    department_id: str,
    skill_id: str,
    material_set_id: str | None,
    reconciliation_dates: Iterable[str],
) -> dict[str, list[str]]:
    """Map successful dates to the preserved workflow records in the material lineage."""
    dates = tuple(reconciliation_dates)
    if not material_set_id or not dates:
        return {}

    lineage: set[str] = set()
    cursor: str | None = material_set_id
    while cursor and cursor not in lineage:
        material_set = db.get(WorkflowMaterialSet, cursor)
        if material_set is None:
            break
        lineage.add(material_set.id)
        cursor = material_set.parent_set_id

    if not lineage:
        return {}
    found: dict[str, list[str]] = {}
    rows = db.execute(
        select(WorkflowSession.reconciliation_date, WorkflowSession.id)
        .where(
            WorkflowSession.owner_id == owner_id,
            WorkflowSession.department_id == department_id,
            WorkflowSession.skill_id == skill_id,
            WorkflowSession.material_set_id.in_(lineage),
            WorkflowSession.state == "succeeded",
            WorkflowSession.reconciliation_date.in_(dates),
        )
        .order_by(WorkflowSession.created_at, WorkflowSession.id)
    ).all()
    for reconciliation_date, workflow_id in rows:
        found.setdefault(reconciliation_date, []).append(workflow_id)
    return found


def list_material_sets(
    db: Session,
    user: UserContext,
    skill_id: str,
    *,
    limit: int = 50,
) -> list[WorkflowMaterialSet]:
    return list(
        db.scalars(
            select(WorkflowMaterialSet)
            .where(
                WorkflowMaterialSet.owner_id == user.user_id,
                WorkflowMaterialSet.department_id == user.department_id,
                WorkflowMaterialSet.skill_id == skill_id,
            )
            .order_by(WorkflowMaterialSet.version.desc())
            .limit(max(1, min(limit, 100)))
        )
    )


def _annual_year(name: str) -> int:
    match = re.search(r"(?<!\d)((?:19|20)\d{2})(?:年)?(?!\d)", name)
    if not match:
        # Historical workbooks without a year were previously routed to the
        # current year. Keep that compatibility while new uploads use a year.
        return datetime.now(UTC).year
    return int(match.group(1))


def _validated_members(
    db: Session,
    user: UserContext,
    skill_id: str,
    bindings: dict[str, list[dict[str, Any]]],
    *,
    source_workflow_id: str = "",
    annual_years: dict[str, int] | None = None,
) -> list[tuple[str, int, FileRecord]]:
    unknown = set(bindings) - MATERIAL_ROLES
    if unknown:
        raise ValueError(f"业务材料包含未知用途：{sorted(unknown)}")
    annual = bindings.get(ANNUAL_LEDGER_ROLE, [])
    flow = bindings.get(RECEIPT_FLOW_ROLE, [])
    if not annual or len(flow) != 1:
        raise ValueError("业务材料必须包含至少一份年度盈亏核算表和一份到账流转表。")

    members: list[tuple[str, int, FileRecord]] = []
    years: set[int] = set()
    for role, entries in ((ANNUAL_LEDGER_ROLE, annual), (RECEIPT_FLOW_ROLE, flow)):
        for entry in entries:
            file_id = str(entry.get("file_id", ""))
            record = db.get(FileRecord, file_id)
            if not record:
                raise ValueError(f"业务材料文件不存在：{file_id}")
            if record.owner_id != user.user_id or record.department_id != user.department_id:
                raise ValueError("业务材料文件所有者或部门不一致。")
            if record.skill_id not in {"", skill_id}:
                raise ValueError("业务材料文件所属 Skill 不一致。")
            if entry.get("sha256") and str(entry["sha256"]) != record.sha256:
                raise ValueError("业务材料文件哈希与平台记录不一致。")
            if source_workflow_id and (
                record.kind != "output" or record.workflow_id != source_workflow_id
            ):
                raise ValueError("发布版本只能引用当前任务登记的输出文件。")
            year = 0
            if role == ANNUAL_LEDGER_ROLE:
                year = (annual_years[file_id] if annual_years and file_id in annual_years
                        else _annual_year(record.original_name))
                if type(year) is not int or not 1900 <= year <= 2099:
                    raise ValueError("业务材料固定的盈亏年度无效。")
            if role == ANNUAL_LEDGER_ROLE and year in years:
                raise ValueError(f"业务材料中存在两份 {year} 年盈亏核算表。")
            years.add(year)
            members.append((role, year, record))
    return members


def _member_key(role: str, year: int, record: FileRecord) -> tuple[str, int, str, str]:
    return role, year, record.id, record.sha256


def _stored_member_keys(material_set: WorkflowMaterialSet) -> set[tuple[str, int, str, str]]:
    return {(item.role, item.year, item.file_id, item.sha256) for item in material_set.files}


def material_set_bindings(
    db: Session,
    material_set: WorkflowMaterialSet,
) -> dict[str, list[dict[str, Any]]]:
    bindings: dict[str, list[dict[str, Any]]] = {}
    for item in sorted(material_set.files, key=lambda value: (value.role, value.year)):
        record = db.get(FileRecord, item.file_id)
        if not record or record.sha256 != item.sha256:
            raise ValueError("业务材料版本引用的文件不存在或哈希不一致。")
        bindings.setdefault(item.role, []).append(
            {
                "file_id": record.id,
                "name": record.original_name,
                "size_bytes": record.size_bytes,
                "sha256": record.sha256,
                "year": item.year or None,
                "material_set_id": material_set.id,
                "material_version": material_set.version,
                "source_workflow_id": material_set.source_workflow_id,
                "published_at": material_set.published_at.isoformat(),
            }
        )
    return bindings


def serialize_material_set(
    db: Session,
    material_set: WorkflowMaterialSet,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for role, entries in material_set_bindings(db, material_set).items():
        files.extend(
            {
                "role": role,
                "year": entry.get("year"),
                "file_id": entry["file_id"],
                "name": entry["name"],
                "size_bytes": entry["size_bytes"],
                "sha256": entry["sha256"],
            }
            for entry in entries
        )
    source_workflow = (
        db.get(WorkflowSession, material_set.source_workflow_id)
        if material_set.source_workflow_id
        else None
    )
    return {
        "id": material_set.id,
        "skill_id": material_set.skill_id,
        "version": material_set.version,
        "parent_set_id": material_set.parent_set_id,
        "source_workflow_id": material_set.source_workflow_id,
        "source_workflow_display_id": (
            source_workflow.display_id if source_workflow and source_workflow.display_id else ""
        ),
        "state": material_set.state,
        "published_at": material_set.published_at,
        "files": files,
    }


def create_or_replace_current_set(
    db: Session,
    user: UserContext,
    skill_id: str,
    bindings: dict[str, list[dict[str, Any]]],
    *,
    source_workflow_id: str = "",
    expected_current_id: str | None = None,
    require_no_current: bool = False,
    annual_years: dict[str, int] | None = None,
) -> WorkflowMaterialSet:
    current = current_material_set(db, user.user_id, user.department_id, skill_id)
    # Reusing a registered file must preserve its immutable year, including
    # unnamed workbooks selected again after New Year. New uploads retain the
    # existing first-registration filename fallback.
    fixed_years = {item.file_id: item.year for item in current.files
                   if item.role == ANNUAL_LEDGER_ROLE} if current else {}
    if annual_years is not None:
        annual_ids = [str(entry.get("file_id", ""))
                      for entry in bindings.get(ANNUAL_LEDGER_ROLE, [])]
        if (not annual_ids or len(annual_ids) != len(set(annual_ids))
                or set(annual_years) != set(annual_ids)):
            raise ValueError("发布年度映射与年度盈亏文件不完整对应。")
        fixed_years = annual_years
    members = _validated_members(
        db,
        user,
        skill_id,
        bindings,
        source_workflow_id=source_workflow_id,
        annual_years=fixed_years,
    )
    if require_no_current and current is not None:
        raise MaterialVersionConflict(
            "业务工作簿已有更新版本；当前任务不能覆盖新版本，请基于最新版本重新创建任务。"
        )
    if expected_current_id is not None and (current is None or current.id != expected_current_id):
        raise MaterialVersionConflict(
            "业务工作簿已有更新版本；当前任务不能覆盖新版本，请基于最新版本重新创建任务。"
        )
    member_keys = {_member_key(*member) for member in members}
    if current and _stored_member_keys(current) == member_keys:
        return current

    parent_set_id = current.id if current else None
    if current:
        changed = db.execute(
            update(WorkflowMaterialSet)
            .where(
                WorkflowMaterialSet.id == current.id,
                WorkflowMaterialSet.state == "current",
            )
            .values(state="superseded")
        )
        if changed.rowcount != 1:
            raise MaterialVersionConflict(
                "业务工作簿版本已被其他任务更新，请基于最新版本重新创建任务。"
            )
    latest_version = db.scalar(
        select(func.max(WorkflowMaterialSet.version)).where(
            WorkflowMaterialSet.owner_id == user.user_id,
            WorkflowMaterialSet.department_id == user.department_id,
            WorkflowMaterialSet.skill_id == skill_id,
        )
    )
    now = datetime.now(UTC)
    created = WorkflowMaterialSet(
        id=str(uuid.uuid4()),
        owner_id=user.user_id,
        department_id=user.department_id,
        skill_id=skill_id,
        version=int(latest_version or 0) + 1,
        parent_set_id=parent_set_id,
        source_workflow_id=source_workflow_id,
        state="current",
        created_at=now,
        published_at=now,
    )
    db.add(created)
    db.flush()
    for role, year, record in members:
        db.add(
            WorkflowMaterialSetFile(
                id=str(uuid.uuid4()),
                material_set_id=created.id,
                role=role,
                year=year,
                file_id=record.id,
                sha256=record.sha256,
            )
        )
    db.flush()
    return created


def material_set_matches_bindings(
    db: Session,
    user: UserContext,
    skill_id: str,
    material_set: WorkflowMaterialSet,
    bindings: dict[str, list[dict[str, Any]]],
) -> bool:
    """Compare an already-started workflow's fixed inputs with an immutable version."""
    members = _validated_members(
        db, user, skill_id, bindings,
        annual_years={item.file_id: item.year for item in material_set.files
                      if item.role == ANNUAL_LEDGER_ROLE},
    )
    return {_member_key(*member) for member in members} == _stored_member_keys(material_set)


def publish_workflow_material_set(
    db: Session,
    workflow: WorkflowSession,
    bindings: dict[str, list[dict[str, Any]]],
    *,
    annual_years: dict[str, int] | None = None,
) -> WorkflowMaterialSet:
    if not workflow.material_set_id:
        raise MaterialVersionConflict(
            "当前任务没有固定业务工作簿版本，请重新选择权威文件后创建任务。"
        )
    actor = UserContext(
        user_id=workflow.owner_id,
        display_name=workflow.owner_name,
        role="finance_user",
        department_id=workflow.department_id,
    )
    return create_or_replace_current_set(
        db,
        actor,
        workflow.skill_id,
        bindings,
        source_workflow_id=workflow.id,
        expected_current_id=workflow.material_set_id,
        annual_years=annual_years,
    )


def restore_material_set(
    db: Session,
    user: UserContext,
    skill_id: str,
    material_set_id: str,
) -> WorkflowMaterialSet:
    from .scheduler import acquire_claim_lock
    from .workflow_material_lock import assert_material_editable
    acquire_claim_lock(db)
    assert_material_editable(db, user, skill_id)
    target = db.scalar(
        select(WorkflowMaterialSet).where(
            WorkflowMaterialSet.id == material_set_id,
            WorkflowMaterialSet.owner_id == user.user_id,
            WorkflowMaterialSet.department_id == user.department_id,
            WorkflowMaterialSet.skill_id == skill_id,
        )
    )
    if not target:
        raise ValueError("要恢复的业务材料历史版本不存在。")
    current = current_material_set(db, user.user_id, user.department_id, skill_id)
    if not current:
        raise MaterialVersionConflict("当前业务材料版本不存在，不能执行历史恢复。")
    if target.id == current.id:
        raise ValueError("该业务材料版本已经是当前版本。")
    return create_or_replace_current_set(
        db,
        user,
        skill_id,
        material_set_bindings(db, target),
        source_workflow_id=target.source_workflow_id,
        expected_current_id=current.id,
        annual_years={item.file_id: item.year for item in target.files
                      if item.role == ANNUAL_LEDGER_ROLE},
    )


def material_binding_is_allowed_output(
    db: Session,
    workflow: WorkflowSession,
    entry: dict[str, Any],
    record: FileRecord,
) -> bool:
    material_set_id = str(entry.get("material_set_id", ""))
    if not material_set_id or material_set_id != workflow.material_set_id:
        return False
    material_set = db.get(WorkflowMaterialSet, material_set_id)
    if (
        not material_set
        or material_set.owner_id != workflow.owner_id
        or material_set.department_id != workflow.department_id
        or material_set.skill_id != workflow.skill_id
    ):
        return False
    return (
        db.scalar(
            select(WorkflowMaterialSetFile.id).where(
                WorkflowMaterialSetFile.material_set_id == material_set_id,
                WorkflowMaterialSetFile.file_id == record.id,
                WorkflowMaterialSetFile.sha256 == record.sha256,
            )
        )
        is not None
    )
