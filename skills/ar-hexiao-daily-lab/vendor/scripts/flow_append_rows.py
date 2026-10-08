"""Append carry rows without relocating any existing worksheet row."""
import re
import zipfile
import xlsx_patch as X


def copy_rows(src, out, sheet, rows):
    # rows: (template row, final appended row, overrides applied by caller).
    with zipfile.ZipFile(src) as z:
        infos=z.infolist();payload={i.filename:z.read(i.filename) for i in infos}
        part=X.sheet_path_for(z,sheet)
    xml=payload[part].decode('utf-8')
    X._validate_shared_formula_integrity(xml)
    maximum=max(int(m.group(1)) for m in re.finditer(r'<row\b[^>]*\br="(\d+)"',xml))
    additions=[]
    for source,target,_ in rows:
        if target<=maximum:raise ValueError('新增流转行必须位于工作表末尾')
        original=re.search(X._ROW_RE_TMPL.format(row=source),xml,re.S)
        if original is None:raise ValueError('流转承接模板行不存在')
        refs=set(re.findall(r'<c\b[^>]*\br="([A-Z]+[0-9]+)"',original.group(0)))
        expanded=X._expand_edited_shared_formulas(xml,refs)
        template=re.search(X._ROW_RE_TMPL.format(row=source),expanded,re.S).group(0)
        additions.append(X._renumber_row_xml(template,source,target))
        maximum=target
    xml=xml.replace('</sheetData>',''.join(additions)+'</sheetData>',1)
    # Extend visible data/filter bounds, never merges belonging to old rows.
    for tag in ('dimension','autoFilter'):
        def extend(m):
            parts=m.group(2).split(':')
            if len(parts)==1:parts=[parts[0],parts[0]]
            parts[-1]=re.sub(r'[0-9]+$',str(maximum),parts[-1])
            return m.group(1)+':'.join(parts)+m.group(3)
        xml=re.sub(r'(<'+tag+r'\b[^>]*\bref=")([^"]+)(")',extend,xml)
    X._validate_shared_formula_integrity(xml)
    payload[part]=xml.encode('utf-8')
    X._drop_calc_chain(payload);X._request_full_recalculation(payload)
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for info in infos:
            if info.filename in payload:z.writestr(info,payload[info.filename])
