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
    import current_parent_rows_allocation as R
    payment['_current_parent_identities']=[R.signature(other) for other in payments]
    own_sos={o.get('so') for o in payment.get('orders') or []}
    def receipt_days(parent):
        return {day for day in (common.norm_date(parent.get('arrival_date')),common.norm_date(parent.get('hexiao_date'))) if day}
    ambiguous=set(); competitors={}
    for other in payments:
        if other.get('ar')==payment.get('ar'):continue
        shared_days=receipt_days(payment)&receipt_days(other)
        shared_sos=own_sos&{o.get('so') for o in other.get('orders') or []}
        for so in shared_sos:
            if any(common.norm_date(r.get('收款时间')) in shared_days and (BR.cents(r.get('回款明细')) or 0)>0 for r in (current.get(so) or {}).values()):
                ambiguous.add(so)
                competitors.setdefault(so,set()).add(str(other.get('ar') or ''))
    payment['_current_parent_ambiguous_sos']=sorted(ambiguous)
    payment['_current_parent_competitors']={so:sorted(ars) for so,ars in competitors.items()}
    payment.pop('_current_parent_receipt_group',None)
    if len(own_sos)==1:
        so=next(iter(own_sos))
        relevant=[p for p in payments if any(o.get('so')==so for o in p.get('orders') or [])]
        import current_parent_receipt_group as G
        proof=G.prove(relevant,current.get(so) or {},payment.get('hexiao_date'))
        if proof:payment['_current_parent_receipt_group']=proof




