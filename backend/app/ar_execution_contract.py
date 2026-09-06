"""Versioned AR phases shared by the deterministic runner and Pi Harness.

This module contains no workbook mutation or model-dependent financial rules.
"""
from __future__ import annotations

from dataclasses import dataclass

CONTRACT_VERSION = "ar-execution-v2"
EVIDENCE_VERSION = "ar-evidence-v1"
INVESTIGATION_ACTION = "inspect_failed_ar_write"


def publication_needs_completion(context: dict) -> bool:
    return ((context.get("ar_execution") or {}).get("publication") == "verified"
            and not context.get("formal_ledgers"))


class ExecutionLeaseLost(RuntimeError):
    """A stale Worker must not overwrite the authoritative action outcome."""


class ExecutionCancelled(RuntimeError):
    """Cancellation observed under the claim lock before starting a phase."""


class ExecutionPhaseFailed(RuntimeError):
    """Route v2 failures through its fenced handler, including script timeouts."""


@dataclass(frozen=True)
class ExecutionPhase:
    name: str
    tool: str
    label: str
    progress: int
    mutates_workbooks: bool = False


PHASES = (
    ExecutionPhase("inspect_materials", "inspect_materials", "检查本次材料", 24),
    ExecutionPhase("classify_receipts", "classify_receipts", "生成首次判定", 32),
    ExecutionPhase("review_order_evidence", "review_order_evidence", "核对逐单依据", 40),
    ExecutionPhase("validate_reconciliation", "validate_reconciliation", "校验写入计划", 48),
    ExecutionPhase("build_initial_report", "build_initial_report", "生成首次核销日清", 54),
    ExecutionPhase("stage_reconciliation", "stage_reconciliation", "准备写入暂存", 58),
    ExecutionPhase("write_ledger", "write_ledger", "写入盈亏并回读", 66, True),
    ExecutionPhase("write_receipt_flow", "write_receipt_flow", "登记及回填流转", 72, True),
    ExecutionPhase("verify_reconciliation", "verify_reconciliation", "写后业务复核", 80),
    ExecutionPhase("rescan_holds", "rescan_holds", "重扫挂账", 86),
    ExecutionPhase("build_final_report", "build_final_report", "生成最终核销日清", 92),
    ExecutionPhase("review_final_report", "review_final_report", "核对最终清单与原因", 95),
    ExecutionPhase("publish_reconciliation", "publish_reconciliation", "发布已复核材料", 97),
    ExecutionPhase("complete_reconciliation", "complete_reconciliation", "核对发布并登记正式台账", 99),
)
PHASE_BY_NAME = {phase.name: phase for phase in PHASES}
TOOL_PHASE = {phase.tool: phase.name for phase in PHASES}
WRITE_GUARD_FIELDS = ("reconciliation_date", "material_set_id", "material_version", "plan_fingerprint")
GUARDED_TOOLS = frozenset(phase.tool for phase in PHASES
                          if phase.mutates_workbooks or phase.name in {"stage_reconciliation", "publish_reconciliation"})
COMMON_AGENT_TOOLS = frozenset({
    "prepare_workspace", "fetch_zhiyun", "build_fetch_preview", "inspect_fetched_data",
    "read_task_file", "inspect_order_evidence", "accept_fetched_data", "finalize_batch",
    "initialize_reconciliation",
})


def next_phase(completed: list[str]) -> ExecutionPhase | None:
    """Only a contiguous, exact prefix is resumable; missing steps are not success."""
    names = [phase.name for phase in PHASES]
    if completed != names[:len(completed)]:
        raise ValueError("执行记录不是合法的步骤前缀，禁止跳过必要检查")
    return PHASES[len(completed)] if len(completed) < len(PHASES) else None


def require_phase(completed: list[str], requested: str) -> ExecutionPhase:
    expected = next_phase(completed)
    if expected is None or expected.name != requested:
        raise ValueError("请求步骤与当前执行检查点不一致")
    return expected
