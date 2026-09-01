from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import classify_hexiao as C
import fetch_zhiyun as F
import validate_plan as V
import writeoff_duplicate_audit as W


DAY = dt.date(2026, 7, 31)


def payment(ar="AR1", amount=100, *, local=None, currency="CNY", huikuan_type=""):
    return {
        "ar": ar,
        "amount_orig": amount,
        "amount_local": local,
        "currency": currency,
        "huikuan_type": huikuan_type,
        "hexiao_date": DAY,
        "arrival_date": DAY,
        "orders": [{"so": "SO1", "deliver": amount, "currency": currency}],
        "writeoffs": {},
        "writeoffs_local": {},
        "cumulative_writeoffs": {},
        "cumulative_writeoffs_local": {},
        "_source_meta": {"historical_detail_rows": 0, "recovered_deliveries": 0},
    }


def row(record_id, amount=100, *, ar="AR1", so="SO1", local=None,
        currency="CNY", day=DAY, revoked=""):
    return {
        "record_id": record_id,
        "rowid": f"row-{record_id}",
        "ar": ar,
        "date": day,
        "so": so,
        "amount": amount,
        "amount_local": local,
        "currency": currency,
        "revoked": revoked,
        "source": "核销明细_20260731.xlsx",
        "snapshot_date": DAY,
    }


def audit(parent, rows):
    return W.audit_parent_writeoffs(parent, rows)


def sod_payment(
    rows,
    *,
    ar="AR1",
    parent_amount=None,
    sod_lines=None,
):
    amount = parent_amount
    if amount is None:
        amount = sum(float(item.get("amount") or 0.0) for item in rows)
    p = payment(ar=ar, amount=amount)
    p["orders"] = [{"so": "SO1", "deliver": 100, "currency": "CNY"}]
    p["sod_lines"] = sod_lines or {
        "SO1": [{
            "sod": "SOD1",
            "deliver": 100,
            "currency": "CNY",
            "source": "订单明细_20260731.xlsx",
        }]
    }
    C.reconcile_writeoff_details([p], {ar: p}, rows, DAY)
    info = p["duplicate_writeoff_audit"]
    p["_duplicate_writeoff_audits"] = {ar: info}
    p["_detailed_parent_ars"] = [ar]
    return p


def test_sod_duplicate_is_collapsed_when_unique_and_each_row_equals_delivery():
    p = sod_payment([row("HX1"), row("HX2")], parent_amount=200)

    records = C.expand_payments([p], {})

    assert p["writeoffs"] == {"SO1": 100.0}
    assert p["cumulative_writeoffs"] == {"SO1": 100.0}
    audit_info = p["duplicate_writeoff_audit"]
    assert len(audit_info["sod_duplicate_groups"]) == 1
    assert audit_info["sod_duplicate_ignored_count"] == 1
    assert sum(item["amount_orig"] for item in records) == 100
    assert records[0]["sod"] == "SOD1"
    assert "W_SYSTEM_DUPLICATE_WRITEOFF_COLLAPSED" in records[0]["warning_codes"]
    assert sum(
        item["disposition"] == "system_duplicate_ignored"
        for item in audit_info["records"]
    ) == 1

    plan = {
        "duplicate_writeoff_audits": {"AR1": audit_info},
        "duplicate_writeoff_audit_sha256": W.audit_fingerprint({"AR1": audit_info}),
        "auto": [{
            "ar": "AR1", "so": "SO1", "sod": "SOD1", "ledger_row_ref": 2,
            "five_cols": {"计提": 100, "回款明细": 100, "是否结账": "是",
                          "收款时间": "2026-07-31", "收款方式": "汇"},
            "warning_codes": ["W_SYSTEM_DUPLICATE_WRITEOFF_COLLAPSED"],
            "duplicate_writeoff_audit": audit_info,
        }],
    }
    rows = {2: {"SO": "SO1", "SOD": "SOD1", "计提": None, "回款明细": None,
                "是否结账": "否", "收款时间": None, "收款方式": None,
                "差异": None, "_差异列存在": True, "应收金额": 100}}
    assert V.validate(plan, rows)["counts"]["write"] == 1


