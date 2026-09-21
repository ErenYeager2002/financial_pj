"""Evidence for retaining an already-finished completion after revocation.

This does not authorize launching a script, claiming a job, publishing materials,
or advancing a batch. The caller must hold its current action lease/claim lock.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from .ar_execution_contract import CONTRACT_VERSION, PHASES
from .ar_process_evidence import SCHEMA_VERSION
from .resource_policy import workflow_root


def require_finished_completion(action, workflow, result: dict) -> str:
    state = (json.loads(workflow.context_json or "{}").get("ar_execution") or {})
    names = [phase.name for phase in PHASES]
    result_state = result.get("ar_execution") or {}
    records = getattr(action, "_ar_process_records", None)
    if (action.name != "ar_complete_reconciliation"
            or getattr(action, "_ar_process_exit_confirmed", False) is not True
            or state.get("schema_version") != CONTRACT_VERSION
            or state.get("completed") != names[:-1] or state.get("publication") != "verified"
            or result_state.get("schema_version") != CONTRACT_VERSION
            or result_state.get("completed") != names or result_state.get("publication") != "verified"
            or result.get("process_evidence_version") != SCHEMA_VERSION
            or not isinstance(records, list) or len(records) != 1
            or result.get("process_records") != records):
        raise ValueError("缺少已执行完成且已发布的收尾证据，不能绕过执行权限继续。")
    reference = records[0]
    record_id = reference.get("record_id", "") if isinstance(reference, dict) else ""
    if (not isinstance(record_id, str) or len(record_id) != 32 or any(c not in "0123456789abcdef" for c in record_id)
            or reference.get("script") != "complete_execution.py"
            or reference.get("state") != "exited"
            or reference.get("direct_process_exit_confirmed") is not True):
        raise ValueError("收尾进程证据无效，未登记完成。")
    root = workflow_root(workflow.owner_id, workflow.id).resolve()
    path = root / "execution-processes" / action.id / record_id / "exited.json"
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("收尾进程证据路径无效。")
    with path.open("rb") as handle:
        raw = handle.read(65537)
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) > 65536 or digest != reference.get("exit_sha256"):
        raise ValueError("收尾进程证据指纹不一致。")
    fact = json.loads(raw)
    expected = {"schema_version":SCHEMA_VERSION, "record_id":record_id,
        "workflow_id":workflow.id, "action_id":action.id, "action_name":action.name,
        "attempt":action.attempt_count, "worker_id":action.worker_id,
        "reconciliation_date":workflow.reconciliation_date, "skill_hash":workflow.skill_hash,
        "script":"complete_execution.py"}
    if (not isinstance(fact, dict) or any(fact.get(k) != v for k,v in expected.items())
            or not action.worker_id or fact.get("communication_completed") is not True
            or fact.get("direct_process_exit_confirmed") is not True
            or type(fact.get("returncode")) is not int or fact["returncode"] != 0):
        raise ValueError("收尾进程没有可验证的成功退出，未登记完成。")
    return digest
