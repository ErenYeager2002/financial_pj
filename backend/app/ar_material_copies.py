"""Retire successful AR task workbook copies; retain reports and ledger evidence."""
import json
import re
from pathlib import Path
from sqlalchemy import select
from .models import AuditEvent, FileRecord, WorkflowSession
from .ar_skill_identity import AR_SKILL_IDS
from .credential_service import encrypt_secret, decrypt_secret
from .ar_material_lifecycle import _digest

ACTION = "workflow.material_copies.retired"
EXTENSIONS = {".xls", ".xlsx", ".xlsm"}


def copy_inventory(workspace, *, flow_names=(), date=""):
    """Only controlled business-table directories, never general XLSX outputs."""
    workspace = Path(workspace)
    if workspace.is_symlink() or workspace.resolve() != workspace:
        raise ValueError("旧工作副本目录不受控")
    roots = [workspace / "02_我的表副本"]
    stages = workspace / "03_写入暂存区"
    if stages.exists():
        if stages.is_symlink():
            raise ValueError("旧工作副本暂存目录异常")
        for stage in stages.iterdir():
            if stage.is_symlink() or not stage.is_dir():
                continue
            roots += [stage / "02_我的表副本",
                      stage / "execution-review" / "flow-protection" / "02_我的表副本",
                      stage / "execution-review" / "protection"]
    result = {}
    # Legacy flow output is a full business workbook, not a reconciliation report.
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date):
        outputs = [workspace / "04_产出"]
        if stages.exists():
            outputs += [stage / "04_产出" for stage in stages.iterdir() if stage.is_dir() and not stage.is_symlink()]
        for output in outputs:
            for name in flow_names:
                filename = "到账流转_已回填_" + Path(name).stem + "_" + date.replace("-", "") + ".xlsx"
                path = output / filename
                if path.exists():
                    if path.is_symlink() or path.resolve() != path or not path.is_file() or not path.is_relative_to(workspace):
                        raise ValueError("兼容流转工作副本路径异常")
                    result[str(path)] = _digest(path)
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() not in EXTENSIONS:
                continue
            if path.is_symlink() or path.resolve() != path or not path.is_file() or not path.is_relative_to(workspace):
                raise ValueError("旧工作副本包含越界或非普通文件")
            if root.name == "protection" and not path.name.startswith("expected_"):
                continue
            result[str(path)] = _digest(path)
    transactions = workspace / ".批次发布事务"
    if transactions.exists():
        for manifest_path in transactions.glob("*/manifest.json"):
            if manifest_path.is_symlink() or manifest_path.resolve() != manifest_path:
                raise ValueError("批次发布事务清单路径异常")
            manifest = json.loads(manifest_path.read_text())
            if manifest.get("state") != "completed":
                continue
            for item in manifest.get("files", []):
                target = Path(str(item.get("target") or ""))
                backup = str(item.get("backup") or "")
                if (target.is_absolute() or ".." in target.parts or not target.parts
                        or target.parts[0] != "02_我的表副本" or target.suffix.lower() not in EXTENSIONS):
                    continue
                if not re.fullmatch(r"backups/[0-9]{5}\.bak", backup):
                    continue
                path = manifest_path.parent / backup
                if not path.exists():
                    continue
                if path.is_symlink() or path.resolve() != path or not path.is_file():
                    raise ValueError("批次发布备份路径异常")
                result[str(path)] = _digest(path)
    return result


def _context(db, workflow, protected):
    from .ar_staging_retention import archive_location, _hold
    from .workflow_service import _controlled_context_workspace, _workflow_storage_root
    context = json.loads(workflow.context_json or "{}")
    if workflow.state != "succeeded" or (workflow.batch_id and workflow.batch.state != "succeeded"):
        return None
    retention = context.get("ar_staging_retention") or {}
    if retention.get("state") in {"verified", "purging", "purged"}:
        return None  # Existing registered archives require their own verified rewrite.
    if not context.get("formal_ledgers"):
        return None
    stage, _, _ = archive_location(db, workflow, context)
    if _hold(db, workflow, stage):
        return None
    workspace = _controlled_context_workspace(_workflow_storage_root(db, workflow), workflow)
    for value in protected:
        path = Path(value)
        if path.is_absolute() and (path == workspace or path.is_relative_to(workspace)):
            return None
    return context, workspace


