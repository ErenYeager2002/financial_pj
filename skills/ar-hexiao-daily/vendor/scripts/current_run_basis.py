"""Decision inputs are current workbooks plus the freshly selected source bundle.

Previous execution journals remain audit artifacts, never decision authority.
Within-plan evidence and write/readback fingerprints still apply.
"""
POLICY = "current_material_and_source_v1"


def enabled(plan):
    return (plan.get("business_rules") or {}).get("decision_basis") == POLICY


def empty_state():
    return {"version": 2, "parents": {}, "baseline_receipts": {}}


def initialize(ledgers, current_evidence=None):
    """Ignore prior runs unless the caller supplies evidence built from this run's checked plan."""
    import copy

    state = empty_state() if current_evidence is None else copy.deepcopy(current_evidence)
    if not isinstance(state, dict) or not isinstance(state.get("parents"), dict):
        raise ValueError("本次核销分配证据结构无效")
    receipts = state.get("baseline_receipts", {})
    if not isinstance(receipts, dict):
        raise ValueError("本次核销回款身份凭据结构无效")
    for ledger in ledgers:
        ledger.baseline_receipt_state = copy.deepcopy(receipts)
    return state


def prior_state(workspace, plan):
    if enabled(plan):
        return empty_state()
    import fallback_allocation_ledger
    return fallback_allocation_ledger.load(workspace)
