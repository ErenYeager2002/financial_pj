"""Read-only evidence for several current parent receipts in one settled row.

This verifier neither assigns flow rows nor changes P&L amounts. Its caller must
supply the full relevant current payment set, not an arbitrarily selected subset.
"""
import hashlib
import json
import common
import baseline_receipts as BR


def prove(payments, rows, day):
    posting=common.norm_date(day)
    if not posting or len(payments)<2:return None
    ars=[p.get('ar') for p in payments]
    if any(not ar for ar in ars) or len(set(ars))!=len(ars):return None
    facts=[]
    for p in payments:
        orders=p.get('orders') or []
        if len(orders)!=1 or not orders[0].get('so'):return None
        order=orders[0];so=order['so']
        if p.get('status')!='手动核销' or common.norm_date(p.get('hexiao_date'))!=posting:return None
        if p.get('currency') not in ('CNY','人民币CNY','人民币'):return None
        if (p.get('duplicate_writeoff_audit') or {}).get('status')!='parent_fallback':return None
        if p.get('writeoffs') or p.get('writeoffs_local'):return None
        if (p.get('_source_meta') or {}).get('raw_writeoff_rows')!=0:return None
        history=(p.get('_current_source_history_by_so') or {}).get(so) or {}
        if history.get('events') or history.get('unresolved_parent_ars'):return None
        if any((BR.cents((p.get(key) or {}).get(so)) or 0)!=0
               for key in ('cumulative_writeoffs','cumulative_writeoffs_local')):return None
        amount=BR.cents(p.get('total_amount_local'))
        if amount is None or amount<=0:return None
        if any(BR.cents(p.get(key))!=amount for key in ('amount_orig','amount_local','total_amount_orig')):return None
        if any((BR.cents(p.get(key)) or 0)!=0 for key in ('fee','tax','other_fee','charge_amount_orig','charge_amount_local')):return None
        delivery=BR.cents(order.get('deliver_local'))
        if delivery is None or delivery<=0 or BR.cents(order.get('deliver'))!=delivery:return None
        arrival=common.norm_date(p.get('arrival_date'))
        if not arrival or arrival>posting:return None
        facts.append(dict(ar=p['ar'],so=so,amount=amount,delivery=delivery,
                          arrival=arrival.isoformat(),posting=posting.isoformat(),status=p['status']))
    if len({(f['so'],f['delivery'],f['arrival'],f['posting'],f['status']) for f in facts})!=1:return None
    fact=facts[0];so=fact['so']
    current={str(ref):BR.normalized(row) for ref,row in rows.items() if row.get('SO')==so}
    if len(current)!=1:return None
    ref,row=next(iter(current.items()))
    if not row.get('SOD') or row.get('是否结账')!='是':return None
    total=sum(f['amount'] for f in facts)
    if total!=fact['delivery'] or BR.cents(row.get('应收金额'))!=total or BR.cents(row.get('回款明细'))!=total:return None
    if (BR.cents(row.get('差异')) or 0)!=0:return None
    row_day=common.norm_date(row.get('收款时间'))
    arrival=common.norm_date(fact['arrival'])
    legal={(arrival,'汇'),(posting,common.pay_way(fact['status'],arrival,posting))}
    if (row_day,row.get('收款方式')) not in legal:return None
    canonical=dict(policy='current-parent-receipt-group-v1',so=so,sod=row['SOD'],
                   date=posting.isoformat(),parents=sorted(facts,key=lambda f:f['ar']),rows=current)
    keys=('customer','sales_name','ar','status','hexiao_date','arrival_date','currency','amount_orig','amount_local',
          'total_amount_orig','total_amount_local','fee','tax','other_fee','charge_amount_orig',
          'charge_amount_local','orders','duplicate_writeoff_audit','_source_meta',
          'writeoffs','writeoffs_local','cumulative_writeoffs','cumulative_writeoffs_local',
          '_current_source_history_by_so')
    # Preserve recheckable source facts, without recursively copying task state.
    canonical['source_payments']=json.loads(json.dumps(
        [{key:p[key] for key in keys if key in p} for p in sorted(payments,key=lambda p:p['ar'])],
        ensure_ascii=False,default=str))
    payload=json.dumps(canonical,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)
    return {**canonical,'fingerprint':hashlib.sha256(payload.encode()).hexdigest(),
            'amounts_by_ar':{f['ar']:f['amount']/100 for f in facts},'ledger_total':total/100}


def check(proof, rows, item, day):
    if not isinstance(proof,dict):return None
    try:
        rebuilt=prove(proof.get('source_payments') or [],rows,day)
        if not rebuilt or rebuilt!=proof:return None
        if item.get('so')!=proof['so'] or item.get('ar') not in proof['amounts_by_ar']:return None
        source=(item.get('source_lineage') or {}).get('source') or {}
        amount=proof['amounts_by_ar'][item['ar']]
        if source.get('ar')!=item['ar'] or source.get('so')!=item['so']:return None
        if common.norm_date(source.get('reconciliation_date'))!=common.norm_date(day):return None
        if BR.cents(source.get('parent_amount_local'))!=BR.cents(amount):return None
        if BR.cents(source.get('parent_amount_orig'))!=BR.cents(amount):return None
        if source.get('currency') not in ('CNY','人民币CNY','人民币'):return None
        if source.get('order_writeoff_local') is not None or source.get('order_writeoff_orig') is not None:return None
        if item.get('code')!='OK_SO_ALREADY_SETTLED' or (item.get('_check') or {}).get('verdict')!='skip':return None
        return {'basis':'current_parent_receipt_group','ar':item['ar'],'so':item['so'],
                'date':proof['date'],'amount':amount,'fingerprint':proof['fingerprint']}
    except (KeyError,TypeError,ValueError):return None