def test_sod_duplicate_is_idempotent_after_the_first_collapse():
    p = sod_payment([row("HX1"), row("HX2")], parent_amount=200)

    first = C.expand_payments([p], {})
    second = C.expand_payments([p], {})

    assert len(first) == len(second) == 1
    assert p["writeoffs"] == {"SO1": 100.0}
    assert len(p["duplicate_writeoff_audit"]["sod_duplicate_groups"]) == 1
    assert p["duplicate_writeoff_audit"]["sod_duplicate_ignored_count"] == 1


def test_sod_duplicate_is_not_collapsed_when_sod_mapping_is_ambiguous():
    p = sod_payment(
        [row("HX1"), row("HX2")],
        parent_amount=200,
        sod_lines={
            "SO1": [
                {"sod": "SOD1", "deliver": 100, "currency": "CNY"},
                {"sod": "SOD2", "deliver": 100, "currency": "CNY"},
            ]
        },
    )

    records = C.expand_payments([p], {})

    assert len(records) == 2
    assert not p["duplicate_writeoff_audit"].get("sod_duplicate_groups")
    assert p["duplicate_writeoff_audit"]["records"]
    assert all(
        item["disposition"] == "kept"
        for item in p["duplicate_writeoff_audit"]["records"]
    )


def test_sod_duplicate_is_not_collapsed_when_folded_history_still_exceeds_delivery():
    p = sod_payment(
        [
            row("HX0", amount=20, day=DAY - dt.timedelta(days=1)),
            row("HX1"),
            row("HX2"),
        ],
        parent_amount=220,
    )

    records = C.expand_payments([p], {})

    assert len(records) == 1
    assert p["writeoffs"] == {"SO1": 200.0}
    assert p["cumulative_writeoffs"] == {"SO1": 220.0}
    assert not p["duplicate_writeoff_audit"].get("sod_duplicate_groups")


def test_sod_duplicate_does_not_cross_parent_ar():
    p1 = sod_payment([row("HX1", ar="AR1")], ar="AR1", parent_amount=100)
    p2 = sod_payment([row("HX2", ar="AR2")], ar="AR2", parent_amount=100)

    records = C.expand_payments([p1, p2], {})

    assert len(records) == 2
    assert not p1["duplicate_writeoff_audit"].get("sod_duplicate_groups")
    assert not p2["duplicate_writeoff_audit"].get("sod_duplicate_groups")


def test_sod_duplicate_requires_each_amount_to_equal_delivery():
    p = sod_payment(
        [row("HX1", amount=80), row("HX2", amount=80)],
        parent_amount=160,
    )

    records = C.expand_payments([p], {})

    assert len(records) == 1
    assert p["writeoffs"] == {"SO1": 160.0}
    assert not p["duplicate_writeoff_audit"].get("sod_duplicate_groups")


def test_sod_duplicate_requires_local_amounts_to_match_when_present():
    p = sod_payment(
        [row("HX1", local=100), row("HX2", local=101)],
        parent_amount=201,
    )
    p["amount_local"] = 201
    C._prepare_parent_totals(p)

    C.expand_payments([p], {})

    assert not p["duplicate_writeoff_audit"].get("sod_duplicate_groups")


def test_two_distinct_ids_same_so_amount_recover_one_logical():
    logical, info = audit(payment(), [row("HX1"), row("HX2")])
    assert info["delta_raw"] == -100
    assert info["delta_dedup"] == 0
    assert info["status"] == "recovered"
    assert [item["record_id"] for item in logical] == ["HX1"]
    assert info["ignored_record_count"] == 1


def test_four_distinct_ids_only_count_once_for_h_and_r():
    p = payment()
    raw = [row(f"HX{i}") for i in range(1, 5)]
    current, audits = C.reconcile_writeoff_details([p], {"AR1": p}, raw, DAY)
    assert len(current) == 1
    assert p["writeoffs"] == {"SO1": 100.0}
    assert p["cumulative_writeoffs"] == {"SO1": 100.0}
    assert audits["AR1"]["ignored_record_count"] == 3


