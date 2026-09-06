"""Parent allocation provenance, using synthetic amounts and identifiers only."""
import copy
import datetime as dt
import json

import pytest

import classify_hexiao as C
import fallback_allocation_ledger as FAL
import validate_plan as V
from test_misjudgment_regressions import _ledger, _payment


def payment(**extra):
    return _payment(
        amount=150.0,
        orders=[{"so": "SO_SMALL", "deliver": 40.0}, {"so": "SO_LARGE", "deliver": 500.0}],
        sod_lines={"SO_SMALL": [{"sod": "SOD_SMALL", "deliver": 40.0}],
                   "SO_LARGE": [{"sod": "SOD_LARGE", "deliver": 500.0}]},
        **extra,
    )


def paid_ledger():
    return _ledger({
        10: {"so": "SO_SMALL", "sod": "SOD_SMALL", "yingshou": 40.0, "huikuan": 40.0,
             "jiezhang": "是", "shoukuan_time": dt.date(2026, 7, 24), "shoukuan_way": "汇"},
        20: {"so": "SO_LARGE", "sod": "SOD_LARGE", "yingshou": 110.0, "huikuan": 110.0,
             "jiezhang": "是", "shoukuan_time": dt.date(2026, 7, 24), "shoukuan_way": "汇"},
        21: {"so": "SO_LARGE", "sod": "SOD_LARGE", "yingshou": 390.0, "huikuan": None, "jiezhang": "否"},
    })


def recorded_state():
    first = payment()
    C.expand_payment(first, {})
    return {"version": 1, "parents": {"AR_TEST": copy.deepcopy(first["_parent_fallback_allocation"])}}


def test_missing_history_blocks_whole_parent_before_settled_skip():
    recs = C.expand_payment(payment(
        _ledger_settled_sos=["SO_SMALL"],
        _ledger_received_local_by_so={"SO_SMALL": 40.0, "SO_LARGE": 110.0},
    ), {})
    assert {r["so"] for r in recs} == {"SO_SMALL", "SO_LARGE"}
    for rec in recs:
        result = C.classify_one(rec, paid_ledger(), {}, 0.0, 2026)
        assert result["bucket"] == "hold"
        assert result["code"] == "E_PARENT_ALLOCATION_HISTORY_MISSING"
        assert "40.00" in result["reason"]
        assert not result["five_cols"]
        assert C._flow_ready(result) == "wait"


def test_same_parent_reuses_original_allocations_and_skips_paid_slice():
    recs = C.expand_payment(payment(
        _fallback_allocation_state=recorded_state(), _ledger_settled_sos=["SO_SMALL"],
        _ledger_received_local_by_so={"SO_SMALL": 40.0, "SO_LARGE": 110.0},
    ), {})
    assert {r["so"]: r["amount_local"] for r in recs} == {"SO_SMALL": 40.0, "SO_LARGE": 110.0}
    large = next(r for r in recs if r["so"] == "SO_LARGE")
    result = C.classify_one(large, paid_ledger(), {}, 0.0, 2026)
    assert result["code"] == "OK_FALLBACK_ALLOCATION_ALREADY_APPLIED"
    assert "row_operation" not in result


def test_first_payment_keeps_existing_split_and_accrual_rules():
    large = next(r for r in C.expand_payment(payment(), {}) if r["so"] == "SO_LARGE")
    result = C.classify_one(large, _ledger({20: {
        "so": "SO_LARGE", "sod": "SOD_LARGE", "yingshou": 500.0, "jiezhang": "否",
    }}), {}, 0.0, 2026)
    assert result["row_operation"]["paid_receivable"] == 110.0
    assert result["row_operation"]["unpaid_receivable"] == 390.0
    assert result["five_cols"]["计提"] is None


def test_new_parent_does_not_borrow_same_amount_date_row_from_prior_parent():
    # A different parent pays the same amount on the same receipt date.
    p = payment(ar="AR_NEXT", _fallback_allocation_state=recorded_state(),
                _ledger_settled_sos=["SO_SMALL"],
                _ledger_received_local_by_so={"SO_SMALL": 40.0, "SO_LARGE": 110.0})
    p["amount_orig"] = p["amount_local"] = 110.0
    rec = next(r for r in C.expand_payment(p, {}) if r["so"] == "SO_LARGE")
    result = C.classify_one(rec, paid_ledger(), {}, 0.0, 2026)
    assert result["row_operation"]["cumulative_received"] == 220.0
    assert result["row_operation"]["unpaid_receivable"] == 280.0


