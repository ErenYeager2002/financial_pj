"""Confirm unchanged, uniquely matched current receipts among other rows.

This proof can only skip. Unexplained other rows are protected, never treated as
unpaid capacity or as evidence authorizing another receipt write.
"""
import baseline_receipts as BR
import common


def prove(records, rows):
    import current_workbook_receipts as W
    if not records or not rows or any(r.get('forced_code') or r.get('customer_archive_failed') or r.get('parent_allocation_audit') for r in records):return None
    records=[W.source(r) for r in records]
    records.sort(key=lambda r:(BR.cents(r['cumulative_received_local']) or -1,BR.event_key(r)))
    so,sod=records[0]['so'],records[0]['sod'];day=records[0]['hexiao_date']
    delivery=BR.cents(records[0]['deliver_local'])
    if not so or not sod or not day or not delivery or delivery<=0:return None
    initial=(BR.cents(records[0]['cumulative_received_local']) or 0)-(BR.cents(records[0]['amount_local']) or 0)
    if initial<0 or len({r['currency'] for r in records})!=1:return None
    total=initial;keys=set()
    for rec in records:
        amount=BR.cents(rec['amount_local']);original=BR.cents(rec['amount_orig']);key=BR.event_key(rec)
        if (rec['so']!=so or rec['sod']!=sod or rec['hexiao_date']!=day or sod not in rec['all_sods']
                or not key or key in keys or not amount or amount<=0 or not original or original<=0
                or not rec['currency'] or rec['status']=='已作废' or not rec['shoukuan_date'] or rec['shoukuan_date']>day
                or BR.cents(rec['deliver_local'])!=delivery
                or (common.is_cny(rec['currency']) and original!=amount)):return None
        keys.add(key);total+=amount
        if BR.cents(rec['cumulative_received_local'])!=total:return None
    if total>delivery+BR.SETTLEMENT_CENTS:return None
    prior_events=[]
    if any('current_source_history' in r for r in records):
        import current_source_matching as M
        parsed=M.source_events(records,day,initial)
        if parsed is None:return None
        events,mandatory,_=parsed;prior_events=[events[i] for i in mandatory]
    elif initial:return None
    rows={str(k):BR.normalized(v) for k,v in rows.items()}
    if any(r['SO']!=so or r['SOD']!=sod or (BR.cents(r['回款明细']) or 0)<0 for r in rows.values()):return None
    if sum(BR.cents(r['回款明细']) or 0 for r in rows.values())>delivery+BR.SETTLEMENT_CENTS:return None
    bindings={};used=set()
    for rec in records:
        amount=BR.cents(rec['amount_local'])
        candidates=[ref for ref,row in rows.items() if BR.cents(row['回款明细'])==amount and row['是否结账']=='是'
                    and row['收款时间'] in (rec['shoukuan_date'],day) and row['收款方式'] in ('汇','冲预收')]
        if len(candidates)!=1 or candidates[0] in used:return None
        ref=candidates[0]
        if any(e['amount_local']==amount and rows[ref]['收款时间'] in (e['arrival_date'],e['posting_date']) for e in prior_events):return None
        bindings[BR.event_key(rec)]=[ref];used.add(ref)
    other_received=sum(BR.cents(r['回款明细']) or 0 for ref,r in rows.items() if ref not in used and r['收款时间'] and r['收款时间']<=day)
    if other_received<initial:return None
    return dict(policy_version=W.POLICY,records=records,before_rows=rows,event_rows=bindings,missing_events=[],
                protected_prior_rows=[],protected_future_rows=[],unpaid_rows=[],read_only_subset=True,
                protected_other_rows=sorted(set(rows)-used),source_sha256=W.digest(records),material_rows_sha256=W.digest(rows))
