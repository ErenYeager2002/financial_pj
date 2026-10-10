"""Whole-receipt flow deductions; membership is not a per-SO allocation."""
import copy
import common

PREFIX = 'parent-net|'


def members(entry):
    values = entry.get('so_list', []) if entry.get('key', '').startswith(PREFIX) else ([entry['so']] if entry.get('so') else [])
    return [str(so).strip().upper() for so in values]


def collect(rows):
    """Preserve the current fetch audit, independent of P&L completion."""
    audits = [r.get('duplicate_writeoff_audit') or {} for r in rows]
    if not any(a.get('status') == 'delivery_fallback' for a in audits):
        return {}
    first = audits[0]
    if not first or any(a != first for a in audits):
        return {'error': '整笔回款的当前来源审计不一致，不能统一扣款'}
    return copy.deepcopy(first)


def bind(item, day):
    """Return one parent amount only for a complete, audited fallback group."""
    from flow_monthly import money, number
    if item.get("receipt_group"):
        return None  # Each member AR is conserved by the merged source validator.
    sources = item.get('source_receipts') or []
    fallback = [s for s in sources if len(s.get('event') or []) > 1
                and str(s['event'][1]).startswith('DELIVERY_FALLBACK|')]
    # Existing gross-channel accounting is a separately confirmed business rule.
    if '微信支付宝' in str(item.get('matched_by') or ''):
        return None
    audit = item.get('parent_net_audit') or {}
    if audit.get('error'):
        raise ValueError(audit['error'])
    audited_group = (audit.get('status') == 'delivery_fallback'
                     and isinstance(audit.get('order_count'), int)
                     and (audit['order_count'] > 1 or (audit['order_count'] == 1
                          and '原币公式' in str(item.get('matched_by') or '')
                          and money(audit.get('parent_charge_orig')) > 0)))
    if not audited_group and (len(sources) <= 1 or not fallback):
        return None
    if (audit.get('ar') != item['ar'] or audit.get('status') != 'delivery_fallback'
            or audit.get('is_whole_payment') is not True or audit.get('raw_record_count') != 0
            or audit.get('records') or audit.get('error_code') or len(fallback) != len(sources)):
        raise ValueError('整笔净到账扣款缺少完整取数审计，不能使用交付额替代')
    records = audit.get('order_records') or []
    expected = {str(r.get('so') or '').upper(): r for r in records}
    actual = {str(s.get('so') or '').upper(): s for s in sources}
    if (len(expected) != len(records) or len(actual) != len(sources) or '' in actual
            or set(actual) != set(expected) or set(actual) != set(item.get('so_list') or [])
            or len(expected) != audit.get('order_count')):
        raise ValueError('整笔回款关联单号未完整对应，不能统一扣款')
    for so, source in actual.items():
        event = source.get('event') or []
        record = expected[so]
        if (source.get('basis') != 'current_source_so_receipt' or source.get('ar') != item['ar']
                or source.get('date') != day.isoformat() or len(event) < 3
                or common.norm_date(event[0]) != day or event[1] != 'DELIVERY_FALLBACK|' + item['ar'] + '|' + so
                or record.get('source') != 'delivery_fallback'
                or money(source.get('amount')) < 0
                or money(source.get('amount')) != money(record.get('amount_local'))
                or money(source.get('amount_orig')) != money(record.get('amount'))):
            raise ValueError('整笔回款来源单号、日期或金额不一致')
    net = money(audit.get('parent_net_local'))
    original = money(audit.get('parent_net_orig'))
    for suffix in ('local', 'orig'):
        if (money(audit.get('parent_total_' + suffix)) - money(audit.get('parent_charge_' + suffix))
                != money(audit.get('parent_net_' + suffix)) or money(audit.get('parent_charge_' + suffix)) < 0):
            raise ValueError('整笔净到账与总到账、手续费不一致')
    currencies = {s.get('currency') or '' for s in sources}
    if len(currencies) != 1:
        raise ValueError('整笔回款币种不一致')
    currency = next(iter(currencies))
    if '原币公式' in str(item.get('matched_by') or ''):
        from flow_source_receipts import fx_basis
        opening, rate = fx_basis(item)
        if common.is_cny(currency) or opening != original:
            raise ValueError('整笔原币净到账与流转公式不一致')
        net = (original * rate).quantize(money('0.01'))
    elif not common.is_cny(currency):
        raise ValueError('整笔外币净到账缺少流转原币公式')
    if net <= 0 or net != money((item.get('identity') or {}).get('amount')):
        raise ValueError('整笔净到账与流转表到账金额不一致')
    sos = sorted(actual)
    entry = dict(key=PREFIX + item['ar'], case_id=item['ar'], date=day.isoformat(),
                 so='', so_list=sos, amount=number(net), basis='whole_receipt_net')
    return entry


def history(entry):
    return dict(basis='current_source_reconcile', parent_net=True, date=entry['date'],
                opening=entry['amount'], entries=[copy.deepcopy(entry)], known_sos=entry['so_list'])


def validate_existing(chain, item):
    """Never convert previous item allocations or partial balances by guessing."""
    wanted = next((e for e in item.get('monthly_entries', []) if e['key'].startswith(PREFIX)), None)
    if not wanted:
        return
    entries = [e for m in chain['months'] for e in m['entries']]
    matching = [e for e in entries if e['key'] == wanted['key']]
    if matching and (len(matching) != 1 or matching[0] != wanted):
        raise ValueError('整笔净到账已登记，但本次日期、单号或金额发生变化')
    if any(e['key'] != wanted['key'] for e in entries):
        # Recognize identical old per-SO events, not merely equal totals. Keep
        # their identities and visible arithmetic; there is no second charge.
        from flow_source_receipts import allocations
        from flow_monthly import money
        expected = allocations(item, common.norm_date(wanted['date']))
        if (entries and len({e['key'] for e in entries}) == len(entries)
                and {e['key']:e for e in entries} == {e['key']:e for e in expected}
                and sum((money(e['amount']) for e in entries), money(0)) == money(wanted['amount'])
                and money(chain['months'][-1]['remaining']) == 0):
            item['monthly_entries'] = copy.deepcopy(entries)
            return
        raise ValueError('当前流转已有其他扣款，不能再次按整笔净到账扣减；请核对已扣金额')