def test_parent_400_four_equal_records_is_normal_not_collapsed():
    logical, info = audit(payment(amount=400), [row(f"HX{i}") for i in range(4)])
    assert info["delta_raw"] == 0
    assert info["status"] == "normal"
    assert len(logical) == 4
    assert not info["duplicate_groups"]


def test_negative_099_is_tolerance_without_business_dedup():
    logical, info = audit(payment(amount=99.01), [row("HX1"), row("HX2", amount=0)])
    assert info["delta_raw"] == -0.99
    assert info["status"] == "tolerance"
    assert len(logical) == 2


def test_negative_100_is_tolerance():
    logical, info = audit(payment(amount=99), [row("HX1")])
    assert info["delta_raw"] == -1
    assert info["status"] == "tolerance"
    assert len(logical) == 1


def test_negative_101_exact_duplicate_recovers_within_tolerance():
    logical, info = audit(
        payment(amount=98.99),
        [row("HX1", amount=50), row("HX2", amount=50)],
    )
    assert info["delta_raw"] == -1.01
    assert info["delta_dedup"] == 48.99
    assert info["status"] == "recovered"
    assert len(logical) == 1


def test_over_writeoff_without_exact_duplicate_is_unresolved():
    logical, info = audit(
        payment(),
        [row("HX1", amount=60), row("HX2", amount=50)],
    )
    assert logical == []
    assert info["status"] == "unresolved"
    assert info["error_code"] == "E_SYSTEM_OVER_WRITEOFF_UNRESOLVED"


def test_whole_parent_without_order_written_off_uses_delivery_fallback():
    logical, info = audit(payment(huikuan_type="整笔回款"), [])

    assert len(logical) == 1
    assert logical[0]["amount"] == 100
    assert info["status"] == "delivery_fallback"
    assert info["comparison_basis"] == "delivery_fallback_original"
    assert info["order_amount_total"] == 100
    assert info["fallback_used"] is True
    assert info["is_whole_payment"] is True
    assert info["effective_detail_count"] == 1
    assert info["unallocated_parent_amount"] == 0.0


def test_whole_parent_without_written_off_or_complete_delivery_is_unresolved():
    parent = payment(huikuan_type="整笔回款")
    parent["orders"][0]["deliver"] = None

    logical, info = audit(parent, [])

    assert logical == []
    assert info["status"] == "unresolved"
    assert info["error_code"] == "E_PARENT_WRITEOFF_MISMATCH"


def test_whole_parent_order_written_off_delta_boundary_uses_one_yuan_tolerance():
    for order_amount in (99.0, 101.0):
        parent = payment(amount=100, huikuan_type="整笔回款")
        parent["orders"][0]["written_off"] = order_amount
        logical, info = audit(parent, [])
        assert len(logical) == 1
        assert info["status"] == "order_written_off_authoritative"

    parent = payment(amount=100, huikuan_type="整笔回款")
    parent["orders"][0]["written_off"] = 98.99
    logical, info = audit(parent, [])
    assert len(logical) == 1
    assert info["status"] == "order_written_off_authoritative"
    assert info["unallocated_parent_amount"] == 1.01

    parent = payment(amount=100, huikuan_type="整笔回款")
    parent["orders"][0]["written_off"] = 101.01
    logical, info = audit(parent, [])
    assert len(logical) == 1
    assert info["status"] == "unresolved"
    assert info["error_code"] == "E_PARENT_WRITEOFF_MISMATCH"


def test_whole_parent_order_written_off_three_cent_difference_passes():
    parent = payment(amount=1000, huikuan_type="整笔回款")
    parent["orders"] = [
        {"so": "SO1", "written_off": 400, "deliver": 400, "currency": "CNY"},
        {"so": "SO2", "written_off": 600.03, "deliver": 600.03, "currency": "CNY"},
    ]

    logical, info = audit(parent, [])

    assert len(logical) == 2
    assert info["status"] == "order_written_off_authoritative"
    assert info["comparison_basis"] == "order_written_off_original"
    assert info["delta"] == -0.03
    assert info["unallocated_parent_amount"] == 0.0


