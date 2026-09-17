"""Compose per-record decisions and route annual workbooks."""
from __future__ import annotations

from pathlib import Path
from typing import Dict
from typing import List
from typing import Optional
import baseline_receipts as BR
import common
import fallback_sequence as FS
import settlement_status
import current_receipt_cohort
from classification_accrual import _apply_so_accrual_gate
from classification_contract import TOL
from classification_decision import classify_one
from classification_ledger import LedgerIndex
from classification_splitting import _expand_ambiguous_sod_waterfall, _make_same_so_multi_sod_aggregate, _make_split_payment_chain
from classification_summary import _dist, build_ar_summary


def classify_records(
    records: List[dict],
    ledger: Optional[LedgerIndex] = None,
    rates: Optional[Dict[str, float]] = None,
    *, defer_sequence_guard: bool = False,
) -> dict:
    rates = rates or {}
    thr = common.tail_threshold()
    year_now = common.current_year()
    resolved_records: List[dict] = []
    resolved_groups = {}
    sod_reservations = {}
    expanded_fallback_sos = set()
    for rec in current_receipt_cohort.expand(records, ledger):
        source = rec.get("so_receipt_source") or {}
        if (rec.get("fallback_batch_ars") and rec.get("fallback_sequence_key")
                and not (rec.get("parent_allocation_audit") or {}).get("reused")
                and len(source.get("all_sods") or []) > 1
                and (not rec.get("forced_code") or rec.get("default_first_sod"))):
            identity = (rec.get("ar"), rec.get("so"))
            if identity in expanded_fallback_sos:
                continue
            expanded_fallback_sos.add(identity)
            rec = {**rec, "default_first_sod": True, "default_amount_local": source.get("amount_local"),
                   "default_amount_orig": source.get("amount_orig"),
                   "default_sod_lines": [{"sod": sod, "deliver_local": amount, "currency": source.get("currency")}
                                         for sod, amount in (source.get("sod_delivery_local") or {}).items()]}
        rec = {**rec, "_batch_sod_reserved": {sod: amount for (so, sod), amount in sod_reservations.items() if so == rec.get("so")} if (rec.get("fallback_sequence_key") or rec.get("writeoff_sequence_key")) else {}}
        for resolved in _expand_ambiguous_sod_waterfall(rec, ledger, max(thr, TOL)):
            if resolved.get("receivable_group_scope"):
                identity = BR.event_key(resolved)
                # SOD subset expansion may repeat one SO receipt. Collapse only
                # identical, source-bound slices of that same event.
                prior = resolved_groups.get(identity) if identity else None
                if prior is not None and prior.get("so_receipt_source") == resolved.get("so_receipt_source"):
                    continue
                if identity:
                    resolved_groups[identity] = resolved
            resolved_records.append(resolved)
            if ((resolved.get("fallback_sequence_key") or (resolved.get("writeoff_sequence_key") and resolved.get("ambiguous_sod_waterfall"))) and resolved.get("sod")
                    and not resolved.get("forced_code") and not resolved.get("fallback_allocation_reused")):
                key = (resolved.get("so"), resolved.get("sod"))
                sod_reservations[key] = round(sod_reservations.get(key, 0) + float(resolved.get("amount_local") or 0), 2)
    # Later receipts in this batch must not switch the same SOD's split mode.
    batch_cumulative = {}
    batch_first_cumulative = {}
    for rec in resolved_records:
        value = common.to_number(rec.get("cumulative_received_local"))
        key = (rec.get("so"), rec.get("sod"))
        if value is not None:
            batch_cumulative[key] = max(batch_cumulative.get(key, 0.0), float(value))
            batch_first_cumulative[key] = min(batch_first_cumulative.get(key, float(value)), float(value))
    results = []
    for rec in resolved_records:
        key = (rec.get("so"), rec.get("sod"))
        rec = {**rec, "_baseline_batch_cumulative": batch_cumulative.get(key),
               "_baseline_batch_first_cumulative": batch_first_cumulative.get(key)}
        result = classify_one(rec, ledger, rates, thr, year_now)
        if rec.get("_execution_source_lineage"):
            result["source_lineage"] = rec["_execution_source_lineage"]
        audit = rec.get("ambiguous_sod_waterfall") or {}
        if audit:
            result["reason"] = (
                "同一 SO 的逐单金额无法唯一落到 SOD，已按盈亏未结清行顺序核销。"
                + str(result.get("reason") or "")
            )
        results.append(result)

    import current_receipt_group
    current_receipt_group.attach(results, resolved_records, ledger)
    BR.combine(results)

    # 同一 SO/SOD 被不同父 AR 依次核销时，通常保留每一笔父回款并建立连续拆行链。
    # 已有完整聚合结清行且小额父回款尾差合计不超过 1 元时，保留聚合行并幂等跳过。
    # 已按本批回款证据幂等确认的记录不再参与当前批次的多父回款重组；
    # 只把尚未覆盖的本批记录交给分笔/合并判断，避免把已写行再次算进链。
    # 不同 SO/SOD、同一父 AR、缺记录号或运行累计不守恒时继续 E8 挂起。
    by_row: Dict[int, List[dict]] = {}
    for r in results:
        ref = r.get("ledger_row_ref")
        if (
            r["bucket"] == "auto"
            and ref is not None
            and not r.get("baseline_receipt_audit")
            and r.get("code") not in {
                "OK_ALREADY_SETTLED",
                settlement_status.SO_ALREADY_SETTLED,
                "OK_FALLBACK_ALLOCATION_ALREADY_APPLIED",
                "OK_ITEMIZED_CUMULATIVE_ALREADY_APPLIED",
            }
        ):
            by_row.setdefault(int(ref), []).append(r)

    for ref, group in by_row.items():
        if len(group) <= 1:
            continue
        aggregate, aggregate_error = _make_same_so_multi_sod_aggregate(
            ref, group, ledger, max(thr, TOL)
        )
        if aggregate is not None:
            target_case_id = str(aggregate["target_case_id"])
            group_id = f"same-so-multi-sod|{ref}|{aggregate['so']}|{aggregate['ar']}"
            for r in group:
                case_id = str(r.get("case_id") or "")
                if case_id == target_case_id:
                    r["five_cols"] = dict(aggregate["target_five_cols"])
                    r["derived_cols"] = {}
                    r["row_operation"] = aggregate
                    r["same_so_multi_sod_group_id"] = group_id
                    warnings = list(r.get("warning_codes") or [])
                    if "W_SAME_SO_MULTI_SOD_AGGREGATE" not in warnings:
                        warnings.append("W_SAME_SO_MULTI_SOD_AGGREGATE")
                    r["warning_codes"] = warnings
                    r["reason"] = (
                        f"{r.get('reason') or '核销命中'}；同一 SO 的多个 SOD 共用一行，"
                        "按 SO 交付金额合并核销"
                    )
                else:
                    r["five_cols"] = {}
                    r["derived_cols"] = {}
                    r.pop("row_operation", None)
                    r["same_so_multi_sod_absorbed"] = {
                        "target_case_id": target_case_id,
                        "group_id": group_id,
                        "member_sods": list(aggregate["member_sods"]),
                        "so_delivery": aggregate["so_delivery"],
                    }
                    r["reason"] = (
                        f"{r.get('reason') or '核销命中'}；已并入同一 SO 多 SOD 合并核销行，"
                        "不重复写金额"
                    )
            continue
        operation, chain_error = _make_split_payment_chain(ref, group, ledger, max(thr, TOL))
        if operation is not None:
            tail_audit = operation.get("tail_tolerance_audit") or {}
            absorbed_by_case = {
                str(item.get("case_id") or ""): item
                for item in (tail_audit.get("absorbed_payments") or [])
            }
            if operation.get("type") == "settlement_tail_aggregate":
                target_case_id = str(operation.get("target_case_id") or "")
                for r in group:
                    case_id = str(r.get("case_id") or "")
                    if case_id in absorbed_by_case:
                        r["five_cols"] = {}
                        r["derived_cols"] = {}
                        r.pop("row_operation", None)
                        r["tail_tolerance_absorbed"] = {
                            **absorbed_by_case[case_id],
                            "target_case_id": target_case_id,
                            "absorbed_total": tail_audit.get("absorbed_total"),
                            "tolerance": tail_audit.get("tolerance"),
                        }
                        r["reason"] = (
                            f"{r.get('reason') or '核销命中'}；本父回款属于结清尾差，"
                            "与同链其他小额父回款合计不超过 1.00 元，审计保留但不单独成行"
                        )
                        continue
                    if case_id != target_case_id:
                        r["bucket"] = "hold"
                        r["code"] = "E8"
                        r["reason"] = "结清尾差合并目标与父回款链不一致，禁止自动写入"
                        r["five_cols"] = {}
                        continue
                    r["five_cols"] = dict(operation.get("target_five_cols") or {})
                    r["derived_cols"] = dict(operation.get("target_derived_cols") or {})
                    r["row_operation"] = operation
                    warnings = list(r.get("warning_codes") or [])
                    if "W_SETTLEMENT_TAIL_TOLERATED" not in warnings:
                        warnings.append("W_SETTLEMENT_TAIL_TOLERATED")
                    r["warning_codes"] = warnings
                    r["reason"] = (
                        f"{r.get('reason') or '核销命中'}；结清尾差合计不超过 1.00 元，"
                        "小额父回款并入本行，实际父 AR 明细保留在审计字段"
                    )
                continue
            if operation.get("type") == "preserve_aggregate_tail_tolerance":
                source_five = dict(operation.get("source_five_cols") or {})
                for r in group:
                    r["five_cols"] = source_five
                    r["derived_cols"] = {}
                    r["row_operation"] = operation
                    r.pop("split_chain_group_id", None)
                    r.pop("split_chain_index", None)
                    r.pop("split_chain_count", None)
                    r["reason"] = (
                        f"{r.get('reason') or '核销命中'}；同一 SO/SOD 多父回款中的结清尾差合计 "
                        f"{operation['tolerated_tail_amount']:.2f} 元不超过 1.00 元，"
                        "保留现有聚合结清行，不为该尾差单独拆行"
                    )
                continue
            group_id = f"split-payment-chain|{ref}|{group[0].get('so') or ''}|{group[0].get('sod') or ''}"
            by_case = {step["case_id"]: step for step in operation["steps"]}
            for r in group:
                case_id = str(r.get("case_id") or "")
                if case_id in absorbed_by_case:
                    r["five_cols"] = {}
                    r["derived_cols"] = {}
                    r.pop("row_operation", None)
                    r.pop("split_chain_group_id", None)
                    r.pop("split_chain_index", None)
                    r.pop("split_chain_count", None)
                    r["tail_tolerance_absorbed"] = {
                        **absorbed_by_case[case_id],
                        "target_case_id": tail_audit.get("target_case_id"),
                        "absorbed_total": tail_audit.get("absorbed_total"),
                        "tolerance": tail_audit.get("tolerance"),
                    }
                    r["reason"] = (
                        f"{r.get('reason') or '核销命中'}；本父回款属于结清尾差，"
                        "合计不超过 1.00 元，审计保留但不单独成行"
                    )
                    continue
                step = by_case.get(case_id)
                if step is None:
                    r["bucket"] = "hold"
                    r["code"] = "E8"
                    r["reason"] = "分笔链步骤与父回款记录无法对应，禁止自动写入"
                    r["five_cols"] = {}
                    continue
                r["five_cols"] = dict(step["five_cols"])
                r["derived_cols"] = dict(step.get("derived_cols") or {})
                r["row_operation"] = operation
                r["split_chain_group_id"] = group_id
                r["split_chain_index"] = int(step["index"])
                r["split_chain_count"] = len(operation["steps"])
                warnings = list(r.get("warning_codes") or [])
                if "W_SPLIT_PAYMENT_SEQUENTIAL" not in warnings:
                    warnings.append("W_SPLIT_PAYMENT_SEQUENTIAL")
                r["warning_codes"] = warnings
                r["reason"] = (
                    f"{r.get('reason') or '核销命中'}；同一 SO/SOD 的 {len(operation['steps'])} 行业务回款"
                    f"按{'到账日期及AR单号' if step.get('sequence_basis') == FS.RULE else '核销记录'}顺序逐笔拆行，本笔序号 {int(step['index']) + 1}"
                )
            continue

        if aggregate_error and "不同 SO/SOD" in chain_error:
            chain_error = f"{chain_error}；多 SOD 合并未通过：{aggregate_error}"
        # 真正的多行/多笔歧义继续 E8，但原因显示实际笔数，不再硬编码“两笔”。
        for r in group:
            r["bucket"] = "hold"
            r["code"] = "E8"
            r["reason"] = (
                f"盈亏表第 {ref} 行被本批 {len(group)} 笔回款同时命中，"
                f"无法建立安全的逐笔分笔回款链：{chain_error}"
            )
            r["five_cols"] = {}

    import receipt_sequence
    receipt_sequence.guard(results)

    # 行冲突、分笔链和同 SO 多 SOD 合并均已定型后，再执行 SO 级计提闸。
    # 这样判断依据是本批最终会落表的状态，不会被单条 classify_one 的中间态误导。
    _apply_so_accrual_gate(results, ledger, max(thr, TOL))
    import receipt_correction
    receipt_correction.finalize_plans(results)

    if not defer_sequence_guard:
        FS.guard(results)
    auto = [r for r in results if r["bucket"] == "auto"]
    hold = [r for r in results if r["bucket"] == "hold"]
    exc = [r for r in results if r["bucket"] == "exception"]
    return {
        "auto": auto,
        "hold": hold,
        "exception": exc,
        "counts": {
            "auto": len(auto), "hold": len(hold),
            "exception": len(exc), "total": len(results),
        },
        "e_code_dist": _dist(results),
        "ar_summary": build_ar_summary(results),
    }

