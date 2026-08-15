from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence
from xml.etree import ElementTree as ET


SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS = f"{{{SPREADSHEET_NS}}}"
FULL_COLUMN_REF = re.compile(
    r"(?<![A-Z0-9_])(?:'[^']+'!)?\$?[A-Z]{1,3}:\$?[A-Z]{1,3}(?![A-Z0-9_])",
    re.IGNORECASE,
)
EXTERNAL_FORMULA_REF = re.compile(r"^\s*\[\d+\]")


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str


@dataclass(frozen=True)
class AuditResult:
    path: str
    size_bytes: int
    sheet_count: int
    cell_count: int
    formula_count: int
    full_column_formula_count: int
    external_formula_count: int
    style_count: int
    external_link_parts: int
    connection_parts: int
    query_table_parts: int
    pivot_parts: int
    calc_chain_parts: int
    media_parts: int
    calc_properties: dict[str, str]
    dimensions: dict[str, str]
    issues: tuple[Issue, ...]

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["errors"] = len(self.errors)
        payload["warnings"] = len(self.warnings)
        payload["lightweight_ready"] = not self.errors and not self.warnings
        return payload


def _is_true(value: str | None) -> bool:
    return str(value).lower() in {"1", "true"}


def _column_number(letters: str) -> int:
    result = 0
    for char in letters.upper():
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def _cell_coordinates(reference: str) -> tuple[int, int]:
    match = re.fullmatch(r"\$?([A-Z]{1,3})\$?(\d+)", reference, re.IGNORECASE)
    if match is None:
        raise ValueError(reference)
    return int(match.group(2)), _column_number(match.group(1))


def _dimension_size(reference: str) -> tuple[int, int, int]:
    end = reference.split(":", 1)[-1]
    row, column = _cell_coordinates(end)
    return row, column, row * column


def _count_prefixed(names: Iterable[str], prefixes: tuple[str, ...]) -> int:
    return sum(1 for name in names if name.startswith(prefixes))