def test_whole_parent_overage_is_unallocated_against_authoritative_written_off():
    parent = payment(amount=300, huikuan_type="整笔回款")
    parent["orders"] = [
        {"so": "SO1", "written_off": 90, "deliver": 100, "currency": "CNY"},
        {"so": "SO2", "written_off": 190, "deliver": 200, "currency": "CNY"},
    ]

    logical, info = audit(parent, [])

    assert [(item["so"], item["amount"]) for item in logical] == [
        ("SO1", 90.0),
        ("SO2", 190.0),
    ]
    assert info["comparison_basis"] == "order_written_off_original"
    assert info["order_amount_total"] == 280.0
    assert info["delta"] == 20.0
    assert info["unallocated_parent_amount"] == 20.0
    assert info["status"] == "order_written_off_authoritative"


def test_non_whole_parent_overage_is_allowed_and_audited():
    logical, info = audit(
        payment(amount=300, huikuan_type="分笔回款"),
        [row("HX1", amount=100)],
    )

    assert len(logical) == 1
    assert info["status"] == "normal"
    assert info["delta"] == 200.0
    assert info["unallocated_parent_amount"] == 200.0


def test_zero_order_written_off_is_present_not_missing():
    parent = payment(amount=100, huikuan_type="整笔回款")
    parent["orders"] = [
        {"so": "SO1", "written_off": 0, "deliver": 100, "currency": "CNY"},
    ]

    logical, info = audit(parent, [])

    assert len(logical) == 1
    assert info["comparison_basis"] == "order_written_off_original"
    assert info["order_amount_total"] == 0
    assert info["status"] == "order_written_off_authoritative"
    assert info["unallocated_parent_amount"] == 100.0


def test_whole_parent_partial_written_off_never_mixes_with_delivery():
    parent = payment(amount=300, huikuan_type="整笔回款")
    parent["orders"] = [
        {"so": "SO1", "written_off": 100, "deliver": 100, "currency": "CNY"},
        {"so": "SO2", "deliver": 200, "currency": "CNY"},
    ]

    logical, info = audit(parent, [])

    assert logical == []
    assert info["status"] == "unresolved"
    assert "禁止混用" in info["reason"]


def test_whole_parent_written_off_overage_does_not_fall_back_to_delivery():
    parent = payment(amount=300, huikuan_type="整笔回款")
    parent["orders"] = [
        {"so": "SO1", "written_off": 90, "deliver": 100, "currency": "CNY"},
        {"so": "SO2", "written_off": 190, "deliver": 200, "currency": "CNY"},
    ]

    logical, info = audit(parent, [])

    assert len(logical) == 2
    assert info["comparison_basis"] == "order_written_off_original"
    assert info["order_amount_total"] == 280
    assert info["status"] == "order_written_off_authoritative"
    assert info["unallocated_parent_amount"] == 20


def test_non_whole_parent_unexplained_overage_is_unresolved():
    logical, info = audit(
        payment(amount=100, huikuan_type="分笔回款"),
        [row("HX1", amount=150)],
    )
    assert logical == []
    assert info["status"] == "unresolved"
    assert info["error_code"] == "E_SYSTEM_OVER_WRITEOFF_UNRESOLVED"


def test_whole_parent_without_comparable_parent_amount_is_unresolved():
    parent = payment(amount=None, local=None, huikuan_type="整笔回款")
    parent["orders"][0]["written_off"] = 100
    logical, info = audit(
        parent,
        [],
    )

    assert logical == []
    assert info["status"] == "unresolved"
    assert info["comparison_basis"] == "unavailable"
    assert info["delta"] is None


def test_whole_parent_gate_blocks_all_orders_before_fallback_allocation():
    p = payment(amount=250, huikuan_type="整笔回款")
    p["orders"] = [
        {"so": "SO1", "deliver": 100, "currency": "CNY"},
        {"so": "SO2", "deliver": 200, "currency": "CNY"},
    ]
    p["sod_lines"] = {}

    C.reconcile_writeoff_details([p], {"AR1": p}, [], DAY)
    records = C.expand_payment(p, {})

    assert {item["so"] for item in records} == {"SO1", "SO2"}
    assert {item["forced_code"] for item in records} == {
        "E_PARENT_WRITEOFF_MISMATCH"
    }
    assert "_parent_fallback_allocation" not in p


