"""Clear active filters and append carry rows after the complete business data."""
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET
import xlsx_patch as X


def last_record_row(ws, cols):
    # Formatting below the data is not a receipt; hidden records still count.
    for row in range(ws.max_row, 1, -1):
        if any(ws.cell(row, col).value not in (None, '') for col in cols.values()):
            return row
    raise ValueError('流转表没有可确认的末条业务记录')


def _table_parts(payload, part):
    rel=posixpath.join(posixpath.dirname(part),'_rels',posixpath.basename(part)+'.rels')
    if rel not in payload:return []
    return [posixpath.normpath(posixpath.join(posixpath.dirname(part),r.attrib['Target']))
            if not r.attrib['Target'].startswith('/') else r.attrib['Target'].lstrip('/')
            for r in ET.fromstring(payload[rel])
            if r.attrib.get('Type','').endswith('/table') and r.attrib.get('TargetMode')!='External']


def _clear_filters(xml):
    hidden_ranges=[]
    def clear(match):
        opening,body=match.group(1),match.group(2)
        ref=re.search(r'\bref="([^"]+)"',opening)
        if ref and re.search(r'<filterColumn\b',body):
            numbers=re.findall(r'\$?[A-Z]+\$?(\d+)',ref.group(1))
            if numbers:hidden_ranges.append((int(numbers[0]),int(numbers[-1])))
        return opening[:-1]+'/>'
    xml=re.sub(r'(<autoFilter\b[^>]*>)(.*?)</autoFilter>',clear,xml,flags=re.S)
    xml=re.sub(r'(<sheetPr\b[^>]*\bfilterMode=")(?:1|true)(")',r'\g<1>0\2',xml)
    return xml,hidden_ranges


def _extend_ref(xml, tag, maximum):
    def extend(match):
        parts=match.group(2).split(':')
        if len(parts)==1:parts=[parts[0],parts[0]]
        old=int(re.search(r'(\d+)$',parts[-1]).group(1))
        parts[-1]=re.sub(r'\d+$',str(max(old,maximum)),parts[-1])
        return match.group(1)+':'.join(parts)+match.group(3)
    return re.sub(r'(<'+tag+r'\b[^>]*\bref=")([^"]+)(")',extend,xml)


def verify_filters_cleared(path, sheet):
    with zipfile.ZipFile(path) as z:
        part=X.sheet_path_for(z,sheet)
        payload={name:z.read(name) for name in z.namelist()}
    for name in [part,*_table_parts(payload,part)]:
        xml=payload[name].decode('utf-8')
        if re.search(r'<filterColumn\b|<sheetPr\b[^>]*\bfilterMode="(?:1|true)"',xml):
            raise ValueError('新增流转行后仍存在筛选条件，回读未通过')


def copy_rows(src, out, sheet, rows):
    # rows: (template row, final appended row, overrides applied by caller).
    with zipfile.ZipFile(src) as z:
        infos=z.infolist();payload={i.filename:z.read(i.filename) for i in infos}
        part=X.sheet_path_for(z,sheet)
    xml,ranges=_clear_filters(payload[part].decode('utf-8'))
    tables=_table_parts(payload,part)
    maximum=max(target for _,target,_ in rows)
    from openpyxl.utils.cell import range_boundaries
    for table in tables:
        text,table_ranges=_clear_filters(payload[table].decode('utf-8'))
        ranges.extend(table_ranges)
        definition=ET.fromstring(text)
        left,top,right,bottom=range_boundaries(definition.attrib['ref'])
        owns_rows=all(top<source<=bottom and overrides and
            all(left<=col<=right for col in overrides) for source,_target,overrides in rows)
        if owns_rows:
            if int(definition.attrib.get('totalsRowCount','0')):
                raise ValueError('流转表含表格汇总行，追加位置需人工核对')
            text=_extend_ref(_extend_ref(text,'table',maximum),'autoFilter',maximum)
        payload[table]=text.encode('utf-8')
    def unhide(match):
        text=match.group(0);row=int(match.group(1))
        return re.sub(r'\s+hidden="(?:1|true)"','',text) if any(a<row<=b for a,b in ranges) else text
    xml=re.sub(r'<row\b[^>]*\br="(\d+)"[^>]*>',unhide,xml)
    X._validate_shared_formula_integrity(xml)
    targets=set()
    for source,target,_ in rows:
        if target in targets or target<=source:raise ValueError('新增流转行位置不唯一或早于原始记录')
        targets.add(target)
        original=re.search(X._ROW_RE_TMPL.format(row=source),xml,re.S)
        if original is None:raise ValueError('流转承接模板行不存在')
        refs=set(re.findall(r'<c\b[^>]*\br="([A-Z]+[0-9]+)"',original.group(0)))
        expanded=X._expand_edited_shared_formulas(xml,refs)
        template=re.search(X._ROW_RE_TMPL.format(row=source),expanded,re.S).group(0)
        new_row=X._renumber_row_xml(template,source,target)
        new_row=re.sub(r'\s+hidden="(?:1|true)"','',new_row,count=1)
        existing=re.search(X._ROW_RE_TMPL.format(row=target),xml,re.S)
        if existing:
            if re.search(r'<f\b|<(?:v|t)\b[^>]*>\s*[^<\s]',existing.group(0)):
                raise ValueError('末条业务记录下方已有内容，禁止覆盖')
            xml=xml[:existing.start()]+new_row+xml[existing.end():]
        else:
            following=next((m for m in re.finditer(r'<row\b[^>]*\br="(\d+)"',xml) if int(m.group(1))>target),None)
            position=following.start() if following else xml.index('</sheetData>')
            xml=xml[:position]+new_row+xml[position:]
    for tag in ('dimension','autoFilter'):
        xml=_extend_ref(xml,tag,maximum)
    X._validate_shared_formula_integrity(xml)
    payload[part]=xml.encode('utf-8')
    X._drop_calc_chain(payload);X._request_full_recalculation(payload)
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for info in infos:
            if info.filename in payload:z.writestr(info,payload[info.filename])
    verify_filters_cleared(out,sheet)