def test_write_precheck_rejects_old_bad_plan_across_years_only_for_same_parent():
    audit = recorded_state()["parents"]["AR_TEST"]
    audit["allocations"][0].update(allocated=0.0, allocated_local=0.0)
    audit["allocations"][1].update(allocated=150.0, allocated_local=150.0)
    rows = {
        2025: {1: {"SO": "SO_SMALL", "SOD": "SOD_SMALL", "回款明细": 40.0, "是否结账": "是"}},
        2026: {1: {"SO": "SO_LARGE", "SOD": "SOD_LARGE", "回款明细": None, "是否结账": "否"},
               2: {"SO": "SO_OTHER", "SOD": "SOD_OTHER", "回款明细": None, "是否结账": "否"}},
    }
    def item(ar, so, sod, year, row):
        return {"case_id": f"{ar}|{so}|{sod}", "ar": ar, "so": so, "sod": sod,
                "ledger_year": year, "ledger_row_ref": row,
                "five_cols": {"回款明细": 10.0, "是否结账": "是", "实收SOD": sod}}
    plan = {"parent_fallback_allocations": {"AR_TEST": audit}, "auto": [
        item("AR_TEST", "SO_LARGE", "SOD_LARGE", 2026, 1),
        item("AR_OTHER", "SO_OTHER", "SOD_OTHER", 2026, 2),
    ]}
    checked = V.validate_by_year(plan, rows)
    assert [x["ar"] for x in checked["conflict"]] == ["AR_TEST"]
    assert "40.00" in checked["conflict"][0]["_check"]["reason"]
    assert [x["ar"] for x in checked["write"]] == ["AR_OTHER"]


@pytest.mark.parametrize("content", ['{', '[]', '{"version": 1, "parents": []}'])
def test_corrupt_ledger_never_becomes_empty_history(tmp_path, content):
    FAL.ledger_path(tmp_path).write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="台账"):
        FAL.load(tmp_path)


def test_initial_empty_workspace_and_valid_ledger_still_load(tmp_path):
    assert FAL.load(tmp_path) == {"version": FAL.VERSION, "parents": {}}
    state = recorded_state()
    FAL.ledger_path(tmp_path).write_text(json.dumps(state), encoding="utf-8")
    assert FAL.load(tmp_path) == state


def test_partial_parent_keeps_original_allocation_without_counting_pending_money(tmp_path):
    state = recorded_state()
    audit = state["parents"]["AR_TEST"]
    FAL.commit(tmp_path, {"hexiao_date": "2026-07-27", "parent_fallback_allocations": {"AR_TEST": audit},
        "write": [{"ar": "AR_TEST", "so": "SO_SMALL", "sod": "SOD_SMALL",
                   "five_cols": {"回款明细": 40.0},
                   "split_payment_source": {"delivery_local": 40.0}}]})
    saved = FAL.load(tmp_path)
    assert saved["version"] == 2
    assert saved["parents"]["AR_TEST"]["applied_sos"] == ["SO_SMALL"]
    _, history = FAL.history_totals(saved, current_ar="AR_NEXT")
    assert history["SO_SMALL"] == 40.0
    assert history.get("SO_LARGE", 0.0) == 0.0
    recs = C.expand_payment(payment(_fallback_allocation_state=saved,
                                   _ledger_settled_sos=["SO_SMALL"],
                                   _ledger_received_local_by_so={"SO_SMALL": 40.0}), {})
    assert {r["so"]: r["amount_local"] for r in recs} == {"SO_SMALL": 40.0, "SO_LARGE": 110.0}
    assert all(not r.get("forced_code") for r in recs)


