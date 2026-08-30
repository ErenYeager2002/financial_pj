#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把多个已选核销日的日期级报表整理为一份任务范围版静态 Excel。

多日任务的日期级 Excel 只是逐日校验和写入时的临时产物。整合范围版成功
生成后，自动删除本次已选日期的日期级同类报告，只保留任务版交付文件。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from copy import copy
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import workbook_finalize  # noqa: E402


CLEANUP_REPORT_PREFIXES = ("核销日清", "变更清单", "订单写入差异")
AGGREGATED_SHEETS = {
    "今日清单": "核销明细",
    "跨月计提补填": "跨月计提补填",
    "流转表怎么填": "流转表怎么填",
}


def _dates(start: str, end: str):
    current = dt.date.fromisoformat(start)
    finish = dt.date.fromisoformat(end)
    if current > finish:
        raise ValueError("开始日期不能晚于结束日期")
    while current <= finish:
        yield current
        current += dt.timedelta(days=1)


def _selected_days(start: str, end: str, selected_dates=None) -> list[dt.date]:
    if selected_dates:
        days = sorted({dt.date.fromisoformat(value) for value in selected_dates})
        if start and days[0] < dt.date.fromisoformat(start):
            raise ValueError("已选日期不能早于开始日期")
        if end and days[-1] > dt.date.fromisoformat(end):
            raise ValueError("已选日期不能晚于结束日期")
        return days
    if not start or not end:
        raise ValueError("未提供已选日期时必须同时提供开始日期和结束日期")
    return list(_dates(start, end))


def _task_report_name(days: list[dt.date]) -> str:
    start = days[0].strftime("%Y%m%d")
    end = days[-1].strftime("%Y%m%d")
    consecutive = len(days) == (days[-1] - days[0]).days + 1
    if consecutive:
        return f"核销日清_{start}_{end}.xlsx"
    return f"核销日清_已选{len(days)}日_{start}_{end}.xlsx"


def _copy_sheet(source, target) -> None:
    for row in source.iter_rows():
        for cell in row:
            out = target[cell.coordinate]
            out.value = cell.value
            # 范围版和多年度合并版都是静态审计报表。源报表中的「公式原文」
            # 以 = 开头，但它只是供人核对的说明文字；openpyxl 赋值到新
            # 单元格时会把它重新识别成可执行公式，导致静态报表校验失败。
            if isinstance(cell.value, str) and cell.value.startswith("="):
                out.data_type = "s"
            if cell.has_style:
                out._style = copy(cell._style)
            if cell.number_format:
                out.number_format = cell.number_format
            out.alignment = copy(cell.alignment)
            out.protection = copy(cell.protection)
    for key, dim in source.column_dimensions.items():
        target.column_dimensions[key].width = dim.width
        target.column_dimensions[key].hidden = dim.hidden
    for key, dim in source.row_dimensions.items():
        target.row_dimensions[key].height = dim.height
        target.row_dimensions[key].hidden = dim.hidden
    for merged in source.merged_cells.ranges:
        target.merge_cells(str(merged))
    target.freeze_panes = source.freeze_panes
    target.sheet_view.showGridLines = source.sheet_view.showGridLines
    target.auto_filter.ref = source.auto_filter.ref


def _daily_counts(out_dir: Path, day: dt.date) -> dict:
    token = day.strftime("%Y%m%d")
    result_path = out_dir / f"判定结果_{token}.json"
    if not result_path.is_file():
        return {}
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    counts = payload.get("counts") or {}
    return {
        "到账笔数": payload.get("payment_count", ""),
        "订单行数": counts.get("total", ""),
        "自动": counts.get("auto", ""),
        "挂账": counts.get("hold", ""),
        "异常": counts.get("exception", ""),
    }


def _is_empty_fetched_day(workspace: Path, day: dt.date) -> bool:
    summary_path = workspace / "01_智云导出" / f"取数摘要_{day.strftime('%Y%m%d')}.json"
    if not summary_path.is_file():
        return False
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(summary, dict):
        return False
    keys = ("回款记录笔数", "下单行数", "核销明细行数", "订单明细SOD行数")
    values = [summary.get(key) for key in keys]
    return bool(
        all(isinstance(value, int) and not isinstance(value, bool) for value in values)
        and all(value == 0 for value in values)
    )


def _daily_report_files(out_dir: Path, prefix: str, day: dt.date) -> list[Path]:
    """返回某核销日的正式日报及多年度内部报告，不误匹配范围版文件。"""
    token = day.strftime("%Y%m%d")
    name_re = re.compile(
        rf"^{re.escape(prefix)}_{token}(?:_\d{{4}})?\.xlsx$"
    )
    return sorted(
        path for path in out_dir.glob(f"{prefix}_{token}*.xlsx")
        if name_re.fullmatch(path.name)
    )