def audit_workbook(path: Path) -> AuditResult:
    path = path.resolve()
    issues: list[Issue] = []
    metrics = {
        "sheet_count": 0,
        "cell_count": 0,
        "formula_count": 0,
        "full_column_formula_count": 0,
        "external_formula_count": 0,
        "style_count": 0,
        "external_link_parts": 0,
        "connection_parts": 0,
        "query_table_parts": 0,
        "pivot_parts": 0,
        "calc_chain_parts": 0,
        "media_parts": 0,
    }
    calc_properties: dict[str, str] = {}
    dimensions: dict[str, str] = {}

    try:
        with zipfile.ZipFile(path, "r") as archive:
            broken_part = archive.testzip()
            if broken_part is not None:
                issues.append(Issue("error", "E_ZIP_CRC", f"压缩部件损坏：{broken_part}"))
            names = set(archive.namelist())
            metrics["external_link_parts"] = _count_prefixed(
                names, ("xl/externalLinks/",)
            )
            metrics["connection_parts"] = int("xl/connections.xml" in names)
            metrics["query_table_parts"] = _count_prefixed(names, ("xl/queryTables/",))
            metrics["pivot_parts"] = _count_prefixed(
                names, ("xl/pivotCache/", "xl/pivotTables/")
            )
            metrics["calc_chain_parts"] = int("xl/calcChain.xml" in names)
            metrics["media_parts"] = _count_prefixed(names, ("xl/media/",))

            workbook_xml = archive.read("xl/workbook.xml")
            workbook_root = ET.fromstring(workbook_xml)
            calc_pr = workbook_root.find(NS + "calcPr")
            if calc_pr is not None:
                calc_properties = dict(calc_pr.attrib)
                if _is_true(calc_pr.attrib.get("fullCalcOnLoad")):
                    issues.append(
                        Issue("error", "E_FULL_CALC_ON_LOAD", "打开文件时要求完整重算。")
                    )
                if _is_true(calc_pr.attrib.get("forceFullCalc")):
                    issues.append(
                        Issue("error", "E_FORCE_FULL_CALC", "文件强制执行完整重算。")
                    )

            styles_name = "xl/styles.xml"
            if styles_name in names:
                styles_root = ET.fromstring(archive.read(styles_name))
                cell_xfs = styles_root.find(NS + "cellXfs")
                if cell_xfs is not None:
                    metrics["style_count"] = int(
                        cell_xfs.attrib.get("count", len(list(cell_xfs)))
                    )

            worksheet_names = sorted(
                name
                for name in names
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
            )
            metrics["sheet_count"] = len(worksheet_names)
            for worksheet_name in worksheet_names:
                sheet_root = ET.fromstring(archive.read(worksheet_name))
                dimension = sheet_root.find(NS + "dimension")
                dimension_ref = dimension.attrib.get("ref", "") if dimension is not None else ""
                dimensions[worksheet_name] = dimension_ref
                cells = sheet_root.findall(f".//{NS}c")
                formulas = sheet_root.findall(f".//{NS}f")
                metrics["cell_count"] += len(cells)
                metrics["formula_count"] += len(formulas)
                for formula in formulas:
                    text = formula.text or ""
                    if FULL_COLUMN_REF.search(text):
                        metrics["full_column_formula_count"] += 1
                    if EXTERNAL_FORMULA_REF.search(text):
                        metrics["external_formula_count"] += 1
                if dimension_ref:
                    try:
                        last_row, last_col, capacity = _dimension_size(dimension_ref)
                    except ValueError:
                        issues.append(
                            Issue(
                                "warning",
                                "W_DIMENSION_UNREADABLE",
                                f"无法识别使用区域：{worksheet_name} {dimension_ref}",
                            )
                        )
                    else:
                        sparse_limit = max(1_000_000, len(cells) * 1_000)
                        if (
                            (last_row > 100_000 or last_col > 500 or capacity > sparse_limit)
                            and len(cells) < 50_000
                        ):
                            issues.append(
                                Issue(
                                    "warning",
                                    "W_SPARSE_USED_RANGE",
                                    f"使用区域异常偏大：{worksheet_name} {dimension_ref}，实际单元格 {len(cells)} 个。",
                                )
                            )
    except FileNotFoundError:
        issues.append(Issue("error", "E_NOT_FOUND", "文件不存在。"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError) as exc:
        issues.append(Issue("error", "E_INVALID_XLSX", f"无法读取 XLSX 结构：{exc}"))

    if metrics["formula_count"] and calc_properties.get("calcMode") == "manual":
        issues.append(
            Issue("warning", "W_MANUAL_CALC", "工作簿含公式但计算模式为手动。")
        )
    if metrics["full_column_formula_count"]:
        issues.append(
            Issue(
                "warning",
                "W_FULL_COLUMN_FORMULA",
                f"发现 {metrics['full_column_formula_count']} 个整列公式引用。",
            )
        )
    if metrics["external_formula_count"] or metrics["external_link_parts"]:
        issues.append(
            Issue(
                "warning",
                "W_EXTERNAL_LINKS",
                "工作簿含外部公式或外部链接部件，打开时可能查询其它文件。",
            )
        )
    if metrics["connection_parts"] or metrics["query_table_parts"]:
        issues.append(
            Issue(
                "warning",
                "W_DATA_CONNECTIONS",
                "工作簿含数据连接或查询表，打开时可能刷新数据。",
            )
        )
    if metrics["pivot_parts"]:
        issues.append(
            Issue(
                "warning",
                "W_PIVOT_PARTS",
                "工作簿含数据透视缓存或数据透视表部件。",
            )
        )
    if metrics["style_count"] > 2_000:
        issues.append(
            Issue(
                "warning",
                "W_STYLE_BLOAT",
                f"单元格样式数量为 {metrics['style_count']}，可能存在样式膨胀。",
            )
        )
    if (
        path.exists()
        and path.stat().st_size > 10 * 1024 * 1024
        and metrics["cell_count"] < 10_000
        and metrics["media_parts"] == 0
    ):
        issues.append(
            Issue(
                "warning",
                "W_UNEXPLAINED_FILE_SIZE",
                "文件超过 10 MB，但单元格和媒体数量较少，可能含冗余部件。",
            )
        )

    return AuditResult(
        path=str(path),
        size_bytes=path.stat().st_size if path.exists() else 0,
        calc_properties=calc_properties,
        dimensions=dimensions,
        issues=tuple(issues),
        **metrics,
    )


def collect_paths(values: Sequence[str]) -> tuple[Path, ...]:
    collected: list[Path] = []
    for value in values:
        path = Path(value).expanduser()
        if path.is_dir():
            collected.extend(
                child
                for child in path.rglob("*")
                if child.suffix.lower() in {".xlsx", ".xlsm"}
                and not child.name.startswith("~$")
            )
        else:
            collected.append(path)
    return tuple(dict.fromkeys(path.resolve() for path in collected))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="检查 XLSX/XLSM 是否含有会拖慢打开速度的重算、链接、异常使用区域或样式膨胀。"
    )
    parser.add_argument("paths", nargs="+", help="工作簿或包含工作簿的目录。")
    parser.add_argument("--strict", action="store_true", help="警告也视为校验失败。")
    parser.add_argument(
        "--allow-warning",
        action="append",
        default=[],
        metavar="CODE",
        help="严格模式下允许指定警告代码，可重复使用。",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON。")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = collect_paths(args.paths)
    if not paths:
        print("没有找到 XLSX/XLSM 文件。", file=sys.stderr)
        return 2
    results = tuple(audit_workbook(path) for path in paths)
    allowed = set(args.allow_warning)
    failed = False
    for result in results:
        remaining_warnings = tuple(
            issue for issue in result.warnings if issue.code not in allowed
        )
        if result.errors or (args.strict and remaining_warnings):
            failed = True
    if args.json:
        print(
            json.dumps(
                [result.to_dict() for result in results],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for result in results:
            print(
                f"{result.path}: {result.size_bytes} 字节，{result.sheet_count} 个 sheet，"
                f"{result.cell_count} 个单元格，{result.formula_count} 个公式"
            )
            for issue in result.issues:
                allowed_text = "（已允许）" if issue.code in allowed else ""
                print(f"  {issue.severity.upper()} {issue.code}{allowed_text}: {issue.message}")
            if not result.issues:
                print("  PASS: 未发现影响轻量化的结构问题。")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
