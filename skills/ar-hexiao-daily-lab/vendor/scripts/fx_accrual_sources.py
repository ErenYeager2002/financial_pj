"""Freeze BOC quote evidence in this run, then attach original delivery facts."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import common
import fx_accrual as FX

SNAPSHOT = "boc-fx-quote-snapshot.json"

def attach_source(payment, record):
    if "_boc_fx_quotes" not in payment: return  # earlier frozen callers retain prior policy
    currency=record.get("currency") or payment.get("currency") or "人民币CNY"
    if common.is_cny(currency): return
    so=str(record.get("so") or "")
    orders=[o for o in payment.get("orders") or [] if str(o.get("so") or "")==so]
    values={common.to_number(o.get("deliver")) for o in orders}
    original=next(iter(values)) if len(values)==1 else None
    sods={}
    conflict=False
    for line in (payment.get("sod_lines") or {}).get(so) or []:
        sod=str(line.get("sod") or ""); value=common.to_number(line.get("deliver"))
        if not sod or value is None: continue
        if sod in sods and sods[sod]!=value: conflict=True
        sods[sod]=value
    try:
        from boc_fx_quotes import normalize_currency
        iso=normalize_currency(currency)
    except ValueError:
        iso=str(currency)
    day=common.norm_date(record.get("hexiao_date") or payment.get("hexiao_date"))
    key=f"{day.isoformat() if day else ''}|{iso}"
    quote=(payment.get("_boc_fx_quotes") or {}).get(key) or {}
    source={"policy":FX.POLICY,"currency":iso,"so_delivery_orig":original,
            "sod_delivery_orig":{} if conflict else sods,
            "reconciliation_date":day.isoformat() if day else ""}
    if quote.get("quote"): source["quote"]=copy.deepcopy(quote["quote"])
    else: source["unavailable_reason"]=quote.get("error") or f"缺少{iso}在{source['reconciliation_date']}的中行现汇买入价；请导入中行历史牌价表"
    def currency_code(value):
        try: return normalize_currency(value)
        except ValueError: return str(value)
    source_currencies={currency_code(o.get("currency") or currency) for o in orders}
    source_currencies.update(currency_code(line.get("currency") or currency)
                             for line in (payment.get("sod_lines") or {}).get(so) or [])
    if source_currencies and source_currencies!={iso}:
        conflict=True
    if conflict:
        source["unavailable_reason"]="当前智云SO/SOD的交付原币或币种有冲突"
        source["so_delivery_orig"]=None;source["sod_delivery_orig"]={};source.pop("quote",None)
    record["fx_accrual_source"]=source

def prepare_quotes(payments, ledger_paths, workspace):
    from boc_fx_quotes import (normalize_currency, load_workbook_quotes, select_quote,
                               fetch_official_quotes, BOCQuoteError, BOCQuoteUnavailableError)
    required=set()
    for p in payments:
        day=common.norm_date(p.get("hexiao_date"))
        if not day: continue
        currencies={o.get("currency") or p.get("currency") for o in p.get("orders") or []}
        currencies.update(line.get("currency") or p.get("currency") for lines in (p.get("sod_lines") or {}).values() for line in lines)
        currencies.add(p.get("currency"))
        for c in currencies:
            if not c or common.is_cny(c): continue
            try: iso=normalize_currency(c)
            except BOCQuoteError: iso=str(c)
            required.add(f"{day.isoformat()}|{iso}")
    if not required: return {}
    path=Path(workspace)/"03_台账"/SNAPSHOT
    frozen={}
    if path.exists():
        value=json.loads(path.read_text(encoding="utf-8"))
        if value.get("policy")!=FX.POLICY or value.get("sha256")!=FX.fingerprint(value.get("entries") or {}):
            raise ValueError("本批中行牌价快照被改动，不能继续写入")
        frozen=value["entries"]
    missing=required-set(frozen)
    imported=[]; import_error=None
    if missing:
        try: imported=load_workbook_quotes(list(ledger_paths.values()))
        except BOCQuoteError as exc: import_error=str(exc)
    for key in sorted(missing):
        day,currency=key.split("|",1)
        try:
            if import_error: raise BOCQuoteError(import_error)
            try:
                quote=fetch_official_quotes(currency,day,timeout=5,max_pages=10)
            except BOCQuoteError:
                quote=select_quote(imported,currency,day)
            snapshot=quote.to_snapshot(day)
            FX.quote_rate({"currency":currency,"reconciliation_date":day,"quote":snapshot})
            frozen[key]={"quote":snapshot}
        except (BOCQuoteError,FX.FxAccrualError,ValueError) as exc:
            frozen[key]={"error":f"{day} {currency} 中行现汇买入价不可用：{exc}；请导入中行历史牌价表"}
    if missing:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({"policy":FX.POLICY,"entries":frozen,"sha256":FX.fingerprint(frozen)},
                                  ensure_ascii=False,indent=2),encoding="utf-8")
    for p in payments: p["_boc_fx_quotes"]=copy.deepcopy(frozen)
    return frozen
