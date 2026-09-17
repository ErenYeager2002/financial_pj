"""Expand parent receipts into source-bound SO and SOD records."""
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


from classification_parent_allocation import _allocate_parent_by_delivery


def expand_payment(p: dict, rates: Dict[str, float]) -> List[dict]:
    """一笔到账 → 若干 SOD 级 record。**任何情况下至少产出一条**（不许静默丢）。"""
    _prepare_parent_totals(p)
    sod_lines: Dict[str, List[dict]] = p.get("sod_lines") or {}
    orders = p.get("orders") or []
    route_fields_by_so = {
        str(order.get("so") or "").strip(): {
            "delivery_date": order.get("delivery_date"),
            "delivery_date_issue": order.get("delivery_date_issue") or "",
        }
        for order in orders if str(order.get("so") or "").strip()
    }
    duplicate_audit = p.get("duplicate_writeoff_audit") or {}
    source_sos = {"", *sod_lines, *(p.get("writeoffs") or {})}
    source_sos.update(str(order.get("so") or "").strip() for order in orders)
    source_lineages = {so: payment_source_lineage(p, so) for so in source_sos}
    so_receipt_sources: Dict[str, dict] = {}

    def finish(items: List[dict]) -> List[dict]:
        # 零分配的整单已结账 SO 也必须有日清记录，并在分类和写前重新复核。
        present_sos = {str(item.get("so") or "").strip() for item in items}
        for allocation in (p.get("_parent_fallback_allocation") or {}).get("allocations") or []:
            so = str(allocation.get("so") or "").strip()
            if allocation.get("status") == "ledger_already_settled" and so and so not in present_sos:
                # A zero receipt allocation does not erase the order's delivery.
                # Preserve the same order-owned currency conversion used above;
                # missing source amounts/rates stay missing for the flow guard.
                deliveries = [
                    _order_delivery_local(order.get("deliver"), p, rates, order)[0]
                    for order in orders if str(order.get("so") or "").strip() == so
                ]
                delivery_local = (
                    round(sum(deliveries), 2)
                    if deliveries and all(value is not None for value in deliveries)
                    else None
                )
                items.append(_hold(
                    p, "E_SETTLED_SO_RECHECK", "顺序分配时盈亏表显示整 SO 已结账，本父回款分配 0；需复核当前全部业务行。",
                    so=so, amount_orig=0.0, amount_local=0.0,
                    deliver_local=delivery_local, so_delivery_local=delivery_local,
                    all_sods=[str(line.get("sod") or "").strip() for line in (sod_lines.get(so) or []) if line.get("sod")],
                ))
                present_sos.add(so)
        order_by_so = {
            str(order.get("so") or "").strip(): order
            for order in orders if str(order.get("so") or "").strip()
        }
        for item in items:
            order = (p.get("_parent_fallback_allocation") or {}).get("processing_order") or {}
            if item.get("forced_code") == FS.ZERO:
                item["zero_reserved_local"] = (p.get("_batch_reserved_local") or {}).get(item.get("so"), 0.0)
            if not item.get("writeoff_sequence_key") and order.get("arrival_date"):
                item["fallback_sequence_key"] = [order["arrival_date"], order["ar"]]
            item["_execution_source_lineage"] = source_lineages.get(str(item.get("so") or "").strip())
            if item.get("so") in so_receipt_sources:
                item["so_receipt_source"] = so_receipt_sources[item["so"]]
            allocation = p.get("_parent_fallback_allocation") or {}
            for allocated in allocation.get("allocations") or []:
                if allocated.get("so") == item.get("so"):
                    reused = bool(allocation.get("reused_successful_allocation"))
                    applied = reused and (
                        "applied_sos" not in allocation or item.get("so") in allocation["applied_sos"]
                    )
                    item["parent_allocation_audit"] = {
                        "ar": p.get("ar"), "so": item.get("so"),
                        "allocated_local": allocated.get("allocated_local"),
                        "historical_received_local": allocated.get("historical_received_local"),
                        "reused": reused, "applied": applied,
                    }
                    item["fallback_allocation_reused"] = applied
                    if "applied_cases" in allocation:
                        item["parent_allocation_audit"]["applied_cases"] = {
                            key: case for key, case in allocation["applied_cases"].items()
                            if case["so"] == item.get("so")
                        }
                    break
            route_fields = route_fields_by_so.get(str(item.get("so") or "").strip()) or {}
            item.setdefault("delivery_date", route_fields.get("delivery_date"))
            item.setdefault("delivery_date_issue", route_fields.get("delivery_date_issue") or "")
            item.setdefault("sales_name", p.get("sales_name") or "")
        if duplicate_audit:
            for item in items:
                item["duplicate_writeoff_audit"] = duplicate_audit
                if duplicate_audit.get("status") == "recovered":
                    item.setdefault("warning_codes", []).append(
                        "W_SYSTEM_DUPLICATE_WRITEOFF_COLLAPSED"
                    )
                if str(duplicate_audit.get("comparison_basis") or "").startswith(
                    "delivery_fallback"
                ):
                    so = str(item.get("so") or "").strip()
                    order = order_by_so.get(so) or {}
                    if common.to_number((p.get("writeoffs_local") or {}).get(so)) is not None:
                        item["local_amount_basis"] = "zhiyun_delivery_local"
                    elif (
                        common.to_number(order.get("rate")) is not None
                        and float(common.to_number(order.get("rate"))) > 0
                    ):
                        item["local_amount_basis"] = "order_exchange_rate"
                    elif common.is_cny(order.get("currency") or p.get("currency") or ""):
                        item["local_amount_basis"] = "cny_same_currency"
                    else:
                        item["local_amount_basis"] = ""
                        item["forced_code"] = "E6"
                        item["forced_reason"] = (
                            f"外币订单 {so} 既没有交付额本币，也没有有效订单汇率，禁止按原币写表"
                        )
                    item.setdefault("warning_codes", []).append(
                        "W_WHOLE_PAYMENT_DELIVERY_FALLBACK"
                    )
        return items

    unresolved = p.get("_parent_audit_unresolved")
    if not unresolved and p.get("_system_over_writeoff_unresolved"):
        unresolved = {
            "code": "E_SYSTEM_OVER_WRITEOFF_UNRESOLVED",
            "reason": p.get("_system_over_writeoff_unresolved"),
        }
    if unresolved:
        return finish(_hold_each_source_order(
            p,
            unresolved.get("code") or "E_PARENT_WRITEOFF_MISMATCH",
            f"父回款需人工检查：{unresolved.get('reason') or '父AR金额守恒检查未通过'}",
        ))

    if not orders:
        return finish([_hold(
            p, "E7",
            "这笔到账在智云没关联任何下单（下单栏为空）——先去智云看看这笔回款建对了没",
        )])

    # 有逐 SO 本次核销额时原样使用，费用只作为父回款审计信息，不二次加到逐单金额。
    # 缺逐 SO 金额时，总到账（净到账+明确费用）按剩余未收从小到大依次承接。
    writeoffs = dict(p.get("writeoffs") or {})
    has_itemized_writeoff = bool(writeoffs)
    detail_cumulative_orig = dict(p.get("cumulative_writeoffs") or {})
    detail_cumulative_local = dict(p.get("cumulative_writeoffs_local") or {})
    fallback_history_orig: Dict[str, float] = {}
    fallback_history_local: Dict[str, float] = {}
    effective_cumulative_orig = dict(detail_cumulative_orig)
    effective_cumulative_local = dict(detail_cumulative_local)
    if has_itemized_writeoff:
        # 逐 SO 明细只覆盖它所在的父 AR，不能抹掉此前已经成功写表的无明细父回款。
        # 两类来源统一进入截至当前核销日的 R；有逐 SO 明细的父 AR 从兜底台账排除，
        # 避免同一父回款既按父金额、又按逐单明细重复累计。
        fallback_history_orig, fallback_history_local = FAL.history_totals(
            p.get("_fallback_allocation_state") or {"parents": {}},
            current_ar=str(p.get("ar") or ""),
            excluded_parent_ars=p.get("_detailed_parent_ars") or [],
            as_of_date=p.get("hexiao_date"),
        )
        for so, amount in fallback_history_orig.items():
            effective_cumulative_orig[so] = round(
                float(effective_cumulative_orig.get(so) or 0.0) + float(amount), 2
            )
        for so, amount in fallback_history_local.items():
            effective_cumulative_local[so] = round(
                float(effective_cumulative_local.get(so) or 0.0) + float(amount), 2
            )
        p["_itemized_cumulative_detail_orig_by_so"] = detail_cumulative_orig
        p["_itemized_cumulative_detail_local_by_so"] = detail_cumulative_local
        p["_itemized_cumulative_fallback_orig_by_so"] = fallback_history_orig
        p["_itemized_cumulative_fallback_local_by_so"] = fallback_history_local
        p["_effective_cumulative_orig_by_so"] = effective_cumulative_orig
        p["_effective_cumulative_local_by_so"] = effective_cumulative_local
    fallback_local_by_so: Dict[str, float] = {}
    comparison_basis = ""
    if writeoffs:
        H = writeoffs
        comparison_basis = str(duplicate_audit.get("comparison_basis") or "")
        if comparison_basis.startswith("order_written_off"):
            basis = "整笔回款订单已核销金额(父AR守恒检查已通过)"
        elif comparison_basis.startswith("delivery_fallback"):
            basis = "整笔回款订单交付额兜底(全部订单无已核销金额且父AR守恒检查已通过)"
        else:
            basis = "智云逐SO本次核销金额(费用仅作父回款总额审计，不重复分配)"
    else:
        H = {}
        missing_delivery_sos = sorted({
            str(o.get("so") or "").strip() for o in orders
            if o.get("deliver") is None and o.get("so")
        })
        if missing_delivery_sos:
            return finish([
                _hold(
                    p, "E7",
                    (
                        f"下单 {so} 没有交付额，且 SOD 金额不完整，判不了"
                        if so in missing_delivery_sos
                        else f"同笔回款含无交付额订单 {','.join(missing_delivery_sos)}，整笔先挂起"
                    ),
                    so=so,
                )
                for so in sorted({str(o.get("so") or "").strip() for o in orders if o.get("so")})
            ])
        H, fallback_local_by_so, allocation_audit, allocation_error = (
            _allocate_parent_by_delivery(p, orders, rates)
        )
        if not allocation_error:
            p["_parent_fallback_allocation"] = allocation_audit
            if not H and allocation_audit.get("allocations") and all(
                entry.get("status") == "ledger_already_settled" for entry in allocation_audit["allocations"]
            ):
                return finish([])
        if not allocation_error and not H and allocation_audit.get("processing_order") and (
            p.get("_batch_previous_ars") or allocation_audit.get("reused_successful_allocation")
        ) and allocation_audit.get("allocations") and all(
            row.get("status") == "already_settled" for row in allocation_audit["allocations"]
        ):
            return finish([_hold(p, FS.ZERO, "前序回款已占满订单应收，本笔分配0，父回款余额保留审计", so=row["so"],
                amount_orig=0.0, amount_local=0.0, deliver_local=next((_order_delivery_local(o.get("deliver"), p, rates, o)[0] for o in orders if o.get("so") == row["so"]), None))
                for row in allocation_audit["allocations"]])
        if allocation_error or not H:
            return finish(_hold_each_source_order(
                p,
                p.get("_parent_allocation_error_code") or "E1",
                allocation_error or "父回款按交付额顺序分配后没有可核销订单",
            ))
        p["_parent_fallback_allocation"] = allocation_audit
        basis = "智云无逐SO金额=父回款总到账按交付额从小到大续核"

    business_local_by_so = (
        p.get("writeoffs_local") or {}
        if has_itemized_writeoff
        else fallback_local_by_so
    )
    delivery_fallback_itemized = (
        has_itemized_writeoff and comparison_basis.startswith("delivery_fallback")
    )

    def itemized_local(
        amount: Optional[float],
        order: Optional[dict],
        *,
        explicit_local: Optional[float] = None,
        explicit_orig: Optional[float] = None,
    ) -> Tuple[Optional[float], Optional[str]]:
        if delivery_fallback_itemized:
            return _order_delivery_local(
                amount, p, rates, order,
                explicit_local=explicit_local,
                explicit_orig=explicit_orig,
            )
        return _writeoff_business_amount(
            amount,
            explicit_local=explicit_local,
            explicit_orig=explicit_orig,
        )

    out: List[dict] = []
    deliver_by_so: Dict[str, float] = {}
    order_by_so: Dict[str, dict] = {}
    for o in orders:
        if o.get("so"):
            order_by_so[o["so"]] = o
        if o.get("deliver") is not None:
            deliver_by_so[o["so"]] = round(deliver_by_so.get(o["so"], 0.0) + float(o["deliver"]), 2)

    for so, h in H.items():
        lines = sod_lines.get(so) or []
        chosen: Optional[List[dict]] = None
        how = ""
        order = order_by_so.get(so) or {}
        so_delivery_orig = deliver_by_so.get(so)
        if has_itemized_writeoff:
            so_delivery_local, _ = itemized_local(
                so_delivery_orig, order,
                explicit_local=business_local_by_so.get(so),
                explicit_orig=h,
            )
        else:
            so_delivery_local, _ = _order_delivery_local(
                so_delivery_orig, p, rates, order
            )
        all_sods = sorted({
            str(x.get("sod") or "").strip() for x in lines
            if str(x.get("sod") or "").strip()
        })
        # SO 级计提闸需要知道该 SO 下每个 SOD 的最新本币交付额。这里一次性
        # 随订单明细固化，后续不得用盈亏表旧应收或 SO/SOD 编号反推。
        sod_delivery_local: Dict[str, float] = {}
        for one_line in lines:
            one_sod = str(one_line.get("sod") or "").strip()
            one_delivery = common.to_number(one_line.get("deliver"))
            if not one_sod or one_delivery is None:
                continue
            if has_itemized_writeoff:
                one_local, _ = itemized_local(
                    one_delivery, order,
                    explicit_local=business_local_by_so.get(so),
                    explicit_orig=h,
                )
            else:
                one_local, _ = _order_delivery_local(
                    one_delivery, p, rates, order,
                    explicit_local=business_local_by_so.get(so),
                    explicit_orig=h,
                )
            if one_local is not None:
                sod_delivery_local[one_sod] = round(
                    sod_delivery_local.get(one_sod, 0.0) + float(one_local), 2
                )
        current_local = None
        if has_itemized_writeoff:
            current_local, _ = itemized_local(
                h, order,
                explicit_local=business_local_by_so.get(so),
                explicit_orig=h,
            )
        else:
            current_local, _ = _order_delivery_local(
                h, p, rates, order,
                explicit_local=business_local_by_so.get(so),
                explicit_orig=h,
            )
        default_lines = []
        for one_line in lines:
            one = dict(one_line)
            if has_itemized_writeoff:
                one["deliver_local"], _ = itemized_local(
                    one.get("deliver"), order,
                    explicit_local=business_local_by_so.get(so),
                    explicit_orig=h,
                )
            else:
                one["deliver_local"], _ = _order_delivery_local(
                    one.get("deliver"), p, rates, order
                )
            default_lines.append(one)
        default_cumulative_local = None
        default_cumulative_orig = (
            effective_cumulative_orig.get(so)
            if has_itemized_writeoff
            else (p.get("_fallback_cumulative_orig_by_so") or {}).get(so)
        )
        if default_cumulative_orig is not None:
            if has_itemized_writeoff:
                default_cumulative_local, _ = itemized_local(
                    default_cumulative_orig, order,
                    explicit_local=effective_cumulative_local.get(so),
                    explicit_orig=default_cumulative_orig,
                )
            else:
                default_cumulative_local, _ = _order_delivery_local(
                    default_cumulative_orig,
                    p,
                    rates,
                    order,
                    explicit_local=(
                        (p.get("_fallback_cumulative_local_by_so") or {}).get(so)
                    ),
                    explicit_orig=default_cumulative_orig,
                )
        so_receipt_sources[so] = {
            "amount_orig": float(h), "amount_local": current_local,
            "delivery_local": so_delivery_local,
            "cumulative_local": default_cumulative_local,
            "currency": order.get("currency") or p.get("currency") or "人民币CNY",
            "itemized_cumulative_authoritative": bool(has_itemized_writeoff and default_cumulative_local is not None),
            "all_sods": all_sods, "sod_delivery_local": sod_delivery_local,
            "writeoff_sequence_key": (p.get("_writeoff_sequence_key_by_so") or {}).get(so),
        }
        fallback_partial = (
            not has_itemized_writeoff
            and so in set((p.get("_parent_fallback_allocation") or {}).get("partial_sos") or [])
        )
        if lines and all(x.get("deliver") is not None for x in lines):
            total_lines = round(sum(float(x["deliver"]) for x in lines), 2)
            if abs(total_lines - h) <= TOL:
                chosen, how = lines, "全部SOD"
            elif len(lines) == 1 and float(h) < total_lines - TOL:
                # 唯一SOD的本次核销可以只是最终/中间一笔；是否结清看截至目标日累计核销。
                chosen, how = lines, "唯一SOD累计核销"
            elif not fallback_partial:
                chosen = subset_sum_unique(lines, h)
                how = "SOD子集" if chosen else ""
        if chosen is None:
            if lines:
                cand = "、".join(
                    f"{x['sod']}={x['deliver']}" for x in lines[:12]
                ) + ("…" if len(lines) > 12 else "")
                out.append(_hold(
                    p, "E5",
                    f"{so} 本次核销 {h:.2f}，但它下面的 SOD 金额凑不出唯一组合"
                    f"（已提供金额的 SOD 合计 {round(sum(float(x['deliver']) for x in lines if x.get('deliver') is not None), 2)}）。"
                    f"候选：{cand}。你指一下这次核的是哪几个 SOD；"
                    f"若你指的那个 SOD 交付额比 {h:.2f} 大，就是只回了一部分——"
                    "实际未收必须按「智云最新交付额 − 累计实际回款」算，不能拿盈亏表旧应收减；"
                    "回款明细填实际回款，计提目标更新为最新交付额，同时保持拆行后的原始应收合计不变。"
                    "按已确认规则，程序将从盈亏表中该 SO 的首个未结清 SOD 开始顺序核销；"
                    "当前 SOD 核满后余额继续进入下一个，最后不足的 SOD 按部分回款拆行。",
                    so=so,
                    default_first_sod=True,
                    default_amount_orig=float(h),
                    default_amount_local=current_local,
                    default_cumulative_received_local=default_cumulative_local,
                    itemized_cumulative_authoritative=bool(
                        has_itemized_writeoff
                        and default_cumulative_local is not None
                    ),
                    fallback_allocation_reused=bool(
                        (p.get("_parent_fallback_allocation") or {}).get(
                            "reused_successful_allocation"
                        )
                    ),
                    default_sod_lines=default_lines,
                    so_delivery_local=so_delivery_local,
                    all_sods=all_sods,
                    writeoff_sequence_key=(p.get("_writeoff_sequence_key_by_so") or {}).get(so),
                    sod_delivery_local=sod_delivery_local,
                    default_match_basis=basis,
                    warning_codes=["W_DEFAULT_FIRST_SOD"],
                ))
            else:
                # 订单明细查不到 SOD → 退化成按 SO 匹配盈亏表（老路，仍可判）
                if has_itemized_writeoff:
                    current_local, _ = itemized_local(
                        h, order,
                        explicit_local=business_local_by_so.get(so),
                        explicit_orig=h,
                    )
                else:
                    current_local, _ = _order_delivery_local(
                        h, p, rates, order,
                        explicit_local=business_local_by_so.get(so),
                        explicit_orig=h,
                    )
                deliver_orig = deliver_by_so.get(so)
                if has_itemized_writeoff:
                    deliver_local, _ = itemized_local(deliver_orig, order)
                else:
                    deliver_local, _ = _order_delivery_local(deliver_orig, p, rates, order)
                cumulative_orig = (
                    effective_cumulative_orig.get(so)
                    if has_itemized_writeoff
                    else (p.get("_fallback_cumulative_orig_by_so") or {}).get(so)
                )
                cumulative_local = None
                if cumulative_orig is not None:
                    if has_itemized_writeoff:
                        cumulative_local, _ = itemized_local(
                            cumulative_orig, order,
                            explicit_local=(
                                effective_cumulative_local.get(so)
                                if has_itemized_writeoff
                                else (p.get("_fallback_cumulative_local_by_so") or {}).get(so)
                            ),
                            explicit_orig=cumulative_orig,
                        )
                    else:
                        cumulative_local, _ = _order_delivery_local(
                            cumulative_orig, p, rates, order,
                            explicit_local=(
                                (p.get("cumulative_writeoffs_local") or {}).get(so)
                                if has_itemized_writeoff
                                else (p.get("_fallback_cumulative_local_by_so") or {}).get(so)
                            ),
                            explicit_orig=cumulative_orig,
                        )
                out.append({
                    "ar": p["ar"], "so": so, "sod": "",
                    "customer": p.get("customer") or "",
                    "amount_orig": h,
                    "amount_local": current_local,
                    "currency": order.get("currency") or p.get("currency") or "人民币CNY",
                    "hexiao_date": p.get("hexiao_date"),
                    "shoukuan_date": p.get("arrival_date"),
                    "status": p.get("status") or "",
                    "huikuan_type": p.get("huikuan_type") or "",
                    "fee": p.get("charge_amount_orig") or 0.0,
                    "arrival_total": p.get("amount_orig"),
                    "business_arrival_total": p.get("total_amount_orig"),
                    "deliver_local": deliver_local,
                    "so_delivery_local": so_delivery_local,
                    "all_sods": all_sods,
                    "sod_delivery_local": sod_delivery_local,
                    "cumulative_received_local": cumulative_local,
                    "cumulative_detail_local": detail_cumulative_local.get(so),
                    "cumulative_fallback_local": fallback_history_local.get(so),
                    "itemized_cumulative_authoritative": bool(
                        has_itemized_writeoff and cumulative_local is not None
                    ),
                    "writeoff_sequence_key": (
                        (p.get("_writeoff_sequence_key_by_so") or {}).get(so)
                    ),
                    "match_basis": f"{basis}/无SOD(按SO匹配)",
                })
            continue
        for line in chosen:
            line_orig = float(line["deliver"])
            unique_partial = (
                len(lines) == 1
                and len(chosen) == 1
                and float(h) < line_orig - TOL
            )
            current_orig = float(h) if unique_partial else line_orig
            if has_itemized_writeoff:
                current_local, _ = itemized_local(
                    current_orig, order,
                    explicit_local=business_local_by_so.get(so),
                    explicit_orig=h,
                )
                deliver_local, _ = itemized_local(
                    line_orig, order,
                    explicit_local=business_local_by_so.get(so),
                    explicit_orig=h,
                )
            else:
                current_local, _ = _order_delivery_local(
                    current_orig, p, rates, order,
                    explicit_local=business_local_by_so.get(so),
                    explicit_orig=h,
                )
                deliver_local, _ = _order_delivery_local(
                    line_orig, p, rates, order,
                    explicit_local=business_local_by_so.get(so),
                    explicit_orig=h,
                )
            cumulative_local = None
            cumulative_orig = (
                effective_cumulative_orig.get(so)
                if has_itemized_writeoff
                else (p.get("_fallback_cumulative_orig_by_so") or {}).get(so)
            )
            if len(lines) == 1 and cumulative_orig is not None:
                if has_itemized_writeoff:
                    cumulative_local, _ = itemized_local(
                        cumulative_orig, order,
                        explicit_local=(
                            effective_cumulative_local.get(so)
                            if has_itemized_writeoff
                            else (p.get("_fallback_cumulative_local_by_so") or {}).get(so)
                        ),
                        explicit_orig=cumulative_orig,
                    )
                else:
                    cumulative_local, _ = _order_delivery_local(
                        cumulative_orig, p, rates, order,
                        explicit_local=(
                            (p.get("cumulative_writeoffs_local") or {}).get(so)
                            if has_itemized_writeoff
                            else (p.get("_fallback_cumulative_local_by_so") or {}).get(so)
                        ),
                        explicit_orig=cumulative_orig,
                    )
            # When this one source event is the entire SO cumulative receipt,
            # its selected SOD slices also have no prior receipts. Preserve this
            # fact for current-row correction instead of dropping it on expansion.
            if (has_itemized_writeoff and len(lines) > 1
                    and cumulative_orig is not None
                    and abs(float(cumulative_orig) - float(h)) <= TOL
                    and default_cumulative_local is not None
                    and so_receipt_sources[so].get("amount_local") is not None
                    and abs(float(default_cumulative_local) - float(so_receipt_sources[so]["amount_local"])) <= TOL):
                cumulative_local = current_local
            out.append({
                "so_all_lines": lines,  # 整段对齐消歧要用（见 LedgerIndex.positional_row）
                "ar": p["ar"], "so": so, "sod": line["sod"],
                "customer": p.get("customer") or "",
                "amount_orig": current_orig,
                "amount_local": current_local,
                "currency": (
                    line.get("currency")
                    or order.get("currency")
                    or p.get("currency")
                    or "人民币CNY"
                ),
                "hexiao_date": p.get("hexiao_date"),
                "shoukuan_date": p.get("arrival_date"),
                "status": p.get("status") or "",
                "huikuan_type": p.get("huikuan_type") or "",
                "fee": p.get("charge_amount_orig") or 0.0,
                "arrival_total": p.get("amount_orig"),
                "business_arrival_total": p.get("total_amount_orig"),
                "deliver_local": deliver_local,
                "so_delivery_local": so_delivery_local,
                "all_sods": all_sods,
                "sod_delivery_local": sod_delivery_local,
                "cumulative_received_local": cumulative_local,
                "cumulative_detail_local": detail_cumulative_local.get(so),
                "cumulative_fallback_local": fallback_history_local.get(so),
                "itemized_cumulative_authoritative": bool(
                    has_itemized_writeoff and cumulative_local is not None
                ),
                "writeoff_sequence_key": (
                    (p.get("_writeoff_sequence_key_by_so") or {}).get(so)
                ),
                "fallback_allocation_reused": bool(
                    (p.get("_parent_fallback_allocation") or {}).get(
                        "reused_successful_allocation"
                    )
                ),
                "match_basis": f"{basis}/{how}",
            })

    if not out:  # 兜底：绝不静默丢单
        out.append(_hold(p, "E7", "这笔到账展开不出任何订单行（请把这条截图发给明昊）"))
    return finish(out)

