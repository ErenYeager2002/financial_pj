"""User-approved one-yuan differences after current receipt evidence is matched."""
from decimal import Decimal

LIMIT=Decimal('1.00')


def source_total(history, text, row_date, opening):
    import common
    import flow_monthly as M
    if not history or history.get('basis')!='current_source_reconcile':return None
    if not M.current_source_balance_matches(text,history):return None
    try:
        if M.money(history['opening'])!=opening:return None
        day=common.norm_date(history['date'])
        if not day or not row_date or day<row_date or day.strftime('%Y-%m')!=row_date.strftime('%Y-%m'):return None
        entries=history['entries']
        dates=[common.norm_date(e['date']) for e in entries]
        if any(not d or d<row_date or d>day for d in dates):return None
        amounts=[M.money(e['amount']) for e in entries]
        if any(a<=0 for a in amounts):return None
        return sum(amounts,Decimal(0))
    except (ValueError,KeyError,TypeError):
        return None


def opening_adjustment(form, amount, parsed, history, text, row_date):
    if str(form or '').strip()!='冲预收':return None
    opening=parsed.get('opening');remaining=parsed.get('remaining')
    if opening is None or remaining is None or not 0<abs(opening-amount)<=LIMIT:return None
    total=source_total(history,text,row_date,amount)
    if total is None or remaining<0 or opening-total!=remaining:return None
    return opening


def balance_adjustment(opening, remaining, history, text, row_date):
    total=source_total(history,text,row_date,opening)
    if total is None:return None
    expected=opening-total
    if expected<0 or not 0<abs(expected-remaining)<=LIMIT:return None
    return expected
