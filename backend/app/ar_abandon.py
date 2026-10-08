"""Explicitly quarantine unpublished staging without rolling back published days."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm.exc import DetachedInstanceError

from .ar_execution_contract import CONTRACT_VERSION
from .models import FileRecord, WorkflowAction, WorkflowMaterialSet, WorkflowSession

KEY = "ar_abandonment"
MESSAGE = "已放弃本日未发布结果，暂存与失败记录已封存；可使用保留材料重新创建任务。"


class AbandonRequest(BaseModel):
    checkpoint_fingerprint: str


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def binding(workflow, context):
    return digest({"workflow_id": workflow.id, "owner_id": workflow.owner_id,
                   "department_id": workflow.department_id, "skill_id": workflow.skill_id,
                   "date": workflow.reconciliation_date, "material_set_id": workflow.material_set_id,
                   "execution": context.get("ar_execution")})


def is_abandoned(workflow, context=None):
    try:
        context = context if context is not None else json.loads(workflow.context_json or "{}")
        marker = context.get(KEY) or {}
        return (marker.get("schema_version") == "ar-abandonment-v1"
                and marker.get("state") == "abandoned"
                and marker.get("binding") == binding(workflow, context))
    except (ValueError, TypeError, AttributeError):
        return False


def _full_domain_stop(inspection):
    total = inspection.get("total")
    fingerprint = inspection.get("fingerprint")
    return (inspection.get("verified") is True and type(total) is int and 0 < total <= 128
            and type(inspection.get("exited")) is int and inspection["exited"] == total
            and type(inspection.get("unconfirmed")) is int and inspection["unconfirmed"] == 0
            and inspection.get("process_evidence_scope") == "linux_descendant_tree"
            and type(inspection.get("descendant_domains_verified")) is int
            and inspection["descendant_domains_verified"] == total
            and isinstance(fingerprint, str) and len(fingerprint) == 64
            and all(char in "0123456789abcdef" for char in fingerprint))


def _action_snapshot(actions):
    return sorted((a.id, a.state, a.attempt_count,
                   (a.finished_at.replace(tzinfo=UTC) if a.finished_at.tzinfo is None
                    else a.finished_at.astimezone(UTC)).isoformat() if a.finished_at else "")
                  for a in actions)


def _process_actions(workflow, context):
    actions = list(workflow.actions)
    failure = context.get("ar_failure") or {}
    checks = [a for a in actions if a.name in {"ar_write_ledger", "ar_write_receipt_flow"}
              and (a.attempt_count or a.started_at)]
    latest = next((a for a in actions if a.id == failure.get("action_id")), None)
    if latest is None:
        raise ValueError("缺少失败动作及退出证据，不能放弃。")
    if latest not in checks:
        checks.append(latest)
    if len(checks) > 128:
        raise ValueError("退出证据核查数量超过上限，不能放弃。")
    for action in checks:
        if not action.finished_at or action.state not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("写入动作未确认结束，不能放弃。")
        if action.state != "succeeded" and failure.get("action_id") != action.id:
            raise ValueError("存在其他未核清的写入尝试，不能放弃。")
    return checks


def _process_evidence_binding(workflow, context, checks):
    bound = {}
    for action in checks:
        result = (json.loads(action.result_json or "{}") if action.state == "succeeded"
                  else context.get("ar_failure") or {})
        bound[action.id] = {"workflow_id": action.workflow_id, "name": action.name,
                            "attempt": action.attempt_count, "worker_id": action.worker_id,
                            "process_evidence_version": result.get("process_evidence_version"),
                            "process_exit_confirmed": result.get("process_exit_confirmed"),
                            "process_records": result.get("process_records")}
    return digest(bound)


def _process_proof(workflow, context):
    from .ar_process_inspection import inspect_process_evidence
    hashes, stops = {}, {}
    for action in _process_actions(workflow, context):
        result = (json.loads(action.result_json or "{}") if action.state == "succeeded"
                  else context.get("ar_failure") or {})
        inspection = inspect_process_evidence(workflow, action, {**result, "action_id": action.id})
        if not _full_domain_stop(inspection):
            raise ValueError("未取得所有脚本及 Linux 后代的完整停止证明，不能放弃暂存结果。")
        hashes[action.id] = inspection["fingerprint"]
        stops[action.id] = {key: inspection[key] for key in (
            "verified", "total", "exited", "unconfirmed", "descendant_domains_verified",
            "process_evidence_scope", "fingerprint")}
    return hashes, stops


def has_verified_abandonment_stop(workflow, context=None):
    """A historical marker is visible even when its stop evidence cannot release occupancy."""
    try:
        context = context if context is not None else json.loads(workflow.context_json or "{}")
        if not is_abandoned(workflow, context):
            return False
        proof = context[KEY].get("proof") or {}
        if (proof.get("binding") != binding(workflow, context)
                or proof.get("material_version") != (context.get("ar_execution") or {}).get("material_version")
                or json.loads(json.dumps(_action_snapshot(workflow.actions))) != proof.get("actions")):
            return False
        hashes = proof.get("process_hashes")
        if not isinstance(hashes, dict) or not hashes or len(hashes) > 128:
            return False
        checks = _process_actions(workflow, context)
        if hashes.keys() != {action.id for action in checks}:
            return False
        stops = proof.get("process_stop_evidence_v2")
        if stops is not None:
            return (proof.get("process_binding_sha256") == _process_evidence_binding(workflow, context, checks)
                    and isinstance(stops, dict) and stops.keys() == hashes.keys()
                    and all(isinstance(value, dict) and _full_domain_stop(value)
                            and value["fingerprint"] == hashes[identity]
                            for identity, value in stops.items()))
        # Legacy markers have only opaque fingerprints. Recheck original facts;
        # never upgrade a direct-child proof or rewrite business history on read.
        current_hashes, _ = _process_proof(workflow, context)
        return current_hashes == hashes
    except (ValueError, TypeError, KeyError, AttributeError, OSError, DetachedInstanceError):
        return False


def require_not_abandoned(workflow):
    if KEY in json.loads(workflow.context_json or "{}"):
        raise ValueError("本任务的未发布结果已封存，不能恢复或继续执行，请创建新任务。")


def _file_hash(path, root):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("材料或暂存文件缺失或路径异常，不能放弃结果。")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _inspect(db, workflow):
    from . import workflow_service as service
    from .settings import settings

    from .ar_skill_identity import is_ar_skill
    if not is_ar_skill(workflow.skill_id):
        raise ValueError("此操作仅适用于应收核销任务。")
    context = json.loads(workflow.context_json or "{}")
    execution = context.get("ar_execution") or {}
    if workflow.state not in {"failed", "cancelled"}:
        raise ValueError("任务尚未结束，不能放弃暂存结果。")
    if (execution.get("schema_version") != CONTRACT_VERSION
            or execution.get("publication") != "not_published"
            or execution.get("reconciliation_date") != workflow.reconciliation_date
            or execution.get("skill_hash") != workflow.skill_hash
            or execution.get("material_set_id") != workflow.material_set_id):
        raise ValueError("本日发布状态或固定材料身份无法确认，不能直接放弃。")
    completed = execution.get("completed") or []
    if any(name in completed for name in ("publish_reconciliation", "complete_reconciliation")):
        raise ValueError("已进入发布阶段，须调查实际发布结果。")
    actions = list(workflow.actions)
    if any(a.state in {"queued", "running"} for a in actions):
        raise ValueError("仍有动作排队或执行中，不能放弃结果。")
    if any(a.name in {"ar_publish_reconciliation", "ar_complete_reconciliation"}
           and (a.attempt_count or a.started_at or a.state == "succeeded") for a in actions):
        raise ValueError("曾尝试发布，不能把发布状态不明当作未发布。")
    if db.scalar(select(WorkflowMaterialSet.id).where(WorkflowMaterialSet.source_workflow_id == workflow.id).limit(1)):
        raise ValueError("发现本日已登记的材料版本，不能放弃已发布结果。")
    material = db.get(WorkflowMaterialSet, workflow.material_set_id)
    if (material is None or material.state != "current" or material.version != execution.get("material_version")
            or (material.owner_id, material.department_id, material.skill_id)
            != (workflow.owner_id, workflow.department_id, workflow.skill_id)):
        raise ValueError("当前材料已变化，不能用旧检查点解除材料锁。")
    if not material.files:
        raise ValueError("写入前材料为空，不能放弃。")
    material_hashes = {}
    for item in material.files:
        record = db.get(FileRecord, item.file_id)
        if (record is None or record.owner_id != workflow.owner_id or record.department_id != workflow.department_id
                or record.sha256 != item.sha256 or _file_hash(record.stored_path, settings.data_dir) != item.sha256):
            raise ValueError("写入前材料已变化或缺失，不能放弃。")
        material_hashes[item.file_id] = item.sha256
    workspace = service._controlled_context_workspace(service._workflow_storage_root(db, workflow), workflow)
    stage_step = (execution.get("steps") or {}).get("stage_reconciliation") or {}
    stage = Path(str(stage_step.get("staging_workspace") or ""))
    parent = (workspace / service.WRITE_STAGING_DIR).resolve()
    if stage.is_symlink() or not stage.is_dir() or stage.resolve() == parent or not stage.resolve().is_relative_to(parent):
        raise ValueError("缺少本任务受控暂存目录，不能确认放弃范围。")
    manifest_path = stage / "execution-manifest.json"
    _file_hash(manifest_path, stage)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest != stage_step.get("manifest") or manifest.get("workflow_id") != workflow.id
            or manifest.get("material_set_id") != material.id or not manifest.get("files")):
        raise ValueError("暂存清单与本任务材料不一致。")
    for relative, expected in manifest["files"].items():
        if _file_hash(workspace / relative, workspace) != expected:
            raise ValueError("任务写入前工作副本已变化，不能放弃。")
    process_hashes, process_stops = _process_proof(workflow, context)
    staged = {}
    for path in sorted(stage.rglob("*")):
        if path.is_symlink():
            raise ValueError("暂存目录含链接，不能封存。")
        if path.is_file():
            staged[path.relative_to(stage).as_posix()] = _file_hash(path, stage)
    if not staged:
        raise ValueError("暂存内容缺失，不能封存。")
    if workflow.batch_id:
        for other in workflow.batch.workflows:
            if other.id == workflow.id or other.state in {"succeeded", "failed", "cancelled"}:
                continue
            if other.state != "queued" or other.actions or any(key in json.loads(other.context_json or "{}") for key in ("ar_execution", "workspace")):
                raise ValueError("批次另有已启动日期，不能放弃本日结果。")
    return {"binding": binding(workflow, context), "material_version": material.version,
            "material_hashes": material_hashes, "process_hashes": process_hashes,
            "process_stop_evidence_v2": process_stops,
            "process_binding_sha256": _process_evidence_binding(workflow, context, _process_actions(workflow, context)),
            "staged_hashes": staged, "staging_workspace": str(stage),
            "actions": _action_snapshot(actions)}


def abandonment_status(db, workflow):
    if is_abandoned(workflow):
        verified = has_verified_abandonment_stop(workflow)
        return {"allowed": False, "abandoned": True, "needs_investigation": not verified,
                "reason": MESSAGE if verified else "历史未发布结果已封存，但完整执行停止证明不足；材料占用仍须调查，不能据此新建冲突任务。",
                "checkpoint_fingerprint": ""}
    try:
        proof = _inspect(db, workflow)
        return {"allowed": True, "abandoned": False, "reason":
                "可放弃本日未发布结果；保留此前成功日期的材料、失败记录和暂存证据。后续日期将取消，旧任务不再恢复。",
                "checkpoint_fingerprint": digest(proof), "material_version": proof["material_version"]}
    except (ValueError, OSError, TypeError, KeyError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else "材料或暂存证据无法核验，不能放弃结果。"
        return {"allowed": False, "abandoned": False, "reason": reason, "checkpoint_fingerprint": ""}


def abandon(db, workflow, request, actor):
    from . import workflow_service as service
    from .scheduler import acquire_claim_lock
    from .resource_policy import assert_owner

    db.commit()
    acquire_claim_lock(db)
    db.refresh(workflow)
    db.expire(workflow, ["actions"])
    assert_owner(workflow.owner_id, actor, "核销任务", workflow.department_id)
    actor = service.refresh_active_user(db, actor)
    service.assert_skill_permission(db, actor, workflow.skill_id)
    service.workflow_owner_context(db, workflow)
    if is_abandoned(workflow):
        return abandonment_status(db, workflow)
    service._assert_single_flight_available(db, workflow.skill_id, exclude_workflow_id=workflow.id,
                                           exclude_batch_id=workflow.batch_id or "")
    try:
        proof = _inspect(db, workflow)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        raise HTTPException(409, "放弃条件已变化或证据不完整，请刷新检查结果。") from exc
    if digest(proof) != request.checkpoint_fingerprint:
        raise HTTPException(409, "材料或暂存检查点已变化，请刷新后再操作。")
    context = json.loads(workflow.context_json or "{}")
    context[KEY] = {"schema_version": "ar-abandonment-v1", "state": "abandoned",
                    "binding": proof["binding"], "proof": proof,
                    "at": datetime.now(UTC).isoformat(), "actor_id": actor.user_id}
    context["stop_after_action"] = True
    workflow.context_json = json.dumps(context, ensure_ascii=False)
    workflow.progress_message = MESSAGE
    if workflow.batch_id:
        batch = workflow.batch
        for other in batch.workflows:
            if other.id != workflow.id and other.state == "queued":
                other.state, other.stage = "cancelled", "cancelled"
                other.progress_message = "前序失败日期已放弃未发布结果，后续日期未执行。"
        batch.state = "cancelled"
        batch.progress_message = MESSAGE
    service.record_audit(db, actor=actor, action="workflow.ar_execution.abandon", resource_type="workflow",
                         resource_id=workflow.id, details={"material_version": proof["material_version"],
                         "checkpoint_fingerprint": request.checkpoint_fingerprint,
                         "staged_file_count": len(proof["staged_hashes"])})
    db.commit()
    return abandonment_status(db, workflow)