def _append_aggregated_sheet(
    target,
    source,
    day: dt.date,
    header_written: bool,
) -> bool:
    rows = list(source.iter_rows())
    if not rows:
        return header_written
    source_header = rows[0]
    if not header_written:
        target.append(["核销日期", *(cell.value for cell in source_header)])
        for column, cell in enumerate(source_header, start=2):
            output = target.cell(row=1, column=column)
            if cell.has_style:
                output._style = copy(cell._style)
            output.number_format = cell.number_format
            output.alignment = copy(cell.alignment)
            output.protection = copy(cell.protection)
        target.cell(row=1, column=1).font = Font(bold=True)
        target.cell(row=1, column=1).fill = PatternFill("solid", fgColor="D9EAF7")
        target.cell(row=1, column=1).alignment = copy(source_header[0].alignment)
        header_written = True
    for source_row in rows[1:]:
        values = [cell.value for cell in source_row]
        if not any(value not in (None, "") for value in values):
            continue
        target.append([day.isoformat(), *values])
        output_row = target.max_row
        target.cell(row=output_row, column=1).alignment = copy(source_header[0].alignment)
        for column, cell in enumerate(source_row, start=2):
            output = target.cell(row=output_row, column=column)
            if isinstance(cell.value, str) and cell.value.startswith("="):
                output.data_type = "s"
            if cell.has_style:
                output._style = copy(cell._style)
            output.number_format = cell.number_format
            output.alignment = copy(cell.alignment)
            output.protection = copy(cell.protection)
    return header_written


def build(
    workspace: Path,
    start: str,
    end: str,
    *,
    selected_dates=None,
) -> list[Path]:
    workspace = Path(workspace)
    if not (workspace / "04_产出").is_dir():
        workspace = common.resolve_workspace(workspace)
    out_dir = workspace / "04_产出"
    days = _selected_days(start, end, selected_dates)
    empty_days = {day for day in days if _is_empty_fetched_day(workspace, day)}
    outputs = []
    daily_sources: set[Path] = set()
    wb = openpyxl.Workbook()
    summary = wb.active
    summary.title = "任务范围"
    headers = ["核销日期", "日报状态", "到账笔数", "订单行数", "自动", "挂账", "异常"]
    summary.append(headers)
    for cell in summary[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAF7")

    aggregated: dict[str, object] = {}
    header_written: set[str] = set()
    for day in days:
        token = day.strftime("%Y%m%d")
        daily = out_dir / f"核销日清_{token}.xlsx"
        for prefix in CLEANUP_REPORT_PREFIXES:
            daily_sources.update(_daily_report_files(out_dir, prefix, day))
        counts = _daily_counts(out_dir, day)
        status = (
            "已纳入"
            if daily.is_file()
            else "无核销记录，已跳过"
            if day in empty_days
            else "当日无该报表"
        )
        summary.append([
            day.isoformat(), status,
            counts.get("到账笔数", ""), counts.get("订单行数", ""),
            counts.get("自动", ""), counts.get("挂账", ""), counts.get("异常", ""),
        ])
        if not daily.is_file():
            if day not in empty_days:
                raise FileNotFoundError(f"缺少日期级核销日清：{daily}")
            continue
        source_wb = openpyxl.load_workbook(daily, data_only=False, read_only=False)
        for source_title, target_title in AGGREGATED_SHEETS.items():
            if source_title not in source_wb.sheetnames:
                continue
            target = aggregated.get(target_title)
            if target is None:
                target = wb.create_sheet(target_title)
                aggregated[target_title] = target
            if _append_aggregated_sheet(
                target,
                source_wb[source_title],
                day,
                target_title in header_written,
            ):
                header_written.add(target_title)
        source_wb.close()

    summary.freeze_panes = "A2"
    summary.auto_filter.ref = summary.dimensions
    for col, width in zip("ABCDEFG", (14, 16, 12, 12, 10, 10, 10)):
        summary.column_dimensions[col].width = width
    if "核销明细" in aggregated:
        detail = aggregated["核销明细"]
        detail.freeze_panes = "B2"
        detail.auto_filter.ref = detail.dimensions
        detail.column_dimensions["A"].width = 14
    for title, sheet in aggregated.items():
        if title != "核销明细":
            sheet.freeze_panes = "B2"
            sheet.auto_filter.ref = sheet.dimensions
            sheet.column_dimensions["A"].width = 14
    target = out_dir / _task_report_name(days)
    wb.save(target)
    workbook_finalize.finalize_static_report(target)
    outputs.append(target)

    # 只有多日任务执行清理。必须等整合范围版保存并完成静态化后再删除日报，
    # 这样任一步失败时仍保留逐日证据，可安全重试。
    if len(days) > 1:
        final_paths = {path.resolve() for path in outputs}
        for source in sorted(daily_sources):
            if source.resolve() not in final_paths and source.is_file():
                source.unlink()
    return outputs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="生成多个已选核销日的一份整合核销日清，并移除已选日期的日报"
    )
    parser.add_argument("--workspace", default=str(common.WORK))
    parser.add_argument("--date-from", default="")
    parser.add_argument("--date-to", default="")
    parser.add_argument("--date", action="append", default=[], help="明确指定一个核销日，可重复")
    args = parser.parse_args(argv)
    try:
        outputs = build(
            Path(args.workspace),
            args.date_from,
            args.date_to,
            selected_dates=args.date,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
