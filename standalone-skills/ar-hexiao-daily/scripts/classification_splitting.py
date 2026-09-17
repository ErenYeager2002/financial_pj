"""Build sequential receipt chains and resolve SOD allocations."""
from __future__ import annotations

from typing import List
from typing import Optional
from typing import Tuple
import baseline_receipts as BR
import common
import fallback_sequence as FS
from classification_contract import BUSINESS_SETTLEMENT_TOL, TOL
from classification_ledger import LedgerIndex


def _make_same_so_multi_sod_aggregate(
    ref: int,
    group: List[dict],
    ledger: Optional[LedgerIndex],
    tolerance: float,
) -> Tuple[Optional[dict], str]:
    """同一物理核销记录的完整多 SOD 集合共用一行时，按 SO 级金额合并。"""
    if ledger is None:
        return None, "缺少盈亏表索引"
    sos = {str(x.get("so") or "").strip() for x in group}
    sods = {str(x.get("sod") or "").strip() for x in group}
    if len(sos) != 1 or "" in sos or len(sods) <= 1 or "" in sods:
        return None, "不是同一 SO 的多个有效 SOD"
    if len(group) != len(sods):
        return None, "同一 SOD 在同行组内重复出现"

    ars = {str(x.get("ar") or "").strip() for x in group}
    if len(ars) != 1 or "" in ars:
        return None, "多个 SOD 不属于同一父回款"
    sources = [x.get("split_payment_source") or {} for x in group]
    sequence_keys = [source.get("writeoff_sequence_key") for source in sources]
    if not all(isinstance(key, (list, tuple)) and len(key) >= 2 and str(key[1]).strip()
               for key in sequence_keys):
        return None, "缺少核销记录NUM，无法证明属于同一物理核销记录"
    normalized_keys = {tuple(str(part or "") for part in key) for key in sequence_keys}
    if len(normalized_keys) != 1:
        return None, "多个 SOD 来自不同物理核销记录"

    expected_sets = {
        tuple(sorted({str(sod or "").strip() for sod in (source.get("all_sods") or [])
                      if str(sod or "").strip()}))
        for source in sources
    }
    if len(expected_sets) != 1 or set(next(iter(expected_sets), ())) != sods:
        return None, "同行组不是该 SO 的完整 SOD 集合"

    amounts = [common.to_number(source.get("amount_local")) for source in sources]
    deliveries = [common.to_number(source.get("delivery_local")) for source in sources]
    so_deliveries = [common.to_number(source.get("so_delivery_local")) for source in sources]
    if any(value is None or float(value) <= 0 for value in amounts + deliveries + so_deliveries):
        return None, "缺少有效的本币 SOD 金额或 SO 交付金额"
    so_delivery = round(float(so_deliveries[0]), 2)
    if any(abs(float(value) - so_delivery) > max(tolerance, TOL) for value in so_deliveries):
        return None, "多个 SOD 携带的 SO 交付金额不一致"
    total_amount = round(sum(float(value) for value in amounts), 2)
    total_delivery = round(sum(float(value) for value in deliveries), 2)
    if abs(total_amount - so_delivery) > max(tolerance, TOL):
        return None, "多个 SOD 的本次核销合计不等于 SO 交付金额"
    if abs(total_delivery - so_delivery) > max(tolerance, TOL):
        return None, "多个 SOD 的交付额合计不等于 SO 交付金额"

    snap = ledger.row_snapshot.get(int(ref)) or {}
    so = next(iter(sos))
    if str(snap.get("so") or "").strip() not in ("", so):
        return None, "盈亏行 SO 与合并组不一致"
    existing_sod = str(snap.get("sod") or "").strip()
    ordered_sods = sorted(sods)
    if existing_sod in sods:
        ordered_sods.remove(existing_sod)
        ordered_sods.insert(0, existing_sod)
    combined_sod = "、".join(ordered_sods)

    dates = {str((x.get("five_cols") or {}).get("收款时间") or "") for x in group}
    ways = {str((x.get("five_cols") or {}).get("收款方式") or "") for x in group}
    if len(dates) != 1 or len(ways) != 1:
        return None, "多个 SOD 的收款时间或收款方式不一致"
    target = next(
        (x for x in group if str(x.get("sod") or "").strip() == existing_sod),
        sorted(group, key=lambda x: (str(x.get("sod") or ""), str(x.get("case_id") or "")))[0],
    )
    target_five = {
        "计提": so_delivery,
        "回款明细": total_amount,
        "是否结账": "是",
        "收款时间": next(iter(dates)) or None,
        "收款方式": next(iter(ways)) or None,
        "实收SOD": combined_sod,
    }
    return {
        "type": "same_so_multi_sod_aggregate",
        "source_receivable": common.to_number(snap.get("yingshou")),
        "source_five_cols": {
            "计提": snap.get("jiti"), "回款明细": snap.get("huikuan"),
            "是否结账": snap.get("jiezhang"),
            "收款时间": common.norm_date(snap.get("shoukuan_time")) or snap.get("shoukuan_time"),
            "收款方式": snap.get("shoukuan_way"), "实收SOD": snap.get("sod"),
        },
        "source_derived_cols": {"差异": snap.get("chayi")},
        "so": so,
        "ar": next(iter(ars)),
        "so_delivery": so_delivery,
        "current_received": total_amount,
        "combined_sod": combined_sod,
        "member_sods": ordered_sods,
        "member_case_ids": [str(x.get("case_id") or "") for x in group],
        "member_amounts": [round(float(value), 2) for value in amounts],
        "member_deliveries": [round(float(value), 2) for value in deliveries],
        "writeoff_sequence_key": list(sequence_keys[0]),
        "target_case_id": str(target.get("case_id") or ""),
        "target_five_cols": target_five,
        "target_derived_cols": {},
    }, ""

