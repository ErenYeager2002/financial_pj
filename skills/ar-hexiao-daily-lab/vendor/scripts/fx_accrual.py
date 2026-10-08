"""Value only new accruals; receipt and delivery settlement amounts stay unchanged."""
from __future__ import annotations
import datetime as dt
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_FLOOR
import hashlib
import json
import re

POLICY = "boc-final-reconciliation-date-spot-buying-v1"
class FxAccrualError(ValueError):
    """A foreign accrual lacks verifiable original-currency/quote evidence."""

class FxQuoteUnavailableError(FxAccrualError):
    """No usable quote was obtained; no substitution can authorize a write."""

_planning=ContextVar("fx_provisional_planning",default=False)
@contextmanager
def provisional_planning():
    token=_planning.set(True)
    try: yield
    finally: _planning.reset(token)

def source_for(record):
    return record.get("fx_accrual_source") or (record.get("split_payment_source") or {}).get("fx_accrual_source") or {}

def _currency(value):
    value=str(value or "").strip().upper()
    if value in {"USD","CNY","EUR","HKD","GBP","JPY","AUD","CAD","CHF","SGD"}: return value
    from boc_fx_quotes import normalize_currency
    try: return normalize_currency(value)
    except ValueError as exc: raise FxAccrualError(str(exc)) from None

def _number(value, name):
    try:
        n=Decimal(str(value))
        if not n.is_finite() or n<=0: raise InvalidOperation
        return n
    except (InvalidOperation,TypeError,ValueError):
        raise FxAccrualError("外币计提缺少有效的"+name) from None

def quote_rate(source):
    q=source.get("quote") or {}
    if not q:
        raise FxQuoteUnavailableError(source.get("unavailable_reason") or "缺少中行核销日现汇买入价；请导入中行历史牌价表")
    try:
        day=dt.date.fromisoformat(str(source["reconciliation_date"]))
        published=dt.datetime.fromisoformat(str(q["published_at"]))
        if published.tzinfo is not None:
            published=published.astimezone(dt.timezone(dt.timedelta(hours=8)))
        if q.get("schema")!="boc_spot_buying_v1" or q.get("rate_type")!="现汇买入价" or q.get("quoted_unit")!=100:
            raise ValueError("不是中行每100原币现汇买入价")
        if q.get("timezone")!="Asia/Shanghai" or q.get("reconciliation_date")!=day.isoformat():
            raise ValueError("牌价日期口径不一致")
        if published.date()>day: raise ValueError("牌价晚于核销日期")
        if q.get("selection") not in {"same_date_latest","closest_earlier"}: raise ValueError("牌价选择方式无效")
        if (published.date()==day)!=(q["selection"]=="same_date_latest"): raise ValueError("牌价选择日期不一致")
        if _currency(q.get("currency"))!=_currency(source.get("currency")): raise ValueError("牌价币种不一致")
        evidence=q.get("source") or {}
        if evidence.get("name")!="中国银行" or evidence.get("kind") not in {"official_page","imported_workbook"}:
            raise ValueError("牌价来源无效")
        if not evidence.get("reference") or not re.fullmatch("[0-9a-f]{64}",str(evidence.get("sha256") or "")):
            raise ValueError("牌价来源指纹缺失")
        price=_number(q.get("buying_price_per_100"),"每100原币现汇买入价")
        rate=_number(q.get("rate_cny_per_unit"),"单位原币汇率")
        if price/100!=rate: raise ValueError("牌价与单位汇率不一致")
        return rate
    except (KeyError,TypeError,ValueError) as exc:
        if isinstance(exc,FxAccrualError): raise
        raise FxAccrualError("中行牌价证据无效："+str(exc)) from None

def _accrual_amount(record, local_delivery, *, sod=None, whole_order=False):
    source=source_for(record)
    # Frozen earlier-version plans retain their original validation contract.
    # The new CLI always attaches explicit facts to every foreign record.
    if not source: return round(float(local_delivery),2)
    currency=record.get("currency") or (record.get("write_currency_audit") or {}).get("currency")
    if currency and _currency(currency)!=_currency(source.get("currency")):
        raise FxAccrualError("外币计提来源与订单币种不一致")
    if _currency(source.get("currency"))=="CNY": return round(float(local_delivery),2)
    scope=record.get("receivable_group_scope") or (record.get("split_payment_source") or {}).get("receivable_group_scope")
    sod=record.get("sod") if sod is None else sod
    if whole_order or scope or not sod:
        original=source.get("so_delivery_orig")
    else:
        original=(source.get("sod_delivery_orig") or {}).get(str(sod))
        if original is None and len(source.get("sod_delivery_orig") or {})==0 and len(record.get("all_sods") or (record.get("split_payment_source") or {}).get("all_sods") or [])<=1:
            original=source.get("so_delivery_orig")
    original=_number(original,"智云整单/明细交付原币")
    total=source.get("so_delivery_orig")
    sods=source.get("sod_delivery_orig") or {}
    if len(sods)>1 and total is not None:
        if abs(sum(_number(v,"明细交付原币") for v in sods.values())-_number(total,"整单交付原币"))>Decimal("0.01"):
            raise FxAccrualError("智云各SOD原币交付合计与整单原币交付不一致，不能猜测计提")
    rate=quote_rate(source)
    amount=(original*rate).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)
    if not whole_order and not scope and sod and len(sods)>1:
        # Apportion integer cents by original delivery weights. Largest
        # remainders make every slice nonnegative and conserve the whole SO;
        # ties go to descending SOD identifier for deterministic readback.
        originals={k:_number(v,"明细交付原币") for k,v in sods.items()}
        total_cents=int((_number(total,"整单交付原币")*rate).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)*100)
        original_sum=sum(originals.values())
        quotas={k:Decimal(total_cents)*value/original_sum for k,value in originals.items()}
        cents={k:int(value.to_integral_value(rounding=ROUND_FLOOR)) for k,value in quotas.items()}
        remaining=total_cents-sum(cents.values())
        ordered=sorted(quotas,key=lambda k:(quotas[k]-cents[k],k),reverse=True)
        for key in ordered[:remaining]: cents[key]+=1
        amount=Decimal(cents[str(sod)])/100
    return float(amount)

def fingerprint(source):
    return hashlib.sha256(json.dumps(source,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()


def accrual_amount(record, local_delivery, *, sod=None, whole_order=False):
    try:
        return _accrual_amount(record,local_delivery,sod=sod,whole_order=whole_order)
    except FxQuoteUnavailableError:
        if not _planning.get(): raise
        # Intermediate SOD plans may be cleared by the whole-SO gate. A strict
        # pass follows that gate; this provisional value never authorizes writes.
        return round(float(local_delivery),2)
