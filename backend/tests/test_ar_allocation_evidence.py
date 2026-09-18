"""Allocation metadata must not change the financial identity of a commit."""
import copy
import importlib
import sys
from pathlib import Path
from unittest.mock import patch
import unittest

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/ar-hexiao-daily-lab/vendor/scripts"
sys.path.insert(0, str(SCRIPTS))
ledger = importlib.import_module("fallback_allocation_ledger")


def entry():
    return {"ar": "AR_TEST", "hexiao_date": "2026-08-20", "parent_amount": 25,
            "allocations": [{"so": "SO_TEST", "allocated": 25, "allocated_local": 25}],
            "applied_cases": {"AR_TEST|SO_TEST|SOD_TEST": {"so": "SO_TEST", "sod": "SOD_TEST", "amount_local": 25}},
            "applied_sos": ["SO_TEST"]}


def invoke(old, new):
    data = {"version": 2, "parents": {"AR_TEST": copy.deepcopy(old)}}
    with patch.object(ledger, "load", return_value=data), \
         patch.object(ledger, "eligible_entries", return_value={"AR_TEST": new}), \
         patch.object(ledger.baseline_receipts, "merge_journal", return_value={}), \
         patch.object(ledger.baseline_receipts, "validate_journal"), \
         patch.object(ledger, "ledger_path") as destination:
        ledger.commit(Path("unused"), {"hexiao_date": "2026-08-20"})
        assert destination.return_value.write_text.call_count == 1
    return data


def check_current_material_evidence_is_not_allocation_change():
    old = entry()
    new = {**old, "reconstructed_from_current_material": True,
           "current_material_evidence": {"SO_TEST": {"42": {"回款明细": 25}}}}
    saved = invoke(old, new)["parents"]["AR_TEST"]
    assert saved["allocations"] == old["allocations"]
    assert ledger.readback_payload(saved) == ledger.readback_payload(new)
    saved = invoke(new, old)["parents"]["AR_TEST"]
    assert ledger.readback_payload(saved) == ledger.readback_payload(old)
    assert ledger.readback_payload(old) != ledger.readback_payload(new)


def check_real_changes_still_fail(mutation):
    old = entry(); new = copy.deepcopy(old)
    if mutation == "amount": new["allocations"][0]["allocated_local"] = 26
    if mutation == "order": new["allocations"][0]["so"] = "SO_OTHER"
    if mutation == "date": old["hexiao_date"] = "2026-08-19"
    if mutation == "case_amount": new["applied_cases"]["AR_TEST|SO_TEST|SOD_TEST"]["amount_local"] = 26
    if mutation == "missing_case": new["applied_cases"] = {}
    if mutation == "unknown_field": new["unrecognized_financial_field"] = 1
    with unittest.TestCase().assertRaises(ValueError): invoke(old, new)

class AllocationEvidenceTests(unittest.TestCase):
    def test_metadata(self):
        check_current_material_evidence_is_not_allocation_change()

    def test_legacy_full_allocation_is_preserved(self):
        old = entry()
        old.pop("applied_cases"); old.pop("applied_sos")
        new = {**entry(), "reconstructed_from_current_material": True,
               "current_material_evidence": {"SO_TEST": {"42": {"回款明细": 25}}}}
        saved = invoke(old, new)["parents"]["AR_TEST"]
        self.assertEqual(ledger.readback_payload(saved), ledger.readback_payload(old))

    def test_repeated_evidence_commit_is_idempotent(self):
        old = entry()
        new = {**old, "reconstructed_from_current_material": True,
               "current_material_evidence": {"SO_TEST": {"42": {"回款明细": 25}}}}
        once = invoke(old, new)["parents"]["AR_TEST"]
        twice = invoke(once, new)["parents"]["AR_TEST"]
        self.assertEqual(ledger.readback_payload(once), ledger.readback_payload(twice))

    def test_financial_guards(self):
        for mutation in ["amount", "order", "date", "case_amount", "missing_case", "unknown_field"]:
            with self.subTest(mutation=mutation):
                check_real_changes_still_fail(mutation)

class ReviewErrorTests(unittest.TestCase):
    def test_review_registration_failure_is_not_version_conflict(self):
        import ast
        import re
        from types import SimpleNamespace
        source = SCRIPTS.parents[3] / "backend/app/workflow_service.py"
        tree = ast.parse(source.read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_workflow_error_detail")
        scope = {"WorkflowSession": object, "TaskErrorDetail": object,
                 "_load": lambda value, default: value,
                 "classify_task_error": lambda *a, **k: ("UNKNOWN", "unknown"),
                 "build_task_error": lambda **kwargs: SimpleNamespace(**kwargs),
                 "PostWriteVerificationError": type("PostWriteVerificationError", (Exception,), {}),
                 "StagedWriteError": type("StagedWriteError", (Exception,), {}), "re": re}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), scope)
        workflow = SimpleNamespace(context_json={"current_step": "verify_reconciliation", "material_version": 1},
                                   stage="applying", owner_name="test", owner_id="test", skill_id="test", skill_name="test")
        detail = scope["_workflow_error_detail"](workflow, RuntimeError("AR_REVIEW_ALLOCATION_FAILED: test"))
        self.assertEqual(detail.error_code, "WORKFLOW_REVIEW_ALLOCATION_FAILED")
        self.assertEqual(detail.write_status, "not_published")
        self.assertFalse(detail.recovery_allowed)
        detail = scope["_workflow_error_detail"](workflow, RuntimeError("unclassified failure"))
        self.assertEqual(detail.error_code, "WORKFLOW_WRITE_STATUS_UNKNOWN")
        self.assertFalse(detail.recovery_allowed)

if __name__ == "__main__":
    unittest.main()