def _make_split_payment_chain(
    ref: int,
    group: List[dict],
    ledger: Optional[LedgerIndex],
    tolerance: float,
) -> Tuple[Optional[dict], str]:
    """同一 SO/SOD 的多父 AR 回款按核销记录顺序形成逐笔拆行链。"""
    if ledger is None:
        return None, "缺少盈亏表索引，无法建立分笔回款链"
    if len({(str(x.get("so") or ""), str(x.get("sod") or "")) for x in group}) != 1:
        return None, "同一盈亏行命中了不同 SO/SOD"
    ars = [str(x.get("ar") or "").strip() for x in group]
    if not all(ars) or len(set(ars)) != len(ars):
        return None, "父回款号缺失或重复，无法证明为不同父回款的分笔链"

    prepared = []
    for result in group:
        source = result.get("split_payment_source") or {}
        amount = common.to_number(source.get("amount_local"))
        cumulative = common.to_number(source.get("cumulative_local"))
        delivery = common.to_number(source.get("delivery_local"))
        order_key = source.get("writeoff_sequence_key") or source.get("fallback_sequence_key")
        if amount is None or cumulative is None or delivery is None:
            return None, "缺少本币本次额、运行累计额或最新交付额"
        if float(amount) <= 0:
            return None, "分笔回款金额必须大于零"
        if not isinstance(order_key, (list, tuple)) or len(order_key) < 2 or not str(order_key[1]).strip():
            return None, "缺少核销记录NUM，无法确定多笔父回款的安全顺序"
        prepared.append((tuple(str(x or "") for x in order_key), result, round(float(amount), 2),
                         round(float(cumulative), 2), round(float(delivery), 2)))
    prepared.sort(key=lambda item: item[0])
    if len({item[0] for item in prepared}) != len(prepared):
        return None, "核销记录顺序键重复，无法确定分笔先后"

    deliveries = [item[4] for item in prepared]
    if max(deliveries) - min(deliveries) > max(tolerance, TOL):
        return None, "同一分笔链的最新交付额不一致"
    latest = deliveries[-1]
    initial_cumulative = round(prepared[0][3] - prepared[0][2], 2)
    if initial_cumulative < -max(tolerance, TOL):
        return None, "首笔运行累计小于本次回款，累计口径不成立"
    expected = initial_cumulative
    for _, _, amount, cumulative, _ in prepared:
        expected = round(expected + amount, 2)
        if abs(expected - cumulative) > max(tolerance, TOL):
            return None, "运行累计未按父回款逐笔递增，禁止合并或跳笔"
        if cumulative > latest + max(tolerance, TOL):
            return None, "分笔累计超过最新交付额"

    opening_remaining = round(latest - initial_cumulative, 2)
    snap = ledger.row_snapshot.get(int(ref)) or {}
    current_receivable = common.to_number(snap.get("yingshou"))
    source_receivable = opening_remaining

    # 已有完整聚合结清行时，1 元以内的父回款尾差不再触发逐父 AR 拆行。
    # 例如 0.12 + 211463.88 = 211464.00：0.12 虽然实际到账，但业务口径
    # 把它视为结清容差，保留 211464.00 的聚合行。这里用小额父回款合计判断，
    # 避免多笔各自不超过 1 元、合计却超过 1 元时被错误忽略。
    settlement_tail_tolerance = BUSINESS_SETTLEMENT_TOL
    tiny_parent_total = round(sum(
        amount for _, _, amount, _, _ in prepared
        if amount <= settlement_tail_tolerance
    ), 2)
    aggregate_received = common.to_number(snap.get("huikuan"))
    aggregate_accrual = common.to_number(snap.get("jiti"))
    aggregate_is_settled = str(snap.get("jiezhang") or "").strip() == "是"
    final_cumulative = prepared[-1][3]
    if (
        0 < tiny_parent_total <= settlement_tail_tolerance
        and abs(final_cumulative - latest) <= max(tolerance, TOL)
        and aggregate_is_settled
        and current_receivable is not None
        and aggregate_received is not None
        and aggregate_accrual is not None
        and abs(float(current_receivable) - source_receivable) <= settlement_tail_tolerance
        and abs(float(aggregate_received) - source_receivable) <= settlement_tail_tolerance
        and abs(float(aggregate_accrual) - latest) <= settlement_tail_tolerance
    ):
        source_five = {
            "计提": snap.get("jiti"),
            "回款明细": snap.get("huikuan"),
            "是否结账": snap.get("jiezhang"),
            "收款时间": common.norm_date(snap.get("shoukuan_time")) or snap.get("shoukuan_time"),
            "收款方式": snap.get("shoukuan_way"),
            "实收SOD": snap.get("sod"),
        }
        return {
            "type": "preserve_aggregate_tail_tolerance",
            "source_receivable": source_receivable,
            "initial_cumulative": initial_cumulative,
            "latest_delivery": latest,
            "final_cumulative": final_cumulative,
            "parent_amounts": [item[2] for item in prepared],
            "tolerated_tail_amount": tiny_parent_total,
            "tolerance": settlement_tail_tolerance,
            "source_five_cols": source_five,
            "source_derived_cols": {"差异": snap.get("chayi")},
        }, ""

    # 新建分笔链时也应用同一业务尾差：独立小额父回款合计不超过 1 元，
    # 且本批累计已经达到最新交付额时，不为这些小额父回款单独创建业务行。
    # 金额并入最后一笔正常父回款；原父 AR、金额和顺序完整保存在审计字段中。
    effective_prepared = list(prepared)
    absorbed_tail_payments: List[dict] = []
    if (
        0 < tiny_parent_total <= settlement_tail_tolerance
        and abs(final_cumulative - latest) <= max(tolerance, TOL)
    ):
        tiny_indexes = [
            index for index, item in enumerate(prepared)
            if item[2] <= settlement_tail_tolerance
        ]
        non_tiny_indexes = [
            index for index, item in enumerate(prepared)
            if item[2] > settlement_tail_tolerance
        ]
        target_index = non_tiny_indexes[-1] if non_tiny_indexes else tiny_indexes[-1]
        absorbed_indexes = [index for index in tiny_indexes if index != target_index]
        if non_tiny_indexes:
            absorbed_indexes = tiny_indexes
        if absorbed_indexes:
            absorbed_set = set(absorbed_indexes)
            absorbed_amount = round(sum(prepared[index][2] for index in absorbed_indexes), 2)
            target = list(prepared[target_index])
            target[2] = round(float(target[2]) + absorbed_amount, 2)
            effective_prepared = []
            for index, item in enumerate(prepared):
                if index in absorbed_set:
                    result = item[1]
                    absorbed_tail_payments.append({
                        "case_id": result.get("case_id") or "",
                        "ar": result.get("ar") or "",
                        "amount": item[2],
                        "writeoff_sequence_key": list(item[0]),
                    })
                    continue
                effective_prepared.append(tuple(target) if index == target_index else item)

            running = initial_cumulative
            rebuilt = []
            for order_key, result, amount, _, delivery in effective_prepared:
                running = round(running + amount, 2)
                rebuilt.append((order_key, result, amount, running, delivery))
            effective_prepared = rebuilt

    steps: List[dict] = []
    previous_remaining = source_receivable
    for index, (order_key, result, amount, cumulative, _) in enumerate(effective_prepared):
        remaining = round(max(latest - cumulative, 0.0), 2)
        settled = remaining <= max(tolerance, TOL)
        if settled and index != len(effective_prepared) - 1:
            return None, "分笔链在最后一笔之前已经结清，后续回款会造成超额"
        paid_receivable = previous_remaining if settled else round(previous_remaining - remaining, 2)
        if paid_receivable < -max(tolerance, TOL):
            return None, "分笔后剩余应收反而增加，连续拆行不守恒"
        five = dict(result.get("five_cols") or {})
        # 已结清行的幂等判定会从盈亏表带回整行历史回款额；分笔链中每个
        # 父回款必须写自己的本次额，不能把历史合计复制到每个拆分步骤。
        five["回款明细"] = amount
        if settled:
            # 复跑时多笔可能都先命中链首的未计提行；最后结清步骤的计提
            # 必须由智云最新交付额确定，不能沿用该比较行的空值。
            five["计提"] = latest
        else:
            five["计提"] = None
        steps.append({
            "index": index,
            "case_id": result.get("case_id") or "",
            "ar": result.get("ar") or "",
            "so": result.get("so") or "",
            "sod": result.get("sod") or "",
            "writeoff_sequence_key": list(order_key),
            "sequence_basis": "writeoff_record" if (result.get("split_payment_source") or {}).get("writeoff_sequence_key") else FS.RULE,
            "current_received": amount,
            "cumulative_received": cumulative,
            "receivable": round(max(paid_receivable, 0.0), 2),
            "remaining_after": remaining,
            "settled": settled,
            "five_cols": five,
            "derived_cols": dict(result.get("derived_cols") or {}) if settled else {},
        })
        previous_remaining = remaining

    tail_audit = {
        "tolerance": settlement_tail_tolerance,
        "absorbed_total": round(sum(x["amount"] for x in absorbed_tail_payments), 2),
        "absorbed_payments": absorbed_tail_payments,
        "original_parent_amounts": [item[2] for item in prepared],
        "target_case_id": steps[-1]["case_id"] if absorbed_tail_payments else "",
    }

    if absorbed_tail_payments and len(steps) == 1:
        target = steps[0]
        return {
            "type": "settlement_tail_aggregate",
            "source_receivable": source_receivable,
            "initial_cumulative": initial_cumulative,
            "latest_delivery": latest,
            "final_cumulative": target["cumulative_received"],
            "target_case_id": target["case_id"],
            "target_five_cols": dict(target["five_cols"]),
            "target_derived_cols": dict(target.get("derived_cols") or {}),
            "source_five_cols": {
                "计提": snap.get("jiti"),
                "回款明细": snap.get("huikuan"),
                "是否结账": snap.get("jiezhang"),
                "收款时间": common.norm_date(snap.get("shoukuan_time")) or snap.get("shoukuan_time"),
                "收款方式": snap.get("shoukuan_way"),
                "实收SOD": snap.get("sod"),
            },
            "source_derived_cols": {"差异": snap.get("chayi")},
            "tail_tolerance_audit": tail_audit,
        }, ""

    final_unpaid = None
    if previous_remaining > max(tolerance, TOL):
        final_unpaid = {
            "receivable": previous_remaining,
            "five_cols": {
                "计提": None, "回款明细": None, "是否结账": "否",
                "收款时间": None, "收款方式": None,
                "实收SOD": steps[-1]["five_cols"].get("实收SOD") or steps[-1]["sod"],
            },
        }

    def row_matches(row_no: int, expected_receivable: float, expected_five: dict) -> bool:
        actual = ledger.row_snapshot.get(int(row_no)) or {}
        actual_receivable = common.to_number(actual.get("yingshou"))
        if actual_receivable is None or abs(float(actual_receivable) - float(expected_receivable)) > max(tolerance, TOL):
            return False
        if str(actual.get("so") or "").strip() != str(group[0].get("so") or "").strip():
            return False
        expected_sod = str(expected_five.get("实收SOD") or group[0].get("sod") or "").strip()
        if expected_sod and str(actual.get("sod") or "").strip() != expected_sod:
            return False
        pairs = (
            ("jiti", "计提"), ("huikuan", "回款明细"),
            ("jiezhang", "是否结账"), ("shoukuan_way", "收款方式"),
        )
        for actual_key, expected_key in pairs:
            actual_value = actual.get(actual_key)
            expected_value = expected_five.get(expected_key)
            if expected_key in ("计提", "回款明细"):
                a_num, e_num = common.to_number(actual_value), common.to_number(expected_value)
                if a_num is None or e_num is None:
                    if a_num is not None or e_num is not None:
                        return False
                elif abs(float(a_num) - float(e_num)) > max(tolerance, TOL):
                    return False
            elif str(actual_value or "").strip() != str(expected_value or "").strip():
                return False
        return common.norm_date(actual.get("shoukuan_time")) == common.norm_date(expected_five.get("收款时间"))

    expected_rows = [
        (float(step["receivable"]), step.get("five_cols") or {}) for step in steps
    ]
    if final_unpaid:
        expected_rows.append((float(final_unpaid["receivable"]), final_unpaid.get("five_cols") or {}))
    business_rows = sorted(ledger.business_rows(
        str(group[0].get("so") or ""), str(group[0].get("sod") or ""), ref
    ))
    materialized_starts = [
        start
        for start in business_rows
        if all(
            row_matches(start + offset, receivable, five)
            for offset, (receivable, five) in enumerate(expected_rows)
        )
    ]
    if len(materialized_starts) > 1:
        return None, "盈亏表中存在多条完整分笔链，无法唯一定位"
    materialized_start = materialized_starts[0] if materialized_starts else None
    if (
        current_receivable is None
        or abs(float(current_receivable) - opening_remaining) > max(tolerance, TOL)
    ) and materialized_start is None:
        return None, "当前未结清行应收与分笔链起点剩余金额不一致"

    operation = {
        "type": "split_payment_chain",
        "source_receivable": source_receivable,
        # 写前校验用这份快照证明当前行仍是生成分笔链时看到的聚合基线。
        # 这样可以安全迁移旧版“多父回款合并在一行”的已填状态，同时拒绝
        # 校验前后被人工改动过的行。
        "source_five_cols": {
            "计提": snap.get("jiti"),
            "回款明细": snap.get("huikuan"),
            "是否结账": snap.get("jiezhang"),
            "收款时间": common.norm_date(snap.get("shoukuan_time")) or snap.get("shoukuan_time"),
            "收款方式": snap.get("shoukuan_way"),
            "实收SOD": snap.get("sod"),
        },
        "source_derived_cols": {"差异": snap.get("chayi")},
        "initial_cumulative": initial_cumulative,
        "latest_delivery": latest,
        "steps": steps,
        "final_unpaid": final_unpaid,
        "materialized_chain_start": materialized_start,
        "tail_tolerance_audit": tail_audit if absorbed_tail_payments else {},
    }
    return operation, ""

