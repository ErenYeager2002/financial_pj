from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit_service import record_audit
from .auth import UserContext
from .auth_models import User
from .contracts import ApprovalRecord as ApprovalRead
from .models import (
    ApprovalRecord,
    FileRecord,
    WorkflowAction,
    WorkflowMessage,
    WorkflowSession,
)
from .registry import SkillManifest
from .resource_policy import workflow_root
from .settings import settings
from .storage import sha256_file


class ApprovalGateError(RuntimeError):
    """A write action no longer matches an effective approval."""


def manifest_requires_approval(manifest: SkillManifest) -> bool:
    """Return whether a manifest can cause a write or external side effect."""
    return bool(
        manifest.risk.requires_approval
        or manifest.risk.level != "read_only"
        or manifest.risk.modifies_uploaded_files
    )


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str, fallback: Any) -> Any:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback
    return parsed


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_dump(value).encode("utf-8")).hexdigest()


def _tree_hash(root: Path) -> str:
    if not root.is_dir():
        raise HTTPException(status_code=409, detail="执行快照目录已经缺失。")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root.resolve()):
            raise HTTPException(status_code=409, detail="执行快照包含越界文件。")
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _safe_workflow_path(workflow: WorkflowSession, value: Any, label: str) -> Path:
    root = workflow_root(workflow.owner_id, workflow.id).resolve()
    path = Path(str(value or "")).resolve()
    if not path.is_file() or not path.is_relative_to(root):
        raise HTTPException(status_code=409, detail=f"{label}已经缺失或超出任务目录。")
    return path


def load_workflow_manifest(workflow: WorkflowSession) -> SkillManifest:
    manifest_path = workflow_root(workflow.owner_id, workflow.id) / "skill" / "tool.yaml"
    if not manifest_path.is_file():
        raise HTTPException(status_code=409, detail="工作流 Skill 快照已经缺失。")
    try:
        return SkillManifest.model_validate(
            yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=409, detail="工作流 Skill 快照无效。") from exc


def workflow_requires_approval(workflow: WorkflowSession) -> bool:
    return manifest_requires_approval(load_workflow_manifest(workflow))


def _reset_waiting_workflow(
    db: Session,
    record: ApprovalRecord,
    message: str,
) -> None:
    if not record.workflow_id:
        return
    workflow = db.get(WorkflowSession, record.workflow_id)
    if not workflow or workflow.stage != "waiting_approval":
        return
    workflow.stage = "awaiting_apply_confirmation"
    workflow.state = "waiting_confirmation"
    workflow.progress_message = message


def _input_evidence(db: Session, workflow: WorkflowSession) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    bindings = _load(workflow.files_json, {})
    if not isinstance(bindings, dict):
        raise HTTPException(status_code=409, detail="工作流输入文件快照无效。")
    for role, raw_items in sorted(bindings.items()):
        if not isinstance(raw_items, list):
            raise HTTPException(status_code=409, detail="工作流输入文件快照无效。")
        items: list[dict[str, Any]] = []
        for raw in raw_items:
            if not isinstance(raw, dict) or not isinstance(raw.get("file_id"), str):
                raise HTTPException(status_code=409, detail="工作流输入文件记录不完整。")
            record = db.get(FileRecord, raw["file_id"])
            if (
                not record
                or record.kind != "input"
                or record.owner_id != workflow.owner_id
                or record.department_id != workflow.department_id
            ):
                raise HTTPException(status_code=409, detail="工作流输入文件已经不可用。")
            path = Path(record.stored_path).resolve()
            actual = sha256_file(path) if path.is_file() else ""
            if not actual or actual != record.sha256 or actual != raw.get("sha256"):
                raise HTTPException(status_code=409, detail="工作流原始输入文件内容已经变化。")
            items.append(
                {
                    "file_id": record.id,
                    "sha256": actual,
                    "size_bytes": record.size_bytes,
                }
            )
        result[str(role)] = items
    return result