def prepare_copies(db, *, limit=1):
    from .ar_staging_retention import _verify_publication
    from .ar_material_lifecycle import protected_ids
    protected = protected_ids(db)
    prepared = select(AuditEvent.resource_id).where(AuditEvent.action == ACTION)
    workflows = db.scalars(select(WorkflowSession).where(
        WorkflowSession.skill_id.in_(AR_SKILL_IDS), WorkflowSession.state == "succeeded",
        WorkflowSession.id.not_in(prepared)).order_by(WorkflowSession.created_at))
    count = 0
    for workflow in workflows:
        checked = _context(db, workflow, protected)
        if checked is None:
            continue
        context, workspace = checked
        _verify_publication(db, workflow, context)
        flow_names = [entry.get("name", "") for entry in json.loads(workflow.files_json or "{}").get("receipt_flow_table", [])]
        files = copy_inventory(workspace, flow_names=flow_names, date=workflow.reconciliation_date)
        # Registered files are owned by the material retirement path; do not
        # bypass its latest-head, active-reference or formal-history checks.
        registered = set(db.scalars(select(FileRecord.stored_path).where(FileRecord.stored_path.in_(files))))
        files = {p:h for p,h in files.items() if p not in registered}
        payload = {"workflow_id":workflow.id,"workspace":str(workspace),"files":files}
        db.add(AuditEvent(actor_id="system",actor_role="system",department_id=workflow.department_id,
            action=ACTION,resource_type="workflow",resource_id=workflow.id,
            details_json=json.dumps({"schema_version":"ar-copies-retirement-v1","count":len(files),
                                    "retirement_secret":encrypt_secret(json.dumps(payload))})))
        count += 1
        if count >= limit:
            break
    return count


def finish_copies(db):
    from .ar_material_lifecycle import protected_ids
    protected = protected_ids(db)
    removed = 0
    events = db.scalars(select(AuditEvent).where(AuditEvent.action == ACTION))
    for event in events:
        envelope = json.loads(event.details_json)
        if envelope.get("complete"):
            continue
        workflow = db.get(WorkflowSession,event.resource_id)
        if not workflow or workflow.department_id != event.department_id:
            raise ValueError("工作副本清理任务归属不一致")
        checked = _context(db,workflow,protected)
        if checked is None:
            continue
        context, workspace = checked
        payload = json.loads(decrypt_secret(envelope["retirement_secret"]))
        if payload["workflow_id"] != workflow.id or payload["workspace"] != str(workspace):
            raise ValueError("工作副本清理凭据与固定目录不一致")
        flow_names = [entry.get("name", "") for entry in json.loads(workflow.files_json or "{}").get("receipt_flow_table", [])]
        current = copy_inventory(workspace, flow_names=flow_names, date=workflow.reconciliation_date)
        expected = payload["files"]
        for name,digest in expected.items():
            path = Path(name)
            if not path.exists():
                continue
            if current.get(name) != digest:
                raise ValueError("旧工作副本在清理前发生变化")
            if db.scalar(select(FileRecord.id).where(FileRecord.stored_path == name).limit(1)):
                raise ValueError("工作副本已成为登记材料，未删除")
            path.unlink()
            removed += 1
        context["staging_retention_complete"] = True
        context["ar_staging_retention"] = {"state":"workbooks_retired","receipt_id":event.id}
        workflow.context_json = json.dumps(context,ensure_ascii=False)
        envelope["complete"] = True
        event.details_json = json.dumps(envelope)
    return removed
