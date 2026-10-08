"""Source identity registration for verified ordinary workbook writes.

Signatures describe visible values, not source identities. Equal signatures
have distinct occurrence slots; slots never identify physical spreadsheet rows.
"""
import copy
import baseline_receipts as BR

POLICY = 'ordinary-receipt-registration-v1'
SUPPORTED = (None, 'split_below', 'split_payment_chain')


def identity(item):
    source = item.get('split_payment_source') or {}
    return BR.event_key({**item, 'writeoff_sequence_key': source.get('writeoff_sequence_key')})


def bind(items, ledger):
    if ledger is None:
        return
    for item in items:
        operation = item.get('row_operation') or {}
        if ((item.get('current_workbook_receipts') and item.get('code') == 'OK_CURRENT_WORKBOOK_RECEIPT_PRESENT') or item.get('bucket') != 'auto' or item.get('baseline_receipt_audit')
                or operation.get('type') not in SUPPORTED):
            continue
        event = identity(item)
        five = item.get('five_cols') or {}
        source = item.get('split_payment_source') or {}
        amount = BR.cents(five.get('回款明细'))
        if not event or not amount or amount <= 0 or amount != BR.cents(source.get('amount_local')):
            continue
        before = BR.ledger_rows(ledger, item['so'], item['sod'], item.get('ledger_row_ref'))
        baseline = sum(BR.cents(row['应收金额']) or 0 for row in before.values())
        if not before or baseline <= 0:
            continue
        item['ordinary_receipt_registration'] = {
            'policy': POLICY, 'event_key': event, 'baseline_receivable': baseline / 100,
            'before_rows': before, 'signature': list(BR.signature(BR.normalized(five))),
        }


def merge(existing, checked):
    updated = copy.deepcopy(existing)
    for item in checked.get('write') or []:
        audit = item.get('ordinary_receipt_registration')
        if not audit:
            continue
        error = registration_error(item)
        if error:
            raise ValueError(error)
        five = item.get('five_cols') or {}
        signature = list(BR.signature(BR.normalized(five)))
        source = item.get('split_payment_source') or {}
        if (audit.get('policy') != POLICY or identity(item) != audit.get('event_key')
                or signature != audit.get('signature')
                or BR.cents(signature[0]) != BR.cents(source.get('amount_local'))):
            raise ValueError('普通回款身份登记与核销写入计划不一致')
        key = BR.group_key(item['so'], item['sod'])
        entry = updated.setdefault(key, {'baseline_receivable': audit['baseline_receivable'],
                                       'events': {}, 'scope_only': True})
        if (not entry.get('scope_only') or
                BR.cents(entry['baseline_receivable']) != BR.cents(audit['baseline_receivable'])):
            raise ValueError('普通回款身份登记不能改变应收基线或业务模式')
        events = entry.setdefault('ordinary_events', {})
        old = events.get(audit['event_key'])
        if old:
            if old['signature'] != signature:
                raise ValueError('已登记回款身份的金额或日期发生变化，须通过历史修正校验')
            continue
        used = {event.get('signature_index', 0) for event in events.values()
                if event['signature'] == signature}
        slot = 0
        while slot in used:
            slot += 1
        events[audit['event_key']] = {'signature': signature, 'signature_index': slot}
    return updated