def test_duplicate_fold_still_over_is_unresolved():
    logical, info = audit(
        payment(),
        [row("HX1", amount=80), row("HX2", amount=80), row("HX3", amount=30)],
    )
    assert logical == []
    assert info["delta_dedup"] == -10
    assert info["status"] == "unresolved"


def test_same_so_different_amounts_are_not_folded():
    logical, info = audit(
        payment(),
        [row("HX1", amount=70), row("HX2", amount=40)],
    )
    assert logical == []
    assert info["status"] == "unresolved"
    assert not info["duplicate_groups"]


def test_validate_accepts_whole_parent_surplus_and_preserves_audit():
    parent = payment(amount=150, huikuan_type="整笔回款")
    parent["orders"][0]["written_off"] = 100
    _, audit_info = audit(parent, [])
    audits = {"AR1": audit_info}
    plan = {
        "duplicate_writeoff_audits": audits,
        "duplicate_writeoff_audit_sha256": W.audit_fingerprint(audits),
        "auto": [{
            "ar": "AR1", "so": "SO1", "sod": "SOD1", "ledger_row_ref": 2,
            "five_cols": {"计提": 100, "回款明细": 100, "是否结账": "是",
                          "收款时间": "2026-07-31", "收款方式": "汇"},
            "warning_codes": [],
            "duplicate_writeoff_audit": audit_info,
        }],
    }
    rows = {2: {"SO": "SO1", "SOD": "SOD1", "计提": None, "回款明细": None,
                "是否结账": "否", "收款时间": None, "收款方式": None,
                "差异": None, "_差异列存在": True, "应收金额": 100}}

    checked = V.validate(plan, rows)

    assert checked["counts"]["write"] == 1
    assert checked["counts"]["conflict"] == 0


def test_different_so_same_amounts_are_not_folded():
    logical, info = audit(
        payment(),
        [row("HX1", amount=100, so="SO1"), row("HX2", amount=100, so="SO2")],
    )
    assert logical == []
    assert info["status"] == "unresolved"
    assert not info["duplicate_groups"]


def test_same_record_id_across_snapshots_is_one_physical_not_system_duplicate():
    earlier = row("HX1")
    later = {**row("HX1"), "source": "核销明细_20260801.xlsx",
             "snapshot_date": dt.date(2026, 8, 1)}
    logical, info = audit(payment(), [earlier, later])
    assert len(logical) == 1
    assert info["physical_snapshot_duplicate_count"] == 1
    assert info["status"] == "normal"
    assert not info["duplicate_groups"]


def test_different_ids_identical_fields_survive_raw_stage_until_over():
    rows = [row("HX1"), row("HX2")]
    normal, normal_info = audit(payment(amount=200), rows)
    second, second_info = audit(payment(amount=100), rows)
    assert len(normal) == 2 and normal_info["status"] == "normal"
    assert len(second) == 1 and second_info["status"] == "recovered"


def test_revoked_record_is_excluded_from_all_totals():
    logical, info = audit(payment(), [row("HX1"), row("HX2", revoked="是")])
    assert len(logical) == 1
    assert info["raw_total"] == 100
    assert info["revoked_count"] == 1


def test_recovered_duplicate_changes_target_h_and_cumulative_r_together():
    p = payment()
    raw = [row("HX1"), row("HX2")]
    C.reconcile_writeoff_details([p], {"AR1": p}, raw, DAY)
    assert p["writeoffs"]["SO1"] == 100
    assert p["cumulative_writeoffs"]["SO1"] == 100