def source_coverage(payments: List[dict], records: List[dict]) -> dict:
    """
    检查输入侧每个 AR/SO 是否都进入判定（自动、挂账或异常均算“进入”）。
    这道闸覆盖“整笔 AR 在，但其中几个订单没进计划”的漏单。
    """
    expected = set()
    linked = set()
    zero_allocated = set()
    for p in payments:
        linked_sos = {
            str(o.get("so") or "").strip() for o in (p.get("orders") or [])
        }
        linked.update(
            (p.get("ar"), so) for so in linked_sos if p.get("ar") and so
        )
        allocation = p.get("_parent_fallback_allocation") or {}
        sos = set((p.get("writeoffs") or {}).keys())
        if allocation:
            sos = set(allocation.get("allocated_sos") or [])
            zero_allocated.update(
                (p.get("ar"), so)
                for so in (allocation.get("zero_sos") or [])
                if p.get("ar") and so
            )
        elif not sos:
            sos = linked_sos
        expected.update((p.get("ar"), so) for so in sos if p.get("ar") and so)
        # Independently compare against pre-filter source expectations.
        day = str(p.get("hexiao_date") or "")
        expected.update(
            tuple(key.split("|", 1))
            for key in p.get("_source_order_keys_by_date", {}).get(day, [])
        )

    produced = {
        (r.get("ar"), str(r.get("so") or "").strip())
        for r in records if r.get("ar") and r.get("so")
    }
    missing = sorted(expected - produced)
    if missing:
        raise CoverageError(
            "有智云订单没有进入任何判定行（即使同一 AR 的其他订单已进入也不放行）："
            f"{[f'{ar}|{so}' for ar, so in missing]}"
        )

    historical_rows = sum(
        int((p.get("_source_meta") or {}).get("historical_detail_rows") or 0)
        for p in payments
    )
    recovered = sum(
        int((p.get("_source_meta") or {}).get("recovered_deliveries") or 0)
        for p in payments
    )
    all_audits = next(
        (p.get("_duplicate_writeoff_audits") for p in payments if p.get("_duplicate_writeoff_audits")),
        {},
    )
    raw_writeoff_rows = sum(
        int(audit.get("raw_input_count") or 0) for audit in all_audits.values()
    )
    accounted_writeoff_rows = sum(
        len(audit.get("records") or []) for audit in all_audits.values()
    )
    if raw_writeoff_rows != accounted_writeoff_rows:
        raise CoverageError(
            "原始核销记录处置覆盖不完整："
            f"读取{raw_writeoff_rows}条，只有{accounted_writeoff_rows}条有明确处置"
        )
    return {
        "source_order_keys_by_date": {
            day: sorted({key for p in payments
                         for key in p.get("_source_order_keys_by_date", {}).get(day, [])})
            for day in sorted({day for p in payments
                               for day in p.get("_source_order_keys_by_date", {})})
        },
        "expected_order_keys": len(expected),
        "produced_order_keys": len(expected) - len(missing),
        "missing_order_keys": [f"{ar}|{so}" for ar, so in missing],
        "linked_order_keys": len(linked),
        "zero_allocation_order_keys": [
            f"{ar}|{so}" for ar, so in sorted(zero_allocated)
        ],
        "historical_detail_rows": historical_rows,
        "recovered_delivery_orders": recovered,
        "raw_writeoff_rows": raw_writeoff_rows,
        "accounted_writeoff_rows": accounted_writeoff_rows,
        "complete": not missing,
    }

