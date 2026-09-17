"""Classify one source-bound receipt against the current workbook."""
from __future__ import annotations

from typing import Dict
from typing import Optional
import baseline_receipts as BR
import common
import datetime as dt
import fallback_allocation_ledger as FAL
import fallback_sequence as FS
import settlement_status
from classification_amounts import _localize_amount, partial_split_guidance
from classification_contract import BUSINESS_SETTLEMENT_TOL, TOL
from classification_ledger import LedgerIndex


def _record_event_coverage(
    rec: dict,
    ledger: LedgerIndex,
    rates: Dict[str, float],
) -> dict:
    """从智云记录生成当前回款的可核对签名，再检查盈亏表覆盖情况。"""
    amount_orig = common.to_number(rec.get("amount_orig"))
    if amount_orig is None:
        return {
            "status": "unavailable",
            "basis": "missing_current_amount",
            "source_ar": rec.get("ar") or "",
        }

    local = common.to_number(rec.get("amount_local"))
    if local is None:
        local, err = _localize_amount(
            float(amount_orig),
            rec,
            rates,
            row_rate=rec.get("rate"),
        )
        if err or local is None:
            return {
                "status": "unavailable",
                "basis": "current_local_amount_unavailable",
                "source_ar": rec.get("ar") or "",
            }

    shoukuan_date = common.norm_date(rec.get("shoukuan_date"))
    hexiao_date = common.norm_date(rec.get("hexiao_date"))
    receipt_time = common.receipt_time(shoukuan_date, hexiao_date)
    payment_way = common.pay_way(
        rec.get("status") or "",
        shoukuan_date,
        hexiao_date,
    )
    coverage = ledger.payment_event_coverage(
        str(rec.get("so") or "").strip(),
        str(rec.get("sod") or "").strip(),
        round(float(local), 2),
        receipt_time,
        payment_way,
    )
    coverage["source_ar"] = rec.get("ar") or ""
    coverage["source_writeoff_sequence_key"] = rec.get("writeoff_sequence_key")
    return coverage

def _mark_event_idempotent(
    result: dict,
    ledger: LedgerIndex,
    coverage: dict,
    code: str,
    reason: str,
) -> dict:
    """把已被当前回款证据覆盖的盈亏行标成幂等跳过。"""
    settled_ref = int(coverage["row"])
    snap = ledger.row_snapshot.get(settled_ref) or {}
    result.update({
        "bucket": "auto",
        "code": code,
        "reason": reason,
        "ledger_row_ref": settled_ref,
        "so": str(snap.get("so") or result.get("so") or "").strip(),
        "sod": str(snap.get("sod") or result.get("sod") or "").strip(),
        "idempotence_audit": coverage,
        "five_cols": {
            "计提": snap.get("jiti"),
            "回款明细": snap.get("huikuan"),
            "是否结账": "是",
            "收款时间": common.norm_date(snap.get("shoukuan_time")),
            "收款方式": snap.get("shoukuan_way"),
            "实收SOD": str(snap.get("sod") or result.get("sod") or "").strip(),
        },
        "current_values": {
            "计提": snap.get("jiti"),
            "回款明细": snap.get("huikuan"),
            "是否结账": snap.get("jiezhang"),
            "收款时间": snap.get("shoukuan_time"),
            "收款方式": snap.get("shoukuan_way"),
        },
    })
    return result

