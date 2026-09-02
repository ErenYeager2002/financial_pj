from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_legacy_builder(script_path: Path) -> ModuleType:
    script_path = script_path.resolve()
    spec = importlib.util.spec_from_file_location("legacy_build_task_reports", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("旧版范围报告脚本无法加载。")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(script_path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _report_name(selected_days: list[dt.date]) -> str:
    start = selected_days[0].strftime("%Y%m%d")
    end = selected_days[-1].strftime("%Y%m%d")
    consecutive = len(selected_days) == (selected_days[-1] - selected_days[0]).days + 1
    if consecutive:
        return f"核销日清_{start}_{end}.xlsx"
    return f"核销日清_已选{len(selected_days)}日_{start}_{end}.xlsx"


def build_selected_reports(
    script_path: Path,
    workspace: Path,
    selected_dates: list[str],
) -> Path:
    selected_days = sorted({dt.date.fromisoformat(value) for value in selected_dates})
    if not selected_days:
        raise ValueError("至少需要一个核销日期。")
    module = _load_legacy_builder(script_path)
    if not callable(getattr(module, "build", None)) or not hasattr(module, "_dates"):
        raise RuntimeError("旧版范围报告脚本不支持平台兼容调用。")

    module._dates = lambda _start, _end: iter(selected_days)
    outputs = module.build(
        workspace.resolve(),
        selected_days[0].isoformat(),
        selected_days[-1].isoformat(),
    )
    legacy_name = (
        f"核销日清_{selected_days[0].strftime('%Y%m%d')}_"
        f"{selected_days[-1].strftime('%Y%m%d')}.xlsx"
    )
    legacy_report = next(
        (Path(path) for path in outputs if Path(path).name == legacy_name),
        None,
    )
    if legacy_report is None or not legacy_report.is_file():
        raise RuntimeError("旧版范围报告脚本未生成核销日清。")
    expected_report = legacy_report.with_name(_report_name(selected_days))
    if expected_report != legacy_report:
        legacy_report.replace(expected_report)
    return expected_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="兼容旧版 Skill 快照生成已选日期范围报告")
    parser.add_argument("--script", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--date", action="append", required=True)
    args = parser.parse_args(argv)
    try:
        report = build_selected_reports(
            Path(args.script),
            Path(args.workspace),
            args.date,
        )
    except Exception:
        print("ERROR: 旧版范围报告生成失败。", file=sys.stderr)
        return 2
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