def _expand_ambiguous_sod_waterfall(
    rec: dict,
    ledger: Optional[LedgerIndex],
    tolerance: float,
) -> List[dict]:
    """先确定盈亏应收组的交付口径，再分配逐 SO 回款到已登记业务行。"""
    if ledger is None or not rec.get("so"):
        return [rec]

    # An SO kept as one historical receivable group uses the SO's latest
    # delivery. Source SOD additions do not change that group's AR baseline.
    # Keep genuinely separate ledger SOD groups on the existing waterfall.
    source = rec.get("so_receipt_source") or {}
    so = str(rec["so"]).strip()
    so_rows = sorted(ledger.so_index.get(so, []))
    ledger_sods = {str((ledger.row_snapshot.get(row) or {}).get("sod") or "").strip() for row in so_rows}
    source_sods = set(source.get("all_sods") or [])
    may_resolve = not rec.get("forced_code") or (
        rec.get("forced_code") == "E5" and rec.get("default_first_sod")
    )
    if not may_resolve:
        return [rec]
    historical_scopes = [entry["receivable_group_scope"]
                         for entry in (getattr(ledger, "baseline_receipt_state", {}) or {}).values()
                         if (entry.get("receivable_group_scope") or {}).get("so") == so]
    if historical_scopes and (
        len(historical_scopes) != 1 or not source or
        ledger_sods != {historical_scopes[0].get("ledger_sod")} or
        not set(historical_scopes[0].get("source_sods") or []).issubset(source_sods)
    ):
        failed = dict(rec)
        failed.pop("default_first_sod", None)
        failed.update(forced_code="E_SOD_HISTORY_MISMATCH",
                      forced_reason="已登记按 SO 最新交付额核销的应收组，当前来源范围缺失、缩减或盈亏出现独立 SOD 组；禁止退回单个 SOD 金额核销。")
        return [failed]
    if source and may_resolve and len(ledger_sods) == 1 and "" not in ledger_sods and source_sods:
        sod = next(iter(ledger_sods))
        rows = BR.ledger_rows(ledger, so, sod)
        anchors = [row for row in rows.values() if row["应收金额"] is not None]
        baseline = sum(BR.cents(row["应收金额"]) or 0 for row in rows.values())
        delivery = BR.cents(source.get("delivery_local"))
        if historical_scopes and BR.cents(historical_scopes[0].get("baseline_receivable")) != baseline:
            failed = dict(rec)
            failed.pop("default_first_sod", None)
            failed.update(forced_code="E_SOD_HISTORY_MISMATCH",
                          forced_reason="SO 应收组的原始应收合计与已登记历史基线不一致，禁止继续核销。")
            return [failed]
        # Several physical AR rows may be ordinary splits of this one SOD.
        if anchors and baseline > 0:
            amounts = source.get("sod_delivery_local") or {}
            if delivery is None or delivery <= 0 or sod not in source_sods:
                failed = dict(rec)
                failed.pop("default_first_sod", None)
                failed.update(forced_code="E_SOD_HISTORY_MISMATCH", forced_reason="原始应收组缺少完整一致的 SO 最新交付额依据，不能用原始应收或单个来源 SOD 金额代替。")
                return [failed]
            resolved = {key: value for key, value in rec.items()
                        if not key.startswith("default_") and key not in {"forced_code", "forced_reason"}}
            resolved.update(
                sod=sod, amount_orig=source["amount_orig"], amount_local=source["amount_local"],
                deliver_local=source["delivery_local"], so_delivery_local=source["delivery_local"],
                cumulative_received_local=source.get("cumulative_local"),
                currency=source.get("currency") or rec.get("currency"),
                itemized_cumulative_authoritative=source.get("itemized_cumulative_authoritative", False),
                all_sods=sorted(source_sods), sod_delivery_local=amounts,
                writeoff_sequence_key=source.get("writeoff_sequence_key"),
                receivable_group_scope={"basis": "so_latest_delivery", "so": so,
                                        "ledger_sod": sod, "source_sods": sorted(source_sods),
                                        "baseline_receivable": baseline / 100},
                match_basis="SO 最新交付额/盈亏既有原始应收组",
            )
            return [resolved]

    if not rec.get("default_first_sod"):
        return [rec]

    import receipt_history
    existing_slices = receipt_history.existing_sod_slices(rec, ledger)
    if existing_slices:
        return existing_slices

    allocation = rec.get("parent_allocation_audit") or {}
    applied_cases = allocation.get("applied_cases") or {}
    if applied_cases and not rec.get("_replayed_applied_cases"):
        # Replay verified SOD slices before considering only the unpaid portion
        # of this SO's fixed allocation. Never move this money to another SO.
        total = float(rec.get("default_amount_local") or 0.0)
        original = float(rec.get("default_amount_orig") or 0.0)
        paid = round(sum(case["amount_local"] for case in applied_cases.values()), 2)
        if total <= TOL or paid > total + TOL:
            failed = dict(rec)
            failed.update(forced_code="E_PARENT_ALLOCATION_HISTORY_MISSING",
                          forced_reason="已写 SOD 金额超过本 SO 原分配或原分配金额缺失，禁止重新分配。")
            failed.pop("default_first_sod", None)
            return [failed]
        replayed = []
        for case in applied_cases.values():
            resolved = {key: value for key, value in rec.items()
                        if not key.startswith("default_") and key not in {"forced_code", "forced_reason"}}
            resolved.update(
                sod=case["sod"], amount_local=case["amount_local"],
                amount_orig=round(case["amount_local"] * original / total, 2),
                deliver_local=case.get("delivery_local"),
                cumulative_received_local=case.get("cumulative_local"),
                fallback_allocation_reused=True,
            )
            replayed.append(resolved)
        remaining = round(total - paid, 2)
        if remaining > TOL:
            pending = {**rec, "_replayed_applied_cases": True,
                       "default_amount_local": remaining,
                       "default_amount_orig": round(original * remaining / total, 2)}
            replayed.extend(_expand_ambiguous_sod_waterfall(pending, ledger, tolerance))
        return replayed

    so = str(rec.get("so") or "").strip()
    if ledger.so_settlement(so)["all_settled"]:
        return [rec]
    total_local = common.to_number(rec.get("default_amount_local"))
    total_orig = common.to_number(rec.get("default_amount_orig"))
    if total_local is None:
        total_local = total_orig
    if total_local is None or float(total_local) <= tolerance:
        failed = dict(rec)
        failed.pop("default_first_sod", None)
        failed["forced_code"] = "E5"
        failed["forced_reason"] = "同 SO 多 SOD 顺序核销缺少可用的本次核销金额。"
        return [failed]

    line_by_sod = {
        str(line.get("sod") or "").strip(): line
        for line in (rec.get("default_sod_lines") or [])
        if str(line.get("sod") or "").strip()
    }
    candidates: List[dict] = []
    capacity_details: List[dict] = []
    seen_sods = set()
    for row_no in sorted(ledger.so_index.get(so, [])):
        snap = ledger.row_snapshot.get(row_no) or {}
        if not ledger._is_outstanding(snap):
            continue
        sod = str(snap.get("sod") or "").strip()
        if not sod or sod in seen_sods:
            continue
        line = line_by_sod.get(sod)
        delivery = common.to_number((line or {}).get("deliver_local"))
        if line is None or delivery is None:
            failed = dict(rec)
            failed.pop("default_first_sod", None)
            failed["forced_code"] = "E5"
            failed["forced_reason"] = (
                f"同 SO 多 SOD 顺序核销命中未结清 SOD {sod or '-'}，"
                "但缺少对应的智云交付额，无法安全分配。"
            )
            return [failed]
        initial_receivable, existing_received, business_rows = ledger.business_totals(
            so, sod, row_no
        )
        if initial_receivable is None:
            failed = dict(rec)
            failed.pop("default_first_sod", None)
            failed["forced_code"] = "E5"
            failed["forced_reason"] = (
                f"同 SO 多 SOD 顺序核销命中未结清 SOD {sod}，"
                "但盈亏行缺少应收金额，无法验证拆分守恒。"
            )
            return [failed]
        existing_received = round(float(existing_received) + float((rec.get("_batch_sod_reserved") or {}).get(sod, 0)), 2)
        capacity = round(float(delivery) - float(existing_received), 2)
        capacity_details.append({"sod": sod, "rows": business_rows, "delivery": float(delivery), "history": float(existing_received), "capacity": capacity})
        if capacity <= tolerance:
            continue
        candidates.append({
            "row": int(row_no),
            "sod": sod,
            "line": line,
            "delivery": round(float(delivery), 2),
            "existing_received": round(float(existing_received), 2),
            "capacity": capacity,
            "business_rows": list(business_rows),
        })
        seen_sods.add(sod)

    available = round(sum(item["capacity"] for item in candidates), 2)
    if float(total_local) > available + tolerance:
        failed = dict(rec)
        failed.pop("default_first_sod", None)
        missing_sods = sorted(set(line_by_sod) - {
            str((ledger.row_snapshot.get(row) or {}).get("sod") or "").strip()
            for row in ledger.so_index.get(so, [])
        })
        history_conflict = any(item["capacity"] < -tolerance for item in capacity_details)
        failed["forced_code"] = "E_SOD_HISTORY_MISMATCH" if history_conflict or missing_sods else "E4"
        detail = "；".join(
            f"SOD={item['sod']}（行 {','.join(map(str, item['rows']))}）：交付 {item['delivery']:.2f} − 历史已填 {item['history']:.2f} = 可承接 {item['capacity']:.2f}"
            for item in capacity_details
        )
        failed["forced_reason"] = (
            f"SO={so} 未结清 SOD 可承接金额合计 {available:.2f}，小于本次核销 {float(total_local):.2f}。"
            + (detail or "未找到同时满足已登记 SOD、未结账且无已填回款的承接行")
            + (f"；来源 SOD 在盈亏表缺行：{','.join(missing_sods)}" if missing_sods else "")
            + "；当前无法将回款安全分配到 SOD。请核对历史回款的 SOD 归属和缺失业务行；SO 总额对平不能证明逐 SOD 归属正确。"
        )
        failed["sod_capacity_audit"] = capacity_details
        return [failed]

    remaining = round(float(total_local), 2)
    allocations: List[dict] = []
    for item in candidates:
        if remaining <= tolerance:
            break
        allocated = round(min(remaining, item["capacity"]), 2)
        if allocated <= tolerance:
            continue
        allocations.append({**item, "allocated_local": allocated})
        remaining = round(remaining - allocated, 2)

    if remaining > tolerance or not allocations:
        failed = dict(rec)
        failed.pop("default_first_sod", None)
        failed["forced_code"] = "E5"
        failed["forced_reason"] = "同 SO 多 SOD 顺序核销未形成完整、守恒的分配结果。"
        return [failed]

    total_orig_f = float(total_orig) if total_orig is not None else float(total_local)
    total_local_f = float(total_local)
    allocated_orig_running = 0.0
    audit_rows = []
    for index, item in enumerate(allocations):
        if index == len(allocations) - 1:
            allocated_orig = round(total_orig_f - allocated_orig_running, 2)
        else:
            allocated_orig = round(
                item["allocated_local"] * total_orig_f / total_local_f, 2
            )
            allocated_orig_running = round(allocated_orig_running + allocated_orig, 2)
        item["allocated_orig"] = allocated_orig
        audit_rows.append({
            "row": item["row"],
            "sod": item["sod"],
            "delivery_local": item["delivery"],
            "existing_received_local": item["existing_received"],
            "allocated_local": item["allocated_local"],
            "remaining_after": round(
                total_local_f - sum(x["allocated_local"] for x in allocations[: index + 1]),
                2,
            ),
        })

    expanded: List[dict] = []
    for index, item in enumerate(allocations):
        resolved = dict(rec)
        for key in (
            "forced_code", "forced_reason", "default_first_sod",
            "default_amount_orig", "default_amount_local",
            "default_cumulative_received_local", "default_sod_lines",
            "default_match_basis",
        ):
            resolved.pop(key, None)
        warnings = list(resolved.get("warning_codes") or [])
        for warning in ("W_DEFAULT_FIRST_SOD", "W_AMBIGUOUS_SOD_WATERFALL"):
            if warning not in warnings:
                warnings.append(warning)
        resolved.update({
            "sod": item["sod"],
            "amount_orig": item["allocated_orig"],
            "amount_local": item["allocated_local"],
            "deliver_local": item["delivery"],
            "currency": item["line"].get("currency") or rec.get("currency"),
            "cumulative_received_local": round(
                item["existing_received"] + item["allocated_local"], 2
            ),
            "itemized_cumulative_authoritative": False,
            "all_sods": sorted((rec.get("sod_delivery_local") or {}).keys()),
            "so_all_lines": rec.get("default_sod_lines") or [],
            "preferred_ledger_row": item["row"],
            "warning_codes": warnings,
            "match_basis": (
                f"{rec.get('default_match_basis') or '智云核销金额'}"
                "/同SO未结清SOD按行顺序核销"
            ),
            "ambiguous_sod_waterfall": {
                "rule": "ledger_open_sod_row_order_waterfall",
                "total_local": round(total_local_f, 2),
                "allocation_index": index,
                "allocation_count": len(allocations),
                "allocations": audit_rows,
            },
        })
        expanded.append(resolved)
    return expanded