def classify_one(
    rec: dict,
    ledger: Optional[LedgerIndex],
    rates: Dict[str, float],
    thr: float,
    year_now: int,
) -> dict:
    result = {
        "ar": rec.get("ar") or "",
        "so": rec.get("so") or "",
        "sod": rec.get("sod") or "",
        # case_id = AR × SO × SOD：她表里一行一个 SOD，粒度必须到 SOD 否则台账互相覆盖
        "case_id": "|".join(
            x for x in (rec.get("ar") or "-", rec.get("so") or "-", rec.get("sod") or "") if x
        ),
        "customer_masked": common.mask_customer(rec.get("customer") or ""),
        "flow_hits": rec.get("flow_hits"),
        "flow_locate": rec.get("flow_locate") or "",
        "flow_matched_by": rec.get("flow_matched_by") or "",
        "flow_order_suggest": rec.get("flow_order_suggest") or "",
        "flow_file": rec.get("flow_file") or "",
        "flow_sheet": rec.get("flow_sheet") or "",
        "flow_row_no": rec.get("flow_row_no"),
        "flow_order_existing": rec.get("flow_order_existing") or "",
        "flow_identity": rec.get("flow_identity") or {},
        "huikuan_type": rec.get("huikuan_type") or "",
        "status": rec.get("status") or "",
        "write_currency_audit": {
            "currency": rec.get("currency") or "",
            "amount_orig": common.to_number(rec.get("amount_orig")),
            "amount_local": common.to_number(rec.get("amount_local")),
            "deliver_local": common.to_number(rec.get("deliver_local")),
            "local_amount_basis": rec.get("local_amount_basis") or "",
        },
        "match_basis": rec.get("match_basis") or "",
        "bucket": "exception",
        "code": "",
        "reason": "",
        "five_cols": {},
        "locate_hint": "",
        "current_values": {},
        "candidates": [],
        "idempotence_audit": {},
        "warning_codes": list(rec.get("warning_codes") or []),
        "duplicate_writeoff_audit": rec.get("duplicate_writeoff_audit") or {},
        "ambiguous_sod_waterfall": rec.get("ambiguous_sod_waterfall") or {},
        "sod_capacity_audit": rec.get("sod_capacity_audit") or [],
        "parent_allocation_audit": rec.get("parent_allocation_audit") or {},
        "fallback_batch_cases": rec.get("fallback_batch_cases") or [],
        "fallback_batch_ars": rec.get("fallback_batch_ars") or [],
        "ledger_year": rec.get("target_ledger_year"),
        "ledger_path": rec.get("target_ledger_path") or "",
        "delivery_date": (
            rec.get("delivery_date").isoformat()
            if isinstance(rec.get("delivery_date"), dt.date)
            else str(rec.get("delivery_date") or "")
        ),
        "delivery_date_issue": rec.get("delivery_date_issue") or "",
        # 仅供同一 SO/SOD 的跨父 AR 分笔链复核；不得用这些字段跨 SO 或跨 SOD 合并。
        "split_payment_source": {
            "receivable_group_scope": rec.get("receivable_group_scope") or {},
            "amount_local": common.to_number(rec.get("amount_local")),
            "cumulative_local": common.to_number(rec.get("cumulative_received_local")),
            "detail_cumulative_local": common.to_number(
                rec.get("cumulative_detail_local")
            ),
            "fallback_cumulative_local": common.to_number(
                rec.get("cumulative_fallback_local")
            ),
            "delivery_local": common.to_number(rec.get("deliver_local")),
            "so_delivery_local": common.to_number(rec.get("so_delivery_local")),
            "all_sods": sorted({
                str(x or "").strip() for x in (rec.get("all_sods") or [])
                if str(x or "").strip()
            }),
            "sod_delivery_local": {
                str(key or "").strip(): round(float(common.to_number(value)), 2)
                for key, value in (rec.get("sod_delivery_local") or {}).items()
                if str(key or "").strip() and common.to_number(value) is not None
            },
            "writeoff_sequence_key": rec.get("writeoff_sequence_key"),
            "fallback_sequence_key": rec.get("fallback_sequence_key"),
        },
    }
    if "_year_route_order" in rec:
        result["_year_route_order"] = rec["_year_route_order"]
    if rec.get("so"):
        ledger_label = (
            f"{rec.get('target_ledger_year')} 年盈亏"
            if rec.get("target_ledger_year")
            else "盈亏"
        )
        result["locate_hint"] = (
            f"在{ledger_label}『明细』按「新智云单号」筛选：{rec['so']}"
            + (f"，找应收金额={rec.get('amount_orig')} 那行" if rec.get("amount_orig") is not None else "")
            + "（禁止用行号）"
        )

    if (rec.get("status") or "") == "已作废":
        result["code"] = "E7"
        result["reason"] = "核销已作废"
        return result

    # 父 AR 金额守恒失败是付款级硬闸；即使盈亏里已有结账行，也必须保留异常，
    # 不能被下面的订单幂等快捷路径改写为普通 auto/skip。
    if rec.get("forced_code") in {"E_PARENT_WRITEOFF_MISMATCH", "E_SYSTEM_OVER_WRITEOFF_UNRESOLVED", "E_PARENT_ALLOCATION_HISTORY_MISSING", "E_PARENT_ALLOCATION_BASELINE_CHANGED", "E_SOD_HISTORY_MISMATCH"}:
        result["code"] = rec["forced_code"]
        result["reason"] = rec.get("forced_reason") or "父回款金额守恒检查未通过"
        if rec["forced_code"] in {"E_PARENT_ALLOCATION_HISTORY_MISSING", "E_PARENT_ALLOCATION_BASELINE_CHANGED", "E_SOD_HISTORY_MISMATCH"}:
            result["bucket"] = "hold"
        return result

    if rec.get("forced_code") == FS.ZERO:
        before = FS.ledger_so_rows(ledger, rec.get("so"))
        received = sum(float(row.get("回款明细") or 0) for row in before.values())
        reserved = float(rec.get("zero_reserved_local") or 0)
        delivery = common.to_number(rec.get("deliver_local"))
        valid = bool(before) and delivery is not None and abs(received + reserved - delivery) <= TOL
        result["zero_allocation_basis"] = {"before_rows": before, "reserved_local": reserved, "delivery_local": delivery}
        if not valid:
            result.update(bucket="hold", code="E_FALLBACK_ZERO_BASELINE", reason="零分配的订单或前序回款余额无法在当前盈亏表核实")
        else:
            result.update(bucket="auto", code=FS.ZERO, reason=rec.get("forced_reason") or "本笔分配0")
        result["_year_route_order"] = rec.get("_year_route_order", 0)
        return result

    import receipt_history
    zero = receipt_history.zero_candidate(rec, result, ledger)
    if zero is not None:
        return zero
    import receipt_correction
    correction = receipt_correction.candidate(rec, result, ledger, rates, thr, year_now)
    if correction is not None:
        return correction

    # Select delivery/baseline handling before any row-filled or settled skip.
    baseline_candidate = BR.candidate(rec, result, ledger)
    if baseline_candidate is not None:
        return baseline_candidate

    # 整 SO 业务状态与本批事件幂等分开；父 AR 硬闸已在前面检查。
    if ledger is not None and rec.get("so"):
        settlement = ledger.so_settlement(rec["so"])
        if settlement["all_settled"]:
            source_notes = []
            if rec.get("forced_code") and rec.get("forced_code") != "E_SETTLED_SO_RECHECK":
                source_notes.append(f"来源检查 {rec['forced_code']}：{rec.get('forced_reason') or '未提供具体原因'}")
            source_sods = set((result.get("split_payment_source") or {}).get("all_sods") or [])
            missing_sods = sorted(source_sods - set(settlement["sods"]))
            if missing_sods:
                source_notes.append(f"当前来源另含表内未登记 SOD：{','.join(missing_sods)}；保留为来源差异，未新增行")
            for source_sod, delivery in (result["split_payment_source"].get("sod_delivery_local") or {}).items():
                initial, _, _ = ledger.business_totals(rec["so"], source_sod)
                if initial is not None and abs(float(delivery) - initial) > TOL:
                    source_notes.append(f"SOD={source_sod} 当前来源交付 {float(delivery):.2f}，表内原始应收合计 {initial:.2f}，差额 {float(delivery) - initial:.2f}；已结账历史值保留")
            result.update({
                "bucket": "auto", "code": settlement_status.SO_ALREADY_SETTLED,
                "reason": settlement["reason"] + (" 来源提示：" + "；".join(source_notes) if source_notes else ""),
                "so_settlement_audit": settlement,
                "ledger_row_ref": settlement["rows"][0]["row"],
                "five_cols": {},
                "locate_hint": f"在对应年度盈亏明细按 SO={rec['so']} 查看全部业务行（含拆分行）",
            })
            if rec.get("forced_code") == "E_SETTLED_SO_RECHECK":
                result["reason"] += " 本父回款分配金额为 0，未占用父回款金额。"
            if source_notes:
                result["warning_codes"].append("W_SETTLED_SO_SOURCE_DIFFERENCE")
            return result

    # 未整单结账时，仍按本批金额、日期和方式判断事件幂等。
    allocation = rec.get("parent_allocation_audit") or {}
    applied = allocation.get("applied", allocation.get("reused"))
    cases = allocation.get("applied_cases") or {}
    if "applied_cases" in allocation:
        prior = cases.get(f"{rec.get('ar')}|{rec.get('so')}|{rec.get('sod') or ''}")
        applied = prior is not None and abs(float(prior["amount_local"]) - float(rec.get("amount_local") or 0.0)) <= TOL
        if prior is not None and not applied:
            result.update({"bucket": "hold", "code": "E_PARENT_ALLOCATION_HISTORY_MISSING",
                           "reason": f"父回款 {rec.get('ar')} 的 SOD={rec.get('sod')} 已写 {prior['amount_local']:.2f}，本次计划金额不同；禁止覆盖原分配，请核对来源变更。"})
            return result
        rec = {**rec, "fallback_allocation_reused": applied}
    fresh_allocation = bool(allocation) and not applied
    if fresh_allocation and ledger is not None:
        _, received = ledger.so_totals(rec.get("so") or "")
        history = common.to_number(allocation.get("historical_received_local"))
        current_applied = sum(case["amount_local"] for case in cases.values())
        known = float(history or 0.0) + current_applied
        error = FAL.unexplained_receipts(
            rec.get("ar") or "", rec.get("so") or "", received, known,
            reused_allocation=bool(allocation.get("reused")), current_applied=current_applied,
        )
        if error:
            code = "E_PARENT_ALLOCATION_BASELINE_CHANGED" if allocation.get("reused") else "E_PARENT_ALLOCATION_HISTORY_MISSING"
            result.update({"bucket": "hold", "code": code, "reason": error})
            return result
    event_coverage = None
    if ledger is not None and rec.get("so") and not fresh_allocation:
        event_coverage = _record_event_coverage(rec, ledger, rates)
        result["idempotence_audit"] = event_coverage
        if event_coverage.get("status") == "covered":
            if rec.get("fallback_allocation_reused"):
                idem_code = "OK_FALLBACK_ALLOCATION_ALREADY_APPLIED"
                idem_reason = (
                    "同一父回款已按回款明细、收款时间和收款方式唯一对应到已结账行；"
                    "复用既有顺序分配，按幂等跳过"
                )
            elif rec.get("itemized_cumulative_authoritative"):
                idem_code = "OK_ITEMIZED_CUMULATIVE_ALREADY_APPLIED"
                idem_reason = (
                    "智云逐单回款已按回款明细、收款时间和收款方式唯一对应到已结账行；"
                    "按幂等跳过，未结账行继续留给后续新回款承接"
                )
            else:
                idem_code = "OK_ALREADY_SETTLED"
                idem_reason = (
                    "本批回款已按回款明细、收款时间和收款方式唯一对应到已结账行；"
                    "按幂等跳过"
                )
            return _mark_event_idempotent(
                result, ledger, event_coverage, idem_code, idem_reason
            )

    # 展开阶段已定性的（分笔/超额/没回满/无下单…）直接落地
    forced = rec.get("forced_code")
    if forced:
        result["code"] = forced
        reason = rec.get("forced_reason") or ""
        if forced == "E_SETTLED_SO_RECHECK" and ledger is not None:
            reason = ledger.so_settlement(rec.get("so"))["reason"] + " 顺序分配时的整单结账依据已变化，请重新生成分配计划。"
        if (
            forced == "E5"
            and ledger is not None
            and rec.get("so")
            and rec.get("partial_latest_delivery") is not None
            and rec.get("partial_current_received") is not None
        ):
            initial_receivable, existing_received = ledger.so_totals(rec["so"])
            reason = (
                f"{rec['so']} 当前回款无法安全落表。"
                + partial_split_guidance(
                    rec["partial_latest_delivery"],
                    rec["partial_current_received"],
                    initial_receivable=initial_receivable,
                    existing_received=existing_received,
                )
                + " 当前无法唯一命中 SOD，先指明承接回款的 SOD；唯一后才能安全写入。"
            )
        result["reason"] = reason
        result["bucket"] = "exception" if forced in ("E4", "E7", "E10", "E12", "E0") else "hold"
        return result

    amount_orig = rec.get("amount_orig")
    if amount_orig is None:
        result["code"] = "E7"
        result["reason"] = "核销金额为空"
        return result

    # 智云已经给出本币金额时直接采用，不再反向要求汇率。只有本币金额也缺失时，
    # 才按“子记录汇率 → 父回款原/本币隐含汇率 → 命令行汇率”逐级换算。
    local = common.to_number(rec.get("amount_local"))
    err = None
    if local is None:
        local, err = _localize_amount(
            float(amount_orig),
            rec,
            rates,
            row_rate=rec.get("rate"),
        )
    if err == "E6" or local is None:
        result["code"] = "E6"
        result["reason"] = (
            f"外币既没有本币核销金额，也没有可用汇率（{rec.get('currency')}）"
        )
        return result

    # Flow ambiguity is handled by the flow plan; ledger evidence is independent.
    if rec.get("flow_hits") not in (None, 1):
        result["warning_codes"].append("W_FLOW_LOCATION_UNRESOLVED")
    if rec.get("customer_archive_failed"):
        result["code"] = "E10"
        result["reason"] = "建档失败/搜不到客户"
        return result

    if ledger is None:
        result["bucket"] = "hold"
        target_year = rec.get("target_ledger_year")
        if target_year is not None and int(target_year) != int(year_now):
            result["code"] = "E3"
            result["reason"] = f"没有提供 {int(target_year)} 年盈亏核算表工作副本"
        else:
            result["code"] = "E2"
            result["reason"] = "未提供本年度盈亏表，无法确认 SO 是否在明细"
        return result

    so, sod = rec.get("so") or "", rec.get("sod") or ""
    preferred_row = rec.get("preferred_ledger_row")
    if preferred_row is not None:
        row, how, cands = int(preferred_row), "同SO未结清SOD顺序核销", []
    else:
        row, how, cands = ledger.match(so, sod, amount_orig)
        if fresh_allocation and sod:
            outstanding = [
                candidate for candidate in ledger.sod_index.get(sod, [])
                if (ledger.row_snapshot.get(candidate) or {}).get("so") == so
                and ledger._is_outstanding(ledger.row_snapshot[candidate])
            ]
            if len(outstanding) == 1:
                row, how, cands = outstanding[0], "本父回款待写SOD唯一未结清行", outstanding

    # 定位不到唯一行 → 用「整段逐位对齐」严格消歧（对不齐就继续挂起）
    align_note = ""
    if how in ("E8", "E2") and sod and rec.get("so_all_lines"):
        aligned = ledger.positional_row(so, sod, rec["so_all_lines"])
        if aligned is not None:
            row, kind, ratio = aligned
            how, cands = "SO整段按SOD序对齐", []
            if kind == "ratio":
                snap0 = ledger.row_snapshot.get(row) or {}
                align_note = (
                    f"⚠ 智云交付额 {amount_orig} 与你表里应收 {snap0.get('yingshou')} 不一致"
                    f"（这个 SO 每一行都差同一个比例 {ratio:.6f}），已按**智云金额**填；"
                    "口径待确认，填之前扫一眼"
                )

    if how == "E8":
        result["bucket"] = "hold"
        result["code"] = "E8"
        result["reason"] = (
            f"盈亏表里有 {len(cands)} 行同时满足 SO={so}"
            + f"，目标 SOD={sod or '-'}、本次匹配金额={amount_orig}；现有身份和金额证据不足以唯一定位。"
            + "候选行：" + ",".join(map(str, cands))
            + "；候选仅表示可能位置，不表示每行应收都等于本次金额。请核对 SOD 和拆分行归属。"
        )
        result["candidates"] = cands
        return result
    if how == "E7":
        result["code"] = "E7"
        result["reason"] = "无单号"
        return result
    if how == "E2" or row is None:
        # 已按交付年度选定盈亏表；只有目标年度表缺单时才挂账。
        y = rec.get("target_ledger_year")
        result["bucket"] = "hold"
        if y is not None and int(y) != int(year_now):
            result["code"] = "E3"
            result["reason"] = f"已检查 {int(y)} 年盈亏表，但明细里没有这张单"
        else:
            result["code"] = "E2"
            result["reason"] = "盈亏表里还没有这张单（多半还没交付进表）"
        return result

    snap = ledger.row_snapshot.get(row, {})
    yingshou = common.to_number(snap.get("yingshou"))
    deliver = common.to_number(rec.get("deliver_local"))

    # 超额核销：本次本币 > **智云这单交付额**（不是她表应收）。
    # 2026-07-24 明妹口径：判超额的上限是智云交付额，别以她表应收为准 —— 应收可能是旧值，
    # 交付额中途变大时（初始 1 → 结算 2），拿旧应收当上限会把「本该填的 2」误报成超额。
    # 只有拿不到智云交付额时，才退回用应收当兜底上限。
    ceiling = deliver if deliver is not None else yingshou
    if (
        ceiling is not None
        and common.is_cny(rec.get("currency") or "")
        and float(local) > float(ceiling) + max(thr, TOL)
    ):
        result["code"] = "E4"
        src = "智云这单交付额" if deliver is not None else "你表里应收"
        result["reason"] = (
            f"本次核销 {local} 比{src} {round(float(ceiling), 2)} 还多，不正常，先找销售核对"
        )
        return result

    shoukuan_date = common.norm_date(rec.get("shoukuan_date"))
    hexiao_date = common.norm_date(rec.get("hexiao_date"))
    # 收款时间/方式只比较到账月和核销月，不再按回款类型分支：
    # 同月 = 到账日期 +「汇」；跨月 = 核销日期 +「冲预收」。
    r_time = common.receipt_time(shoukuan_date, hexiao_date)
    way = common.pay_way(
        rec.get("status") or "",
        shoukuan_date,
        hexiao_date,
    )
    local_f = round(float(local), 2)
    result["split_payment_source"]["amount_local"] = local_f

    if event_coverage is None:
        event_coverage = ledger.payment_event_coverage(
            so,
            sod,
            local_f,
            r_time,
            way,
        )
        result["idempotence_audit"] = event_coverage

    # 所有目标行都已结账，但本批事件没有在表中留下可核对的证据时，
    # 明确挂起，禁止把历史结账行当成本批已写入，也禁止覆盖历史金额。
    settled_ref = ledger.settled_without_open_row(so, sod)
    if (
        settled_ref is not None
        and (event_coverage or {}).get("status") != "covered"
    ):
        matched_rows = (event_coverage or {}).get("matched_rows") or []
        if (event_coverage or {}).get("status") == "ambiguous":
            detail = f"金额、收款时间和收款方式同时命中 {len(matched_rows)} 行"
        elif matched_rows:
            detail = "找到相同回款证据，但对应行尚未结账"
        else:
            expected = (event_coverage or {}).get("expected") or {}
            actual = (event_coverage or {}).get("candidate_values") or []
            values = "；".join(
                f"第 {v['row']} 行：金额={v.get('回款明细')}、日期={v.get('收款时间')}、方式={v.get('收款方式') or '空'}"
                for v in actual
            )
            detail = (
                f"本批要求金额={expected.get('回款明细')}、日期={expected.get('收款时间')}、方式={expected.get('收款方式') or '空'}；"
                f"历史值为 {values or '无可用候选'}，没有同时匹配的唯一行"
            )
        result.update({
            "bucket": "hold",
            "code": "E_SETTLED_CURRENT_EVENT_UNCOVERED",
            "reason": (
                f"盈亏表中 SO={so}、SOD={sod or '-'} 的目标行已全部结账，但{detail}；"
                "同 SO 仍有未结账业务行，不能整单跳过；请核对本批回款与历史记录的归属，不覆盖历史行"
            ),
            "ledger_row_ref": settled_ref,
            "current_values": {
                "计提": snap.get("jiti"),
                "回款明细": snap.get("huikuan"),
                "差异": snap.get("chayi"),
                "是否结账": str(snap.get("jiezhang") or "").strip()
                if snap.get("jiezhang") is not None
                else "",
                "收款时间": str(snap.get("shoukuan_time") or "")[:10],
                "收款方式": snap.get("shoukuan_way"),
                "实收SOD": snap.get("sod"),
            },
        })
        return result

    # ── 结账 / 计提（2026-07-29 交付额变动会议更新）──────────────────────────
    # 【结账】= 这笔到账给这个 SOD 下发的「任务」做完没有。任务 = 智云本次核销这个单的金额。
    #   能走到这里（bucket=auto）的行 = 核销命中 + 已交付进表 → 任务能做且已做 → 一律「是」。
    #   ⚠ **绝不能拿「回款记录整笔」的核销状态判每个小单**：
    #     “预存部分核销”只是说那笔预存余额没花完（实测 6300 核 6090、剩 210 挂预收），
    #     跟这个单本身收没收满、任务做没做完**毫无关系**。旧版拿 status∈SETTLED 判结账，
    #     把 6 个已收满的预存视频单全误判成「否」（2026-07-24 对明妹真答案实测：146/152→修后应全对）。
    #   （结账=否 只属于“没交付/没做任务”的行，那是 E2/E3，早已挂起、根本走不到这里。）
    # 【计提】只有累计实际回款达到最新实际交付额 D 才填 D；未达到时两侧计提都留空。
    # 【部分回款】当前未结清行改成“本次已回款行”，并在其正下方复制出“剩余未回款行”：
    #   U = D - (历史累计回款 + 本次回款)
    #   当前已回款切片应收 = 当前未结清行应收 - U
    #   新增未回款行应收 = U
    # 这样所有拆分行应收合计始终等于原始应收基线，且累计只在当前 SOD 内计算。
    if sod and str(snap.get("sod") or "").strip() not in ("", sod):
        result.update({
            "bucket": "hold", "code": "E_SOD_HISTORY_MISMATCH",
            "reason": f"SO={so} 的目标 SOD={sod}，候选第 {row} 行已登记 SOD={snap.get('sod')}；不能借用其他 SOD 的历史回款。请核对 SOD 归属后重判。",
            "ledger_row_ref": row,
        })
        return result
    initial_receivable, existing_received, business_rows = ledger.business_totals(so, sod, row)
    source_cumulative = common.to_number(rec.get("cumulative_received_local"))
    # 部分回款仍保留一条未结账行，不能只靠“全部行已结账”判幂等：
    # - 无逐单金额：同一父回款重跑复用成功顺序分配；
    # - 有逐单金额：智云给出截至目标日的累计核销真相。
    # 只要拆分组表内累计已收已经覆盖对应累计，就跳过当前记录，未结账行只给后续新回款。
    if (
        source_cumulative is not None
        and (
            rec.get("fallback_allocation_reused")
            or rec.get("itemized_cumulative_authoritative")
        )
        and existing_received + max(thr, TOL) >= float(source_cumulative)
    ):
        materialized_rows = [
            one_row
            for one_row in business_rows
            if (
                common.to_number(
                    (ledger.row_snapshot.get(one_row) or {}).get("huikuan")
                )
                is not None
                or str(
                    (ledger.row_snapshot.get(one_row) or {}).get("jiezhang") or ""
                ).strip()
                == "是"
            )
        ]
        idempotent_row = ledger.comparison_row(
            so,
            sod,
            current_received=local_f,
            receipt_time=r_time,
            payment_way=way,
        )
        if idempotent_row not in materialized_rows:
            # 无法同时按本次金额、收款时间和收款方式定位到已落表切片时，
            # 即使累计金额已经较大，也不能借用另一笔父回款的行判幂等。
            idempotent_row = None
        if idempotent_row is not None:
            idem = ledger.row_snapshot.get(idempotent_row) or {}
            result.update({
                "bucket": "auto",
                "code": (
                    "OK_FALLBACK_ALLOCATION_ALREADY_APPLIED"
                    if rec.get("fallback_allocation_reused")
                    else "OK_ITEMIZED_CUMULATIVE_ALREADY_APPLIED"
                ),
                "reason": (
                    (
                        "同一父回款复用既有顺序分配"
                        if rec.get("fallback_allocation_reused")
                        else "智云逐单累计核销已由盈亏拆分行完整覆盖"
                    )
                    + "；按幂等跳过，未结账行继续留给后续新回款承接"
                ),
                "ledger_row_ref": idempotent_row,
                "five_cols": {
                    "计提": idem.get("jiti"),
                    "回款明细": idem.get("huikuan"),
                    "是否结账": idem.get("jiezhang"),
                    "收款时间": common.norm_date(idem.get("shoukuan_time")),
                    "收款方式": idem.get("shoukuan_way"),
                    "实收SOD": str(idem.get("sod") or sod or "").strip(),
                },
                "current_values": {
                    "计提": idem.get("jiti"),
                    "回款明细": idem.get("huikuan"),
                    "差异": idem.get("chayi"),
                    "是否结账": idem.get("jiezhang"),
                    "收款时间": idem.get("shoukuan_time"),
                    "收款方式": idem.get("shoukuan_way"),
                    "实收SOD": idem.get("sod"),
                },
            })
            return result
    if source_cumulative is not None:
        # 智云核销明细是事实源：同一 SO/SOD 截至目标日的历史核销 + 本次核销，
        # 比盈亏表里是否已经写过历史回款更可靠，也避免把历史核销漏算成“本次部分回款”。
        cumulative_received = round(float(source_cumulative), 2)
        existing_received = round(max(cumulative_received - local_f, 0.0), 2)
    else:
        target_received = common.to_number(snap.get("huikuan"))
        if (
            target_received is not None
            and abs(float(target_received) - local_f) <= max(thr, TOL)
        ):
            existing_received = round(max(existing_received - float(target_received), 0.0), 2)
        cumulative_received = round(existing_received + local_f, 2)

    settlement_delta = (
        round(float(deliver) - cumulative_received, 2)
        if deliver is not None else None
    )
    business_tail_settled = (
        settlement_delta is not None
        and abs(settlement_delta) > max(thr, TOL)
        and abs(settlement_delta) <= BUSINESS_SETTLEMENT_TOL
    )
    if business_tail_settled:
        result["settlement_tolerance_audit"] = {
            "latest_delivery": round(float(deliver), 2),
            "cumulative_received": cumulative_received,
            "exact_delta": settlement_delta,
            "business_tolerance": BUSINESS_SETTLEMENT_TOL,
            "technical_equal": False,
            "business_equal": True,
        }
        warnings = list(result.get("warning_codes") or [])
        if "W_SETTLEMENT_TAIL_TOLERATED" not in warnings:
            warnings.append("W_SETTLEMENT_TAIL_TOLERATED")
        result["warning_codes"] = warnings

    if (
        deliver is not None
        and cumulative_received > float(deliver) + max(thr, TOL)
        and not business_tail_settled
    ):
        result["bucket"] = "hold"
        result["code"] = "E5"
        result["reason"] = partial_split_guidance(
            float(deliver),
            local_f,
            initial_receivable=initial_receivable,
            existing_received=existing_received,
        )
        result["ledger_row_ref"] = row
        return result

    if (
        deliver is not None
        and cumulative_received < float(deliver) - max(thr, TOL)
        and not business_tail_settled
    ):
        remaining = round(float(deliver) - cumulative_received, 2)
        current_receivable = common.to_number(snap.get("yingshou"))
        if current_receivable is None:
            result["bucket"] = "hold"
            result["code"] = "E5"
            result["reason"] = "部分回款已识别，但当前未结清行没有应收金额，无法证明拆行后应收守恒。"
            result["ledger_row_ref"] = row
            return result
        paid_slice = round(float(current_receivable) - remaining, 2)
        if paid_slice < -max(thr, TOL):
            result["bucket"] = "hold"
            result["code"] = "E5"
            result["reason"] = (
                f"部分回款后实际未收 {remaining:.2f} 大于当前未结清行应收 "
                f"{float(current_receivable):.2f}，无法安全拆行；先核对交付额变化。"
            )
            result["ledger_row_ref"] = row
            return result

        paid_slice = max(paid_slice, 0.0)
        paid_side_total = (
            round(float(initial_receivable) - remaining, 2)
            if initial_receivable is not None
            else None
        )
        result["five_cols"] = {
            "计提": None,
            "回款明细": local_f,
            "是否结账": "是",
            "收款时间": r_time.isoformat() if r_time else None,
            "收款方式": way,
            "实收SOD": sod or snap.get("sod") or None,
        }
        result["row_operation"] = {
            "type": "split_below",
            "source_receivable": round(float(current_receivable), 2),
            "paid_receivable": paid_slice,
            "unpaid_receivable": remaining,
            "baseline_receivable": initial_receivable,
            "paid_side_receivable_total": paid_side_total,
            "existing_received": existing_received,
            "current_received": local_f,
            "cumulative_received": cumulative_received,
            "latest_delivery": round(float(deliver), 2),
            "business_rows": business_rows,
            "inserted_five_cols": {
                "计提": None,
                "回款明细": None,
                "是否结账": "否",
                "收款时间": None,
                "收款方式": None,
                "实收SOD": sod or snap.get("sod") or None,
            },
        }
        result["bucket"] = "auto"
        result["code"] = "E5"
        result["reason"] = partial_split_guidance(
            float(deliver),
            local_f,
            initial_receivable=initial_receivable,
            existing_received=existing_received,
        )
        result["current_values"] = {
            "计提": snap.get("jiti"),
            "回款明细": snap.get("huikuan"),
            "差异": snap.get("chayi"),
            "是否结账": str(snap.get("jiezhang") or "").strip()
            if snap.get("jiezhang") is not None
            else "",
            "收款时间": str(snap.get("shoukuan_time") or "")[:10],
            "收款方式": snap.get("shoukuan_way"),
            "实收SOD": snap.get("sod"),
        }
        result["ledger_row_ref"] = row
        return result

    jiti_target = round(float(deliver), 2) if deliver is not None else local_f

    result["five_cols"] = {
        "计提": jiti_target,
        "回款明细": local_f,
        "是否结账": "是",
        "收款时间": r_time.isoformat() if r_time else None,
        "收款方式": way,
        "实收SOD": sod or snap.get("sod") or None,
    }
    # 业务值差异只在最终结清时产生：原始应收是历史基线，计提按最新实际交付额。
    # 两者不一致时保留原始应收不动，并在“差异”列写公式 = 应收金额 - 计提金额。
    # 部分回款阶段计提留空，因此不提前写差异。
    baseline_for_difference = (
        initial_receivable if initial_receivable is not None else yingshou
    )
    if (
        baseline_for_difference is not None
        and abs(float(baseline_for_difference) - jiti_target) > max(thr, TOL)
    ):
        result["derived_cols"] = {
            "差异": round(float(baseline_for_difference) - jiti_target, 2)
        }
    # ── 交付额变化提醒（2026-07-24 明妹原话："要让他动脑子检查交付额，别以我表里的为准")──
    # 命中行后，若**智云结算额**（本次核销/交付，= amount_orig）和她表里那行的**应收金额**
    # 对不上，一律顶一个 ⚠ 到「怎么办」。以前只有 ratio 消歧路径会提醒，靠 SOD / SO 唯一行
    # 命中的（她已手动改过应收、或压根没写 SOD）就闷声按智云额填、不吭声——她要的是**每一笔
    # 都被明确检查一次**。回款明细用本次实际核销额，计提目标用智云最新交付额；只是多一句让她扫。
    # align_note 已经说过（比例差）就不重复。
    disc_note = ""
    if not align_note and baseline_for_difference is not None:
        if abs(jiti_target - float(baseline_for_difference)) > max(thr, TOL):
            disc_note = (
                f"⚠ 智云最新实际交付额 {jiti_target} 与表里原始应收 "
                f"{round(float(baseline_for_difference), 2)} 不一致：计提按最新交付额，原始应收不改，"
                f"差异列写应收减计提"
            )

    result["bucket"] = "auto"
    result["code"] = ""
    duplicate_note = ""
    audit = rec.get("duplicate_writeoff_audit") or {}
    if audit.get("status") == "recovered":
        duplicate_note = (
            "⚠ 智云疑似系统重复核销，本次每组只按一次处理；"
            f"重复组{len(audit.get('duplicate_groups') or [])}个，"
            f"原始{audit.get('raw_record_count', 0)}条，"
            f"保留{audit.get('logical_record_count', 0)}条，"
            f"忽略{audit.get('ignored_record_count', 0)}条，"
            f"折叠前差额{audit.get('delta_raw')}，折叠后差额{audit.get('delta_dedup')}"
        )
    settlement_note = ""
    if business_tail_settled:
        settlement_note = (
            f"累计实际回款与最新交付额精确差额 {settlement_delta:.2f} 元，"
            "绝对值不超过 1.00 元，按业务结清尾差处理；实际回款金额保持不变，不新增未回款行"
        )
    tail = "；".join(
        x for x in (align_note, disc_note, duplicate_note, settlement_note) if x
    )
    result["reason"] = f"{rec.get('match_basis') or '判定'} · 定位={how}" + (
        f"；{tail}" if tail else ""
    )
    result["current_values"] = {
        "计提": snap.get("jiti"),
        "回款明细": snap.get("huikuan"),
        "差异": snap.get("chayi"),
        "是否结账": str(snap.get("jiezhang") or "").strip() if snap.get("jiezhang") is not None else "",
        "收款时间": str(snap.get("shoukuan_time") or "")[:10],
        "收款方式": snap.get("shoukuan_way"),
        "实收SOD": snap.get("sod"),
    }
    result["ledger_row_ref"] = row
    return result
