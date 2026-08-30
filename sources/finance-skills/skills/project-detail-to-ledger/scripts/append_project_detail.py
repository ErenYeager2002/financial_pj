import argparse
import html
import json
import re
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from workbook_finalize import create_portable_copy

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
Q = lambda ns, tag: "{" + ns + "}" + tag

PROJECT_HEADERS = ["销售", "客户", "SO", "SOD", "业务类别", "订单名称", "下单日期", "整单交付日期", "下单数量", "单价", "交付额/本币", "项目经理"]
LEDGER_HEADERS = ["销售人员", "客户名称", "新智云单号", "翻译类型", "文件名", "项目下单日期", "项目交付日期", "字数统计", "价格", "应收金额", "实收金额", "项目经理"]


def norm(v):
    if v is None:
        return ""
    return re.sub(r"\s+", "", str(v)).strip()


def col_num(ref):
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return 0
    n = 0
    for ch in m.group(1):
        n = n * 26 + ord(ch) - 64
    return n


def cell_ref(row, col):
    letters = ""
    n = col
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row}"


def strings_from_zip(z):
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(t.text or "" for t in si.iter(Q(NS_MAIN, "t"))) for si in root.findall(Q(NS_MAIN, "si"))]


def workbook_sheets(z):
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rel_map = {r.attrib["Id"]: r.attrib["Target"] for r in rels.findall(Q(NS_PKG_REL, "Relationship"))}
    result = []
    for s in wb.find(Q(NS_MAIN, "sheets")):
        rid = s.attrib.get(Q(NS_REL, "id"))
        target = rel_map[rid]
        target = target.lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        result.append((s.attrib["name"], target))
    return result


def read_sheet(z, path, shared):
    root = ET.fromstring(z.read(path))
    rows = {}
    for row in root.findall(".//" + Q(NS_MAIN, "row")):
        rnum = int(row.attrib["r"])
        vals = {}
        for c in row.findall(Q(NS_MAIN, "c")):
            ref = c.attrib.get("r", "")
            col = col_num(ref)
            typ = c.attrib.get("t")
            f = c.find(Q(NS_MAIN, "f"))
            v = c.find(Q(NS_MAIN, "v"))
            inline = c.find(Q(NS_MAIN, "is"))
            formula = f.text if f is not None else None
            if inline is not None:
                value = "".join(t.text or "" for t in inline.iter(Q(NS_MAIN, "t")))
            elif v is None:
                value = ""
            else:
                raw = v.text or ""
                if typ == "s":
                    try:
                        value = shared[int(raw)]
                    except (ValueError, IndexError):
                        value = raw
                elif typ == "b":
                    value = raw == "1"
                else:
                    value = raw
            vals[col] = {"value": value, "formula": formula, "style": c.attrib.get("s"), "type": typ}
        rows[rnum] = vals
    return rows


def find_header(rows, candidates, max_row=20):
    candidates = {norm(x) for x in candidates}
    best = None
    for r in sorted(rows):
        if r > max_row:
            break
        found = {}
        for c, item in rows[r].items():
            key = norm(item["value"])
            if key in candidates:
                found[key] = c
        if best is None or len(found) > len(best[1]):
            best = (r, found)
    return best if best and best[1] else (None, {})


def table_from_file(path, candidates):
    with zipfile.ZipFile(path, "r") as z:
        shared = strings_from_zip(z)
        result = []
        for name, sheet_path in workbook_sheets(z):
            rows = read_sheet(z, sheet_path, shared)
            header_row, header_map = find_header(rows, candidates)
            result.append({"name": name, "path": sheet_path, "rows": rows, "header_row": header_row, "header_map": header_map})
        return result


