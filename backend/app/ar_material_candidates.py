"""Read upload candidates separately from immutable task material bindings."""
from __future__ import annotations
import json
import re
from pathlib import Path
from sqlalchemy import select, or_, and_
from fastapi import HTTPException
from .audit_service import record_audit
from .ar_skill_identity import is_ar_skill
from .models import AuditEvent, FileRecord

ROLES = {"profit_loss_ledgers", "receipt_flow_table"}


HIDDEN_ACTION = "workflow.material_candidate.hidden"


def hidden_candidate_ids(user):
    return select(AuditEvent.resource_id).where(
        AuditEvent.actor_id == user.user_id,
        AuditEvent.department_id == user.department_id,
        AuditEvent.action == HIDDEN_ACTION,
        AuditEvent.resource_type == "file",
    )


def remove_material_candidates(db, user, skill_id, *, file_id=None, all_files=False):
    """Hide choices; never delete files or mutate historical material bindings."""
    from .workflow_material_service import current_material_set, material_set_bindings
    if not is_ar_skill(skill_id) or bool(file_id) == all_files:
        raise HTTPException(status_code=422, detail="请选择一个候选文件，或明确选择全部移除。")
    current = current_material_set(db, user.user_id, user.department_id, skill_id)
    bindings = material_set_bindings(db, current) if current else {}
    bound_ids = [entry["file_id"] for entries in bindings.values() for entry in entries]
    query = select(FileRecord).where(
        FileRecord.owner_id == user.user_id,
        FileRecord.department_id == user.department_id,
        or_(and_(FileRecord.kind == "input", FileRecord.skill_id == skill_id),
            and_(FileRecord.id.in_(bound_ids), FileRecord.skill_id.in_(["", skill_id]))),
    )
    if file_id:
        query = query.where(FileRecord.id == file_id)
        if db.scalar(query) is None:
            raise HTTPException(status_code=404, detail="候选文件不存在或不属于当前工具。")
    records = db.scalars(query.where(FileRecord.id.not_in(hidden_candidate_ids(user)))).all()
    for record in records:
        record_audit(db, actor=user, action=HIDDEN_ACTION, resource_type="file",
                     resource_id=record.id, details={"skill_id": skill_id})
    return len(records)


def candidate_year(name: str) -> int | None:
    years = set(re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", name))
    return int(next(iter(years))) if len(years) == 1 else None


def material_candidates(db, user, skill_id, bindings, *, page=1, page_size=30):
    # Defaults stay the current published business version. Candidates never
    # enter task bindings until explicitly submitted by the user.
    bound_ids = [entry["file_id"] for entries in bindings.values() for entry in entries]
    hidden_bound = set(db.scalars(hidden_candidate_ids(user).where(AuditEvent.resource_id.in_(bound_ids)))) if bound_ids else set()
    result = {role: [dict(entry, selected=True) for entry in entries if entry["file_id"] not in hidden_bound]
              for role, entries in bindings.items()}
    existing = {entry["file_id"] for entries in result.values() for entry in entries}
    records = list(db.scalars(select(FileRecord).where(
        FileRecord.owner_id == user.user_id,
        FileRecord.department_id == user.department_id,
        FileRecord.skill_id == skill_id,
        FileRecord.kind == "input",
        FileRecord.id.not_in(hidden_candidate_ids(user)),
    ).order_by(FileRecord.created_at.desc(), FileRecord.id.desc())
      .offset((page - 1) * page_size).limit(page_size + 1)))
    next_page = page + 1 if len(records) > page_size else None
    records = records[:page_size]
    ids = [record.id for record in records]
    # Upload provenance records the explicit role, including neutral filenames.
    upload_roles = {}
    if ids:
        events = db.scalars(select(AuditEvent).where(
            AuditEvent.actor_id == user.user_id,
            AuditEvent.department_id == user.department_id,
            AuditEvent.action == "file.upload",
            AuditEvent.resource_type == "file",
            AuditEvent.resource_id.in_(ids),
        ).order_by(AuditEvent.id))
        for event in events:
            try:
                metadata = json.loads(event.details_json)
            except (ValueError, TypeError):
                continue
            if isinstance(metadata, dict) and metadata.get("role") in ROLES:
                upload_roles[event.resource_id] = metadata["role"]
    for record in records:
        if record.id in existing or not Path(record.stored_path).is_file():
            continue
        role = upload_roles.get(record.id)
        if not role:
            name = record.original_name.lower()
            if any(word in name for word in ("到账", "流转", "receipt", "flow")):
                role = "receipt_flow_table"
            elif any(word in name for word in ("盈亏", "利润", "profit", "ledger")):
                role = "profit_loss_ledgers"
            else:
                continue
        entry = dict(file_id=record.id, name=record.original_name,
                     sha256=record.sha256, size_bytes=record.size_bytes, selected=False)
        if role == "profit_loss_ledgers":
            entry["year"] = candidate_year(record.original_name)
        result.setdefault(role, []).append(entry)
    return result, next_page
