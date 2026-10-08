"""Source-confirmed receipt allocation is independent of P&L registration."""
import copy
import json
from decimal import Decimal
import common

BLOCKED = {'E7','E6','E0','E12','E_PARENT_WRITEOFF_MISMATCH',
           'E_SYSTEM_OVER_WRITEOFF_UNRESOLVED','E_PARENT_ALLOCATION_HISTORY_MISSING',
           'E_PARENT_ALLOCATION_BASELINE_CHANGED','E_SOD_HISTORY_MISMATCH'}


def proof(rec):
    from flow_monthly import money, number
    source = rec.get('so_receipt_source') or {}
    if not source or rec.get('status') == '已作废' or rec.get('forced_code') in BLOCKED:
        return {}
    try:
        amount = money(source.get('amount_local'))
        day = common.norm_date(rec.get('hexiao_date'))
        event = source.get('writeoff_sequence_key') or []
        if amount < 0 or not day or not rec.get('ar') or not rec.get('so'):
            return {}
        if event and (len(event) < 3 or common.norm_date(event[0]) != day):
            return {}
        original = source.get('amount_orig')
        if original is not None and original != '':
            original = money(original)
            if original < 0:
                return {}
        elif source.get('currency') and not common.is_cny(source['currency']):
            return {}
        receipt = {'ar':rec['ar'], 'so':rec['so'], 'date':day.isoformat(),
                   'amount':number(amount), 'currency':source.get('currency') or '',
                   'event':list(event), 'basis':'current_source_so_receipt'}
        if original is not None and original != '':
            receipt['amount_orig'] = number(original)
        return receipt
    except (ValueError, TypeError):
        return {}


def collect(rows):
    """Keep one copy of a source event expanded across multiple SOD rows."""
    receipts = []
    seen = set()
    for row in rows:
        source = row.get('flow_source_receipt')
        if not source:
            continue
        fingerprint = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        receipts.append(copy.deepcopy(source))
    return receipts


def fx_basis(item):
    """The flow row's own USD formula fixes its accounting conversion rate."""
    from flow_monthly import money
    identity = item.get('identity') or {}
    if '原币公式' not in str(item.get('matched_by') or ''):
        raise ValueError('外币流转缺少原币公式定位')
    original = money(identity.get('formula_orig_amount'))
    try:
        rate = Decimal(str(identity.get('formula_rate')))
    except (ValueError, TypeError):
        raise ValueError('流转行缺少可核实的原币汇率') from None
    if original <= 0 or not rate.is_finite() or rate <= 0:
        raise ValueError('流转行原币金额或汇率无效')
    if money(identity.get('amount')) != (original * rate).quantize(Decimal('.01')):
        raise ValueError('流转行原币公式与到账金额不一致')
    return original, rate


def flow_original(item, original):
    """A proven single-SO foreign receipt spends its net original currency."""
    from flow_monthly import money
    amount = money(original)
    net = item.get('receipt_net_orig')
    total = item.get('receipt_total_orig')
    fee = item.get('receipt_fee_orig')
    if net in (None, '') or total in (None, '') or fee in (None, ''):
        return amount
    net, total, fee = money(net), money(total), money(fee)
    if fee <= 0 or total-net != fee:
        return amount
    sources = item.get('source_receipts') or []
    if len(sources) != 1:
        raise ValueError('外币多订单到账手续费缺少逐SO归属，需核实')
    source = sources[0]
    opening, _rate = fx_basis(item)
    if (net != opening or money(source.get('amount_orig')) != total):
        raise ValueError('外币到账净额、总额与来源核销额不能对应')
    return net if amount == total else amount


def flow_amount(item, original, local, currency):
    """Use the flow workbook rate for an original-currency formula row."""
    from flow_monthly import money
    if '原币公式' in str(item.get('matched_by') or ''):
        if currency and common.is_cny(currency):
            raise ValueError('原币公式行与智云人民币币种不一致')
        opening, rate = fx_basis(item)
        amount_orig = flow_original(item, original)
        if amount_orig < 0 or amount_orig > opening:
            raise ValueError('智云本次原币核销金额超出流转到账原币金额')
        return (amount_orig * rate).quantize(Decimal('.01'))
    if currency and not common.is_cny(currency):
        raise ValueError('外币流转余额与本币核销金额口径未确认')
    return money(local)


def verify_formula(item, ws, cols):
    if '原币公式' not in str(item.get('matched_by') or ''):
        return
    from flow_ledger import formula_original_amount
    from flow_monthly import money, value
    original, rate = fx_basis(item)
    row = int(item['row_no'])
    actual_orig, actual_rate = formula_original_amount(
        value(ws, row, cols, '金额'), value(ws, row, cols, '收款形式'))
    if actual_orig is None or money(actual_orig) != original or Decimal(str(actual_rate)) != rate:
        raise ValueError('流转原币公式或汇率已变化，需重新定位')


