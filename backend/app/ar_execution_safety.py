"""Durable per-attempt facts for AR phases that can change business material.

This records intent, verified completion, and unresolved material occupancy.
An intent without a completion fact must never imply no effect.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from types import SimpleNamespace

from .ar_execution_contract import INVESTIGATION_ACTION


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



PROCESS_OBSERVATION_PHASE = "build_initial_report"
PROCESS_OBSERVATION_SCRIPT = "build_worklist.py"
PROCESS_OBSERVATION_NAMESPACE = "process_observations"
PROCESS_OBSERVATION_SCHEMA = "ar-process-observations-v1"
PROCESS_OBSERVATION_SCHEMA_V2 = "ar-process-observations-v2"
PROCESS_OBSERVATION_SCHEMA_V3 = "ar-process-observations-v3"
PROCESS_OBSERVATION_SCRIPTS = {
    PROCESS_OBSERVATION_PHASE: PROCESS_OBSERVATION_SCRIPT,
    "rescan_holds": "rescan_execution_holds.py",
    INVESTIGATION_ACTION: "investigate_failed_write.py",
}
PROCESS_OBSERVATION_ACTIONS = {phase: (phase if phase == INVESTIGATION_ACTION else "ar_" + phase)
                               for phase in PROCESS_OBSERVATION_SCRIPTS}
RESCAN_INPUT_BINDING_FIELDS = frozenset({
    "staging_workspace_sha256", "manifest_sha256", "staged_plan_sha256",
    "initial_result_sha256", "reviewed_result_sha256", "arguments_sha256",
})


INVESTIGATION_INPUT_BINDING_FIELDS = frozenset({
    "staging_workspace_sha256", "manifest_sha256", "staged_plan_sha256",
    "request_sha256", "failed_action_binding_sha256", "workbook_inputs_sha256", "arguments_sha256",
})


def _valid_rescan_input_binding(value) -> bool:
    return (isinstance(value, dict) and set(value) == RESCAN_INPUT_BINDING_FIELDS
            and all(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
                    for digest in value.values()))


def _valid_investigation_input_binding(value) -> bool:
    return (isinstance(value, dict) and set(value) == INVESTIGATION_INPUT_BINDING_FIELDS
            and all(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
                    for digest in value.values()))


def _process_state(context: dict, workflow_id: str | None = None, *, observation=False) -> dict:
    """Select the one server-owned observation partition; effect is the default."""
    outer = _state(context, workflow_id)
    if not observation:
        return outer
    state = outer.get(PROCESS_OBSERVATION_NAMESPACE)
    if state is None and PROCESS_OBSERVATION_NAMESPACE not in outer:
        return {"schema_version": PROCESS_OBSERVATION_SCHEMA, "revision": 0, "attempts": []}
    if (not isinstance(state, dict) or set(state) != {"schema_version", "revision", "attempts"}
            or state["schema_version"] not in {PROCESS_OBSERVATION_SCHEMA, PROCESS_OBSERVATION_SCHEMA_V2, PROCESS_OBSERVATION_SCHEMA_V3}
            or type(state["revision"]) is not int or state["revision"] < 0
            or not isinstance(state["attempts"], list) or len(state["attempts"]) > MAX_ATTEMPTS):
        raise ValueError("首次日清原进程观察分区无效，禁止继续登记。")
    seen = set()
    for entry in state["attempts"]:
        phase = entry.get("phase") if isinstance(entry, dict) else None
        rescan = phase == "rescan_holds"
        investigation = phase == INVESTIGATION_ACTION
        binding_fields = (*BINDING_FIELDS, "input_binding") if rescan or investigation else BINDING_FIELDS
        fields = set(binding_fields) | {"binding_sha256", "intent_at", "prepared_process_refs", "terminal_process_refs"}
        if (not isinstance(entry, dict) or set(entry) != fields
                or any(not isinstance(entry.get(key), str) or not entry[key] or len(entry[key]) > 255
                       for key in set(BINDING_FIELDS) - {"attempt", "material_version"})
                or type(entry.get("attempt")) is not int or entry["attempt"] < 1
                or type(entry.get("material_version")) is not int or entry["material_version"] < 1
                or phase not in PROCESS_OBSERVATION_SCRIPTS
                or (state["schema_version"] == PROCESS_OBSERVATION_SCHEMA and phase != PROCESS_OBSERVATION_PHASE)
                or (investigation and (state["schema_version"] != PROCESS_OBSERVATION_SCHEMA_V3
                                      or not _valid_investigation_input_binding(entry.get("input_binding"))))
                or (rescan and not _valid_rescan_input_binding(entry.get("input_binding")))
                or (workflow_id is not None and entry.get("workflow_id") != workflow_id)
                or (entry["action_id"], entry["attempt"]) in seen
                or any(not isinstance(entry.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", entry[key])
                       for key in ("skill_hash", "plan_fingerprint", "workspace_sha256", "binding_sha256"))
                or entry["binding_sha256"] != hashlib.sha256(_canonical({key: entry[key] for key in binding_fields})).hexdigest()
                or not isinstance(entry["prepared_process_refs"], list) or len(entry["prepared_process_refs"]) > 1
                or not isinstance(entry["terminal_process_refs"], list)):
            raise ValueError("首次日清原进程观察身份或绑定无效，禁止继续登记。")
        try:
            stamp = entry["intent_at"]
            if not isinstance(stamp, str) or len(stamp) > 64:
                raise ValueError
            parsed = datetime.fromisoformat(stamp)
            if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
                raise ValueError
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("首次日清原进程观察时间无效。") from exc
        for ref in entry["prepared_process_refs"]:
            if isinstance(ref, dict) and (not isinstance(ref.get("registered_at"), str)
                    or len(ref["registered_at"]) > 64):
                raise ValueError("首次日清原进程准备登记时间无效。")
        seen.add((entry["action_id"], entry["attempt"]))
    refs = _prepared_process_refs(state)
    effect_ids = {ref["record_id"] for _, ref in _prepared_process_refs(outer)}
    if any(ref["script"] != PROCESS_OBSERVATION_SCRIPTS[entry["phase"]]
            or ref["record_id"] in effect_ids for entry, ref in refs):
        raise ValueError("首次日清原进程准备引用与原脚本或分区冲突。")
    for entry in state["attempts"]:
        _terminal_process_refs(entry)
    return state


def _store_process_state(context: dict, state: dict, *, observation=False) -> None:
    if observation:
        outer = _state(context)
        outer[PROCESS_OBSERVATION_NAMESPACE] = state
        context["execution_safety_v1"] = outer
    else:
        context["execution_safety_v1"] = state


def register_process_observation_intent(context: dict, workflow, action, *, input_binding=None) -> dict:
    """Record a fixed existing-plan caller at its phase-owned commit."""
    phase = action.name.removeprefix("ar_")
    if (not isinstance(context, dict) or action.workflow_id != workflow.id
            or action.name != PROCESS_OBSERVATION_ACTIONS.get(phase) or action.state != "running"
            or type(action.attempt_count) is not int or action.attempt_count <= 0 or not action.worker_id):
        raise ValueError("首次日清动作与原观察绑定不一致。")
    execution = context.get("ar_execution")
    if not isinstance(execution, dict) or not isinstance(context.get("workspace"), str):
        raise ValueError("首次日清原材料或计划绑定不完整。")
    if ((phase == "rescan_holds" and not _valid_rescan_input_binding(input_binding))
            or (phase == INVESTIGATION_ACTION and not _valid_investigation_input_binding(input_binding))
            or (phase == PROCESS_OBSERVATION_PHASE and input_binding is not None)):
        raise ValueError("核销原进程观察的阶段输入绑定无效。")
    state = _process_state(context, workflow.id, observation=True)
    if len(state["attempts"]) >= MAX_ATTEMPTS or any(
            entry["action_id"] == action.id and entry["attempt"] == action.attempt_count for entry in state["attempts"]):
        raise ValueError("首次日清原观察意图重复或超过记录上限。")
    binding = {
        "workflow_id": workflow.id, "action_id": action.id, "attempt": action.attempt_count,
        "phase": phase, "worker_id": action.worker_id,
        "owner_id": workflow.owner_id, "department_id": workflow.department_id,
        "skill_id": workflow.skill_id, "skill_hash": workflow.skill_hash,
        "material_set_id": execution.get("material_set_id"), "material_version": execution.get("material_version"),
        "reconciliation_date": workflow.reconciliation_date, "plan_fingerprint": context.get("plan_fingerprint"),
        "workspace_sha256": hashlib.sha256(context["workspace"].encode("utf-8")).hexdigest(),
    }
    if phase in {"rescan_holds", INVESTIGATION_ACTION}:
        binding["input_binding"] = dict(input_binding)
        if phase == INVESTIGATION_ACTION:
            state["schema_version"] = PROCESS_OBSERVATION_SCHEMA_V3
        elif state["schema_version"] != PROCESS_OBSERVATION_SCHEMA_V3:
            state["schema_version"] = PROCESS_OBSERVATION_SCHEMA_V2
    state["attempts"].append({**binding, "binding_sha256": hashlib.sha256(_canonical(binding)).hexdigest(),
        "intent_at": datetime.now(UTC).isoformat(), "prepared_process_refs": [], "terminal_process_refs": []})
    state["revision"] += 1
    _store_process_state(context, state, observation=True)
    _process_state(context, workflow.id, observation=True)
    return context


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


def _prepared_process_refs(state: dict) -> list[tuple[dict, dict]]:
    from .ar_process_evidence import SCHEMA_VERSION as EVIDENCE_VERSION
    from .ar_process_inspection import MAX_RECORDS

    fields = {"schema_version", "record_id", "prepared_sha256", "script",
              "script_sha256", "arguments_sha256", "binding_sha256", "registered_at"}
    seen = set()
    result = []
    counts = {}
    for entry in state["attempts"]:
        refs = entry.get("prepared_process_refs", [])
        if not isinstance(refs, list) or len(refs) > MAX_RECORDS:
            raise ValueError("核销进程准备引用格式或数量无效。")
        counts[entry["action_id"]] = counts.get(entry["action_id"], 0) + len(refs)
        if counts[entry["action_id"]] > MAX_RECORDS:
            raise ValueError("核销动作进程引用超过记录上限。")
        for ref in refs:
            if (not isinstance(ref, dict) or set(ref) != fields
                    or ref.get("schema_version") != EVIDENCE_VERSION
                    or not isinstance(ref.get("record_id"), str)
                    or len(ref["record_id"]) != 32
                    or any(char not in "0123456789abcdef" for char in ref["record_id"])
                    or ref["record_id"] in seen
                    or not isinstance(ref.get("script"), str) or not ref["script"]
                    or len(ref["script"]) > 255 or not re.fullmatch(r"[a-z_]+\.py", ref["script"])
                    or ref.get("binding_sha256") != entry["binding_sha256"]):
                raise ValueError("核销进程准备引用身份或绑定无效。")
            for field in ("prepared_sha256", "script_sha256", "arguments_sha256", "binding_sha256"):
                value = ref.get(field)
                if (not isinstance(value, str) or len(value) != 64
                        or any(char not in "0123456789abcdef" for char in value)):
                    raise ValueError("核销进程准备引用摘要无效。")
            try:
                stamp = datetime.fromisoformat(ref["registered_at"])
                if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
                    raise ValueError("核销进程准备引用时间无效。")
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError("核销进程准备引用时间无效。") from exc
            seen.add(ref["record_id"])
            result.append((entry, ref))
    return result


def register_prepared_process_ref(context: dict, entry: dict, anchor, *, observation=False) -> dict:
    from .ar_process_evidence import SCHEMA_VERSION as EVIDENCE_VERSION
    from .ar_process_inspection import MAX_RECORDS

    state = _process_state(context, entry["workflow_id"], observation=observation)
    refs = _prepared_process_refs(state)
    if observation and (anchor.script != PROCESS_OBSERVATION_SCRIPTS[entry["phase"]] or entry["prepared_process_refs"]
            or (entry["phase"] != PROCESS_OBSERVATION_PHASE and anchor.arguments_sha256 != entry["input_binding"]["arguments_sha256"])
            or any(ref["record_id"] == anchor.record_id for _, ref in _prepared_process_refs(_state(context)))):
        raise ValueError("首次日清原准备引用重复或分区冲突，禁止再次启动。")
    if any(ref["record_id"] == anchor.record_id for _, ref in refs):
        raise ValueError("核销进程准备引用已登记，禁止再次启动。")
    if sum(item["action_id"] == entry["action_id"] for item, _ in refs) >= MAX_RECORDS:
        raise ValueError("核销动作进程引用达到记录上限。")
    ref = {
        "schema_version": EVIDENCE_VERSION, "record_id": anchor.record_id,
        "prepared_sha256": anchor.prepared_sha256, "script": anchor.script,
        "script_sha256": anchor.script_sha256, "arguments_sha256": anchor.arguments_sha256,
        "binding_sha256": entry["binding_sha256"], "registered_at": datetime.now(UTC).isoformat(),
    }
    entry.setdefault("prepared_process_refs", []).append(ref)
    _prepared_process_refs(state)
    state["revision"] += 1
    _store_process_state(context, state, observation=observation)
    return ref


def _terminal_process_refs(entry: dict) -> list[dict]:
    from .ar_process_evidence import SCHEMA_VERSION as EVIDENCE_VERSION

    fields = {"schema_version", "record_id", "prepared_sha256", "script", "started_sha256",
              "exit_sha256", "domain_exit_sha256", "terminal_state", "binding_sha256", "registered_at"}
    anchors = {ref["record_id"]: ref for ref in entry.get("prepared_process_refs", [])}
    refs = entry.get("terminal_process_refs", [])
    if not isinstance(refs, list) or len(refs) > len(anchors):
        raise ValueError("原进程终态引用数量或格式无效。")
    seen = set()
    for ref in refs:
        if (not isinstance(ref, dict) or set(ref) != fields
                or ref.get("schema_version") != EVIDENCE_VERSION
                or not isinstance(ref.get("record_id"), str) or ref["record_id"] not in anchors
                or ref["record_id"] in seen
                or ref.get("terminal_state") not in {"exited", "exit_unconfirmed", "launch_unconfirmed"}):
            raise ValueError("原进程终态引用身份或格式无效。")
        anchor = anchors[ref["record_id"]]
        if any(type(ref.get(key)) is not type(anchor[key]) or ref[key] != anchor[key]
               for key in ("prepared_sha256", "script", "binding_sha256")):
            raise ValueError("原进程终态引用与准备锚点不一致。")
        for key in ("started_sha256", "exit_sha256", "domain_exit_sha256"):
            value = ref[key]
            if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)):
                raise ValueError("原进程终态指纹无效。")
        value = ref["registered_at"]
        try:
            if not isinstance(value, str) or len(value) > 64:
                raise ValueError("原进程终态登记时间无效。")
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
                raise ValueError("原进程终态登记时间无效。")
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("原进程终态登记时间无效。") from exc
        seen.add(ref["record_id"])
    return refs


def register_terminal_process_ref(context: dict, anchor, observation, *, process_observation=False) -> tuple[dict, dict, bool]:
    from .ar_process_evidence import (PREPARED_IDENTITY_FIELDS, SCHEMA_VERSION as EVIDENCE_VERSION,
                                     TerminalProcessObservation, TerminalProcessRegistrationError)

    identity = dict(anchor.prepared_identity)
    if (type(anchor.prepared_identity) is not tuple or len(anchor.prepared_identity) != len(PREPARED_IDENTITY_FIELDS)
            or set(identity) != set(PREPARED_IDENTITY_FIELDS) or anchor.schema_version != EVIDENCE_VERSION
            or not isinstance(anchor.binding_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", anchor.binding_sha256)
            or type(observation) is not TerminalProcessObservation):
        raise TerminalProcessRegistrationError("terminal_binding_invalid")
    state = _process_state(context, identity["workflow_id"], observation=process_observation)
    _prepared_process_refs(state)
    matches = []
    for entry in state["attempts"]:
        expected = {"action_name": (PROCESS_OBSERVATION_ACTIONS[entry["phase"]] if process_observation else "ar_" + entry["phase"]),
                    **{key: entry[key] for key in PREPARED_IDENTITY_FIELDS if key != "action_name"}}
        if (entry["binding_sha256"] == anchor.binding_sha256
                and all(type(identity[key]) is type(expected[key]) and identity[key] == expected[key]
                        for key in PREPARED_IDENTITY_FIELDS)):
            matches.append(entry)
    if len(matches) != 1:
        raise TerminalProcessRegistrationError("terminal_binding_invalid")
    entry = matches[0]
    prepared = [ref for ref in entry.get("prepared_process_refs", []) if ref["record_id"] == anchor.record_id]
    if len(prepared) != 1 or any(type(prepared[0][key]) is not type(value) or prepared[0][key] != value
            for key, value in {"prepared_sha256": anchor.prepared_sha256, "script": anchor.script,
                "script_sha256": anchor.script_sha256, "arguments_sha256": anchor.arguments_sha256,
                "binding_sha256": anchor.binding_sha256}.items()):
        raise TerminalProcessRegistrationError("terminal_binding_invalid")
    ref = {"schema_version": EVIDENCE_VERSION, "record_id": anchor.record_id,
           "prepared_sha256": anchor.prepared_sha256, "script": anchor.script,
           "started_sha256": observation.started_sha256, "exit_sha256": observation.exit_sha256,
           "domain_exit_sha256": observation.domain_exit_sha256, "terminal_state": observation.terminal_state,
           "binding_sha256": anchor.binding_sha256, "registered_at": datetime.now(UTC).isoformat()}
    try:
        existing = _terminal_process_refs(entry)
        candidate = {**entry, "terminal_process_refs": [ref]}
        _terminal_process_refs(candidate)
    except ValueError as exc:
        raise TerminalProcessRegistrationError("terminal_ref_conflict") from exc
    for prior in existing:
        if prior["record_id"] == anchor.record_id:
            if _canonical({key: value for key, value in prior.items() if key != "registered_at"}) != _canonical(
                    {key: value for key, value in ref.items() if key != "registered_at"}):
                raise TerminalProcessRegistrationError("terminal_ref_conflict")
            return entry, prior, False
    entry.setdefault("terminal_process_refs", []).append(ref)
    state["revision"] += 1
    _store_process_state(context, state, observation=process_observation)
    return entry, ref, True


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
