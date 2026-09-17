"""Evaluate SO settlement and accrual across SOD records."""
from __future__ import annotations

from pathlib import Path
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
import amount_policy
import baseline_receipts as BR
import common
import datetime as dt
import json
from classification_contract import TOL
from classification_ledger import LedgerIndex


def _clear_new_accrual(result: dict) -> None:
    """SO 尚未全部结清时，只撤销本批将要新增的计提，不改历史已填值。"""
    if (result.get("baseline_receipt_audit") or {}).get("disposition") in {"skip", "conflict"}:
        return
    if result.get("code") != "OK_ALREADY_SETTLED":
        five = result.get("five_cols") or {}
        if five:
            five["计提"] = None
        result["derived_cols"] = {}

    op = result.get("row_operation") or {}
    op_type = op.get("type")
    if op_type in {"split_payment_chain", BR.OPERATION}:
        for step in op.get("steps") or []:
            (step.get("five_cols") or {})["计提"] = None
            step["derived_cols"] = {}
    elif op_type in {"settlement_tail_aggregate", "same_so_multi_sod_aggregate"}:
        (op.get("target_five_cols") or {})["计提"] = None
        op["target_derived_cols"] = {}

def _planned_settled_sods(result: dict) -> set[str]:
    """返回该计划写完后能被证明已结清的 SOD；拆分后仍有承接行则不算。"""
    if result.get("bucket") != "auto":
        return set()
    op = result.get("row_operation") or {}
    op_type = op.get("type")
    scope = (result.get("split_payment_source") or {}).get("receivable_group_scope") or {}
    represented_sods = set(scope.get("source_sods") or []) if scope else {str(result.get("sod") or "")}
    if op_type == BR.OPERATION:
        return represented_sods if op.get("settled") else set()
    if result.get("baseline_receipt_audit"):
        audit = result["baseline_receipt_audit"]
        return (represented_sods if audit["disposition"] == "skip" and
                all(row["是否结账"] == "是" for row in audit["before_rows"].values()) else set())
    history = result.get("receipt_correction") or {}
    if history.get("history_mode") and history.get("kind") == "existing":
        before = history.get("before_rows") or {}
        ref = str(result.get("ledger_row_ref"))
        if (history.get("current_remaining", 0) > float(amount_policy.BUSINESS_SETTLEMENT_TOLERANCE)
                or any(row["是否结账"] != "是" for key,row in before.items() if key != ref)):
            return set()
    if op_type == "split_below":
        return set()
    if op_type == "split_payment_chain":
        if op.get("final_unpaid"):
            return set()
        if scope and any(step.get("settled") for step in (op.get("steps") or [])):
            return represented_sods
        return {
            str(step.get("sod") or result.get("sod") or "").strip()
            for step in (op.get("steps") or [])
            if step.get("settled")
            and str(step.get("sod") or result.get("sod") or "").strip()
        }
    if op_type == "same_so_multi_sod_aggregate":
        target = op.get("target_five_cols") or {}
        if target.get("是否结账") == "是":
            return {
                str(sod or "").strip() for sod in (op.get("member_sods") or [])
                if str(sod or "").strip()
            }
        return set()
    if (result.get("five_cols") or {}).get("是否结账") == "是":
        sod = str(result.get("sod") or "").strip()
        return represented_sods if sod else set()
    return set()

def _has_new_planned_accrual(result: dict, sod: str) -> bool:
    """历史幂等行不算“本批会写计提”；它可能正是需要补填的旧行。"""
    if result.get("bucket") != "auto" or result.get("code") == "OK_ALREADY_SETTLED":
        return False
    if (result.get("baseline_receipt_audit") or {}).get("disposition") in {"skip", "conflict"}:
        return False
    op = result.get("row_operation") or {}
    scope = (result.get("split_payment_source") or {}).get("receivable_group_scope") or {}
    if scope and sod in scope.get("source_sods", []):
        return (common.to_number((result.get("five_cols") or {}).get("计提")) is not None or
                any(common.to_number((step.get("five_cols") or {}).get("计提")) is not None for step in op.get("steps") or []))
    if op.get("type") in {"split_payment_chain", BR.OPERATION}:
        return any(
            str(step.get("sod") or result.get("sod") or "").strip() == sod
            and common.to_number((step.get("five_cols") or {}).get("计提")) is not None
            for step in (op.get("steps") or [])
        )
    if op.get("type") == "same_so_multi_sod_aggregate":
        return sod in set(op.get("member_sods") or []) and common.to_number(
            (op.get("target_five_cols") or {}).get("计提")
        ) is not None
    return (
        str(result.get("sod") or "").strip() == sod
        and common.to_number((result.get("five_cols") or {}).get("计提")) is not None
    )