def test_same_so_across_parents_uses_running_cumulative_at_each_parent():
    p1 = payment("AR1", 100)
    p2 = payment("AR2", 50)
    p2["orders"] = [{"so": "SO1", "deliver": 150, "currency": "CNY"}]
    raw = [
        row("HX1", 100, ar="AR1"),
        row("HX2", 50, ar="AR2"),
    ]
    _, audits = C.reconcile_writeoff_details(
        [p1, p2], {"AR1": p1, "AR2": p2}, raw, DAY
    )
    assert audits["AR1"]["status"] == "normal"
    assert audits["AR2"]["status"] == "normal"
    assert p1["cumulative_writeoffs"]["SO1"] == 100
    assert p2["cumulative_writeoffs"]["SO1"] == 150
    assert p1["_writeoff_sequence_key_by_so"]["SO1"][1] == "HX1"
    assert p2["_writeoff_sequence_key_by_so"]["SO1"][1] == "HX2"


def test_historical_parent_audit_blocks_only_overlapping_so():
    old = payment("AR_OLD", amount=83420.79, local=83420.79)
    old["fee"] = 13.17
    old["orders"] = [
        {"so": "SO25120629", "deliver": 13500.0, "currency": "CNY"},
        {"so": "SO24110809", "deliver": 74940.0, "currency": "CNY"},
    ]

    current = payment("AR_CURRENT", amount=129600.0, local=129600.0)
    current["orders"] = [
        {"so": "SO25120629", "deliver": 13500.0, "currency": "CNY"},
        {"so": "SO25090362", "deliver": 20000.0, "currency": "CNY"},
        {"so": "SO26010085", "deliver": 30000.0, "currency": "CNY"},
        {"so": "SO26010086", "deliver": 30000.0, "currency": "CNY"},
        {"so": "SO26010088", "deliver": 36100.0, "currency": "CNY"},
    ]

    raw = [
        row("OLD-1", 13500.0, ar="AR_OLD", so="SO25120629", local=13500.0),
        row("OLD-2", 74940.0, ar="AR_OLD", so="SO24110809", local=74940.0),
        row("CUR-1", 13500.0, ar="AR_CURRENT", so="SO25120629", local=13500.0),
        row("CUR-2", 20000.0, ar="AR_CURRENT", so="SO25090362", local=20000.0),
        row("CUR-3", 30000.0, ar="AR_CURRENT", so="SO26010085", local=30000.0),
        row("CUR-4", 30000.0, ar="AR_CURRENT", so="SO26010086", local=30000.0),
        row("CUR-5", 36100.0, ar="AR_CURRENT", so="SO26010088", local=36100.0),
    ]

    C.reconcile_writeoff_details(
        [old, current],
        {"AR_OLD": old, "AR_CURRENT": current},
        raw,
        DAY,
    )

    assert old["duplicate_writeoff_audit"]["status"] == "unresolved"
    assert current["duplicate_writeoff_audit"]["status"] == "normal"
    assert set(current["_parent_audit_unresolved_by_so"]) == {"SO25120629"}
    assert "_parent_audit_unresolved" not in current

    records = C.expand_payment(current, {})

    assert {item["so"] for item in records} == {
        "SO25120629", "SO25090362", "SO26010085", "SO26010086", "SO26010088"
    }
    blocked = [item for item in records if item["so"] == "SO25120629"]
    allowed = [item for item in records if item["so"] != "SO25120629"]
    assert len(blocked) == 1
    assert blocked[0]["forced_code"] == "E_PARENT_WRITEOFF_MISMATCH"
    assert all("forced_code" not in item for item in allowed)


