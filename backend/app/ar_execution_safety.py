"""Durable per-attempt facts for AR phases that can change business material.

This records intent, verified completion, and unresolved material occupancy.
An intent without a completion fact must never imply no effect.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace


SCHEMA_VERSION = "ar-execution-safety-v1"
EFFECT_PHASES = frozenset({
    "write_ledger", "write_receipt_flow", "publish_reconciliation",
    "complete_reconciliation",
})
MAX_ATTEMPTS = 128
MAX_WORKFLOW_SCAN = 2048


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


BINDING_FIELDS = (
    "workflow_id", "action_id", "attempt", "phase", "worker_id", "owner_id",
    "department_id", "skill_id", "skill_hash", "material_set_id", "material_version",
    "reconciliation_date", "plan_fingerprint", "workspace_sha256",
)


def _validate_entry(entry: dict, workflow_id: str | None) -> None:
    """Check persisted identity, not just the presence of an action/attempt pair.

    The digest detects inconsistent records; it is not an authorization token.
    Historical records without this index retain their existing recovery path.
    """
    strings = set(BINDING_FIELDS) - {"attempt", "material_version"}
    if (any(not isinstance(entry.get(key), str) or not entry[key] for key in strings)
            or type(entry.get("material_version")) is not int or entry["material_version"] < 1
            or entry.get("phase") not in EFFECT_PHASES
            or entry.get("status") not in {"intent_recorded", "phase_completed"}
            or (workflow_id is not None and entry.get("workflow_id") != workflow_id)
            or not isinstance(entry.get("intent_at"), str) or not entry["intent_at"]):
        raise ValueError("核销执行安全索引的身份或阶段无效，禁止继续写入。")
    binding = {key: entry[key] for key in BINDING_FIELDS}
    if entry.get("binding_sha256") != hashlib.sha256(_canonical(binding)).hexdigest():
        raise ValueError("核销执行安全索引的绑定摘要不一致，禁止继续写入。")
    if entry["status"] == "phase_completed":
        digest = entry.get("result_sha256")
        if (not isinstance(entry.get("completed_at"), str) or not entry["completed_at"]
                or not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise ValueError("核销执行安全索引缺少完整的完成事实，禁止继续写入。")


def _state(context: dict, workflow_id: str | None = None) -> dict:
    value = context.get("execution_safety_v1")
    if value is None:
        return {"schema_version": SCHEMA_VERSION, "revision": 0, "attempts": []}
    if (not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION
            or type(value.get("revision")) is not int or value["revision"] < 0
            or not isinstance(value.get("attempts"), list)
            or len(value["attempts"]) > MAX_ATTEMPTS):
        raise ValueError("核销执行安全索引无效，禁止继续写入。")
    seen = set()
    for entry in value["attempts"]:
        if (not isinstance(entry, dict) or not isinstance(entry.get("action_id"), str)
                or type(entry.get("attempt")) is not int or entry["attempt"] <= 0
                or (entry["action_id"], entry["attempt"]) in seen):
            raise ValueError("核销执行安全索引存在重复或无效动作，禁止继续写入。")
        _validate_entry(entry, workflow_id)
        seen.add((entry["action_id"], entry["attempt"]))
    return value


def register_effect_intent(context: dict, workflow, action, phase: str) -> dict:
    """Append intent before the phase handler can start a child or publish."""
    if phase not in EFFECT_PHASES:
        return context
    if (not isinstance(context, dict) or action.workflow_id != workflow.id
            or action.name != "ar_" + phase or action.state != "running"
            or type(action.attempt_count) is not int or action.attempt_count <= 0
            or not action.worker_id):
        raise ValueError("核销写入动作与启动意图绑定不一致。")
    execution = context.get("ar_execution")
    if (not isinstance(execution, dict) or not isinstance(execution.get("material_set_id"), str)
            or type(execution.get("material_version")) is not int
            or not isinstance(context.get("workspace"), str)
            or not isinstance(context.get("plan_fingerprint"), str)):
        raise ValueError("核销写入材料或计划绑定不完整。")
    state = _state(context, workflow.id)
    if len(state["attempts"]) >= MAX_ATTEMPTS or any(
        item["action_id"] == action.id and item["attempt"] == action.attempt_count
        for item in state["attempts"]
    ):
        raise ValueError("核销写入动作启动意图重复或超过记录上限。")
    binding = {
        "workflow_id": workflow.id, "action_id": action.id,
        "attempt": action.attempt_count, "phase": phase,
        "worker_id": action.worker_id, "owner_id": workflow.owner_id,
        "department_id": workflow.department_id, "skill_id": workflow.skill_id,
        "skill_hash": workflow.skill_hash,
        "material_set_id": execution["material_set_id"],
        "material_version": execution["material_version"],
        "reconciliation_date": workflow.reconciliation_date,
        "plan_fingerprint": context["plan_fingerprint"],
        "workspace_sha256": hashlib.sha256(context["workspace"].encode("utf-8")).hexdigest(),
    }
    entry = {
        **binding,
        "binding_sha256": hashlib.sha256(_canonical(binding)).hexdigest(),
        "status": "intent_recorded", "intent_at": datetime.now(UTC).isoformat(),
    }
    _validate_entry(entry, workflow.id)
    state["attempts"].append(entry)
    state["revision"] += 1
    context["execution_safety_v1"] = state
    return context


def record_effect_completion(context: dict, action, phase: str, result: dict) -> dict:
    """Record a checkpoint after the phase result passed its existing checks."""
    if phase not in EFFECT_PHASES:
        return context
    state = _state(context, action.workflow_id)
    matches = [item for item in state["attempts"] if item["action_id"] == action.id
               and item["attempt"] == action.attempt_count and item["phase"] == phase]
    if len(matches) != 1 or matches[0].get("status") != "intent_recorded":
        raise ValueError("核销写入完成事实缺少唯一的启动意图。")
    if not isinstance(result, dict):
        raise ValueError("核销写入完成事实缺少阶段结果。")
    entry = matches[0]
    if action.name != "ar_" + phase or action.worker_id != entry["worker_id"]:
        raise ValueError("核销完成事实与启动时的执行者或阶段不一致。")
    entry.update(status="phase_completed", completed_at=datetime.now(UTC).isoformat(),
                 result_sha256=hashlib.sha256(_canonical(result)).hexdigest())
    state["revision"] += 1
    context["execution_safety_v1"] = state
    return context


def _has_unresolved_effect(workflow) -> bool:
    try:
        context = json.loads(workflow.context_json or "{}")
        if not isinstance(context, dict):
            return True
        from .ar_abandon import is_abandoned, has_verified_abandonment_stop
        if is_abandoned(workflow, context):
            return not has_verified_abandonment_stop(workflow, context)
        execution = context.get("ar_execution") or {}
        if not isinstance(execution, dict):
            return True
        completed = execution.get("completed") or []
        if not isinstance(completed, list):
            return True
        state = _state(context, workflow.id)
        if any(entry.get("workflow_id") == workflow.id and entry.get("status") == "intent_recorded"
               for entry in state["attempts"]):
            return True
        # Publication has changed the authoritative workbooks, but the date
        # remains unresolved until its separate formal-ledger registration.
        if execution.get("publication") == "verified":
            return not ("complete_reconciliation" in completed and context.get("formal_ledgers"))
        if any(phase in completed for phase in ("write_ledger", "write_receipt_flow")):
            return True
        return any(action.name.removeprefix("ar_") in EFFECT_PHASES
                   and action.state in {"running", "failed", "cancelled"}
                   and action.attempt_count > 0 for action in workflow.actions)
    except (ValueError, TypeError, KeyError, AttributeError):
        return True


def has_effect_history(workflow) -> bool:
    """A reset must not erase evidence after any AR side-effect attempt."""
    try:
        context = json.loads(workflow.context_json or "{}")
        if not isinstance(context, dict):
            return True
        execution = context.get("ar_execution") or {}
        if not isinstance(execution, dict):
            return True
        completed = execution.get("completed") or []
        if not isinstance(completed, list):
            return True
        if any(phase in completed for phase in EFFECT_PHASES) or execution.get("publication") == "verified":
            return True
        if _state(context, workflow.id)["attempts"]:
            return True
        failure = context.get("ar_failure") or {}
        if isinstance(failure, dict) and failure.get("phase") in EFFECT_PHASES:
            return True
        return any(action.name.removeprefix("ar_") in EFFECT_PHASES
                   and action.attempt_count > 0 for action in workflow.actions)
    except (ValueError, TypeError, KeyError, AttributeError):
        return True


def current_material_blocker(db, owner_id: str, department_id: str, skill_id: str, *,
                             exclude_workflow_id: str = "", exclude_batch_id: str = "") -> dict | None:
    """Find unresolved effect on the exact current material scope; fail closed on truncation."""
    from sqlalchemy import or_, select

    from .ar_skill_identity import AR_SKILL_IDS, is_ar_skill
    from .models import FileRecord, WorkflowAction, WorkflowMaterialSet, WorkflowMaterialSetFile, WorkflowSession

    if not is_ar_skill(skill_id):
        return None
    if not owner_id or not department_id:
        return {"reason": "scope_missing"}
    current = db.execute(select(WorkflowMaterialSet.id, WorkflowMaterialSet.version,
        WorkflowMaterialSet.source_workflow_id).where(
        WorkflowMaterialSet.owner_id == owner_id,
        WorkflowMaterialSet.department_id == department_id,
        WorkflowMaterialSet.skill_id == skill_id,
        WorkflowMaterialSet.state == "current",
    )).first()
    if current is None:
        return None
    # Different AR Skill aliases are independent unless they reference the
    # same writable FileRecord. Equal content hashes on separate files do not
    # imply shared output paths.
    shared_set_ids = {current.id}
    file_ids = set(db.scalars(select(WorkflowMaterialSetFile.file_id).where(
        WorkflowMaterialSetFile.material_set_id == current.id)).all())
    if file_ids:
        # One physical workbook can have more than one FileRecord ID.
        # Equal hashes on separate paths remain independent.
        current_files = db.execute(select(FileRecord.id, FileRecord.stored_path).where(
            FileRecord.id.in_(file_ids), FileRecord.owner_id == owner_id,
            FileRecord.department_id == department_id).limit(MAX_WORKFLOW_SCAN + 1)).all()
        if len(current_files) != len(file_ids) or any(not path for _, path in current_files):
            return {"reason": "material_file_identity_incomplete"}
        paths = {path for _, path in current_files}
        linked = db.scalars(select(WorkflowMaterialSetFile.material_set_id)
            .join(WorkflowMaterialSet, WorkflowMaterialSet.id == WorkflowMaterialSetFile.material_set_id)
            .join(FileRecord, FileRecord.id == WorkflowMaterialSetFile.file_id)
            .where(WorkflowMaterialSet.owner_id == owner_id,
                   WorkflowMaterialSet.department_id == department_id,
                   WorkflowMaterialSet.skill_id.in_(AR_SKILL_IDS),
                   or_(WorkflowMaterialSetFile.file_id.in_(file_ids),
                       FileRecord.stored_path.in_(paths)))
            .distinct().limit(MAX_WORKFLOW_SCAN + 1)).all()
        if len(linked) > MAX_WORKFLOW_SCAN:
            return {"reason": "shared_material_scan_incomplete"}
        shared_set_ids.update(linked)
    # Column projections bypass stale ORM identity-map objects without expiring
    # or overwriting the caller's pending changes.
    columns = (WorkflowSession.id, WorkflowSession.owner_id, WorkflowSession.department_id,
               WorkflowSession.skill_id, WorkflowSession.skill_hash, WorkflowSession.reconciliation_date,
               WorkflowSession.material_set_id, WorkflowSession.batch_id,
               WorkflowSession.display_id, WorkflowSession.context_json)
    rows = db.execute(select(*columns).where(
        WorkflowSession.owner_id == owner_id,
        WorkflowSession.department_id == department_id,
        WorkflowSession.skill_id.in_(AR_SKILL_IDS),
    ).order_by(WorkflowSession.created_at, WorkflowSession.id).limit(MAX_WORKFLOW_SCAN + 1)).all()
    if len(rows) > MAX_WORKFLOW_SCAN:
        return {"reason": "scan_incomplete"}
    for row in rows:
        workflow = SimpleNamespace(**dict(row._mapping))
        if workflow.id == exclude_workflow_id or (exclude_batch_id and workflow.batch_id == exclude_batch_id):
            continue
        try:
            context = json.loads(workflow.context_json or "{}")
            execution = context.get("ar_execution") or {}
            steps = execution.get("steps") or {}
            publication = (steps.get("publish_reconciliation") or {}) if isinstance(steps, dict) else {}
            source_ids = {execution.get("material_set_id"), workflow.material_set_id}
            if isinstance(publication, dict):
                source_ids.add(publication.get("material_set_id"))
        except (ValueError, TypeError, AttributeError):
            source_ids = {workflow.material_set_id}
        if current.source_workflow_id == workflow.id:
            source_ids.add(current.id)
        if source_ids & shared_set_ids:
            actions = db.execute(select(WorkflowAction.id, WorkflowAction.workflow_id, WorkflowAction.name,
                WorkflowAction.state, WorkflowAction.attempt_count, WorkflowAction.worker_id,
                WorkflowAction.started_at, WorkflowAction.finished_at, WorkflowAction.result_json).where(WorkflowAction.workflow_id == workflow.id)
                .limit(MAX_WORKFLOW_SCAN + 1)).all()
            if len(actions) > MAX_WORKFLOW_SCAN:
                return {"reason": "action_scan_incomplete"}
            workflow.actions = actions
            if _has_unresolved_effect(workflow):
                return {"reason": "unresolved_write", "workflow_id": workflow.id,
                        "display_id": workflow.display_id or workflow.id,
                        "material_set_id": current.id, "material_version": current.version}
    return None


MATERIAL_OPERATIONS = frozenset({
    "create_run", "replace_materials", "continue_batch", "resume_phase",
    "claim_action", "publish", "complete_registration",
})
CONTINUATION_OPERATIONS = frozenset({
    "resume_phase", "claim_action", "publish", "complete_registration",
})
ACTIVE_MATERIAL_MESSAGE = "当前有任务正在进行，任务材料已锁定；任务结束后可选择、替换或恢复材料。"
UNRESOLVED_MATERIAL_MESSAGE = (
    "当前材料存在未核清的核销写入或暂存结果，请先恢复原任务或调查处置；不能进行冲突操作。"
)
INCOMPLETE_MATERIAL_MESSAGE = "当前材料的核销占用记录无法完整核查，请联系管理员处理后再操作。"


class MaterialOccupancyConflict(ValueError):
    def __init__(self, view: dict):
        super().__init__(view["message"])
        self.view = view


def _active_material_blocker(db, owner_id, department_id, skill_id):
    from sqlalchemy import select
    from .models import WorkflowAction, WorkflowBatch, WorkflowSession

    terminal = ("succeeded", "failed", "cancelled")
    scope = dict(owner_id=owner_id, department_id=department_id, skill_id=skill_id)
    batch = db.scalar(select(WorkflowBatch.id).filter_by(**scope)
        .where(WorkflowBatch.state.not_in(terminal)).limit(1))
    single = db.scalar(select(WorkflowSession.id).filter_by(**scope).where(
        WorkflowSession.batch_id.is_(None), WorkflowSession.state.not_in(terminal),
        WorkflowSession.stage.not_in(("awaiting_date", "awaiting_date_confirmation", "awaiting_files"))).limit(1))
    action = db.scalar(select(WorkflowAction.id).join(WorkflowSession).where(
        WorkflowSession.owner_id == owner_id, WorkflowSession.department_id == department_id,
        WorkflowSession.skill_id == skill_id, WorkflowAction.state.in_(("queued", "running"))).limit(1))
    return {"reason": "active_task"} if batch or single or action else None


def _blocking_execution_view(db, blocker):
    """Describe persisted effects separately from unobserved process liveness.

    This does not upgrade direct-child exit receipts to full execution-domain
    termination. Recovery remains responsible for live process investigation.
    """
    from sqlalchemy import select
    from .models import WorkflowSession

    workflow_id = blocker.get("workflow_id")
    if not workflow_id:
        return None
    raw = db.scalar(select(WorkflowSession.context_json).where(WorkflowSession.id == workflow_id))
    effect = "unknown"
    revision = None
    try:
        context = json.loads(raw or "{}")
        state = _state(context, workflow_id)
        revision = state["revision"]
        execution = context.get("ar_execution") or {}
        completed = execution.get("completed") or []
        if not isinstance(execution, dict) or not isinstance(completed, list):
            raise ValueError("Invalid execution checkpoint")
        if execution.get("publication") == "verified":
            effect = "published_verified"
        elif any(phase in completed for phase in ("write_ledger", "write_receipt_flow")):
            effect = "candidate_changed"
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    return {"workflow_id": workflow_id, "process_state": "unknown",
            "effect_state": effect, "evidence_revision": revision,
            "process_evidence_scope": "not_observed"}


def get_safety_view(db, owner_id: str, department_id: str, skill_id: str, *,
                    operation: str = "create_run", exclude_workflow_id: str = "") -> dict:
    """Read-only material admission projection, not an execution authorization.

    A free scope has no selected blocking execution (execution=None); it does
    not assert that every historical process was verified never-started/exited.
    Existing permission, single-flight, phase and recovery checks still apply.
    No flush, lock, commit, filesystem mutation or process termination occurs.
    """
    if operation not in MATERIAL_OPERATIONS:
        raise ValueError("此操作尚未接入材料占用策略。")
    if exclude_workflow_id and operation not in CONTINUATION_OPERATIONS:
        raise ValueError("新建、换材料或跨日期继续不能排除已有任务占用。")
    with db.no_autoflush:
        blocker = None
        if operation == "replace_materials":
            blocker = _active_material_blocker(db, owner_id, department_id, skill_id)
        if blocker is None:
            blocker = current_material_blocker(db, owner_id, department_id, skill_id,
                                               exclude_workflow_id=exclude_workflow_id)
        reason = blocker["reason"] if blocker else ""
        execution = _blocking_execution_view(db, blocker) if blocker else None
    message = (ACTIVE_MATERIAL_MESSAGE if reason == "active_task" else
               UNRESOLVED_MATERIAL_MESSAGE if reason == "unresolved_write" else
               INCOMPLETE_MATERIAL_MESSAGE if reason else "")
    return {"schema_version": "ar-material-safety-view-v1", "operation": operation,
            "material_admission_allowed": blocker is None,
            "occupancy_state": "held" if reason == "active_task" else
                               "needs_investigation" if blocker else "free",
            "reason": reason, "message": message, "blocker": blocker,
            "execution": execution}


def assert_operation_allowed(db, owner_id: str, department_id: str, skill_id: str, *,
                             operation: str, exclude_workflow_id: str = "") -> dict:
    """Recompute material admission in the caller's locked transaction.

    No cached/UI view, force flag or caller-supplied process verdict is accepted.
    The caller owns commit/rollback and must not wait for scripts under this lock.
    """
    from .scheduler import acquire_claim_lock

    # Validate arguments before any database changes, including pending flushes.
    if operation not in MATERIAL_OPERATIONS or (exclude_workflow_id and operation not in CONTINUATION_OPERATIONS):
        raise ValueError("材料操作或任务排除范围无效。")
    with db.no_autoflush:
        acquire_claim_lock(db)
    db.flush()
    view = get_safety_view(db, owner_id, department_id, skill_id,
                         operation=operation, exclude_workflow_id=exclude_workflow_id)
    if not view["material_admission_allowed"]:
        raise MaterialOccupancyConflict(view)
    return view
