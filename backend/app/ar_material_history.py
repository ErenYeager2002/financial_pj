"""Verify existing receipt facts when a newer annual workbook is selected."""
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import hashlib
import re
import openpyxl
from .models import FileRecord


def receipt_rows(path):
    path = Path(path)
    if path.suffix.lower() == ".xls":
        import xlrd
        book = xlrd.open_workbook(str(path))
        sheet = book.sheet_by_name("明细")
        rows = [[xlrd.xldate_as_datetime(cell.value, book.datemode) if cell.ctype == xlrd.XL_CELL_DATE else cell.value
                 for cell in sheet.row(i)] for i in range(sheet.nrows)]
        book.release_resources()
    else:
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            rows = list(book["明细"].values)
        finally:
            book.close()
    aliases = {"so": ("新智云单号", "SO", "SO号"), "sod": ("实收金额", "实收SOD", "SOD", "SOD号"),
               "amount": ("回款明细",), "date": ("收款时间", "收款日期"),
               "method": ("收款方式(支/汇/现)", "收款方式（支/汇/现）", "收款方式")}
    columns = None
    for index, row in enumerate(rows[:30]):
        headers = [str(v or "").strip() for v in row]
        found = {key: next((headers.index(a) for a in names if a in headers), None) for key, names in aliases.items()}
        if all(value is not None for value in found.values()):
            columns, start = found, index + 1
            break
    if columns is None:
        raise ValueError("最新盈亏表缺少核实历史回款所需的SO、SOD、回款、日期或方式列")
    result = []
    for row_number, row in enumerate(rows[start:], start + 1):
        values = {key: row[col] if col < len(row) else None for key, col in columns.items()}
        if not str(values["so"] or "").strip():
            continue
        raw = values["amount"]
        if raw in (None, ""):
            raw = 0
        try:
            amount = Decimal(str(raw)).quantize(Decimal("0.01"))
            if not amount.is_finite():
                raise ValueError("历史回款金额不是有限数值")
        except InvalidOperation as exc:
            raise ValueError("历史回款金额无法核实") from exc
        day = values["date"]
        if isinstance(day, (date, datetime)):
            day = day.strftime("%Y-%m-%d")
        else:
            day = str(day or "").strip()
            parts = re.fullmatch(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?", day)
            if parts:
                day = date(*(int(part) for part in parts.groups())).isoformat()
        result.append({"row": row_number, "so": str(values["so"] or "").strip(),
                       "sod": str(values["sod"] or "").strip(), "amount": str(amount),
                       "date": day, "method": str(values["method"] or "").strip()})
    return result


def fact(row):
    return tuple(row[k] for k in ("so", "sod", "amount", "date", "method"))


def receipt_facts(path):
    return Counter(fact(row) for row in receipt_rows(path) if Decimal(row["amount"]))


def history_differences(previous, current, year):
    old = Counter(fact(row) for row in previous if Decimal(row["amount"]))
    new = Counter(fact(row) for row in current if Decimal(row["amount"]))
    missing, extra = old - new, new - old
    differences = []
    for key, count in missing.items():
        candidates = [row for row in current if (row["so"], row["sod"]) == key[:2]]
        conflicting = [row for row in candidates if extra.get(fact(row), 0) or
                       (not Decimal(row["amount"]) and (row["date"] or row["method"]))]
        differences.append({"year": year, "sheet": "明细", "so": key[0], "sod": key[1],
                            "status": "conflict" if conflicting else "missing",
                            "expected": dict(zip(("so", "sod", "amount", "date", "method"), key)),
                            "previous_rows": [row["row"] for row in previous if fact(row) == key],
                            "current_rows": candidates, "count": count})
    return differences


def verify_updated_annual_materials(db, ancestor, selected, *, differences=None):
    """Flow changes and identical content need no financial-history remapping."""
    before = {(f.role, f.year): f for f in ancestor.files}
    changed = []
    for current in selected.files:
        previous = before.get((current.role, current.year))
        if current.role != "profit_loss_ledgers" or previous is None or current.sha256 == previous.sha256:
            continue
        paths = []
        for member in (previous, current):
            record = db.get(FileRecord, member.file_id)
            if record is None or (record.owner_id, record.department_id, record.skill_id) != (selected.owner_id, selected.department_id, selected.skill_id):
                raise ValueError("盈亏表历史核实的文件归属不一致")
            path = Path(record.stored_path)
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != member.sha256:
                raise ValueError("盈亏表历史核实的文件不存在或指纹已改变")
            paths.append(path)
        changes = history_differences(receipt_rows(paths[0]), receipt_rows(paths[1]), current.year)
        if differences is not None:
            differences.extend(changes)
        changed.append(current.year)
    return changed