def test_validate_inherited_parent_audit_is_scoped_to_so():
    _, audit_info = audit(payment(amount=200), [row("HX1", amount=200)])
    audit_info["inherited_unresolved_by_so"] = {"SO1": ["AR_OLD"]}
    audits = {"AR1": audit_info}
    base = {
        "duplicate_writeoff_audits": audits,
        "duplicate_writeoff_audit_sha256": W.audit_fingerprint(audits),
    }
    common_item = {
        "ar": "AR1", "ledger_row_ref": 2,
        "five_cols": {"计提": 100, "回款明细": 100, "是否结账": "是",
                      "收款时间": "2026-07-31", "收款方式": "汇"},
        "warning_codes": [], "duplicate_writeoff_audit": audit_info,
    }
    rows = {
        2: {"SO": "SO1", "SOD": "SOD1", "计提": None, "回款明细": None,
            "是否结账": "否", "收款时间": None, "收款方式": None,
            "差异": None, "_差异列存在": True, "应收金额": 100},
        3: {"SO": "SO2", "SOD": "SOD2", "计提": None, "回款明细": None,
            "是否结账": "否", "收款时间": None, "收款方式": None,
            "差异": None, "_差异列存在": True, "应收金额": 100},
    }
    plan = {
        **base,
        "auto": [
            {**common_item, "so": "SO1", "sod": "SOD1"},
            {**common_item, "so": "SO2", "sod": "SOD2", "ledger_row_ref": 3},
        ],
    }

    checked = V.validate(plan, rows)

    assert checked["counts"]["conflict"] == 1
    assert checked["counts"]["write"] == 1
    assert "SO1" in next(
        item["_check"]["reason"]
        for item in checked["conflict"]
    )


def test_local_amounts_are_preferred_for_comparison():
    parent = payment(amount=10, local=100, currency="USD")
    logical, info = audit(
        parent,
        [row("HX1", amount=9, local=100, currency="USD"),
         row("HX2", amount=9, local=100, currency="USD")],
    )
    assert info["comparison_basis"] == "detail_local"
    assert info["status"] == "recovered"
    assert len(logical) == 1


def test_parent_duplicate_audit_uses_computed_amount_plus_fee_tax_total():
    parent = payment(amount=299, local=299, currency="CNY")
    parent["fee"] = 1
    C._prepare_parent_totals(parent)
    logical, info = audit(parent, [row("HX1", amount=300, local=300)])
    assert len(logical) == 1
    assert info["status"] == "normal"
    assert info["parent_net_local"] == 299
    assert info["parent_charge_local"] == 1
    assert info["parent_total_local"] == 300


def test_parent_duplicate_audit_prefers_zhiyun_total_received():
    parent = payment(amount=83420.79, local=83420.79, currency="CNY")
    parent.update({
        "fee": 13.17,
        "tax": 4992.87,
        "total_amount_orig": 88440.0,
        "total_amount_local": 88440.0,
    })
    C._prepare_parent_totals(parent)

    logical, info = audit(parent, [row("HX1", amount=88440, local=88440)])

    assert len(logical) == 1
    assert info["status"] == "normal"
    assert info["parent_total_orig"] == 88440.0
    assert info["parent_total_local"] == 88440.0


def test_original_amounts_used_only_when_currency_matches():
    logical, info = audit(
        payment(amount=100, currency="USD"),
        [row("HX1", amount=100, currency="USD")],
    )
    assert info["comparison_basis"] == "detail_original"
    assert info["status"] == "normal"
    assert len(logical) == 1


def test_incomparable_currency_or_missing_record_id_overage_is_unresolved():
    _, currency_info = audit(
        payment(amount=100, currency="USD"),
        [row("HX1", amount=200, currency="EUR")],
    )
    _, missing_id_info = audit(payment(), [row("", amount=200)])
    assert currency_info["status"] == "unresolved"
    assert missing_id_info["status"] == "unresolved"


def test_every_raw_row_has_explicit_disposition():
    rows = [
        row("HX1"),
        {**row("HX1"), "snapshot_date": dt.date(2026, 8, 1)},
        row("HX2", revoked="是"),
    ]
    _, info = audit(payment(), rows)
    assert len(info["records"]) == 3
    assert all(item["disposition"] in {
        "kept", "physical_snapshot_duplicate", "system_duplicate_ignored", "revoked"
    } for item in info["records"])


