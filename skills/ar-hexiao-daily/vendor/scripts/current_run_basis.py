"""Decision inputs are current workbooks plus the freshly selected source bundle.

Previous execution journals remain audit artifacts, never decision authority.
Within-plan evidence and write/readback fingerprints still apply.
"""
POLICY = "current_material_and_source_v1"


def enabled(plan):
    return (plan.get("business_rules") or {}).get("decision_basis") == POLICY


def empty_state():
    return {"version": 2, "parents": {}, "baseline_receipts": {}}


def initialize(ledgers):
    for ledger in ledgers:
        ledger.baseline_receipt_state = {}
    return empty_state()


def prior_state(workspace, plan):
    if enabled(plan):
        return empty_state()
    import fallback_allocation_ledger
    return fallback_allocation_ledger.load(workspace)
