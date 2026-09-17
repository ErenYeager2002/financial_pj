"""Command-line orchestration and classification artifact generation."""
from __future__ import annotations

from pathlib import Path
from typing import List
from typing import Optional
from typing import Sequence
import amount_policy
import argparse
import common
import datetime as dt
import fallback_allocation_ledger as FAL
import json
import sys
import writeoff_duplicate_audit as WDA
from classification_accrual import annotate_cross_month_accruals
from classification_amounts import _prepare_parent_totals
from classification_contract import BUSINESS_SETTLEMENT_TOL, CoverageError, InputError, TOL
from classification_expansion import expand_payments, source_coverage
from classification_exports import assess_shifted_detail_dates, load_exports
from classification_ledger import LedgerIndex
from classification_runner import classify_records_by_year
from classification_summary import serialize_result


def payments_from_fixture(fixture: dict) -> List[dict]:
    """
    夹具格式（v2）：
      {"payments": [{ar, hexiao_date, arrival_date, amount_orig, ...,
                     orders:[{so, deliver}], writeoffs:{so: amt}}],
       "sod_lines": {"SO…": [{"sod": "SOD…", "deliver": 1.0}]}}
    """
    if "payments" not in fixture:
        raise InputError("夹具不是 v2 格式（需要 payments 键）")
    sod_lines = fixture.get("sod_lines") or {}
    out = []
    for p in fixture["payments"]:
        q = dict(p)
        q["hexiao_date"] = common.norm_date(p.get("hexiao_date"))
        q["arrival_date"] = common.norm_date(p.get("arrival_date"))
        q["amount_orig"] = common.to_number(p.get("amount_orig"))
        q["amount_local"] = common.to_number(p.get("amount_local"))
        q["fee"] = common.to_number(p.get("fee")) or 0.0
        q["fee_local"] = common.to_number(p.get("fee_local"))
        q["tax"] = common.to_number(p.get("tax")) or 0.0
        q["tax_local"] = common.to_number(p.get("tax_local"))
        q["other_fee"] = common.to_number(p.get("other_fee")) or 0.0
        q["other_fee_local"] = common.to_number(p.get("other_fee_local"))
        q.setdefault("currency", "人民币CNY")
        q.setdefault("orders", [])
        q.setdefault("writeoffs", {})
        q["sod_lines"] = sod_lines
        _prepare_parent_totals(q)
        out.append(q)
    return out

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="核销判定（单入口 · SOD 级 · 三栏）")
    ap.add_argument("--workspace", default=str(common.WORK))
    ap.add_argument("--fixture", default="", help="离线夹具 JSON（v2: payments/sod_lines）")
    ap.add_argument("--ledger", default="", help="本年度盈亏核算表副本（只读）")
    ap.add_argument(
        "--ledger-year", action="append", default=[], metavar="YEAR=PATH",
        help="其它年度盈亏工作副本，可重复，例如 2025=...xlsx",
    )
    ap.add_argument("--rate", action="append", default=[], help="外币汇率 美元USD=7.0")
    ap.add_argument("--out", default="", help="判定结果 json 路径")
    ap.add_argument("--flow", default="", help="到账流转表副本（只读）；不给则扫 02_我的表副本/")
    ap.add_argument("--flow-source-workspace", default="", help="优化测试的只读流转材料目录")
    ap.add_argument(
        "--name-map", action="append", default=[],
        help="名称对照表路径（表头为到账名称/系统客户名称），可重复；默认按表头自动识别",
    )
    ap.add_argument(
        "--flow-complete", action="store_true",
        help="声明当天所有渠道的流转表都已给全；只有这时才判 E0（对不到账）",
    )
    ap.add_argument(
        "--hexiao-date", default="",
        help="声明这批是哪个**核销日期**（由任务指令确定）。给了就跟数据核对，对不上直接退出",
    )
    ap.add_argument(
        "--allow-mixed-dates", action="store_true",
        help="允许一批里混着多个核销日（默认禁止：混批会让覆盖率/幂等校验和她逐行核对全失真）",
    )
    args = ap.parse_args(argv)

    ws = common.ensure_out_dirs(args.workspace)  # 解析真工作区，防产出分家
    rates = common.parse_rate_args(args.rate)
    requested_date = common.resolve_batch_date(args.hexiao_date) if args.hexiao_date else None
    if args.hexiao_date and requested_date is None:
        print(f"ERROR: 认不出 --hexiao-date {args.hexiao_date!r}", file=sys.stderr)
        return 2

    try:
        ledger_paths = common.discover_year_ledgers(
            ws, primary=args.ledger, year_specs=args.ledger_year
        )
        ledgers = {year: LedgerIndex(path) for year, path in ledger_paths.items()}
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if not ledgers:
        print(
            "WARN: 未提供任何年度盈亏表；本年度订单 hold E2，往年订单 hold E3",
            file=sys.stderr,
        )

    try:
        if args.fixture:
            payments = payments_from_fixture(json.loads(Path(args.fixture).read_text(encoding="utf-8")))
        else:
            payments = load_exports(ws, target_date=requested_date)
        allocation_state = FAL.load(ws)
        for ledger in ledgers.values():
            ledger.baseline_receipt_state = allocation_state.get("baseline_receipts") or {}
        import current_parent_allocation
        for payment in payments:
            current_parent_allocation.attach(payment, ledgers, payments=payments)
            payment.setdefault("_fallback_allocation_state", allocation_state)
            if ledgers:
                payment["_ledger_received_local_by_so"] = {
                    str(order["so"]).strip(): ledgers[delivery_date.year].so_totals(order["so"])[1]
                    for order in (payment.get("orders") or [])
                    for delivery_date in [common.norm_date(order.get("delivery_date"))]
                    if order.get("so") and delivery_date is not None and delivery_date.year in ledgers
                }
                payment["_ledger_settled_sos"] = sorted({
                    str(order.get("so") or "").strip()
                    for order in (payment.get("orders") or [])
                    for delivery_date in [common.norm_date(order.get("delivery_date"))]
                    if order.get("so") and delivery_date is not None
                    and delivery_date.year in ledgers
                    and ledgers[delivery_date.year].so_settlement(order["so"])["all_settled"]
                })
        records = expand_payments(payments, rates)
    except (InputError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except CoverageError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 3

    import flow_ledger as FL

    name_map_paths = [Path(p) for p in args.name_map] if args.name_map else None
    flow = (
        FL.FlowLedger.from_paths([Path(args.flow)], name_map_paths=name_map_paths)
        if args.flow
        else FL.FlowLedger.from_workspace(Path(args.flow_source_workspace) if args.flow_source_workspace else ws,
                                         name_map_paths=name_map_paths)
    )
    if flow.rows:
        FL.annotate_records(records, flow, complete=args.flow_complete)
        print(f"流转表已接入：{len(flow.rows)} 行，来源 {flow.sources}")
        if flow.name_map_sources:
            print(
                f"名称对照已接入：{len(flow.name_map)} 个有效名称，来源 {flow.name_map_sources}"
            )
        if flow.name_map_issues:
            print(
                f"WARN: 名称对照表有 {len(flow.name_map_issues)} 个空值/格式问题，"
                "相关订单不自动猜测",
                file=sys.stderr,
            )
    else:
        print(
            "WARN: 未认出到账流转表（02_我的表副本/）→ 本轮不做三键匹配，"
            "E0/E12 不判、清单不给流转定位",
            file=sys.stderr,
        )

    # ── 这一批到底是哪个核销日（2026-07-25 立）─────────────────────────
    # 产出、清单、文件名一律按**核销日**走，不按"跑的那天"走：她补跑 7-22 的批次时，
    # 文件名写成运行日就会跟今天的批次撞名/盖掉，事后也说不清哪份是哪天的。
    batch_dates = sorted({p["hexiao_date"] for p in payments if p.get("hexiao_date")})
    if len(batch_dates) > 1 and not args.allow_mixed_dates:
        print(
            "ERROR: 这批数据里混着多个核销日期："
            + "、".join(d.isoformat() for d in batch_dates)
            + "\n  一次只跑一个核销日（混批会让 AR 覆盖率、幂等校验和她逐行核对全部失真）。"
            "\n  重新取一天的数，或确实要混批就加 --allow-mixed-dates。",
            file=sys.stderr,
        )
        return 2
    hexiao_date = batch_dates[0] if batch_dates else None
    if requested_date:
        if hexiao_date is not None and requested_date != hexiao_date:
            # 任务指定的是这天、数据却是那天 → 多半取数取错了日子，绝不能闷头往下判
            print(
                f"ERROR: 任务指定要跑的是 {common.date_cn(requested_date)}，"
                f"但 01_智云导出/ 里的数据是 {common.date_cn(hexiao_date)} 的。\n"
                "  按任务指定日期重新取数。",
                file=sys.stderr,
            )
            return 2
        hexiao_date = hexiao_date or requested_date

    result = classify_records_by_year(records, ledgers, rates, ledger_paths)
    duplicate_audits = next(
        (
            p.get("_duplicate_writeoff_audits")
            for p in payments if p.get("_duplicate_writeoff_audits")
        ),
        {},
    )
    result["duplicate_writeoff_audits"] = duplicate_audits
    result["duplicate_writeoff_audit_sha256"] = WDA.audit_fingerprint(duplicate_audits)
    result["flow_sources"] = flow.sources
    result["business_rules"] = {
        "parent_receipt_basis": "zhiyun_total_received_without_fee_tax_deduction",
        "whole_parent_conservation_gate": "actual_details_or_verified_parent_allocation",
        "itemized_fee_policy": "whole_parent_conservation_then_no_double_allocation",
        "writeoff_basis": "zhiyun_current_writeoff_direct",
        "parent_fallback_allocation": "missing_itemized_amount_delivery_ascending_outstanding_waterfall",
        "parent_fallback_state": FAL.LEDGER_NAME,
        "ledger_settled_precheck": (
            "all_so_business_rows_settled_skip_without_financial_write_else_current_event_signature"
        ),
        "settled_event_uncovered": (
            "open_so_closed_sod_without_current_event_evidence_is_"
            "E_SETTLED_CURRENT_EVENT_UNCOVERED"
        ),
        "ledger_year_routing": "zhiyun_project_delivery_date_to_matching_annual_ledger_no_number_inference",
        "missing_rate_policy": "use_writeoff_amount_directly",
        "technical_amount_tolerance": TOL,
        "cent_tolerance": float(amount_policy.CENT_TOLERANCE),
        "business_settlement_tolerance": BUSINESS_SETTLEMENT_TOL,
        "business_tail_policy": "keep_exact_amount_no_unpaid_row_and_absorb_tiny_parent_audit",
        "cross_month_so_accrual_notice": "report_prior_month_sods_when_current_batch_closes_entire_so",
    }
    result["parent_fallback_allocations"] = {
        p.get("ar"): p.get("_parent_fallback_allocation")
        for p in payments
        if p.get("ar") and p.get("_parent_fallback_allocation")
    }
    result["payment_count"] = len(payments)
    result["source_coverage"] = source_coverage(payments, records)
    result["shifted_detail_dates"] = assess_shifted_detail_dates(
        ws
    )
    result["hexiao_date"] = hexiao_date.isoformat() if hexiao_date else ""
    annotate_cross_month_accruals(result, ws, hexiao_date)
    stamp = hexiao_date.strftime("%Y%m%d") if hexiao_date else dt.date.today().strftime("%Y%m%d")
    out_path = Path(args.out) if args.out else (ws / "04_产出" / f"判定结果_{stamp}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(serialize_result(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    audit_path = out_path.parent / f"核销明细重复审计_{stamp}.json"
    audit_path.write_text(
        json.dumps(
            serialize_result({
                "hexiao_date": result["hexiao_date"],
                "fingerprint": result["duplicate_writeoff_audit_sha256"],
                "parents": duplicate_audits,
            }),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    c = result["counts"]
    print(f"核销日期：{common.date_cn(hexiao_date)}（这批算的是这一天核销的到账）")
    print(
        f"判定完成 到账 {len(payments)} 笔 → 订单行 {c['total']} 条："
        f"可填={c['auto']} 挂账={c['hold']} 异常={c['exception']}"
    )
    print(f"E码分布: {result['e_code_dist']}")
    sc = result["source_coverage"]
    print(
        f"来源覆盖：AR/SO {sc['produced_order_keys']}/{sc['expected_order_keys']}，"
        f"原始核销记录 {sc.get('raw_writeoff_rows', 0)}/"
        f"{sc.get('accounted_writeoff_rows', 0)} 有处置，"
        f"历史子核销还原 {sc['historical_detail_rows']} 行，SOD回补交付额 {sc['recovered_delivery_orders']} 单"
    )
    recovered = [a for a in duplicate_audits.values() if a.get("status") == "recovered"]
    unresolved = [a for a in duplicate_audits.values() if a.get("status") == "unresolved"]
    print(
        "系统重复核销审计："
        f"纠正父回款 {len(recovered)} 笔，"
        f"重复组 {sum(len(a.get('duplicate_groups') or []) for a in recovered)} 个，"
        f"忽略记录 {sum(int(a.get('ignored_record_count') or 0) for a in recovered)} 条，"
        f"未解决父回款 {len(unresolved)} 笔"
    )
    print(f"重复审计: {audit_path}")
    print(f"结果: {out_path}")

    late_other = {
        day: info for day, info in result["shifted_detail_dates"].items()
        if day != result["hexiao_date"] and info.get("needs_rerun")
    }
    if late_other:
        summary = "；".join(
            f"{day} 有 {info['rows']} 行（{len(info['ars'])} 笔AR）"
            for day, info in late_other.items()
        )
        print(
            "\n⚠ 发现后续快照才出现的历史核销明细：" + summary
            + "\n   历史日期缺少本工作区的判定证据；批次结束后按已选日期汇总核对，不自动扩大执行范围。",
            file=sys.stderr,
        )

    # 登记跑批台账：这一天判过了。没这一步就查不出"哪天从来没跑过"
    if hexiao_date is not None:
        try:
            import batch_ledger

            batch_ledger.record(
                ws, hexiao_date, "classified",
                payments=len(payments), counts=dict(c),
            )
            # 顺手把漏天报出来。**不能指望编排的 AI 记得先跑 gaps**
            # （2026-07-25 opencode 实测：它直接开跑，§0.4 的查漏天那步被跳过了）。
            # 漏天是"事后看不出来"的错，宁可每次判完都提一句。
            info = batch_ledger.find_gaps(ws, through=hexiao_date)
            others = [g for g in info["gaps"] if g != hexiao_date]
            if others:
                short = "、".join(f"{g.month}-{g.day}" for g in others[:6])
                print(
                    f"\n⚠ 还有 {len(others)} 个核销日从来没跑过：{short}"
                    f"{'…' if len(others) > 6 else ''}"
                    f"\n   跟她说一句：这几天也没跑，要不要接着补？（一天一批，从早到晚）",
                    file=sys.stderr,
                )
        except Exception as e:  # 台账写不了不该让已算对的判定失败
            print(f"WARN: 跑批台账登记失败（不影响本次判定）：{type(e).__name__}", file=sys.stderr)
    return 0
