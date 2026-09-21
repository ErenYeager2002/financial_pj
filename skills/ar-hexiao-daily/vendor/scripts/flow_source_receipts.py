"""Source-confirmed receipt allocation is independent of P&L registration."""
import copy
import json
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
        return {'ar':rec['ar'], 'so':rec['so'], 'date':day.isoformat(),
                'amount':number(amount), 'currency':source.get('currency') or '',
                'event':list(event), 'basis':'current_source_so_receipt'}
    except (ValueError, TypeError):
        return {}


def collect(rows):
    """One SO source total, even if the ledger expands it into many SODs."""
    return [copy.deepcopy(r['flow_source_receipt']) for r in rows if r.get('flow_source_receipt')]


def allocations(item, day):
    from flow_monthly import money, number
    values = {}
    for source in item.get('source_receipts') or []:
        if source.get('basis') != 'current_source_so_receipt' or source.get('ar') != item['ar'] or source.get('date') != day.isoformat():
            raise ValueError('智云核销来源身份或日期不一致')
        so = str(source.get('so') or '').strip().upper()
        amount = money(source.get('amount'))
        if not so or amount < 0:raise ValueError('智云核销单号或金额无效')
        if source.get('currency') and not common.is_cny(source['currency']) and '原币公式' not in item.get('matched_by',''):
            raise ValueError('外币流转余额与本币核销金额口径未确认')
        event = source.get('event') or []
        if event and (len(event)<3 or common.norm_date(event[0])!=day):raise ValueError('智云核销事件日期不一致')
        key = 'source|' + json.dumps([item['ar'],so,day.isoformat(),event[1:3]],ensure_ascii=False,separators=(',',':'))
        entry = {'key':key,'case_id':item['ar']+'|'+so,'date':day.isoformat(),'so':so,'amount':number(amount)}
        if key in values and values[key]!=entry:raise ValueError('同一智云核销事项金额冲突')
        values[key]=entry
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