def assess(rec, rows, journal):
    """Compare source identity with recorded events and visible receipt counts."""
    import common
    from collections import Counter
    event = BR.event_key(rec)
    amount = BR.cents(rec.get('amount_local'))
    cumulative = BR.cents(rec.get('cumulative_received_local'))
    arrival, posting = common.norm_date(rec.get('shoukuan_date')), common.norm_date(rec.get('hexiao_date'))
    if not event or not rows or not amount or amount <= 0 or not arrival or not posting:
        return {'state': 'unavailable'}
    if journal and not journal.get('scope_only'):
        return {'state': 'unavailable'}
    if journal and BR.cents(journal.get('baseline_receivable')) != sum(BR.cents(row['应收金额']) or 0 for row in rows.values()):
        return {'state': 'conflict', 'reason': '当前盈亏业务组的原始应收与回款身份台账不一致'}
    day = common.receipt_time(arrival, posting).isoformat()
    way = common.pay_way(rec.get('status') or '', arrival, posting)
    expected = [amount / 100, day, way]
    events = journal.get('ordinary_events') or {}
    paid = {ref: row for ref, row in rows.items() if (BR.cents(row['回款明细']) or 0) > 0}
    actual = Counter(BR.signature(row) for row in paid.values())
    registered = Counter(tuple(item['signature']) for item in events.values())
    owned = events.get(event)
    if owned:
        if BR.cents(owned['signature'][0]) != amount:
            return {'state': 'conflict', 'reason': '同一回款事件的来源金额与成功登记记录不同，不能覆盖或重复登记'}
        if owned['signature'] != expected:
            return {'state': 'correction'}
        matches = [ref for ref, row in paid.items() if list(BR.signature(row)) == expected]
        slots = [item.get('signature_index', 0) for item in events.values() if item['signature'] == expected]
        needed = max(len(slots), max(slots, default=-1) + 1)
        if not matches and needed == 1:
            rebound = [row for row in paid.values() if BR.cents(row['回款明细']) == amount
                       and row['收款时间'] in {arrival.isoformat(), posting.isoformat(), day}]
            if len(rebound) == 1:
                return {'state': 'correction'}
            if len(paid) == 1 and cumulative == amount:
                return {'state': 'correction'}
        if len(matches) < needed or any(paid[ref]['是否结账'] != '是' for ref in matches):
            return {'state': 'conflict', 'reason': '已登记回款身份在当前盈亏材料中缺少对应数量的完整记录，请核对材料版本'}
        return {'state': 'owned', 'rows': matches, 'event_key': event, 'signature': expected}
    days = {arrival.isoformat(), posting.isoformat(), day}
    matches = [ref for ref, row in paid.items() if BR.cents(row['回款明细']) == amount and row['收款时间'] in days]
    if not matches:
        return {'state': 'unavailable'}
    received = sum(BR.cents(row['回款明细']) for row in paid.values())
    # A complete journal separates the existing receipts from this new event.
    if (registered and registered == actual and cumulative == received + amount
            and all(row['是否结账'] == '是' for row in paid.values())):
        return {'state': 'new'}
    # Legacy recognition requires chronological conservation as well as visible
    # values. It must never relabel a record already owned by another event.
    chronological = sum(BR.cents(row['回款明细']) for row in paid.values()
                        if common.norm_date(row['收款时间']) and common.norm_date(row['收款时间']) <= posting)
    claimed = any(registered[BR.signature(paid[ref])] for ref in matches)
    parent = rec.get('parent_allocation_audit') or {}
    prior = (parent.get('applied_cases') or {}).get('|'.join(str(rec.get(k) or '') for k in ('ar','so','sod'))) or {}
    if (not claimed and len(matches) == 1 and parent.get('reused') and parent.get('applied')
            and parent.get('ar') == rec.get('ar') and prior.get('so') == rec.get('so')
            and prior.get('sod') == rec.get('sod') and BR.cents(prior.get('amount_local')) == amount):
        return {'state': 'parent'}
    if not claimed and cumulative is not None and chronological == cumulative:
        return {'state': 'legacy'}
    return {'state': 'ambiguous', 'reason': '相同金额和日期的历史行尚不能证明属于本次回款；来源累计、已登记身份与当前材料不一致'}


def inspect(rec, ledger):
    if ledger is None or not rec.get('so') or not rec.get('sod'):
        return {'state': 'unavailable'}
    rows = BR.ledger_rows(ledger, rec['so'], rec['sod'])
    journal = getattr(ledger, 'baseline_receipt_state', {}).get(BR.group_key(rec['so'], rec['sod'])) or {}
    try:
        assessment = assess(rec, rows, journal)
    except (KeyError, TypeError, ValueError):
        assessment = {'state': 'conflict', 'reason': '来源回款或当前台账的身份核验字段无效'}
    return {**assessment, 'before_rows': rows, 'journal': copy.deepcopy(journal), 'rec': copy.deepcopy(rec)}


