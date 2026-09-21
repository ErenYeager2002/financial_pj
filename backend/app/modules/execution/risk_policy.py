"""Common retry decision. Callers supply verified immutable and current facts.

No registry, database, filesystem or process access belongs in this module.
A true fact is evidence collected at the owning boundary, never a default.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryDecision:
    allowed: bool
    code: str
    explanation: str


def deny(code, explanation):
    return RetryDecision(False, code, explanation)


def evaluate_retry_policy(snapshot, execution_facts, reason):
    if not isinstance(reason, str) or reason not in {"manual", "lease_expired"}:
        return deny("RETRY_REASON_UNKNOWN", "无法确定重试来源。")
    if not isinstance(snapshot, dict) or not isinstance(execution_facts, dict):
        return deny("RETRY_EVIDENCE_INVALID", "重试依据缺失或格式不正确。")
    if snapshot.get("snapshot_verified") is not True or snapshot.get("risk_declared") is not True:
        return deny("RETRY_SNAPSHOT_UNVERIFIED", "未核实原始固定快照及明确风险声明。")
    risk = snapshot.get("risk")
    flags = ("requires_confirmation", "requires_change_review", "requires_approval", "modifies_uploaded_files")
    if not isinstance(risk, dict) or any(type(risk.get(key)) is not bool for key in flags):
        return deny("RETRY_RISK_INCOMPLETE", "原始风险声明不完整，不能按只读任务重试。")
    if risk.get("level") != "read_only" or risk["modifies_uploaded_files"]:
        return deny("RETRY_WRITE_FORBIDDEN", "涉及写入或修改原材料的任务不能直接重试。")
    facts = execution_facts
    if snapshot.get("adapter") != "python" or facts.get("adapter_safe_replay") is not True:
        return deny("RETRY_ADAPTER_UNSAFE", "执行器没有经过验证的安全重放能力。")
    if facts.get("owner_authorized") is not True or facts.get("files_accessible") is not True:
        return deny("RETRY_ACCESS_REVOKED", "当前身份或输入文件访问条件不满足。")
    if facts.get("cancel_requested") is not False:
        return deny("RETRY_CANCELLED", "取消状态不允许重试。")
    states = {"manual": {"failed", "timed_out"}, "lease_expired": {"running"}}
    if not isinstance(facts.get("state"), str) or facts["state"] not in states[reason]:
        return deny("RETRY_STATE_FORBIDDEN", "当前状态不允许该重试操作。")
    used, limit = facts.get("attempts_used"), facts.get("max_attempts")
    if type(used) is not int or type(limit) is not int or used < 0 or limit <= 0 or used >= limit:
        return deny("RETRY_ATTEMPTS_EXHAUSTED", "重试次数已经达到上限或缺少可信次数记录。")
    if facts.get("outcome_unknown") is not False or facts.get("process_exit_confirmed") is not True:
        return deny("EXECUTION_OUTCOME_UNKNOWN", "执行结果或进程退出情况尚未核实，不能重复执行。")
    if facts.get("steps_retryable") is not True or facts.get("steps_idempotent") is not True:
        return deny("RETRY_STEP_UNSAFE", "执行步骤不满足重试与幂等条件。")
    return RetryDecision(True, "RETRY_ALLOWED", "固定风险声明及当前执行证据满足安全重试条件。")