def reconstruct(payment, grouped, basis, parent_amount):
    payment.pop('_current_parent_reconstruction_reason',None)
    def reject(reason):
        payment['_current_parent_reconstruction_reason']=reason
        return None
    import current_parent_source_allocation as S
    restored=S.reconstruct(payment,grouped,basis,parent_amount)
    if restored is not None:return restored
    import current_parent_rows_allocation as R
    restored=R.reconstruct(payment,grouped,basis,parent_amount)
    if restored is not None:return restored
    if basis!='local' or not grouped:return None
    ambiguous=sorted(set(grouped)&set(payment.get('_current_parent_ambiguous_sos') or []))
    if ambiguous:
        detail='；'.join(f"SO={so} 同日候选父回款={','.join([str(payment.get('ar') or '')]+(payment.get('_current_parent_competitors') or {}).get(so,[]))}" for so in ambiguous)
        return reject('当前表已有回款行同时符合多个父回款的订单和日期，无法唯一确定归属：'+detail)
    if any((BR.cents(g.get('deliver_local')) or 0)<=0 or (BR.cents(g.get('deliver_orig')) or 0)<=0 for g in grouped.values()):return None
    if any((BR.cents(v) or 0)>0 for v in (payment.get('_batch_reserved_local') or {}).values()):return None
    # Reconstruct the original waterfall before looking at which allocations
    # were already written. Never give the whole parent to remaining open SOs.
    if any((BR.cents((payment.get('cumulative_writeoffs_local') or {}).get(so)) or 0)>0 for so in grouped):return None
    if any((BR.cents((payment.get('cumulative_writeoffs') or {}).get(so)) or 0)>0 for so in grouped):return None
    if any((payment.get('_current_source_history_by_so') or {}).get(so,{}).get('events') or (payment.get('_current_source_history_by_so') or {}).get(so,{}).get('unresolved_parent_ars') for so in grouped):return None
    remaining=BR.cents(parent_amount)
    if remaining is None or remaining<=0:return None
    expected={};allocations=[];orig={};local={};partial=[];zero=[]
    ordered=sorted(grouped.items(),key=lambda pair:(BR.cents(pair[1]['deliver_local']),pair[1].get('first_index',0),pair[0]))
    for so,g in ordered:
        delivery=BR.cents(g['deliver_local']);amount=min(remaining,delivery);remaining-=amount
        original=round(g['deliver_orig']*amount/delivery,2)
        expected[so]=amount
        if amount:
            orig[so]=original;local[so]=amount/100
            if amount<delivery:partial.append(so)
        else:zero.append(so)
        allocations.append(dict(so=so,delivery=delivery/100,historical_received=0.,historical_received_orig=0.,historical_received_local=0.,
            outstanding_before=delivery/100,allocated=amount/100,allocated_orig=original,allocated_local=amount/100,
            cumulative_after=amount/100,status='zero' if not amount else 'full' if amount==delivery else 'partial'))
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
        received=sum(BR.cents(r.get('回款明细')) or 0 for r in rows.values())
        if received!=expected[so]:
            return reject(f"SO={so} 当前表已收{received/100:.2f}，按本次父回款与交付额顺序计算应分配{expected[so]/100:.2f}，差额{(received-expected[so])/100:.2f}；已收候选行={','.join(map(str,paid))}")
        receivable=sum(BR.cents(r.get('应收金额')) or 0 for r in rows.values())
        if receivable!=BR.cents(group['deliver_local']):
            return reject(f"SO={so} 当前表行{','.join(map(str,rows))}应收合计{receivable/100:.2f}，智云交付额{group['deliver_local']:.2f}；当前父回款重建尚不支持此金额结构，不能据此调整原应收")
        if expected[so]<BR.cents(group['deliver_local']):
            if len(payment.get('sod_lines',{}).get(so) or [])!=1:
                return reject(f"SO={so} 本次分配{expected[so]/100:.2f}小于交付额{group['deliver_local']:.2f}，关联SOD数量={len(payment.get('sod_lines',{}).get(so) or [])}；部分回款跨SOD的已有分配尚未证明")
            adjustments={ref:r for ref,r in rows.items() if BR.cents(r.get('计提')) not in (None,0) or BR.cents(r.get('差异')) not in (None,0)}
            if adjustments:
                detail='；'.join(f"行{ref}计提={r.get('计提')}、差异={r.get('差异')}" for ref,r in adjustments.items())
                return reject(f"SO={so} 部分回款存在{detail}；当前父回款重建尚未证明这些调整的归属，保留原值")
        for ref,r in rows.items():
            if ref in paid:
                if r.get('是否结账')!='是':
                    return reject(f"SO={so} 当前表行{ref}已收{(BR.cents(r.get('回款明细')) or 0)/100:.2f}，结账标记={r.get('是否结账')}；不符合当前父回款已登记证明的行结构")
            elif (r.get('是否结账')!='否' or r.get('收款时间') or r.get('收款方式')
                  or (BR.cents(r.get('应收金额')) or 0)<=0):return None
        if len({r['SOD'] for r in paid.values()})!=len(paid):
            return reject(f"SO={so} 同一SOD存在多条已收行，候选行={','.join(map(str,paid))}；当前父回款重建尚不能唯一绑定各笔回款，不按行顺序猜归属")
        for ref,row in paid.items():
            if common.norm_date(row.get('收款时间')) not in days or row.get('收款方式')!=expected_way:
                return reject(f"SO={so} SOD={row['SOD']} 当前表行{ref}已收{float(row['回款明细']):.2f}，收款日期={row.get('收款时间')}，方式={row.get('收款方式')}；本次可对应日期={','.join(sorted(d.isoformat() for d in days))}，要求方式={expected_way}，字段不对应，不能认作同笔回款")
            if BR.cents(row.get('应收金额'))!=BR.cents(row.get('回款明细')):
                return reject(f"SO={so} SOD={row['SOD']} 当前表行{ref}应收={row.get('应收金额')}、回款={row.get('回款明细')}；该行不是已证明的全额回款结构，保留原应收和回款")
            key=f"{payment['ar']}|{so}|{row['SOD']}"
            cases[key]={'so':so,'sod':row['SOD'],'amount_local':row['回款明细'],'cumulative_local':row['回款明细'],'delivery_local':group['deliver_local'] if expected[so]<BR.cents(group['deliver_local']) else row['回款明细']}
        evidence[so]=rows
    if not cases:return None
    payment['_fallback_cumulative_orig_by_so']=dict(orig);payment['_fallback_cumulative_local_by_so']=dict(local)
    audit={'hexiao_date':posting.isoformat(),'basis':basis,'parent_amount':parent_amount,'parent_net_amount':float(payment['amount_local']),
           'parent_charge_amount':float(payment.get('charge_amount_local') or 0),'allocations':allocations,
           'allocated_sos':list(orig),'partial_sos':partial,'zero_sos':zero,'already_settled_sos':[],
           'unallocated_parent_amount':remaining/100,'rule':'delivery_amount_ascending_outstanding_waterfall',
           'processing_order':{'rule':FS.RULE,'arrival_date':str(arrival),'ar':payment['ar']},
           'applied_cases':cases,'applied_sos':sorted(evidence),'current_material_evidence':evidence,
           'reconstructed_from_current_material':True}
    return orig,local,audit,None