def classify_records_by_year(
    records: List[dict],
    ledgers: Dict[int, LedgerIndex],
    rates: Optional[Dict[str, float]] = None,
    ledger_paths: Optional[Dict[int, Path]] = None,
) -> dict:
    """只按智云订单详情的项目交付日期选择年度盈亏表；缺失或冲突时挂账。"""
    rates = rates or {}
    ledger_paths = ledger_paths or {}
    grouped: Dict[int, List[dict]] = {}
    unrouted: List[dict] = []
    for order, source in enumerate(records):
        rec = dict(source)
        rec["_year_route_order"] = order
        delivery_date = common.norm_date(rec.get("delivery_date"))
        if delivery_date is None:
            rec["target_ledger_year"] = None
            rec["target_ledger_path"] = ""
            if not rec.get("forced_code"):
                issue = str(rec.get("delivery_date_issue") or "").strip()
                conflict = "冲突" in issue
                rec["forced_code"] = (
                    "E_DELIVERY_DATE_CONFLICT" if conflict else "E_DELIVERY_DATE_MISSING"
                )
                rec["forced_reason"] = (
                    issue
                    or "智云订单详情缺少项目交付日期，无法确定年度盈亏表；禁止按 SO/SOD 编号推测"
                )
            unrouted.append(rec)
            continue
        year = delivery_date.year
        rec["delivery_date"] = delivery_date
        rec["target_ledger_year"] = year
        rec["target_ledger_path"] = str(ledger_paths.get(year) or "")
        grouped.setdefault(int(year), []).append(rec)

    all_results: List[dict] = []
    if unrouted:
        part = classify_records(unrouted, None, rates, defer_sequence_guard=True)
        for bucket in ("auto", "hold", "exception"):
            all_results.extend(part.get(bucket) or [])
    for year, year_records in grouped.items():
        part = classify_records(year_records, ledgers.get(year), rates, defer_sequence_guard=True)
        for bucket in ("auto", "hold", "exception"):
            all_results.extend(part.get(bucket) or [])

    FS.guard(all_results)
    all_results.sort(key=lambda item: int(item.pop("_year_route_order", 0) or 0))
    auto = [r for r in all_results if r.get("bucket") == "auto"]
    hold = [r for r in all_results if r.get("bucket") == "hold"]
    exc = [r for r in all_results if r.get("bucket") == "exception"]
    return {
        "auto": auto,
        "hold": hold,
        "exception": exc,
        "counts": {
            "auto": len(auto), "hold": len(hold),
            "exception": len(exc), "total": len(all_results),
        },
        "e_code_dist": _dist(all_results),
        "ar_summary": build_ar_summary(all_results),
        "ledger_targets": {
            str(year): str(path) for year, path in sorted(ledger_paths.items())
        },
    }