def choose_sheet(sheets, candidates, label):
    scored = []
    for sheet in sheets:
        score = len(set(sheet["header_map"]) & set(candidates)) if sheet["header_row"] else 0
        scored.append((score, len(sheet["rows"]), sheet))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    if not scored or scored[0][0] < len(candidates) - 2:
        raise RuntimeError(f"无法识别{label}工作表，请确认表头未被删除或改名")
    if len(scored) > 1 and scored[0][0] == scored[1][0] and scored[0][1] == scored[1][1]:
        raise RuntimeError(f"{label}工作表识别存在并列，请只上传对应的两张表")
    return scored[0][2]


def discover_files(input_dir):
    files = sorted(Path(input_dir).glob("*.xlsx"))
    files = [p for p in files if not p.name.endswith("_项目明细补录版.xlsx") and not p.name.startswith("~$")]
    if len(files) < 2:
        raise RuntimeError("输入目录至少需要上传两份 .xlsx 文件")
    ranked = []
    for path in files:
        sheets = table_from_file(path, sorted(set(PROJECT_HEADERS + LEDGER_HEADERS)))
        project_score = max((len(set(s["header_map"]) & set(PROJECT_HEADERS)) for s in sheets), default=0)
        ledger_score = max((len(set(s["header_map"]) & set(LEDGER_HEADERS)) for s in sheets), default=0)
        ranked.append((path, project_score, ledger_score))
    project_candidates = sorted(ranked, key=lambda x: (x[1], -x[2]), reverse=True)
    ledger_candidates = sorted(ranked, key=lambda x: (x[2], -x[1]), reverse=True)
    project = project_candidates[0][0] if project_candidates[0][1] >= len(PROJECT_HEADERS) - 2 else None
    ledger = ledger_candidates[0][0] if ledger_candidates[0][2] >= len(LEDGER_HEADERS) - 2 else None
    if project is None or ledger is None or project == ledger:
        raise RuntimeError("无法从上传文件中分别识别项目明细表和盈亏核算表")
    return project, ledger


def xml_escape(value):
    text = "" if value is None else str(value)
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def numeric_text(value):
    text = norm(value).replace(",", "")
    if not text:
        return None
    try:
        from decimal import Decimal, InvalidOperation
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def inline_cell(ref, value, style=None):
    attrs = [f'r="{ref}"']
    if style not in (None, ""):
        attrs.append(f's="{xml_escape(style)}"')
    if value in (None, ""):
        return f'<c {" ".join(attrs)}/>'
    return (f'<c {" ".join(attrs)} t="inlineStr"><is><t xml:space="preserve">'
            f'{xml_escape(value)}</t></is></c>')


def numeric_cell(ref, value, style=None):
    attrs = [f'r="{ref}"']
    if style not in (None, ""):
        attrs.append(f's="{xml_escape(style)}"')
    if value is None:
        return f'<c {" ".join(attrs)}/>'
    return f'<c {" ".join(attrs)}><v>{xml_escape(value)}</v></c>'


def row_fragment(row_num, values, styles):
    cells = []
    numeric_cols = {10, 11, 12}
    for col in sorted(values):
        value = values[col]
        ref = cell_ref(row_num, col)
        style = styles.get(col)
        if col in numeric_cols:
            cells.append(numeric_cell(ref, value, style))
        else:
            cells.append(inline_cell(ref, value, style))
    return f'<row r="{row_num}">' + "".join(cells) + "</row>"


