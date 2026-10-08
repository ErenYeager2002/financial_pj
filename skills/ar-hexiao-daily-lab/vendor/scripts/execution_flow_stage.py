#!/usr/bin/env python3
"""Run the flow stage after verified ledger writes, retaining both phase outcomes."""
from __future__ import annotations

import argparse
import copy
import re
import json
from pathlib import Path

import apply_flow
import build_flow_plan
import common


def remap_manual_rows(items: list[dict], changes: list[dict]) -> list[dict]:
    """Keep plan coordinates fixed; report coordinates refer to delivered rows."""
    result=copy.deepcopy(items)
    for manual in result:
        row=manual.get("row_no")
        if not isinstance(row,int) or row<=0:
            continue
        def shift(value):
            return value+sum(
                change.get("文件")==manual.get("file")
                and change.get("sheet")==manual.get("sheet")
                and isinstance(change.get("inserted_after_row"),int)
                and change["inserted_after_row"]<value
                for change in changes)
        manual["row_no"]=shift(row)
        # This exact internal diagnostic embeds a list of workbook coordinates.
        # Do not replace arbitrary digits: reasons also contain financial amounts.
        reason=manual.get("reason")
        if isinstance(reason,str):
            manual["reason"]=re.sub(r"流转行([0-9]+(?:,[0-9]+)*)已出现",
                lambda m:"流转行"+",".join(str(shift(int(v))) for v in m[1].split(","))+"已出现",reason)
    return result


def run(workspace: Path, checked: Path) -> dict:
    plan = json.loads(checked.read_text(encoding="utf-8"))
    date = common.norm_date(plan.get("hexiao_date"))
    if date is None:
        raise ValueError("校验后计划缺少核销日期")
    tag = date.strftime("%Y%m%d")
    source = workspace / "04_产出" / "流转写入计划_校验后.json"
    result = {"schema_version": "ar-flow-result-v1", "flow_written": False, "phases": {}}
    try:
        flow = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(flow, dict) or not isinstance(flow.get("items"), list):
            raise ValueError("流转计划无效")
    except (OSError, ValueError) as exc:
        result["phases"]["plan"] = {"state": "failed", "error_type": type(exc).__name__, "reason": str(exc)}
        return result
    result["manual_count"] = sum(item.get("verdict") == "hand" for item in flow["items"])
    for phase in ("prefill", "status"):
        try:
            phase_plan = flow if phase == "prefill" else build_flow_plan.finalize_plan_after_ledger(flow, plan, workspace=workspace)
            if phase == "status":
                result["manual_items"] = phase_plan["manual_items"]
                result["manual_count"] = len(result["manual_items"])
                (workspace / "04_产出" / f"流转状态回填计划_{tag}.json").write_text(
                    json.dumps(phase_plan, ensure_ascii=False, indent=2), encoding="utf-8",
                )
            items = phase_plan.get("items") or []
            changes, problems = apply_flow.write_flow_items(workspace, items, in_place=True, phase=phase)
            report = workspace / "04_产出" / f"流转{'前置' if phase == 'prefill' else '状态'}变更清单_{tag}.xlsx"
            apply_flow.write_change_report(changes, report)
            eligible = sum(item.get("verdict") == "write" for item in items)
            monthly_prefill = phase == "prefill" and any(item.get("monthly_schema") for item in items)
            if monthly_prefill:
                from flow_order_prefill import pending_sos
                eligible = sum(item.get("verdict") == "write" and bool(pending_sos(item)) and not item.get("source_receipts") for item in items)
            applicable = not monthly_prefill or eligible > 0
            result["phases"][phase] = {
                "state": "failed" if problems else "verified",
                "applicable": applicable,
                "reason": "本批没有需要单独预填的待处理订单" if not applicable else "",
                "eligible_count": eligible,
                "changed_count": None if problems else len(changes),
                "unchanged_count": None if problems else eligible - len(changes),
                "problems": problems,
                "changes": changes,
            }
            if phase == "status" and not problems:
                result["manual_items"] = remap_manual_rows(result["manual_items"], changes)
                result["manual_row_basis"] = "final_workbook_v1"
            if problems:
                break
        except Exception as exc:
            result["phases"][phase] = {"state": "failed", "error_type": type(exc).__name__, "reason": str(exc)}
            break
    result["flow_written"] = result["phases"].get("status", {}).get("state") == "verified"
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="盈亏回读后的流转登记及状态回填")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--checked", required=True)
    args = parser.parse_args(argv)
    workspace = Path(args.workspace).resolve(strict=True)
    checked = Path(args.checked).resolve(strict=True)
    if not checked.is_relative_to(workspace):
        raise ValueError("计划超出当前工作区")
    result = run(workspace, checked)
    target = workspace / "04_产出" / "流转阶段执行结果.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("AR_FLOW_RESULT " + json.dumps({"flow_written": result["flow_written"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
