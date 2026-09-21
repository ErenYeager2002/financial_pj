"""Publish one reusable AR result per completed task and retire superseded books.

Material rows remain as provenance/checkpoints. Retired bytes are never used as
proof: a durable receipt records the strict publication readback performed before
unlinking, and historical readers must explicitly opt into that evidence.
"""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
from sqlalchemy import select
from .models import AuditEvent, FileRecord, WorkflowBatch, WorkflowMaterialSet, WorkflowSession, WorkflowAction, RunRecord, TaskDraftRecord
from .ar_skill_identity import is_ar_skill

RETIRED = "workflow.material_workbook.retired"
_last_maintenance = 0.0


def _scope(row):
    return row.owner_id, row.department_id, row.skill_id


def _finished(db, material):
    if not material.source_workflow_id:
        return True
    workflow = db.get(WorkflowSession, material.source_workflow_id)
    if not workflow or _scope(workflow) != _scope(material) or workflow.state != "succeeded":
        return False
    if workflow.batch_id:
        batch = db.get(WorkflowBatch, workflow.batch_id)
        return bool(batch and _scope(batch) == _scope(material) and batch.state == "succeeded")
    return True


def visible_material_set(db, owner_id, department_id, skill_id):
    from .workflow_material_service import current_material_set
    current = current_material_set(db, owner_id, department_id, skill_id)
    if not is_ar_skill(skill_id):
        return current
    seen = set()
    while current and current.id not in seen:
        seen.add(current.id)
        if _finished(db, current):
            return current
        current = db.get(WorkflowMaterialSet, current.parent_set_id) if current.parent_set_id else None
        if current and _scope(current) != (owner_id, department_id, skill_id):
            raise ValueError("材料检查点的业务归属不一致")
    return None


def retired_file_ids():
    return select(AuditEvent.resource_id).where(AuditEvent.action == RETIRED,
                                               AuditEvent.resource_type == "file")


def retirement_receipt(db, record):
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == RETIRED,
        AuditEvent.resource_type == "file", AuditEvent.resource_id == record.id,
        AuditEvent.department_id == record.department_id).order_by(AuditEvent.id.desc()))
    if not event:
        return None
    from .credential_service import decrypt_secret
    envelope = json.loads(event.details_json)
    value = json.loads(decrypt_secret(envelope["retirement_secret"]))
    expected = {"owner_id": record.owner_id, "department_id": record.department_id,
                "skill_id": record.skill_id, "sha256": record.sha256, "stored_path": record.stored_path}
    if value.get("identity") != expected:
        raise ValueError("旧工作簿清理凭据与文件登记不一致")
    return value


def historical_publication(db, workflow):
    """Only historical bundle reads may use a pre-deletion verified manifest."""
    from .ar_publication import publication_manifest
    return publication_manifest(db, workflow, allow_retired=True)


def _ids(value):
    if isinstance(value, dict):
        result = {value["file_id"]} if isinstance(value.get("file_id"), str) else set()
        for item in value.values():
            result.update(_ids(item))
        return result
    if isinstance(value, list):
        return set().union(*(_ids(item) for item in value)) if value else set()
    return {value} if isinstance(value, str) else set()


def protected_ids(db):
    """Preserve current heads and every unfinished task's recovery references."""
    protected = set()
    for material in db.scalars(select(WorkflowMaterialSet).where(WorkflowMaterialSet.state == "current")):
        protected.update(f.file_id for f in material.files)
    unfinished_batches = set(db.scalars(select(WorkflowBatch.id).where(WorkflowBatch.state.not_in(["succeeded", "cancelled"]))))
    for workflow in db.scalars(select(WorkflowSession)):
        if workflow.state == "succeeded" and workflow.batch_id not in unfinished_batches:
            continue
        if workflow.state == "cancelled" and workflow.batch_id not in unfinished_batches:
            continue
        context = json.loads(workflow.context_json or "{}")
        protected.update(_ids(context))
        protected.update(_ids(json.loads(workflow.files_json or "{}")))
        for material_id in (workflow.material_set_id, (context.get("ar_execution") or {}).get("material_set_id")):
            material = db.get(WorkflowMaterialSet, material_id) if material_id else None
            if material:
                protected.update(f.file_id for f in material.files)
    for batch in db.scalars(select(WorkflowBatch).where(WorkflowBatch.id.in_(unfinished_batches))):
        protected.update(_ids(json.loads(batch.files_json or "{}")))
    for run in db.scalars(select(RunRecord).where(RunRecord.state.not_in(["succeeded", "cancelled"]))):
        protected.update(_ids(json.loads(run.files_json or "{}")))
        protected.update(_ids(json.loads(run.parameters_json or "{}")))
    for draft in db.scalars(select(TaskDraftRecord).where(TaskDraftRecord.run_id.is_(None))):
        protected.update(_ids(json.loads(draft.files_json or "{}")))
        protected.update(_ids(json.loads(draft.parameters_json or "{}")))
    # Some legacy bindings use absolute paths rather than file IDs.
    protected.update(db.scalars(select(FileRecord.id).where(FileRecord.stored_path.in_(protected))))
    return protected


def _path(record):
    from .settings import settings
    path = Path(record.stored_path)
    roots = [settings.upload_dir.resolve(), settings.workflow_dir.resolve()]
    resolved = path.resolve()
    if (not path.is_absolute() or path.is_symlink() or path != resolved
            or path.suffix.lower() not in {".xlsx", ".xlsm", ".xls"}
            or not any(resolved.is_relative_to(root) and resolved != root for root in roots)):
        raise ValueError("旧工作簿清理路径异常")
    return path