def test_unresolved_parent_cannot_enter_auto_and_audit_tamper_conflicts():
    recovered_rows = [row("HX1"), row("HX2")]
    _, recovered = audit(payment(), recovered_rows)
    audits = {"AR1": recovered}
    plan = {
        "duplicate_writeoff_audits": audits,
        "duplicate_writeoff_audit_sha256": W.audit_fingerprint(audits),
        "auto": [{
            "ar": "AR1", "so": "SO1", "sod": "SOD1", "ledger_row_ref": 2,
            "five_cols": {"计提": 100, "回款明细": 100, "是否结账": "是",
                          "收款时间": "2026-07-31", "收款方式": "汇"},
            "warning_codes": ["W_SYSTEM_DUPLICATE_WRITEOFF_COLLAPSED"],
            "duplicate_writeoff_audit": recovered,
        }],
    }
    rows = {2: {"SO": "SO1", "SOD": "SOD1", "计提": None, "回款明细": None,
                "是否结账": "否", "收款时间": None, "收款方式": None,
                "差异": None, "_差异列存在": True, "应收金额": 100}}
    assert V.validate(plan, rows)["counts"]["write"] == 1
    plan["duplicate_writeoff_audits"]["AR1"]["logical_total"] = 999
    checked = V.validate(plan, rows)
    assert checked["counts"]["conflict"] == 1
    assert "指纹不一致" in checked["conflict"][0]["_check"]["reason"]


def test_legacy_unresolved_parent_is_rejected_if_hand_edited_into_auto():
    _, current = audit(payment(amount=100), [row("HX1", amount=80), row("HX2", amount=30)])
    unresolved = {**current, "status": "unresolved", "reason": "旧计划未解决超核销"}
    audits = {"AR1": unresolved}
    plan = {
        "duplicate_writeoff_audits": audits,
        "duplicate_writeoff_audit_sha256": W.audit_fingerprint(audits),
        "auto": [{
            "ar": "AR1", "so": "SO1", "sod": "SOD1", "ledger_row_ref": 2,
            "five_cols": {"计提": 100, "回款明细": 100, "是否结账": "是",
                          "收款时间": "2026-07-31", "收款方式": "汇"},
            "warning_codes": [],
            "duplicate_writeoff_audit": unresolved,
        }],
    }
    rows = {2: {"SO": "SO1", "SOD": "SOD1", "计提": None, "回款明细": None,
                "是否结账": "否", "收款时间": None, "收款方式": None,
                "差异": None, "_差异列存在": True, "应收金额": 100}}
    checked = V.validate(plan, rows)
    assert checked["counts"]["conflict"] == 1
    assert "未解决" in checked["conflict"][0]["_check"]["reason"]


def test_validate_recomputes_whole_parent_gate_after_status_and_hash_tamper():
    parent = payment(amount=100, huikuan_type="整笔回款")
    parent["orders"][0]["written_off"] = 110
    _, unresolved = audit(parent, [])
    tampered = {
        **unresolved,
        "status": "parent_fallback",
        "error_code": "",
        "reason": "手工改成可写",
    }
    audits = {"AR1": tampered}
    plan = {
        "duplicate_writeoff_audits": audits,
        "duplicate_writeoff_audit_sha256": W.audit_fingerprint(audits),
        "auto": [{
            "ar": "AR1", "so": "SO1", "sod": "SOD1", "ledger_row_ref": 2,
            "five_cols": {"计提": 100, "回款明细": 100, "是否结账": "是",
                          "收款时间": "2026-07-31", "收款方式": "汇"},
            "warning_codes": [],
            "duplicate_writeoff_audit": tampered,
        }],
    }
    rows = {2: {"SO": "SO1", "SOD": "SOD1", "计提": None, "回款明细": None,
                "是否结账": "否", "收款时间": None, "收款方式": None,
                "差异": None, "_差异列存在": True, "应收金额": 100}}

    checked = V.validate(plan, rows)

    assert checked["counts"]["conflict"] == 1
    assert "低于订单金额合计超过" in checked["conflict"][0]["_check"]["reason"]


def test_fetch_contract_exposes_record_identity_and_new_version():
    assert F.MINGXI_COLS[0] == "核销记录NUM"
    assert "订单已核销金额" in F.XIADAN_COLS
    assert F.EXPORT_SCHEMA_VERSION == "2026-08-31-total-received-v7"
    assert "项目交付日期" in F.XIADAN_COLS
