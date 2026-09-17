"""Read-only empty-date proof using the task's pinned classifier and exports."""
from __future__ import annotations
import argparse
import importlib
import json
from pathlib import Path
import sys


def confirmed_empty(classifier, workspace: Path, day):
    try:
        payments = classifier.load_exports(workspace, target_date=day)
    except classifier.InputError as exc:
        # Only this explicit no-record outcome is eligible. Missing snapshots,
        # columns, orphan details and all other input errors remain failures.
        if str(exc) != f"目标核销日没有可处理的回款记录：{day}":
            raise
    else:
        if payments:
            return False
    # A missing parent can also produce no payments. Independently check raw
    # dates so an orphan same-day detail can never be mistaken for an empty day.
    for kind in ("回款记录", "核销明细"):
        files = sorted((workspace / "01_智云导出").glob(f"{kind}_*.xlsx"))
        if not files:
            raise ValueError(f"缺少{kind}，无法确认空日期")
        for path in files:
            headers, rows = classifier._sheet_rows(path)
            if "核销日期" not in headers:
                raise ValueError(f"{kind}缺少核销日期，无法确认空日期")
            index = headers.index("核销日期")
            for row in rows:
                value = classifier.common.norm_date(row[index] if index < len(row) else None)
                if value is None:
                    raise ValueError(f"{kind}存在无法识别的核销日期，无法确认空日期")
                if value == day:
                    return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scripts", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(args.scripts).resolve()))
    classifier = importlib.import_module("classify_hexiao")
    day = classifier.common.resolve_batch_date(args.date)
    if day is None:
        raise ValueError("核销日期无效")
    empty = confirmed_empty(classifier, Path(args.workspace), day)
    print(json.dumps({"schema": "ar-empty-day-v1", "date": args.date, "empty": empty}))


if __name__ == "__main__":
    main()