def source_rows_and_mapping(project_path, ledger_path):
    project = choose_sheet(table_from_file(project_path, PROJECT_HEADERS), PROJECT_HEADERS, "项目明细")
    ledger = choose_sheet(table_from_file(ledger_path, LEDGER_HEADERS), LEDGER_HEADERS, "盈亏核算表")
    source_map = project["header_map"]
    required = ["销售", "客户", "SO", "SOD", "业务类别", "订单名称", "下单日期", "整单交付日期", "下单数量", "单价", "交付额/本币", "项目经理"]
    missing = [x for x in required if x not in source_map]
    if missing:
        raise RuntimeError("项目明细缺少字段: " + ", ".join(missing))
    existing_keys = set()
    target_so_col = ledger["header_map"].get("新智云单号")
    target_sod_col = ledger["header_map"].get("实收金额")
    if target_so_col and target_sod_col:
        for target_row, target_values in ledger["rows"].items():
            if target_row <= ledger["header_row"]:
                continue
            so = norm(target_values.get(target_so_col, {}).get("value", ""))
            sod = norm(target_values.get(target_sod_col, {}).get("value", ""))
            if so and sod:
                existing_keys.add((so, sod))
    rows = []
    skipped_existing = []
    invalid_numeric = []
    for source_row in sorted(project["rows"]):
        if source_row <= project["header_row"]:
            continue
        src = project["rows"][source_row]
        get = lambda name: src.get(source_map[name], {}).get("value", "")
        source_key = (norm(get("SO")), norm(get("SOD")))
        if source_key[0] and source_key[1] and source_key in existing_keys:
            skipped_existing.append(source_row)
            continue
        qty = numeric_text(get("下单数量"))
        price = numeric_text(get("单价"))
        receivable = numeric_text(get("交付额/本币"))
        for field, raw, converted in (("下单数量", get("下单数量"), qty), ("单价", get("单价"), price), ("交付额/本币", get("交付额/本币"), receivable)):
            if norm(raw) and converted is None:
                invalid_numeric.append({"source_row": source_row, "field": field, "value": str(raw)})
        rows.append({
            2: get("销售"), 3: get("客户"), 4: "", 5: get("SO"), 6: get("业务类别"),
            7: get("订单名称"), 8: get("下单日期"), 9: get("整单交付日期"), 10: qty,
            11: price, 12: receivable, 20: get("SOD"), 21: get("项目经理")
        })
    return project, ledger, rows, invalid_numeric, skipped_existing


def update_formula_ranges(xml_text, old_last_row, new_last_row):
    count = 0
    cache_cleared = 0
    formula_pattern = re.compile(r"(<f(?:\s[^>]*)?>)(.*?)(</f>)", re.S)
    cell_pattern = re.compile(r"(<c\b[^>]*>)(.*?)(</c>)", re.S)
    value_pattern = re.compile(r"<v(?:\s[^>]*)?>.*?</v>", re.S)

    def update_formula(match):
        nonlocal count
        body = match.group(2)
        updated = re.sub(
            rf"(:\$?[A-Z]{{1,3}}\$?){old_last_row}(?!\d)",
            rf"\g<1>{new_last_row}",
            body,
        )
        if updated != body:
            count += 1
        return match.group(1) + updated + match.group(3)

    def update_cell(match):
        nonlocal cache_cleared
        inner = match.group(2)
        before_count = count
        updated = formula_pattern.sub(update_formula, inner)
        if count != before_count:
            updated, removed = value_pattern.subn("", updated, count=1)
            cache_cleared += removed
        return match.group(1) + updated + match.group(3)

    updated_xml = cell_pattern.sub(update_cell, xml_text)
    updated_xml = formula_pattern.sub(update_formula, updated_xml)
    return updated_xml, count, cache_cleared


def set_lightweight_calculation_flags(workbook_xml):
    def replace_calc_pr(match):
        attrs = re.sub(
            r'\s+(?:fullCalcOnLoad|forceFullCalc|calcOnSave|calcMode)="[^"]*"',
            "",
            match.group(1),
        )
        return (
            '<calcPr' + attrs
            + ' calcMode="auto" fullCalcOnLoad="0" forceFullCalc="0" calcOnSave="0"/>'
        )

    if "<calcPr" in workbook_xml:
        return re.sub(r"<calcPr\b([^>]*)/>", replace_calc_pr, workbook_xml, count=1)
    return workbook_xml.replace(
        "</workbook>",
        '<calcPr calcMode="auto" fullCalcOnLoad="0" forceFullCalc="0" calcOnSave="0"/></workbook>',
        1,
    )