def expand_payments(payments: List[dict], rates: Optional[Dict[str, float]] = None) -> List[dict]:
    """全部到账 → records，并做 **AR + AR/SO 两级覆盖率硬校验**。"""
    rates = rates or {}
    records: List[dict] = []
    from collections import defaultdict
    reservations = defaultdict(list)
    dependencies = {}
    for p in FS.ordered(payments):
        sos = {o.get("so") for o in p.get("orders") or []}
        reserved = [entry for so in sos for entry in reservations[so]] if not p.get("writeoffs") else []
        p["_batch_reserved_orig"] = {so: round(sum(x[1] for x in reservations[so]), 2) for so in sos} if reserved else {}
        p["_batch_reserved_local"] = {so: round(sum(x[2] for x in reservations[so]), 2) for so in sos} if reserved else {}
        dependencies[p.get("ar")] = sorted({entry[0] for entry in reserved})
        p["_batch_previous_ars"] = dependencies[p.get("ar")]
        records.extend(expand_payment(p, rates))
        FS.reserve(p, reservations)
    FS.bind_groups(records, dependencies)
    want = {p["ar"] for p in payments if p.get("ar")}
    got = {r.get("ar") for r in records if r.get("ar")}
    missing = sorted(want - got)
    if missing:
        raise CoverageError(
            "有到账没产出任何判定（这就是 2026-07-22 静默丢 3 笔的那类 bug，绝不放行）："
            f"{missing}"
        )
    source_coverage(payments, records)
    return records