def _apply_so_accrual_gate(
    results: List[dict], ledger: Optional[LedgerIndex], tolerance: float
) -> None:
    """
    同一 SO 有多个 SOD 时，只有全部 SOD 结清才允许计提。

    最后一个 SOD 结清的同批计划还会携带历史补填：此前已结清但计提为空的
    SOD，只在其最后一条已结清业务行补一次计提；校验和写入层会再次逐行复核。
    """
    if ledger is None:
        return
    by_so: Dict[str, List[dict]] = {}
    for result in results:
        so = str(result.get("so") or "").strip()
        if so:
            by_so.setdefault(so, []).append(result)

    for so, group in by_so.items():
        if ledger.so_settlement(so)["all_settled"]:
            continue  # 已整单结账不清空计提、不生成历史补填。
        all_sods: set[str] = set()
        delivery_by_sod: Dict[str, float] = {}
        group_delivery_sods: set[str] = set()
        for result in group:
            source = result.get("split_payment_source") or {}
            scope = source.get("receivable_group_scope") or {}
            if scope:
                group_delivery_sods.update(scope.get("source_sods") or [])
            all_sods.update(
                str(sod or "").strip() for sod in (source.get("all_sods") or [])
                if str(sod or "").strip()
            )
            for sod, amount in (source.get("sod_delivery_local") or {}).items():
                sod_s = str(sod or "").strip()
                amount_n = common.to_number(amount)
                if sod_s and amount_n is not None:
                    delivery_by_sod[sod_s] = round(float(amount_n), 2)
            # 兼容直接构造的单元测试/人工计划：每条 SOD record 自身的最新
            # 交付额也是智云证据，可与同批其它 SOD 拼成完整映射。
            result_sod = str(result.get("sod") or "").strip()
            result_delivery = common.to_number(source.get("delivery_local"))
            if result_sod and result_delivery is not None:
                delivery_by_sod[result_sod] = round(float(result_delivery), 2)

        # 单 SOD 继续沿用原有逐单计提规则；没有完整 SOD 清单时也不得猜测。
        if len(all_sods) <= 1:
            continue

        planned_settled: set[str] = set()
        for result in group:
            planned_settled.update(_planned_settled_sods(result))

        unsettled: List[str] = []
        missing_delivery = sorted(sod for sod in all_sods if sod not in delivery_by_sod and sod not in group_delivery_sods)
        for sod in sorted(all_sods):
            same_sod_results = [
                result for result in group
                if str(result.get("sod") or "").strip() == sod
            ]
            if any(result.get("bucket") != "auto" or
                   (result.get("baseline_receipt_audit") or {}).get("disposition") == "conflict"
                   for result in same_sod_results):
                unsettled.append(sod)
                continue
            if sod in planned_settled:
                continue
            if ledger.settled_without_open_row(so, sod) is None:
                unsettled.append(sod)

        all_settled = not unsettled and not missing_delivery
        current_batch_sods = sorted(planned_settled & all_sods)
        audit = {
            "rule": "all_sods_under_so_before_accrual",
            "so": so,
            "all_sods": sorted(all_sods),
            "current_batch_sods": current_batch_sods,
            "prior_settled_sods": sorted(all_sods - set(current_batch_sods)),
            "settled_sods": sorted(all_sods - set(unsettled)),
            "unsettled_sods": sorted(set(unsettled)),
            "missing_delivery_sods": missing_delivery,
            "all_settled": all_settled,
        }
        for result in group:
            result["so_accrual_audit"] = dict(audit)

        if not all_settled:
            for result in group:
                _clear_new_accrual(result)
                warnings = list(result.get("warning_codes") or [])
                if "W_SO_ACCRUAL_DEFERRED" not in warnings:
                    warnings.append("W_SO_ACCRUAL_DEFERRED")
                result["warning_codes"] = warnings
                detail = sorted(set(unsettled) | set(missing_delivery))
                result["reason"] = (
                    f"{result.get('reason') or '核销命中'}；同一 SO 尚有 SOD 未全部结清或缺少交付额"
                    f"（{','.join(detail) or '-'}），本批计提暂不填写"
                )
            continue

        aggregate_sods: set[str] = set()
        for result in group:
            op = result.get("row_operation") or {}
            scope = (result.get("split_payment_source") or {}).get("receivable_group_scope") or {}
            aggregate_sods.update(scope.get("source_sods") or [])
            if op.get("type") == "same_so_multi_sod_aggregate":
                aggregate_sods.update(str(x or "").strip() for x in op.get("member_sods") or [])

        backfills: List[dict] = []
        for sod in sorted(all_sods):
            if sod in aggregate_sods or any(
                _has_new_planned_accrual(result, sod) for result in group
            ):
                continue
            business_rows = ledger.business_rows(so, sod)
            settled_rows = [
                row_no for row_no in business_rows
                if str((ledger.row_snapshot.get(row_no) or {}).get("jiezhang") or "").strip() == "是"
            ]
            if not settled_rows:
                continue
            target_row = max(settled_rows)
            snap = ledger.row_snapshot.get(target_row) or {}
            target_accrual = round(float(delivery_by_sod[sod]), 2)
            existing_accrual = common.to_number(snap.get("jiti"))
            if (
                existing_accrual is not None
                and abs(float(existing_accrual) - target_accrual) <= max(tolerance, TOL)
            ):
                continue
            receivables = [
                common.to_number((ledger.row_snapshot.get(row_no) or {}).get("yingshou"))
                for row_no in business_rows
            ]
            baseline = (
                round(sum(float(value) for value in receivables if value is not None), 2)
                if any(value is not None for value in receivables) else None
            )
            difference = (
                round(float(baseline) - target_accrual, 2)
                if baseline is not None
                and abs(float(baseline) - target_accrual) > max(tolerance, TOL)
                else None
            )
            backfills.append({
                "so": so,
                "sod": sod,
                "ledger_row_ref": int(target_row),
                "business_rows": [int(row_no) for row_no in business_rows],
                "accrual": target_accrual,
                "difference": difference,
                "current_accrual": snap.get("jiti"),
                "current_difference": snap.get("chayi"),
                "historical_receipt_time": common.norm_date(
                    snap.get("shoukuan_time")
                ),
                "current_batch_sods": current_batch_sods,
                "all_sods": sorted(all_sods),
                "ledger_year": next(
                    (result.get("ledger_year") for result in group if result.get("ledger_year")),
                    None,
                ),
            })

        carriers = [
            result for result in group
            if result.get("bucket") == "auto" and result.get("ledger_row_ref") is not None
            and (result.get("baseline_receipt_audit") or {}).get("disposition") not in {"skip", "conflict"}
            and not result.get("same_so_multi_sod_absorbed")
            and not result.get("tail_tolerance_absorbed")
        ]
        if backfills and carriers:
            carrier = carriers[-1]
            carrier["so_accrual_backfills"] = backfills
            carrier["so_accrual_audit"] = {**audit, "backfill_count": len(backfills)}
            carrier["reason"] = (
                f"{carrier.get('reason') or '核销命中'}；同一 SO 的全部 SOD 已结清，"
                f"同步补填此前 {len(backfills)} 个已结清 SOD 的计提"
            )
        for result in group:
            warnings = list(result.get("warning_codes") or [])
            if "W_SO_ALL_SODS_SETTLED_ACCRUAL_RELEASED" not in warnings:
                warnings.append("W_SO_ALL_SODS_SETTLED_ACCRUAL_RELEASED")
            result["warning_codes"] = warnings