def inspect_lightweight_output(path):
    with zipfile.ZipFile(path, "r") as archive:
        if archive.testzip() is not None:
            raise RuntimeError("输出工作簿 ZIP 校验失败")
        names = archive.namelist()
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8", "replace")
    full = re.search(r'\bfullCalcOnLoad="([^"]*)"', workbook_xml)
    force = re.search(r'\bforceFullCalc="([^"]*)"', workbook_xml)
    full_value = full.group(1) if full else ""
    force_value = force.group(1) if force else ""
    external_parts = sum(name.startswith("xl/externalLinks/") for name in names)
    if full_value == "1" or force_value == "1":
        raise RuntimeError("输出工作簿仍要求打开时完整重算")
    if external_parts:
        raise RuntimeError("输出工作簿仍包含历史外部链接")
    return {
        "full_calc_on_load": full_value,
        "force_full_calc": force_value,
        "external_link_parts": external_parts,
        "calc_chain_present": "xl/calcChain.xml" in names,
    }


def patch_workbook(project_path, ledger_path, output_path, audit_path):
    project, ledger, append_rows, invalid_numeric, skipped_existing = source_rows_and_mapping(project_path, ledger_path)
    old_last_row = max(ledger["rows"])
    start_row = old_last_row + 1
    new_last_row = old_last_row + len(append_rows)
    tail = ledger["rows"][old_last_row]
    styles = {col: item.get("style") for col, item in tail.items()}
    fragments = [row_fragment(start_row + i, values, styles) for i, values in enumerate(append_rows)]

    with zipfile.ZipFile(ledger_path, "r") as zin:
        members = {info.filename: zin.read(info.filename) for info in zin.infolist()}
    sheet_path = ledger["path"]
    sheet_text = members[sheet_path].decode("utf-8")
    sheet_text = sheet_text.replace("</sheetData>", "".join(fragments) + "</sheetData>", 1)
    sheet_text, dimension_count = re.subn(
        rf'(<dimension\s+ref="[^"]*:[A-Z]+){old_last_row}("[^>]*>)',
        rf'\g<1>{new_last_row}\g<2>', sheet_text, count=1)
    sheet_text = re.sub(
        rf'(sqref="[A-Z]+\d+:[A-Z]+){old_last_row}(?=")',
        rf'\g<1>{new_last_row}', sheet_text)
    members[sheet_path] = sheet_text.encode("utf-8")

    formula_updates = 0
    formula_caches_cleared = 0
    formula_members = []
    for name, data in list(members.items()):
        if name == sheet_path or not name.endswith(".xml"):
            continue
        text = data.decode("utf-8", errors="strict")
        decoded_text = html.unescape(text)
        if ledger["name"] not in decoded_text and "明细" not in decoded_text:
            continue
        if str(old_last_row) not in text:
            continue
        updated, count, cleared = update_formula_ranges(text, old_last_row, new_last_row)
        if count:
            members[name] = updated.encode("utf-8")
            formula_updates += count
            formula_caches_cleared += cleared
            formula_members.append(name)

    # 公式单元格位置没有变化，只是引用范围延长，因此保留原计算链。
    # 已更新公式的旧缓存会被清除，Excel/WPS 只需计算受影响的公式，不能把全表重算转嫁给打开文件的电脑。
    calc_chain_preserved = "xl/calcChain.xml" in members
    wb_name = "xl/workbook.xml"
    if wb_name in members:
        wb = members[wb_name].decode("utf-8")
        members[wb_name] = set_lightweight_calculation_flags(wb).encode("utf-8")

    output_path = Path(output_path)
    working_path = output_path.with_name(output_path.stem + ".working.tmp.xlsx")
    temp_path = output_path.with_name(output_path.stem + ".tmp.xlsx")
    for candidate in (working_path, temp_path):
        if candidate.exists():
            candidate.unlink()
    portable_audit = None
    try:
        with zipfile.ZipFile(working_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for name, data in members.items():
                zout.writestr(name, data)
        has_external_links = any(
            name.startswith("xl/externalLinks/") for name in members
        )
        if has_external_links:
            portable_audit = create_portable_copy(working_path, temp_path)
        else:
            working_path.replace(temp_path)
        lightweight = inspect_lightweight_output(temp_path)
        temp_path.replace(output_path)
    finally:
        for candidate in (working_path, temp_path):
            if candidate.exists():
                candidate.unlink()
    audit = {
        "project": str(project_path), "ledger_original": str(ledger_path), "output": str(output_path),
        "source_sheet": project["name"], "target_sheet": ledger["name"], "source_header_row": project["header_row"],
        "source_data_rows": len(append_rows) + len(skipped_existing), "target_original_last_row": old_last_row,
        "appended_rows": len(append_rows), "skipped_existing_rows": len(skipped_existing),
        "target_new_last_row": new_last_row, "target_dimension_updated": bool(dimension_count),
        "formula_updates": formula_updates, "formula_caches_cleared": formula_caches_cleared,
        "formula_members": formula_members, "calc_chain_preserved": calc_chain_preserved,
        "external_formulas_frozen": portable_audit.frozen_external_formulas if portable_audit else 0,
        "lightweight": lightweight, "invalid_numeric": invalid_numeric,
        "mapping": {"销售人员": "销售", "客户名称": "客户", "单号": "(空白)", "新智云单号": "SO", "翻译类型": "业务类别", "文件名": "订单名称", "项目下单日期": "下单日期", "项目交付日期": "整单交付日期", "字数统计": "下单数量", "价格": "单价", "应收金额": "交付额/本币", "实收金额": "SOD", "项目经理": "项目经理"}
    }
    Path(audit_path).write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", help="包含两份上传表格的目录；可自动识别项目明细表和盈亏核算表")
    ap.add_argument("--project", help="项目明细表路径；与 --ledger 一起使用时跳过自动识别")
    ap.add_argument("--ledger", help="盈亏核算表路径；与 --project 一起使用时跳过自动识别")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--output", help="输出新表路径；省略时写到盈亏核算表同目录")
    ap.add_argument("--audit")
    args = ap.parse_args()
    if args.input_dir and (args.project or args.ledger):
        ap.error("--input-dir 不要与 --project/--ledger 混用")
    if not args.input_dir and (not args.project or not args.ledger):
        ap.error("请提供 --input-dir，或同时提供 --project 和 --ledger")
    if args.input_dir:
        args.project, args.ledger = discover_files(args.input_dir)
    if args.inspect:
        project_sheets = table_from_file(args.project, PROJECT_HEADERS)
        ledger_sheets = table_from_file(args.ledger, LEDGER_HEADERS)
        print(json.dumps({"project_file": str(args.project), "ledger_file": str(args.ledger),
                          "project_sheets": [{"name": s["name"], "header_row": s["header_row"], "headers": s["header_map"], "rows": len(s["rows"])} for s in project_sheets],
                          "ledger_sheets": [{"name": s["name"], "header_row": s["header_row"], "headers": s["header_map"], "rows": len(s["rows"])} for s in ledger_sheets]}, ensure_ascii=False, indent=2))
        return
    if not args.output:
        ledger_path = Path(args.ledger)
        args.output = str(ledger_path.with_name(ledger_path.stem + "_项目明细补录版.xlsx"))
    if not args.audit:
        output_path = Path(args.output)
        args.audit = str(output_path.with_name(output_path.stem + "_补录报告.json"))
    if Path(args.output).resolve() in {Path(args.project).resolve(), Path(args.ledger).resolve()}:
        ap.error("输出路径不能覆盖任一上传原件")
    if Path(args.output).exists() or Path(args.audit).exists():
        ap.error("输出文件已存在，为避免覆盖请换一个输出目录或文件名")
    if args.output:
        audit = patch_workbook(args.project, args.ledger, args.output, args.audit)
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
