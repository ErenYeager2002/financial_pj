"""Fill missing salesperson initials without changing existing order text."""
import re
import sys
from pathlib import Path


def has_initials(text):
    without_orders = re.sub(r"SO[A-Z0-9]+", "", str(text or ""), flags=re.I)
    return bool(re.search(r"[A-Za-z]{2,}", without_orders))


FIXED_SALES_INITIALS = {'吴洪伟': 'WH', '郑瑞': 'ZR', '陈霞': 'CX', '赵贺斌': 'HB', '孙苗红': 'SM', '张丽丽': 'ZL', '张健': 'JZ', '石肖璞': 'SX', '于占国': 'ZG', '骆利飞': 'LL', '王雄': 'WX', '胡伟明': 'HW', '杨利宏': 'YL', '姜征': 'OJ', '黄怡玮': 'HY', '李刚': 'LG', '梁玲玲': 'IL', '高洋': 'GY', '牛强': 'NQ', '王艳玲': 'AA'}

def from_records(records):
    names = {re.sub(r"\s+", "", str(r.get("sales_name") or "")) for r in records} - {""}
    if not names:
        return {"sales_initials": "", "sales_initials_note": "智云销售姓名为空，未补销售缩写"}
    if len(names) != 1:
        return {"sales_initials": "", "sales_initials_note": "同笔回款存在多个销售姓名，未补销售缩写"}
    name = next(iter(names))
    fixed = FIXED_SALES_INITIALS.get(name)
    if fixed:
        return {'sales_initials': fixed, 'sales_initials_note': ''}
    if re.fullmatch(r"[A-Za-z]{2,8}", name):
        initials = name.upper()
    elif re.fullmatch(r"[\u3400-\u9fff]{2,8}", name):
        vendor = str(Path(__file__).resolve().parent / "_vendor")
        if vendor not in sys.path:
            sys.path.insert(0, vendor)
        from pypinyin import lazy_pinyin, Style
        initials = "".join(lazy_pinyin(name, style=Style.FIRST_LETTER)).upper()
        # These characters have a different common pronunciation as surnames.
        surname = {"曾": "Z", "单": "S", "解": "X", "仇": "Q", "区": "O", "查": "Z", "朴": "P", "乐": "Y"}
        if name[0] in surname:
            initials = surname[name[0]] + initials[1:]
    else:
        initials = ""
    if not re.fullmatch(r"[A-Z]{2,8}", initials):
        return {"sales_initials": "", "sales_initials_note": "销售姓名格式无法可靠转换，未补销售缩写"}
    return {"sales_initials": initials, "sales_initials_note": ""}


def ensure(text, item):
    text = str(text or "")
    initials = item.get("sales_initials") or ""
    if not re.fullmatch(r"[A-Z]{2,8}", initials) or has_initials(text):
        return text
    return initials + ("\n" + text if text else "")


def rich(value, item):
    from apply_flow import _rich_signature
    text = "".join(fragment for fragment, _ in _rich_signature(value))
    desired = ensure(text, item)
    if desired == text:
        return value
    from apply_flow import _rich_signature
    import xlsx_patch
    prefix = desired[:-len(text)] if text else desired
    runs = [xlsx_patch.RichTextRun(prefix)]
    runs += [xlsx_patch.RichTextRun(fragment, color) for fragment, color in _rich_signature(value)]
    return xlsx_patch.RichTextValue(tuple(runs))