def _digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def prepare_retirements(db, *, limit=4):
    """Must run under claim lock. Commit receipts before any irreversible unlink."""
    from .ar_material_history import receipt_rows
    from .ar_publication import publication_manifest
    from .ar_formal_ledger_service import read_formal_ledger_bundle
    protected = protected_ids(db)
    candidates = {}
    for head in db.scalars(select(WorkflowMaterialSet).where(WorkflowMaterialSet.state == "current")):
        if not is_ar_skill(head.skill_id) or not head.source_workflow_id or not _finished(db, head):
            continue
        # The replacement itself must still pass strict physical readback.
        workflow = db.get(WorkflowSession, head.source_workflow_id)
        publication_manifest(db, workflow)
        read_formal_ledger_bundle(db, workflow)
        cursor = head.parent_set_id
        seen = set()
        while cursor and cursor not in seen:
            seen.add(cursor)
            old = db.get(WorkflowMaterialSet, cursor)
            if not old or _scope(old) != _scope(head):
                raise ValueError("旧材料来源链不完整")
            for member in old.files:
                if member.file_id not in protected:
                    candidates.setdefault(member.file_id, (member, head))
            cursor = old.parent_set_id
    count = 0
    manifests = {}
    for file_id, (member, head) in candidates.items():
        record = db.get(FileRecord, file_id)
        if not record or (record.owner_id, record.department_id) != (head.owner_id, head.department_id):
            raise ValueError("旧工作簿归属不一致")
        if record.sha256 != member.sha256:
            raise ValueError("旧工作簿登记指纹不一致")
        if retirement_receipt(db, record):
            continue
        path = _path(record)
        if not path.is_file():
            continue  # Never legitimize a file that was already missing.
        if _digest(path) != record.sha256:
            raise ValueError("旧工作簿指纹改变，停止清理")
        publication = None
        if record.kind == "output":
            source = db.get(WorkflowSession, record.workflow_id)
            if not source or not source.material_set_id:
                continue
            if source.id not in manifests:
                # Verify both workbook publication and the durable business ledger.
                manifests[source.id] = publication_manifest(db, source, allow_retired=True)
                read_formal_ledger_bundle(db, source)
            publication = manifests[source.id]
        rows = receipt_rows(path) if member.role == "profit_loss_ledgers" else None
        payload = {"identity": {"owner_id": record.owner_id, "department_id": record.department_id,
            "skill_id": record.skill_id, "sha256": record.sha256, "stored_path": record.stored_path},
            "replacement_material_set_id": head.id, "publication": publication,
            "receipt_rows": rows, "schema_version": "ar-workbook-retirement-v1"}
        from .credential_service import encrypt_secret
        envelope = {"schema_version": "ar-workbook-retirement-v1",
                    "replacement_material_set_id": head.id,
                    "retirement_secret": encrypt_secret(json.dumps(payload, ensure_ascii=False))}
        db.add(AuditEvent(actor_id="system", actor_role="system", department_id=record.department_id,
            action=RETIRED, resource_type="file", resource_id=record.id,
            details_json=json.dumps(envelope)))
        count += 1
        if count >= limit:
            break
    return count


def finish_retirements(db):
    """Idempotently unlink only registered books with committed verification receipts."""
    protected = protected_ids(db)
    protected_paths = set(db.scalars(select(FileRecord.stored_path).where(FileRecord.id.in_(protected))))
    removed = 0
    records = db.scalars(select(FileRecord).where(FileRecord.id.in_(retired_file_ids())))
    for record in records:
        if record.id in protected or record.stored_path in protected_paths:
            continue
        receipt = retirement_receipt(db, record)
        replacement = db.get(WorkflowMaterialSet, receipt["replacement_material_set_id"])
        if not replacement or not _finished(db, replacement):
            raise ValueError("替换任务尚未成功，不能清理旧工作簿")
        path = _path(record)
        if not path.exists():
            continue
        if not path.is_file() or _digest(path) != record.sha256:
            raise ValueError("清理前旧工作簿指纹改变")
        # A shared path is never removed while another live registration uses it.
        other = db.scalar(select(FileRecord.id).where(FileRecord.stored_path == record.stored_path,
            FileRecord.id != record.id, FileRecord.id.not_in(retired_file_ids())))
        if other:
            continue
        path.unlink()
        removed += 1
    return removed


def maintain_materials(db, *, force=False):
    global _last_maintenance
    from .settings import settings
    enabled = settings.data_dir / "maintenance" / "ar-material-retirement.enabled"
    if not force and not enabled.is_file():
        return False
    now = time.monotonic()
    if not force and now - _last_maintenance < 60:
        return False
    _last_maintenance = now
    from .scheduler import acquire_claim_lock
    acquire_claim_lock(db)
    busy = db.scalar(select(WorkflowAction.id).where(WorkflowAction.state.in_(
        ["running", "queued", "ar_v2:running", "ar_v2:queued"])).limit(1))
    busy = busy or db.scalar(select(RunRecord.id).where(RunRecord.state.in_(
        ["running", "queued", "cancelling"])).limit(1))
    if busy:
        db.rollback()
        return False
    from .ar_material_copies import prepare_copies, finish_copies
    prepared = prepare_retirements(db) + prepare_copies(db)
    db.commit()
    acquire_claim_lock(db)
    # A new task may have started at the receipt-commit boundary.
    busy = db.scalar(select(WorkflowAction.id).where(WorkflowAction.state.in_(
        ["running", "queued", "ar_v2:running", "ar_v2:queued"])).limit(1))
    busy = busy or db.scalar(select(RunRecord.id).where(RunRecord.state.in_(
        ["running", "queued", "cancelling"])).limit(1))
    if busy:
        db.rollback()
        return bool(prepared)
    removed = finish_retirements(db) + finish_copies(db)
    db.commit()
    if prepared or removed:
        _last_maintenance = 0.0
    return bool(prepared or removed)