def _workflow_evidence(
    db: Session, workflow: WorkflowSession
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    root = workflow_root(workflow.owner_id, workflow.id).resolve()
    context = _load(workflow.context_json, {})
    if not isinstance(context, dict):
        raise HTTPException(status_code=409, detail="工作流变更预览上下文无效。")
    business = Path(str(context.get("workspace", ""))).resolve()
    if not business.is_dir() or not business.is_relative_to(root):
        raise HTTPException(status_code=409, detail="工作流变更预览目录已经缺失。")
    checked_plan = _safe_workflow_path(workflow, context.get("checked_plan"), "校验后计划")
    ledger = _safe_workflow_path(workflow, context.get("ledger"), "财务工作副本")
    raw_artifacts = context.get("artifacts", [])
    artifacts = []
    if isinstance(raw_artifacts, list):
        for item in raw_artifacts:
            if not isinstance(item, dict):
                continue
            artifacts.append(
                {
                    "file_id": str(item.get("file_id", "")),
                    "name": str(item.get("name", ""))[:512],
                    "sha256": str(item.get("sha256", "")),
                    "size_bytes": int(item.get("size_bytes", 0) or 0),
                }
            )
    if not artifacts or any(len(item["sha256"]) != 64 for item in artifacts):
        raise HTTPException(status_code=409, detail="变更预览文件或哈希已经缺失。")
    preview = {
        "workflow_id": workflow.id,
        "skill_id": workflow.skill_id,
        "skill_name": workflow.skill_name,
        "reconciliation_date": workflow.reconciliation_date,
        "summary": context.get("summary", {}),
        "artifacts": artifacts,
    }
    preview_hash = _hash_payload(preview)
    snapshot = {
        "resource_type": "workflow",
        "resource_id": workflow.id,
        "department_id": workflow.department_id,
        "owner_id": workflow.owner_id,
        "skill_id": workflow.skill_id,
        "skill_version": workflow.skill_version,
        "skill_hash": workflow.skill_hash,
        "skill_snapshot_sha256": _tree_hash(root / "skill"),
        "reconciliation_date": workflow.reconciliation_date,
        "inputs": _input_evidence(db, workflow),
        "business_workspace_sha256": _tree_hash(business),
        "checked_plan_sha256": sha256_file(checked_plan),
        "ledger_sha256": sha256_file(ledger),
        "preview_sha256": preview_hash,
    }
    return snapshot, preview, _hash_payload(snapshot), preview_hash


def _user_name(db: Session, user_id: str) -> str:
    user = db.get(User, user_id) if user_id else None
    return user.display_name if user else ""


def serialize_approval(db: Session, record: ApprovalRecord) -> ApprovalRead:
    return ApprovalRead(
        id=record.id,
        resource_type=record.resource_type,
        resource_id=record.resource_id,
        run_id=record.run_id,
        workflow_id=record.workflow_id,
        skill_id=record.skill_id,
        snapshot_sha256=record.snapshot_sha256,
        preview_sha256=record.preview_sha256,
        preview=_load(record.preview_json, {}),
        status=record.status,
        requested_by=record.requested_by,
        requested_by_name=_user_name(db, record.requested_by),
        decided_by=record.decided_by,
        decided_by_name=_user_name(db, record.decided_by),
        reason=record.reason,
        execution_action_id=record.execution_action_id,
        created_at=record.created_at,
        decided_at=record.decided_at,
        expires_at=record.expires_at,
    )


def request_workflow_approval(
    db: Session, workflow: WorkflowSession, actor: UserContext
) -> ApprovalRead:
    if actor.user_id != workflow.owner_id or actor.department_id != workflow.department_id:
        raise HTTPException(status_code=404, detail="工作流不存在。")
    if workflow.stage != "awaiting_apply_confirmation":
        raise HTTPException(status_code=409, detail="当前工作流不能申请写入审批。")
    if not workflow_requires_approval(workflow):
        raise HTTPException(status_code=409, detail="当前工作流不需要审批。")
    snapshot, preview, snapshot_hash, preview_hash = _workflow_evidence(db, workflow)
    now = datetime.now(UTC)
    existing = list(
        db.scalars(
            select(ApprovalRecord).where(
                ApprovalRecord.resource_type == "workflow",
                ApprovalRecord.resource_id == workflow.id,
                ApprovalRecord.status == "pending",
            )
        ).all()
    )
    for item in existing:
        if _utc(item.expires_at) <= now:
            item.status = "expired"
            item.decided_at = now
            item.reason = "审批已超过有效期。"
        elif item.snapshot_sha256 == snapshot_hash:
            workflow.stage = "waiting_approval"
            workflow.state = "waiting_approval"
            workflow.progress_message = "等待另一名管理员审批写入"
            return serialize_approval(db, item)
        else:
            item.status = "revoked"
            item.decided_at = now
            item.reason = "变更预览或执行快照已经变化。"
    record = ApprovalRecord(
        id=str(uuid.uuid4()),
        resource_type="workflow",
        resource_id=workflow.id,
        workflow_id=workflow.id,
        department_id=workflow.department_id,
        skill_id=workflow.skill_id,
        snapshot_sha256=snapshot_hash,
        preview_sha256=preview_hash,
        snapshot_json=_dump(snapshot),
        preview_json=_dump(preview),
        status="pending",
        requested_by=actor.user_id,
        expires_at=now + timedelta(minutes=settings.approval_ttl_minutes),
    )
    db.add(record)
    db.flush()
    workflow.stage = "waiting_approval"
    workflow.state = "waiting_approval"
    workflow.progress_message = "等待另一名管理员审批写入"
    db.add(
        WorkflowMessage(
            workflow_id=workflow.id,
            role="assistant",
            content="写入确认已记录，变更预览已锁定。需要另一名平台管理员审批后才能执行。",
            data_json=_dump({"kind": "approval_requested", "approval_id": record.id}),
        )
    )
    record_audit(
        db,
        action="approval.request",
        actor=actor,
        resource_type="approval",
        resource_id=record.id,
        details={
            "workflow_id": workflow.id,
            "skill_id": workflow.skill_id,
            "snapshot_sha256": snapshot_hash,
            "preview_sha256": preview_hash,
        },
    )
    return serialize_approval(db, record)


def list_approvals(
    db: Session, actor: UserContext, *, status: str = "", limit: int = 200
) -> list[ApprovalRead]:
    if not actor.is_admin:
        raise HTTPException(status_code=403, detail="只有平台管理员可以查看审批。")
    now = datetime.now(UTC)
    pending = list(
        db.scalars(
            select(ApprovalRecord).where(
                ApprovalRecord.department_id == actor.department_id,
                ApprovalRecord.status == "pending",
            )
        ).all()
    )
    for item in pending:
        if _utc(item.expires_at) <= now:
            item.status = "expired"
            item.decided_at = now
            item.reason = "审批已超过有效期。"
            _reset_waiting_workflow(db, item, "审批已过期，需要重新确认并申请审批")
            record_audit(
                db,
                action="approval.expire",
                actor=actor,
                resource_type="approval",
                resource_id=item.id,
                details={"workflow_id": item.workflow_id, "skill_id": item.skill_id},
            )
    query = select(ApprovalRecord).where(ApprovalRecord.department_id == actor.department_id)
    if status:
        query = query.where(ApprovalRecord.status == status)
    records = list(
        db.scalars(
            query.order_by(ApprovalRecord.created_at.desc(), ApprovalRecord.id.desc()).limit(
                min(max(limit, 1), 500)
            )
        ).all()
    )
    record_audit(
        db,
        action="admin.approvals.read",
        actor=actor,
        resource_type="approval",
        details={"status": status, "count": len(records)},
    )
    db.commit()
    return [serialize_approval(db, item) for item in records]


def revoke_workflow_approvals(
    db: Session,
    workflow: WorkflowSession,
    actor: UserContext,
    reason: str,
) -> None:
    records = list(
        db.scalars(
            select(ApprovalRecord).where(
                ApprovalRecord.resource_type == "workflow",
                ApprovalRecord.resource_id == workflow.id,
                ApprovalRecord.status == "pending",
            )
        ).all()
    )
    if not records:
        return
    now = datetime.now(UTC)
    for record in records:
        record.status = "revoked"
        record.decided_at = now
        record.reason = reason[:2000]
        record_audit(
            db,
            action="approval.revoke",
            actor=actor,
            resource_type="approval",
            resource_id=record.id,
            details={"workflow_id": workflow.id, "skill_id": workflow.skill_id},
        )


def decide_approval(
    db: Session,
    actor: UserContext,
    approval_id: str,
    *,
    decision: str,
    reason: str,
) -> ApprovalRead:
    if not actor.is_admin:
        raise HTTPException(status_code=403, detail="只有平台管理员可以审批写入任务。")
    record = db.get(ApprovalRecord, approval_id)
    if not record or record.department_id != actor.department_id:
        raise HTTPException(status_code=404, detail="审批记录不存在。")
    now = datetime.now(UTC)
    if record.status == "pending" and _utc(record.expires_at) <= now:
        record.status = "expired"
        record.decided_at = now
        record.reason = "审批已超过有效期。"
        _reset_waiting_workflow(db, record, "审批已过期，需要重新确认并申请审批")
        record_audit(
            db,
            action="approval.expire",
            actor=actor,
            resource_type="approval",
            resource_id=record.id,
            details={"workflow_id": record.workflow_id, "skill_id": record.skill_id},
        )
        db.commit()
        raise HTTPException(status_code=409, detail="审批已经过期。")
    if record.status != "pending":
        raise HTTPException(status_code=409, detail="审批已经处理，不能重复决定。")
    if record.requested_by == actor.user_id:
        raise HTTPException(status_code=409, detail="发起人不能审批自己的写入任务。")
    if record.resource_type != "workflow" or not record.workflow_id:
        raise HTTPException(status_code=409, detail="当前审批资源类型尚不支持执行。")
    workflow = db.get(WorkflowSession, record.workflow_id)
    if not workflow or workflow.department_id != actor.department_id:
        raise HTTPException(status_code=404, detail="审批对应的工作流不存在。")
    try:
        snapshot, preview, snapshot_hash, preview_hash = _workflow_evidence(db, workflow)
    except HTTPException as exc:
        record.status = "revoked"
        record.decided_at = now
        record.reason = "审批所依据的变更预览或执行快照已经不可用。"
        _reset_waiting_workflow(db, record, "执行快照已失效，需要重新生成并申请审批")
        record_audit(
            db,
            action="approval.revoke",
            actor=actor,
            resource_type="approval",
            resource_id=record.id,
            details={
                "workflow_id": workflow.id,
                "skill_id": workflow.skill_id,
                "cause": "snapshot_unavailable",
            },
        )
        db.commit()
        raise HTTPException(
            status_code=409,
            detail="审批所依据的变更预览或执行快照已经不可用，原审批已失效。",
        ) from exc
    if snapshot_hash != record.snapshot_sha256 or preview_hash != record.preview_sha256:
        record.status = "revoked"
        record.decided_at = now
        record.reason = "变更预览或执行快照已经变化。"
        workflow.stage = "awaiting_apply_confirmation"
        workflow.state = "waiting_confirmation"
        workflow.progress_message = "执行快照已变化，需要重新确认并申请审批"
        db.commit()
        raise HTTPException(status_code=409, detail="执行快照已经变化，原审批已失效。")
    record.decided_by = actor.user_id
    record.decided_at = now
    record.reason = reason.strip()
    if decision == "reject":
        record.status = "rejected"
        workflow.stage = "awaiting_apply_confirmation"
        workflow.state = "waiting_confirmation"
        workflow.progress_message = "审批未通过，等待重新确认"
        db.add(
            WorkflowMessage(
                workflow_id=workflow.id,
                role="assistant",
                content=f"管理员未批准本次写入：{record.reason}",
                data_json=_dump({"kind": "approval_rejected", "approval_id": record.id}),
            )
        )
    else:
        active = db.scalar(
            select(WorkflowAction.id).where(
                WorkflowAction.workflow_id == workflow.id,
                WorkflowAction.state.in_(("queued", "running")),
            )
        )
        if active:
            raise HTTPException(status_code=409, detail="工作流已有动作正在执行。")
        action = WorkflowAction(
            id=str(uuid.uuid4()),
            workflow_id=workflow.id,
            name="apply_confirmed",
            input_json=_dump(
                {
                    "reconciliation_date": workflow.reconciliation_date,
                    "files": _load(workflow.files_json, {}),
                    "context": _load(workflow.context_json, {}),
                    "approval_id": record.id,
                    "approval_snapshot_sha256": snapshot_hash,
                }
            ),
        )
        db.add(action)
        record.status = "approved"
        record.execution_action_id = action.id
        workflow.stage = "applying"
        workflow.state = "running"
        workflow.progress = 5
        workflow.progress_message = "审批通过，等待执行写入"
        db.add(
            WorkflowMessage(
                workflow_id=workflow.id,
                role="assistant",
                content="另一名管理员已批准写入。Worker 将再次校验审批快照后执行。",
                data_json=_dump({"kind": "approval_approved", "approval_id": record.id}),
            )
        )
    record.preview_json = _dump(preview)
    record.snapshot_json = _dump(snapshot)
    record_audit(
        db,
        action=f"approval.{decision}",
        actor=actor,
        resource_type="approval",
        resource_id=record.id,
        details={
            "workflow_id": workflow.id,
            "skill_id": workflow.skill_id,
            "snapshot_sha256": snapshot_hash,
        },
    )
    db.commit()
    db.refresh(record)
    return serialize_approval(db, record)


def assert_workflow_action_approval(
    db: Session, action: WorkflowAction, workflow: WorkflowSession
) -> None:
    if action.name != "apply_confirmed" or not workflow_requires_approval(workflow):
        return
    payload = _load(action.input_json, {})
    approval_id = payload.get("approval_id") if isinstance(payload, dict) else None
    snapshot_hash = (
        payload.get("approval_snapshot_sha256") if isinstance(payload, dict) else None
    )
    record = db.get(ApprovalRecord, approval_id) if isinstance(approval_id, str) else None
    now = datetime.now(UTC)
    if not record or record.status != "approved":
        raise ApprovalGateError("写入动作缺少有效的双人审批。")
    if _utc(record.expires_at) <= now:
        record.status = "expired"
        record.reason = "审批在 Worker 执行前过期。"
        record.decided_at = now
        raise ApprovalGateError("写入审批已经过期。")
    if record.requested_by == record.decided_by:
        raise ApprovalGateError("写入审批不满足双人复核要求。")
    if record.execution_action_id != action.id or snapshot_hash != record.snapshot_sha256:
        raise ApprovalGateError("写入动作与批准的执行快照不一致。")
    expected_payload = {
        "reconciliation_date": workflow.reconciliation_date,
        "files": _load(workflow.files_json, {}),
        "context": _load(workflow.context_json, {}),
    }
    actual_payload = {
        "reconciliation_date": payload.get("reconciliation_date"),
        "files": payload.get("files"),
        "context": payload.get("context"),
    }
    if _dump(actual_payload) != _dump(expected_payload):
        raise ApprovalGateError("写入动作内容与批准的工作流快照不一致。")
    _, _, current_hash, current_preview_hash = _workflow_evidence(db, workflow)
    if current_hash != record.snapshot_sha256 or current_preview_hash != record.preview_sha256:
        record.status = "revoked"
        record.reason = "Worker 执行前检测到快照变化。"
        record.decided_at = now
        raise ApprovalGateError("写入前快照已经变化，审批自动失效。")
