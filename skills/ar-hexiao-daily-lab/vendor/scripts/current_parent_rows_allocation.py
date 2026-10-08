"""Use uniquely identified current receipts, or strictly earlier workbook balances.

No saved allocation journal participates in this proof. Ambiguous current-day
rows never become capacity for a new receipt.
"""
import copy
import common
import baseline_receipts as BR
import fallback_sequence as FS


def signature(payment):
    arrival=common.norm_date(payment.get('arrival_date'))
    posting=common.norm_date(payment.get('hexiao_date'))
    amount=common.to_number(payment.get('total_amount_local'))
    if amount is None:
        net=common.to_number(payment.get('amount_local'))
        fee=common.to_number(payment.get('charge_amount_local')) or 0
        amount=None if net is None else round(net+fee,2)
    return dict(ar=payment.get('ar'),sos=sorted({o['so'] for o in payment.get('orders') or [] if o.get('so')}),
                amount=amount,day=str(common.receipt_time(arrival,posting)) if arrival and posting else '',
                way=common.pay_way(payment.get('status') or '',arrival,posting) if arrival and posting else '')


def matches(identity, rows):
    target=BR.cents(identity.get('amount'))
    if not target or target<=0:return []
    eligible=[(ref,row) for ref,row in rows.items() if row['SO'] in identity['sos']
              and str(common.norm_date(row.get('收款时间')))==identity['day']
              and row.get('收款方式')==identity['way'] and (BR.cents(row.get('回款明细')) or 0)>0]
    # Keep two solutions per amount: uniqueness, not the first convenient subset.
    totals={0:[()]}
    for ref,row in eligible:
        value=BR.cents(row['回款明细'])
        for subtotal,paths in [(total,tuple(paths)) for total,paths in totals.items()]:
            total=subtotal+value
            if total>target:continue
            slot=totals.setdefault(total,[])
            for path in list(paths):
                candidate=path+(ref,)
                if candidate not in slot and len(slot)<2:slot.append(candidate)
        if len(totals)>20000:return None
    return totals.get(target,[])


