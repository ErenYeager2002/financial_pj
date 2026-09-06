"""Use a task's pinned annual workbook roles without consulting today's year."""
from __future__ import annotations

import re
from pathlib import Path


def fixed_annual_ledgers(workspace: Path, mapping: object) -> dict[int, Path]:
    if not isinstance(mapping, dict) or not mapping or len(mapping) > 32:
        raise ValueError("任务固定的年度盈亏映射缺失、无效或超过 32 份上限，不能按当前年份重新猜测。")
    root = workspace.resolve(strict=True)
    folder = root / "02_我的表副本"
    if not folder.is_dir() or folder.is_symlink() or folder.resolve().parent != root:
        raise ValueError("任务年度盈亏副本目录缺失或不属于固定工作区。")
    ledgers = {}
    for year, raw_path in mapping.items():
        if not re.fullmatch(r"20\d{2}", str(year)) or not isinstance(raw_path, (str, Path)) or not str(raw_path):
            raise ValueError("任务年度盈亏映射包含无效年份或文件引用。")
        path = Path(raw_path)
        if not path.is_absolute():
            raise ValueError(f"{year} 年盈亏引用不是固定的绝对路径。")
        if (path.is_symlink() or not path.is_file() or path.resolve().parent != folder
                or path.suffix.lower() not in {".xlsx", ".xlsm"}):
            raise ValueError(f"{year} 年盈亏副本缺失、格式不支持或超出固定目录。")
        if path.resolve() in ledgers.values() or int(year) in ledgers:
            raise ValueError("年度盈亏映射重复引用同一年份或同一文件，不能区分年度。")
        ledgers[int(year)] = path.resolve()
    discovered = {path.resolve() for path in folder.glob("*盈亏*.xls*")
                  if path.is_file() and not path.name.startswith(("~$", ".")) and "便携版" not in path.stem}
    if discovered != set(ledgers.values()):
        raise ValueError("年度盈亏文件集合与任务固定映射不一致，存在新增、缺失或非预期文件。")
    return dict(sorted(ledgers.items()))


def annual_ledgers_in_copy(source: Path, target: Path, ledgers: dict[int, Path]) -> dict[int, Path]:
    source = source.resolve(strict=True)
    target = target.resolve(strict=True)
    mapping = {year: target / path.relative_to(source) for year, path in ledgers.items()}
    return fixed_annual_ledgers(target, mapping)
