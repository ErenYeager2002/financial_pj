"""Allocate a parent receipt across its current SO delivery evidence."""
from __future__ import annotations
from execution_lineage import payment_source_lineage
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
import common
import fallback_allocation_ledger as FAL
import fallback_sequence as FS
from classification_amounts import _currency_key, _hold, _hold_each_source_order, _order_delivery_local, _prepare_parent_totals, _writeoff_business_amount, subset_sum_unique
from classification_contract import CoverageError, TOL

def _allocate_parent_by_delivery(
    p: dict,
    orders: List[dict],
    rates: Dict[str, float],
) -> Tuple[Dict[str, float], Dict[str, float], dict, Optional[str]]:
    """
    缺逐 SO 核销金额时，把父回款按 SO 交付额从小到大顺序承接。

    优先在人民币本币口径排序和分配；本币不可得时，仅允许父子原币一致后
    使用原币口径。每个 SO 先全额承接，余额不足时只给当前 SO 做部分回款，
    后续 SO 记为零分配但不生成写表任务。相同交付额按智云关联顺序稳定处理。
    """
    _prepare_parent_totals(p)
    if p.get("_charge_error"):
        return {}, {}, {}, str(p["_charge_error"])

    grouped: Dict[str, dict] = {}
    parent_currency = p.get("currency") or ""
    for index, order in enumerate(orders):
        so = str(order.get("so") or "").strip()
        deliver_orig = common.to_number(order.get("deliver"))
        if not so or deliver_orig is None:
            return {}, {}, {}, "关联订单缺 SO 或交付额，无法按交付额顺序分配父回款"
        deliver_local, _ = _order_delivery_local(
            float(deliver_orig), p, rates, order
        )
        item = grouped.setdefault(
            so,
            {
                "so": so,
                "first_index": index,
                "deliver_orig": 0.0,
                "deliver_local": 0.0,
                "local_complete": True,
                "currencies": set(),
            },
        )
        item["deliver_orig"] = round(
            float(item["deliver_orig"]) + float(deliver_orig), 2
        )
        if deliver_local is None:
            item["local_complete"] = False
        else:
            item["deliver_local"] = round(
                float(item["deliver_local"]) + float(deliver_local), 2
            )
        item["currencies"].add(
            _currency_key(order.get("currency") or parent_currency)
        )

    parent_local = common.to_number(p.get("total_amount_local"))
    parent_orig = common.to_number(p.get("total_amount_orig"))
    local_complete = bool(grouped) and all(
        item["local_complete"] for item in grouped.values()
    )
    parent_currency_key = _currency_key(parent_currency)
    original_comparable = (
        parent_orig is not None
        and bool(parent_currency_key)
        and all(
            item["currencies"] == {parent_currency_key}
            for item in grouped.values()
        )
    )
    if parent_local is not None and local_complete:
        allocation_basis = "local"
        parent_amount = round(float(parent_local), 2)
    elif original_comparable:
        allocation_basis = "original"
        parent_amount = round(float(parent_orig), 2)
    else:
        return (
            {},
            {},
            {},
            "父回款与订单交付无法形成统一本币或同币种原币口径，禁止顺序分配",
        )
    if parent_amount <= TOL:
        return {}, {}, {}, "父回款金额为空、为零或为负，无法形成有效核销"

    def basis_delivery(item: dict) -> float:
        return round(
            float(
                item["deliver_local"]
                if allocation_basis == "local"
                else item["deliver_orig"]
            ),
            2,
        )

    import current_parent_allocation
    restored = current_parent_allocation.reconstruct(p, grouped, allocation_basis, parent_amount)
    if restored is not None:
        return restored

    state = p.get("_fallback_allocation_state") or {"parents": {}}
    existing = (state.get("parents") or {}).get(str(p.get("ar") or ""))
    if existing:
        expected_amount = common.to_number(existing.get("parent_amount"))
        existing_basis = existing.get("basis")
        existing_rows = existing.get("allocations") or []
        current_deliveries = {
            item["so"]: basis_delivery(item) for item in grouped.values()
        }
        recorded_deliveries = {
            str(row.get("so") or ""): common.to_number(row.get("delivery"))
            for row in existing_rows
        }
        same_deliveries = set(current_deliveries) == set(recorded_deliveries) and all(
            recorded_deliveries.get(so) is not None
            and abs(float(recorded_deliveries[so]) - value) <= TOL
            for so, value in current_deliveries.items()
        )
        if (
            existing_basis != allocation_basis
            or expected_amount is None
            or abs(float(expected_amount) - parent_amount) > TOL
            or not same_deliveries
        ):
            return (
                {}, {}, {},
                "该父回款已有成功顺序分配记录，但总到账金额、币种口径或关联订单已变化，禁止覆盖原分配",
            )
        allocations_orig = {
            str(row["so"]): round(float(row["allocated_orig"]), 2)
            for row in existing_rows
            if common.to_number(row.get("allocated_orig")) is not None
            and float(row.get("allocated") or 0.0) > TOL
        }
        allocations_local = {
            str(row["so"]): round(float(row["allocated_local"]), 2)
            for row in existing_rows
            if common.to_number(row.get("allocated_local")) is not None
            and float(row.get("allocated") or 0.0) > TOL
        }
        audit = dict(existing)
        audit["reused_successful_allocation"] = True
        p["_fallback_cumulative_orig_by_so"] = {
            str(row["so"]): round(
                float(row.get("historical_received_orig") or 0.0)
                + float(row.get("allocated_orig") or 0.0), 2
            )
            for row in existing_rows if row.get("so")
        }
        p["_fallback_cumulative_local_by_so"] = {
            str(row["so"]): round(
                float(row.get("historical_received_local") or 0.0)
                + float(row.get("allocated_local") or 0.0), 2
            )
            for row in existing_rows
            if row.get("so") and row.get("allocated_local") is not None
        }
        return allocations_orig, allocations_local, audit, None

    ordered = sorted(
        grouped.values(),
        key=lambda item: (basis_delivery(item), item["first_index"], item["so"]),
    )
    remaining = parent_amount
    fallback_hist_orig, fallback_hist_local = FAL.history_totals(
        state,
        current_ar=str(p.get("ar") or ""),
        excluded_parent_ars=p.get("_detailed_parent_ars") or [],
    )
    detail_hist_orig = p.get("cumulative_writeoffs") or {}
    detail_hist_local = p.get("cumulative_writeoffs_local") or {}
    # Only a new allocation needs this guard; an existing parent was handled above.
    # Check the whole parent before skipping settled orders or assigning any money.
    settled_sos = set(p.get("_ledger_settled_sos") or [])
    if not set(grouped).issubset(settled_sos):
        for so in grouped:
            received = float((p.get("_ledger_received_local_by_so") or {}).get(so) or 0.0)
            known = round(float(detail_hist_local.get(so) or 0.0) + float(fallback_hist_local.get(so) or 0.0), 2)
            error = FAL.unexplained_receipts(str(p.get("ar") or ""), so, received, known)
            if error:
                p["_parent_allocation_error_code"] = "E_PARENT_ALLOCATION_HISTORY_MISSING"
                return {}, {}, {}, error
    detail_hist_orig = dict(detail_hist_orig)
    detail_hist_local = dict(detail_hist_local)
    for so, amount in (p.get("_batch_reserved_orig") or {}).items():
        detail_hist_orig[so] = round(float(detail_hist_orig.get(so) or 0) + amount, 2)
    for so, amount in (p.get("_batch_reserved_local") or {}).items():
        detail_hist_local[so] = round(float(detail_hist_local.get(so) or 0) + amount, 2)
    allocations_orig: Dict[str, float] = {}
    allocations_local: Dict[str, float] = {}
    cumulative_orig_by_so: Dict[str, float] = {}
    cumulative_local_by_so: Dict[str, float] = {}
    rows: List[dict] = []
    partial_sos: List[str] = []
    zero_sos: List[str] = []
    already_settled_sos: List[str] = []
    ledger_settled_sos = {
        str(so or "").strip() for so in (p.get("_ledger_settled_sos") or [])
        if str(so or "").strip()
    }
    for item in ordered:
        so = item["so"]
        delivery_basis = basis_delivery(item)
        historical_orig = round(
            float(detail_hist_orig.get(so) or 0.0) + float(fallback_hist_orig.get(so) or 0.0), 2
        )
        historical_local = round(
            float(detail_hist_local.get(so) or 0.0) + float(fallback_hist_local.get(so) or 0.0), 2
        )
        historical_basis = historical_local if allocation_basis == "local" else historical_orig
        if so in ledger_settled_sos:
            already_settled_sos.append(so)
            zero_sos.append(so)
            rows.append({
                "so": so,
                "delivery": delivery_basis,
                "historical_received": historical_basis,
                "outstanding_before": 0.0,
                "allocated": 0.0,
                "allocated_orig": 0.0,
                "allocated_local": 0.0 if item["local_complete"] else None,
                "historical_received_orig": historical_orig,
                "historical_received_local": historical_local,
                "status": "ledger_already_settled",
                "ledger_settled_bootstrap": True,
            })
            cumulative_orig_by_so[so] = historical_orig
            cumulative_local_by_so[so] = historical_local
            continue
        if historical_basis > delivery_basis + TOL:
            return {}, {}, {}, f"订单 {so} 的历史累计回款超过最新交付额，无法自动续核"
        outstanding_basis = round(max(delivery_basis - historical_basis, 0.0), 2)
        allocated_basis = round(min(max(remaining, 0.0), outstanding_basis), 2)
        if outstanding_basis <= TOL:
            already_settled_sos.append(so)
            zero_sos.append(so)
            rows.append({
                "so": so,
                "delivery": delivery_basis,
                "historical_received": historical_basis,
                "outstanding_before": 0.0,
                "allocated": 0.0,
                "allocated_orig": 0.0,
                "allocated_local": 0.0 if item["local_complete"] else None,
                "historical_received_orig": historical_orig,
                "historical_received_local": historical_local,
                "status": "already_settled",
            })
            cumulative_orig_by_so[so] = historical_orig
            cumulative_local_by_so[so] = historical_local
            continue
        if allocated_basis <= TOL:
            zero_sos.append(so)
            rows.append({
                "so": so,
                "delivery": delivery_basis,
                "historical_received": historical_basis,
                "outstanding_before": outstanding_basis,
                "allocated": 0.0,
                "allocated_orig": 0.0,
                "allocated_local": 0.0 if item["local_complete"] else None,
                "historical_received_orig": historical_orig,
                "historical_received_local": historical_local,
                "status": "zero",
            })
            cumulative_orig_by_so[so] = historical_orig
            cumulative_local_by_so[so] = historical_local
            continue

        is_full = abs(allocated_basis - outstanding_basis) <= TOL
        deliver_orig = round(float(item["deliver_orig"]), 2)
        deliver_local = (
            round(float(item["deliver_local"]), 2)
            if item["local_complete"]
            else None
        )
        if allocation_basis == "local":
            allocated_local = allocated_basis
            allocated_orig = (
                round(deliver_orig * allocated_basis / delivery_basis, 2)
                if delivery_basis > TOL
                else 0.0
            )
        else:
            allocated_orig = allocated_basis
            allocated_local = (
                round(deliver_local * allocated_basis / delivery_basis, 2)
                if deliver_local is not None and delivery_basis > TOL
                else None
            )
        allocations_orig[so] = allocated_orig
        if allocated_local is not None:
            allocations_local[so] = allocated_local
        if not is_full:
            partial_sos.append(so)
        rows.append({
            "so": so,
            "delivery": delivery_basis,
            "historical_received": historical_basis,
            "outstanding_before": outstanding_basis,
            "allocated": allocated_basis,
            "allocated_orig": allocated_orig,
            "allocated_local": allocated_local,
            "historical_received_orig": historical_orig,
            "historical_received_local": historical_local,
            "cumulative_after": round(historical_basis + allocated_basis, 2),
            "status": "full" if is_full else "partial",
        })
        cumulative_orig_by_so[so] = round(historical_orig + allocated_orig, 2)
        if allocated_local is not None:
            cumulative_local_by_so[so] = round(historical_local + allocated_local, 2)
        remaining = round(remaining - allocated_basis, 2)

    p["_fallback_cumulative_orig_by_so"] = cumulative_orig_by_so
    p["_fallback_cumulative_local_by_so"] = cumulative_local_by_so
    audit = {
        "basis": allocation_basis,
        "parent_amount": parent_amount,
        "parent_net_amount": round(float(p.get("amount_local") if allocation_basis == "local" else p.get("amount_orig")), 2),
        "parent_charge_amount": round(float(p.get("charge_amount_local") if allocation_basis == "local" else p.get("charge_amount_orig")), 2),
        "allocations": rows,
        "allocated_sos": list(allocations_orig),
        "partial_sos": partial_sos,
        "zero_sos": zero_sos,
        "already_settled_sos": already_settled_sos,
        "unallocated_parent_amount": round(max(remaining, 0.0), 2),
        "rule": "delivery_amount_ascending_outstanding_waterfall",
        "processing_order": {"rule": FS.RULE, "arrival_date": str(common.norm_date(p.get("arrival_date")) or ""), "ar": p.get("ar")},
    }
    return allocations_orig, allocations_local, audit, None