def _historical_sod_writeoff_index(
    workspace: Path, current_hexiao_date: Optional[dt.date]
) -> Dict[Tuple[str, str], List[dict]]:
    """从当前工作区既有日清结果读取 SO/SOD 的真实历史核销日期。"""
    out_dir = Path(workspace) / "04_产出"
    index: Dict[Tuple[str, str], List[dict]] = {}
    if not out_dir.is_dir():
        return index
    for path in sorted(out_dir.glob("判定结果_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        history_date = common.norm_date(payload.get("hexiao_date"))
        if history_date is None:
            continue
        if current_hexiao_date is not None and history_date >= current_hexiao_date:
            continue
        for item in payload.get("auto") or []:
            so = str(item.get("so") or "").strip()
            sod = str(item.get("sod") or "").strip()
            if not so or not sod:
                continue
            index.setdefault((so, sod), []).append({
                "hexiao_date": history_date.isoformat(),
                "source": path.name,
            })
    return index

def annotate_cross_month_accruals(
    result: dict,
    workspace: Path,
    current_hexiao_date: Optional[dt.date],
) -> List[dict]:
    """
    标出“本批结清整个 SO，并补填以前月份 SOD 计提”的使用者提示。

    历史核销月份优先取当前工作区既有《判定结果》的真实核销日期。若工作区
    缺历史日清，按业务口径直接使用盈亏表收款时间判断月份；两者都缺失才待确认。
    """
    history_index = _historical_sod_writeoff_index(workspace, current_hexiao_date)
    notices: List[dict] = []
    for item in result.get("auto") or []:
        audit = item.get("so_accrual_audit") or {}
        if not audit.get("all_settled"):
            continue
        current_sods = sorted({
            str(sod or "").strip() for sod in (audit.get("current_batch_sods") or [])
            if str(sod or "").strip()
        })
        all_sods = sorted({
            str(sod or "").strip() for sod in (audit.get("all_sods") or [])
            if str(sod or "").strip()
        })
        if not current_sods or set(current_sods) >= set(all_sods):
            continue
        for backfill in item.get("so_accrual_backfills") or []:
            so = str(backfill.get("so") or item.get("so") or "").strip()
            sod = str(backfill.get("sod") or "").strip()
            if not so or not sod or sod in set(current_sods):
                continue
            evidence = history_index.get((so, sod), [])
            dates = sorted({str(row.get("hexiao_date") or "") for row in evidence if row.get("hexiao_date")})
            sources = sorted({str(row.get("source") or "") for row in evidence if row.get("source")})
            exact_cross_month = bool(
                current_hexiao_date
                and any(
                    (history_date := common.norm_date(value)) is not None
                    and (history_date.year, history_date.month)
                    != (current_hexiao_date.year, current_hexiao_date.month)
                    for value in dates
                )
            )
            receipt_date = common.norm_date(backfill.get("historical_receipt_time"))
            receipt_cross_month = bool(
                current_hexiao_date
                and receipt_date
                and (receipt_date.year, receipt_date.month)
                != (current_hexiao_date.year, current_hexiao_date.month)
            )
            # 历史日清优先；缺历史日清时，按业务口径以盈亏表收款时间判断月份。
            # 有判断日期且全部在本月时不是跨月；两种日期都缺失才列为待确认。
            if dates and not exact_cross_month:
                continue
            if not dates and receipt_date and not receipt_cross_month:
                continue
            effective_dates = dates or (
                [receipt_date.isoformat()] if receipt_date else []
            )
            month_status = "是" if (exact_cross_month or receipt_cross_month) else "待确认"
            history_source = (
                "历史核销日清" if dates
                else "盈亏核算表收款时间" if receipt_date
                else "未找到历史日清及盈亏收款时间"
            )
            notice = {
                "so": so,
                "current_batch_sods": current_sods,
                "historical_sod": sod,
                "all_sods": all_sods,
                "current_hexiao_date": (
                    current_hexiao_date.isoformat() if current_hexiao_date else ""
                ),
                "historical_hexiao_dates": effective_dates,
                "historical_hexiao_months": sorted({value[:7] for value in effective_dates}),
                "cross_month_status": month_status,
                "history_source": history_source,
                "history_source_files": sources,
                "historical_receipt_time": (
                    receipt_date.isoformat() if receipt_date else ""
                ),
                "current_accrual": backfill.get("current_accrual"),
                "planned_accrual": backfill.get("accrual"),
                "planned_difference": backfill.get("difference"),
                "ledger_year": backfill.get("ledger_year") or item.get("ledger_year"),
                "ledger_row_ref": backfill.get("ledger_row_ref"),
                "reason": (
                    "本次核销完成后该 SO 的全部 SOD 已结清，"
                    "因此同步补填以前已结清但计提为空的 SOD"
                ),
            }
            backfill["cross_month_accrual_notice"] = dict(notice)
            notices.append(notice)
    result["cross_month_accrual_cases"] = notices
    return notices