def check(item, rows):
    proof = item.get('ordinary_receipt_proof')
    if not proof:
        return None
    def bad(reason):
        return {'verdict': 'conflict', 'reason': reason}
    try:
        rec = proof['rec']
        source = item.get('split_payment_source') or {}
        if (any(rec.get(k) != item.get(k) for k in ('ar','so','sod'))
                or identity(item) != BR.event_key(rec)
                or BR.cents(source.get('amount_local')) != BR.cents(rec.get('amount_local'))):
            return bad('重复执行的来源回款身份或金额发生变化')
        current = {str(ref): BR.normalized(row) for ref,row in rows.items()
                   if row.get('SO') == item['so'] and row.get('SOD') == item['sod']}
        expected = assess(rec, current, proof['journal'])
        if current != proof['before_rows'] or expected.get('state') != 'owned':
            return bad('已登记回款的当前材料或归属证据发生变化')
        ref = str(item['ledger_row_ref'])
        if ref not in expected['rows']:
            return bad('重复执行的展示行不属于已验证回款记录集合')
        wanted = BR.normalized(item.get('five_cols') or {})
        if any(wanted[k] != current[ref][k] for k in ('计提','回款明细','是否结账','收款时间','收款方式')):
            return bad('已登记回款的跳过计划包含金额或核销字段修改')
        if item.get('row_operation') or item.get('derived_cols') or item.get('so_accrual_backfills'):
            return bad('已登记回款的跳过计划包含额外写入')
        return {'verdict': 'skip', 'reason': '来源回款身份、金额及当前材料中的登记数量已核实，不重复写入'}
    except (KeyError, TypeError, ValueError):
        return bad('已登记回款的归属复核依据不完整')


def preflight(existing, checked):
    for item in (checked.get('write') or []) + (checked.get('skip') or []):
        proof = item.get('ordinary_receipt_proof')
        if proof and proof.get('journal') != existing.get(BR.group_key(item['so'], item['sod']), {}):
            raise ValueError('回款归属台账在判定后发生变化，请重新生成计划')


def registration_error(item, rows=None, verdict=None):
    audit = item.get('ordinary_receipt_registration')
    if not audit:
        return ''
    try:
        before = audit['before_rows']
        source = item.get('split_payment_source') or {}
        signature = list(BR.signature(BR.normalized(item.get('five_cols') or {})))
        if (audit.get('policy') != POLICY or not identity(item) or identity(item) != audit['event_key']
                or signature != audit['signature']
                or (BR.cents(signature[0]) or 0) <= 0
                or BR.cents(signature[0]) != BR.cents(source.get('amount_local'))
                or not before or any(row['SO'] != item['so'] or row['SOD'] not in ('', item['sod']) for row in before.values())
                or sum(BR.cents(row['应收金额']) or 0 for row in before.values()) != BR.cents(audit['baseline_receivable'])):
            return '普通回款登记身份、金额或应收基线与写入计划不一致'
        if rows is not None and verdict == 'write':
            current = {str(ref): BR.normalized(row) for ref,row in rows.items()
                       if row.get('SO') == item['so'] and (row.get('SOD') == item['sod']
                           or (str(ref) in before and not row.get('SOD')))}
            if current != before:
                return '普通回款登记的原始业务组在计划后发生变化'
        return ''
    except (KeyError, TypeError, ValueError):
        return '普通回款身份登记依据不完整'


def unique_blank_sod_target(item, rows):
    # Require one source SOD and one unchanged workbook business row for the SO.
    audit = item.get('ordinary_receipt_registration') or {}
    source = item.get('split_payment_source') or {}
    if set(source.get('all_sods') or []) != {item.get('sod')} or not audit:
        return None
    if registration_error(item, rows, 'write'):
        return None
    candidates = [(ref,row) for ref,row in rows.items() if row.get('SO') == item.get('so')]
    if len(candidates) != 1:
        return None
    ref,row = candidates[0]
    if row.get('SOD') or BR.normalized(row) != audit['before_rows'].get(str(ref)):
        return None
    return ref