def allocations(item, day):
    from flow_monthly import money, number
    values = {}
    fx = '原币公式' in str(item.get('matched_by') or '')
    original_total, rate = fx_basis(item) if fx else (None, None)
    cumulative_orig = Decimal(0)
    cumulative_flow = Decimal(0)
    for source in item.get('source_receipts') or []:
        if source.get('basis') != 'current_source_so_receipt' or source.get('ar') != item['ar'] or source.get('date') != day.isoformat():
            raise ValueError('智云核销来源身份或日期不一致')
        so = str(source.get('so') or '').strip().upper()
        if not so:
            raise ValueError('智云核销单号无效')
        event = source.get('event') or []
        if event and (len(event)<3 or common.norm_date(event[0])!=day):
            raise ValueError('智云核销事件日期不一致')
        key = 'source|' + json.dumps([item['ar'],so,day.isoformat(),event[1:3]],ensure_ascii=False,separators=(',',':'))
        if key in values:
            raise ValueError('同一智云核销事项重复或金额冲突')
        local = money(source.get('amount'))
        if local < 0:
            raise ValueError('智云核销金额无效')
        amount = flow_amount(item, source.get('amount_orig'), local, source.get('currency') or '')
        if fx:
            cumulative_orig += flow_original(item, source['amount_orig'])
            if cumulative_orig > original_total:
                raise ValueError('智云核销原币合计超过流转到账原币金额')
            next_flow = (cumulative_orig * rate).quantize(Decimal('.01'))
            amount = next_flow - cumulative_flow
            cumulative_flow = next_flow
        entry = {'key':key,'case_id':item['ar']+'|'+so,'date':day.isoformat(),'so':so,'amount':number(amount)}
        values[key] = entry
    return [e for e in values.values() if money(e['amount'])>0]


def new_entries(wanted, recorded):
    """Adopt earlier per-SOD allocations without charging the SO total twice."""
    from flow_monthly import money, number
    output=[]
    for entry in wanted:
        key=entry['key']
        if key in recorded:
            old=recorded[key]
            expected={**old,'amount':old.get('source_total',old['amount'])}
            expected.pop('source_total',None)
            if expected!=entry:raise ValueError('已登记核销事项金额发生变化')
            continue
        paid=money(0)
        identity=json.loads(key.split('|',1)[1])
        for old_key,old in recorded.items():
            if old['so']!=entry['so'] or old['date']!=entry['date']:continue
            if old_key.startswith('source|'):
                raise ValueError('同日同订单核销身份发生变化，需核对当前流转记录')
            if old_key.startswith('event|'):
                event=json.loads(old_key.split('|',1)[1])
                if event[1:3]!=identity[3]:raise ValueError('已有同日核销事件身份不一致')
            elif not old_key.startswith(entry['date']+'|') or identity[3]:
                raise ValueError('已有同日登记缺少核销事件身份，不能重复扣减')
            paid+=money(old['amount'])
        remaining=money(entry['amount'])-paid
        if remaining<0:raise ValueError('已有流转核销额超过本次有效金额')
        # A zero bridge records the identity migration and allows later P&L
        # completion, without creating a second monetary deduction.
        output.append({**entry,'amount':number(remaining),'source_total':entry['amount']} if paid else entry)
    return output


def collect_history(rows):
    """Audited fetch events for this parent; never execution-journal entries."""
    output = {}
    for row in rows:
        audit = row.get('duplicate_writeoff_audit') or {}
        if audit.get('status') not in ('normal', 'recovered'):
            continue
        for raw in audit.get('records') or []:
            if raw.get('disposition') != 'kept' or raw.get('revoked'):
                continue
            if raw.get('ar') != row.get('ar'):
                return []
            date = common.norm_date(raw.get('date'))
            if not date or not raw.get('record_id') or not raw.get('so'):
                return []
            source = dict(ar=raw['ar'], so=raw['so'], date=date.isoformat(),
                          amount=raw.get('amount_local'), amount_orig=raw.get('amount'),
                          currency=raw.get('currency') or '', basis='current_source_so_receipt',
                          event=[date.isoformat(),raw['record_id'],raw.get('rowid') or '',raw['ar'],raw['so']])
            key=tuple(source['event'])
            if key in output and output[key]!=source:
                return []
            output[key]=source
    return [output[key] for key in sorted(output)]


def balance_history(item, current_entries, day):
    """Prior source events can prove recorded balances, never become new writes."""
    history=item.get('source_receipt_history') or []
    if not history:return None
    grouped={}
    for source in history:
        date=common.norm_date(source.get('date'))
        if not date or date>day:continue
        grouped.setdefault(date,[]).append(source)
    entries=[]
    try:
        for date,sources in sorted(grouped.items()):
            entries.extend(allocations({**item,'source_receipts':sources},date))
        current={e['key']:e for e in entries if e['date']==day.isoformat()}
        if current!={e['key']:e for e in current_entries}:return None
        if len({e['key'] for e in entries})!=len(entries):return None
        from flow_monthly import money,number
        opening=money((item.get('identity') or {}).get('amount'))
        total=sum((money(e['amount']) for e in entries),Decimal(0))
        # A partial prefix is only a candidate. legacy_month must reconcile it
        # with the visible balance and SO coverage before adopting any identity.
        # Blank balances still require full coverage of the opening amount.
        if not entries or any(money(e['amount'])<0 for e in entries) or not 0<=total<=opening:return None
        result=dict(basis='current_source_reconcile',date=day.isoformat(),opening=number(opening),
                    entries=entries,known_sos=sorted(e['so'] for e in entries))
        months=sorted({e['date'][:7] for e in entries})
        if len(months)>1:
            periods={};remaining=opening
            for month in months:
                subset=[e for e in entries if e['date'][:7]==month]
                periods[month]=dict(basis='current_source_reconcile',date=max(e['date'] for e in subset),
                    opening=number(remaining),entries=subset,known_sos=sorted({e['so'] for e in subset}))
                remaining-=sum((money(e['amount']) for e in subset),Decimal(0))
            result['periods']=periods
        return result
    except (ValueError,KeyError,TypeError):
        return None
