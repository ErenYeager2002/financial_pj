"""Recognize a uniquely evidenced whole single-order receipt despite a date typo."""
import re
import common

BASIS = '唯一整笔单SO来源+同名同额（到账日期差异）'

def match(flow, rec):
    from flow_ledger import normalize_name, amounts_equal
    from flow_monthly import SO
    empty = {'hits': 0, 'rows': [], 'matched_by': ''}
    audit = rec.get('duplicate_writeoff_audit') or {}
    history = rec.get('current_source_history') or {}
    so, ar = rec.get('so'), rec.get('ar')
    if (audit.get('status') != 'single_order_parent' or not audit.get('is_whole_payment')
            or audit.get('order_count') != 1 or history.get('basis') != 'audited_current_exports'
            or not history.get('identity_fields_complete') or history.get('unresolved_parent_ars')):
        return empty
    events = history.get('events') or []
    if len(events) != 1:return empty
    event = events[0]
    arrival, day = common.norm_date(rec.get('shoukuan_date')), common.norm_date(rec.get('hexiao_date'))
    total = common.to_number(rec.get('business_arrival_total'))
    if (event.get('ar') != ar or event.get('so') != so or event.get('missing_fields')
            or not arrival or not day or arrival > day
            or common.norm_date(event.get('arrival_date')) != arrival
            or common.norm_date(event.get('posting_date')) != day
            or not event.get('record_id') or total is None or total <= 0
            or not amounts_equal(event.get('amount_orig'), total)
            or not amounts_equal(rec.get('so_delivery_local'), total)
            or 'CNY' not in str(rec.get('currency', '')).upper()):
        return empty
    names = {normalize_name(rec.get(k) or '') for k in ('sales_name','customer')} - {''}
    candidates = []
    posted = flow.match_existing_posting(rec) if hasattr(flow, 'match_existing_posting') else empty
    for row in flow.rows:
        date = row.get('date')
        if not date or date == arrival or (date.year,date.month) != (arrival.year,arrival.month):continue
        if row.get('formula_orig_amount') is not None or str(row.get('form') or '').strip() == '冲预收':continue
        shown = set(SO.findall(str(row.get('order_cell') or '').upper()))
        if shown != {so}:
            # After a proved cross-month write, the root displays only transfer
            # text. Rebind it only through one exact, already deducted posting.
            if shown or posted.get('hits') != 1:continue
            carry = posted['rows'][0]
            if (carry.get('file') != row.get('file') or carry.get('sheet') != row.get('sheet')
                    or normalize_name(carry.get('payer') or '') != normalize_name(row.get('payer') or '')
                    or not amounts_equal(carry.get('amount'), row.get('amount'))
                    or not re.search(r'转\s*' + str(day.month) + r'(?:月|$)', str(row.get('order_cell') or '') + ' ' + str(row.get('prepayment') or ''))):continue
        if not names.intersection(normalize_name(row.get(k) or '') for k in ('payer','company_name','remitter')):continue
        gross = any(x in str(row.get('form') or '') for x in ('微信','支付宝'))
        expected = total if gross else rec.get('arrival_total')
        if amounts_equal(row.get('amount'), expected):candidates.append(row)
    if len(candidates) != 1:return empty
    return {'hits':1,'rows':candidates,'matched_by':BASIS}