def reconstruct(payment,grouped,basis,parent_amount):
    if basis!='local' or not grouped:return None
    arrival=common.norm_date(payment.get('arrival_date'));posting=common.norm_date(payment.get('hexiao_date'))
    if not arrival or not posting or arrival>posting:return None
    current=payment.get('_current_parent_rows') or {}
    # This seam requires all annual workbooks and one unambiguous SOD per SO.
    # Existing annual routing and itemized-source reconstruction remain separate.
    all_rows={};totals={}
    for so,g in grouped.items():
        delivery=BR.cents(g.get('deliver_local'));original=BR.cents(g.get('deliver_orig'))
        rows=current.get(so);lines=(payment.get('sod_lines') or {}).get(so) or []
        if not delivery or delivery<=0 or not original or original<=0 or not rows or len(lines)!=1:return None
        if any(r['SO']!=so or r['SOD']!=lines[0].get('sod') for r in rows.values()):return None
        if sum(BR.cents(r.get('应收金额')) or 0 for r in rows.values())!=delivery:return None
        paid=0
        for ref,row in rows.items():
            amount=BR.cents(row.get('回款明细')) or 0;expected=BR.cents(row.get('应收金额')) or 0
            if expected<=0 or amount not in (0,expected):return None
            if amount:
                if row.get('是否结账')!='是' or not common.norm_date(row.get('收款时间')) or row.get('收款方式') not in ('汇','冲预收'):return None
            elif row.get('是否结账')!='否' or row.get('收款时间') or row.get('收款方式'):return None
            paid+=amount
            all_rows[so+'|'+str(ref)]=row
        if paid>delivery:return None
        totals[so]=paid
    own=signature(payment);own['amount']=parent_amount
    candidates=matches(own,all_rows)
    if candidates is None or len(candidates)>1:return None
    selected=set(candidates[0]) if candidates else set()
    if selected:
        for other in payment.get('_current_parent_identities') or []:
            if other.get('ar')==payment.get('ar'):continue
            alternatives=matches(other,all_rows)
            if alternatives is None or any(selected.intersection(refs) for refs in alternatives):return None
        # Multiple rows of the same SO need event-level slicing, not a summed
        # invented posting. Leave that case to the existing itemized proof.
        if len({all_rows[ref]['SO'] for ref in selected})!=len(selected):return None
    else:
        # A new receipt can only use proven earlier balances. A partial match,
        # current/future row, or missing date is not proof of an unwritten event.
        if any((BR.cents(r.get('回款明细')) or 0)>0 and common.norm_date(r['收款时间'])>=arrival for r in all_rows.values()):return None
        if any((payment.get('_current_source_history_by_so') or {}).get(so,{}).get('events') for so in grouped):return None
    remaining=BR.cents(parent_amount);orig={};local={};cases={};evidence={};allocations=[];partial=[];zero=[];settled=[];cum={};cum_orig={}
    for so,g in sorted(grouped.items(),key=lambda pair:(BR.cents(pair[1]['deliver_local']),pair[1].get('first_index',0),pair[0])):
        delivery=BR.cents(g['deliver_local']);paid=totals[so]
        chosen=[all_rows[ref] for ref in selected if all_rows[ref]['SO']==so]
        reserved=BR.cents((payment.get('_batch_reserved_local') or {}).get(so)) or 0
        amount=sum(BR.cents(r['回款明细']) for r in chosen) if selected else min(remaining,max(delivery-paid-reserved,0))
        prior=paid-amount if selected else paid+reserved
        remaining-=amount
        original=round(g['deliver_orig']*amount/delivery,2);prior_orig=round(g['deliver_orig']*prior/delivery,2)
        cum[so]=(prior+amount)/100;cum_orig[so]=round(prior_orig+original,2)
        if amount:
            orig[so]=original;local[so]=amount/100
            if amount<delivery-prior:partial.append(so)
        else:
            zero.append(so)
            if paid==delivery:settled.append(so)
        if chosen:
            row=chosen[0];cases[f"{payment['ar']}|{so}|{row['SOD']}"]=dict(so=so,sod=row['SOD'],amount_local=amount/100,cumulative_local=cum[so],delivery_local=delivery/100)
            evidence[so]=copy.deepcopy(current[so])
        allocations.append(dict(so=so,delivery=delivery/100,historical_received=prior/100,historical_received_orig=prior_orig,historical_received_local=prior/100,
            outstanding_before=(delivery-prior)/100,allocated=amount/100,allocated_orig=original,allocated_local=amount/100,cumulative_after=cum[so],
            status='ledger_already_settled' if not amount and paid==delivery else 'already_settled' if not amount and prior==delivery else 'zero' if not amount else 'full' if prior+amount==delivery else 'partial'))
    if remaining:return None
    payment['_fallback_cumulative_orig_by_so']=cum_orig;payment['_fallback_cumulative_local_by_so']=cum
    audit=dict(hexiao_date=posting.isoformat(),basis=basis,parent_amount=parent_amount,parent_net_amount=float(payment['amount_local']),
        parent_charge_amount=float(payment.get('charge_amount_local') or 0),allocations=allocations,allocated_sos=list(orig),partial_sos=partial,zero_sos=zero,
        already_settled_sos=settled,unallocated_parent_amount=0.,rule='delivery_amount_ascending_outstanding_waterfall',
        processing_order=dict(rule=FS.RULE,arrival_date=arrival.isoformat(),ar=payment['ar']),applied_cases=cases,applied_sos=sorted(evidence),
        current_material_evidence=evidence,reconstructed_from_current_material=bool(selected),reused_successful_allocation=bool(selected),
        current_workbook_balance_basis='unique_receipt_rows' if selected else 'strictly_earlier_paid_rows')
    return orig,local,audit,None
