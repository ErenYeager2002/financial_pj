"""Recover a full parent allocation from current dated workbook receipts."""
import common
import baseline_receipts as BR
import fallback_sequence as FS


def attach(payment,ledgers, *, payments=()):
    current={}
    for order in payment.get('orders') or []:
        day=common.norm_date(order.get('delivery_date'));so=order.get('so')
        if not day or day.year not in ledgers or not so:continue
        ledger=ledgers[day.year];rows={}
        for ref in ledger.so_index.get(so,[]):
            sod=ledger.row_snapshot[ref].get('sod')
            if sod:rows.update(BR.ledger_rows(ledger,so,sod))
        current[so]=rows
    payment['_current_parent_rows']=current
    own_sos={o.get('so') for o in payment.get('orders') or []}
    payment['_current_parent_ambiguous_sos']=sorted({o.get('so') for other in payments
        if other.get('ar')!=payment.get('ar') and common.norm_date(other.get('arrival_date'))==common.norm_date(payment.get('arrival_date'))
        for o in other.get('orders') or [] if o.get('so') in own_sos and o.get('so')})


def reconstruct(payment, grouped, basis, parent_amount):
    if basis!='local' or not grouped:return None
    if set(grouped)&set(payment.get('_current_parent_ambiguous_sos') or []):return None
    if any((BR.cents(g.get('deliver_local')) or 0)<=0 or (BR.cents(g.get('deliver_orig')) or 0)<=0 for g in grouped.values()):return None
    if any((BR.cents(v) or 0)>0 for v in (payment.get('_batch_reserved_local') or {}).values()):return None
    if sum(BR.cents(g['deliver_local']) for g in grouped.values())!=BR.cents(parent_amount):return None
    arrival=common.norm_date(payment.get('arrival_date'));posting=common.norm_date(payment.get('hexiao_date'))
    if not arrival or not posting:return None
    expected_day=common.receipt_time(arrival,posting)
    days={arrival,posting,expected_day}
    expected_way=common.pay_way(payment.get('status') or '',arrival,posting)
    cases={};evidence={}
    for so,group in grouped.items():
        rows=(payment.get('_current_parent_rows') or {}).get(so)
        if rows is None:continue  # Annual routing reports a missing workbook independently.
        paid={ref:r for ref,r in rows.items() if (BR.cents(r.get('回款明细')) or 0)>0}
        if not paid:
            if any(r.get('收款时间') or r.get('收款方式') or (BR.cents(r.get('回款明细')) or 0)!=0 for r in rows.values()):return None
            continue
        if any(r.get('是否结账')!='是' for r in rows.values()):return None
        if sum(BR.cents(r.get('回款明细')) or 0 for r in rows.values())!=BR.cents(group['deliver_local']):return None
        if len({r['SOD'] for r in paid.values()})!=len(paid):return None
        for ref,row in paid.items():
            if common.norm_date(row.get('收款时间')) not in days or row.get('收款方式')!=expected_way:return None
            if BR.cents(row.get('应收金额'))!=BR.cents(row.get('回款明细')):return None
            key=f"{payment['ar']}|{so}|{row['SOD']}"
            cases[key]={'so':so,'sod':row['SOD'],'amount_local':row['回款明细'],'cumulative_local':row['回款明细'],'delivery_local':row['回款明细']}
        evidence[so]=rows
    if not cases:return None
    orig={so:g['deliver_orig'] for so,g in grouped.items()};local={so:g['deliver_local'] for so,g in grouped.items()}
    allocations=[{'so':so,'delivery':g['deliver_local'],'historical_received':0.,'historical_received_orig':0.,'historical_received_local':0.,'outstanding_before':g['deliver_local'],'allocated':g['deliver_local'],'allocated_orig':g['deliver_orig'],'allocated_local':g['deliver_local'],'cumulative_after':g['deliver_local'],'status':'full'} for so,g in grouped.items()]
    payment['_fallback_cumulative_orig_by_so']=dict(orig);payment['_fallback_cumulative_local_by_so']=dict(local)
    audit={'hexiao_date':posting.isoformat(),'basis':basis,'parent_amount':parent_amount,'parent_net_amount':float(payment['amount_local']),
           'parent_charge_amount':float(payment.get('charge_amount_local') or 0),'allocations':allocations,
           'allocated_sos':list(orig),'partial_sos':[],'zero_sos':[],'already_settled_sos':[],
           'unallocated_parent_amount':0.,'rule':'delivery_amount_ascending_outstanding_waterfall',
           'processing_order':{'rule':FS.RULE,'arrival_date':str(arrival),'ar':payment['ar']},
           'applied_cases':cases,'applied_sos':sorted(evidence),'current_material_evidence':evidence,
           'reconstructed_from_current_material':True}
    return orig,local,audit,None