def test_partial_sod_history_and_waterfall_replay_keep_only_actual_written_amounts(tmp_path):
    p = _payment(amount=150.0, orders=[{"so": "SO1", "deliver": 500.0}],
                 sod_lines={"SO1": [{"sod": "SOD_A", "deliver": 100.0},
                                     {"sod": "SOD_B", "deliver": 400.0}]})
    C.expand_payment(p, {})
    FAL.commit(tmp_path, {"hexiao_date": "2026-07-27",
        "parent_fallback_allocations": {"AR_TEST": p["_parent_fallback_allocation"]},
        "write": [{"ar": "AR_TEST", "so": "SO1", "sod": "SOD_A",
                   "five_cols": {"回款明细": 100.0},
                   "split_payment_source": {"delivery_local": 100.0, "cumulative_local": 100.0}}]})
    state = FAL.load(tmp_path)
    assert state["parents"]["AR_TEST"]["applied_sos"] == []
    assert FAL.history_totals(state, current_ar="AR_NEXT")[1]["SO1"] == 100.0
    ledger = _ledger({
        10: {"so": "SO1", "sod": "SOD_A", "yingshou": 100.0, "huikuan": 100.0, "jiezhang": "是",
             "shoukuan_time": dt.date(2026, 7, 24), "shoukuan_way": "汇"},
        11: {"so": "SO1", "sod": "SOD_B", "yingshou": 400.0, "huikuan": None, "jiezhang": "否"},
    })
    p["_fallback_allocation_state"] = state
    recs = C.expand_payment(p, {})
    expanded = C._expand_ambiguous_sod_waterfall(recs[0], ledger, 0.001)
    assert {r["sod"]: r["amount_local"] for r in expanded} == {"SOD_A": 100.0, "SOD_B": 50.0}
    results = [C.classify_one(r, ledger, {}, 0.0, 2026) for r in expanded]
    assert results[0]["code"] == "OK_FALLBACK_ALLOCATION_ALREADY_APPLIED"
    assert results[1]["row_operation"]["unpaid_receivable"] == 350.0
    FAL.commit(tmp_path, {"hexiao_date": "2026-07-27",
        "parent_fallback_allocations": {"AR_TEST": p["_parent_fallback_allocation"]},
        "skip": [results[0]], "write": [results[1]]})
    completed = FAL.load(tmp_path)
    assert completed["parents"]["AR_TEST"]["applied_sos"] == ["SO1"]
    assert FAL.history_totals(completed, current_ar="AR_NEXT")[1]["SO1"] == 150.0


def test_unwritten_order_without_local_amount_does_not_block_successful_evidence(tmp_path):
    audit = recorded_state()["parents"]["AR_TEST"]
    audit["allocations"][1]["allocated_local"] = None
    FAL.commit(tmp_path, {"hexiao_date": "2026-07-27",
        "parent_fallback_allocations": {"AR_TEST": audit},
        "write": [{"ar": "AR_TEST", "so": "SO_SMALL", "sod": "SOD_SMALL",
                   "five_cols": {"回款明细": 40.0}}]})
    saved = FAL.load(tmp_path)
    assert saved["parents"]["AR_TEST"]["applied_sos"] == ["SO_SMALL"]
    assert FAL.history_totals(saved, current_ar="AR_NEXT")[1]["SO_SMALL"] == 40.0


def test_formal_readback_compares_execution_evidence_separately_from_allocation():
    original = {"ar": "AR_TEST", "allocations": [], "applied_cases": {}, "applied_sos": []}
    changed = {**original, "applied_sos": ["SO_SMALL"]}
    assert FAL._stable_payload(original) == FAL._stable_payload(changed)
    assert FAL.readback_payload(original) != FAL.readback_payload(changed)
    changed = {**original, "applied_cases": {"AR_TEST|SO_SMALL|SOD_SMALL": {"amount_local": 40.0}}}
    assert FAL.readback_payload(original) != FAL.readback_payload(changed)
    assert FAL.readback_payload(original) == FAL.readback_payload({**original, "last_verified_at": "later"})


def test_partial_replay_with_changed_baseline_reports_amounts_without_claiming_missing_history():
    reason = FAL.unexplained_receipts("AR_TEST", "SO1", 120.0, 100.0,
                                      reused_allocation=True, current_applied=100.0)
    assert "原分配账面基准已变化" in reason
    assert "原分配历史 0.00" in reason
    assert "本父回款已写 100.00" in reason
    assert "增加 20.00" in reason
    assert "归属未确认" not in reason
    assert C._flow_ready({"code": "E_PARENT_ALLOCATION_BASELINE_CHANGED"}) == "wait"
