"""Rebuild a no-detail parent allocation from audited source history and rows."""
import copy
import common
import baseline_receipts as BR
import current_source_matching as M
import fallback_sequence as FS
from classification_amounts import _currency_key


def reconstruct(payment,grouped,basis,parent_amount):
    currency=_currency_key(payment.get('currency') or '')
    if basis!='local' or not currency:return None
    if any(g.get('currencies')!={currency} for g in grouped.values()):return None
    if set(grouped)&set(payment.get('_current_parent_ambiguous_sos') or []):return None
    if any(BR.cents(v) not in (None,0) for v in (payment.get('_batch_reserved_local') or {}).values()):return None
    arrival=common.norm_date(payment.get('arrival_date'));posting=common.norm_date(payment.get('hexiao_date'))
    if not arrival or not posting or arrival>posting:return None
    history_by_so=payment.get('_current_source_history_by_so') or {}
    if not any(h.get('events') for so,h in history_by_so.items() if so in grouped):return None
    remaining=BR.cents(parent_amount)
    if remaining is None or remaining<=0:return None
    allocations=[];orig={};local={};cumulative={};cumulative_orig={};partial=[];zero=[];settled_sos=[];cases={};evidence={};source_evidence={}
    ordered=sorted(grouped.items(),key=lambda pair:(BR.cents(pair[1]['deliver_local']) or 0,pair[1].get('first_index',0),pair[0]))
    for so,g in ordered:
        delivery=BR.cents(g.get('deliver_local'));original=BR.cents(g.get('deliver_orig'))
        if not delivery or delivery<=0 or not original or original<=0:return None
        sod_lines=(payment.get('sod_lines') or {}).get(so) or []
        if len(sod_lines)!=1 or not sod_lines[0].get('sod'):return None
        sod=sod_lines[0]['sod']
        rows=(payment.get('_current_parent_rows') or {}).get(so)
        if not rows or any(r['SO']!=so or r['SOD']!=sod for r in rows.values()):return None
        if sum(BR.cents(r['应收金额']) or 0 for r in rows.values())!=delivery:return None
        for row in rows.values():
            expected,paid=BR.cents(row['应收金额']),BR.cents(row['回款明细'])
            if not expected or expected<=0 or paid not in (None,0,expected):return None
            if paid:
                if row['是否结账']!='是' or row['收款方式'] not in ('汇','冲预收'):return None
            elif row['是否结账']!='否' or row['收款时间'] or row['收款方式']:return None
        history=copy.deepcopy(history_by_so.get(so) or dict(basis='audited_current_exports',as_of_date=posting.isoformat(),events=[],unresolved_parent_ars=[]))
        if history.get('basis')!='audited_current_exports' or history.get('as_of_date')!=posting.isoformat() or history.get('unresolved_parent_ars'):return None
        events=history.get('events') or []
        prior=0;prior_orig=0
        for event in events:
            day=common.norm_date(event.get('posting_date'))
            amount=BR.cents(event.get('amount_local'))
            if (not day or day>=posting or event.get('ar')==payment.get('ar') or event.get('so')!=so
                    or not amount or amount<=0 or (BR.cents(event.get('amount_orig')) or 0)<=0
                    or _currency_key(event.get('currency') or '')!=currency):return None
            prior+=amount
            prior_orig+=BR.cents(event["amount_orig"])
        if (BR.cents((payment.get('cumulative_writeoffs_local') or {}).get(so,0))!=prior
                or BR.cents((payment.get('cumulative_writeoffs') or {}).get(so,0))!=prior_orig):return None
        outstanding=delivery-prior
        if outstanding<0:return None
        amount=min(remaining,outstanding)
        remaining-=amount
        allocated_orig=round((original/100)*(amount/100)/(delivery/100),2)
        paid={ref:r for ref,r in rows.items() if (BR.cents(r['回款明细']) or 0)>0}
        if amount==0:
            history['identity_fields_complete']=True
            matched=M.bind([],paid,posting.isoformat(),prior,source_history=history,source_so=so)
            if matched is None:return None
            _,prior_refs=matched;refs=[]
            zero.append(so)
            if outstanding==0:settled_sos.append(so)
        else:
            sequence=[posting.isoformat(),'parent-allocation',str(payment['ar'])]
            rec=dict(ar=payment['ar'],so=so,sod=sod,amount_orig=allocated_orig,amount_local=amount/100,
                     currency=payment['currency'],status=payment.get('status') or '',
                     shoukuan_date=arrival.isoformat(),hexiao_date=posting.isoformat(),
                     writeoff_sequence_key=sequence)
            # This event is explicitly derived from the parent waterfall, not
            # advertised as a downloaded writeoff detail. The unchanged downloaded
            # prefix is retained independently in source_evidence below.
            history['events']=events+[dict(ar=payment['ar'],so=so,record_id='parent-allocation',rowid=str(payment['ar']),
                posting_date=posting.isoformat(),arrival_date=arrival.isoformat(),amount_orig=allocated_orig,amount_local=amount/100,
                currency=payment['currency'],status=rec['status'],missing_fields=[],derived_from_parent_allocation=True)]
            history['identity_fields_complete']=True
            rec['current_source_history']=history
            paid={ref:r for ref,r in rows.items() if (BR.cents(r['回款明细']) or 0)>0}
            matched=M.bind([rec],paid,posting.isoformat(),prior)
            if matched is None:return None
            bindings,prior_refs=matched;refs=bindings[BR.event_key(rec)]
        if refs:
            cases[f"{payment['ar']}|{so}|{sod}"]=dict(so=so,sod=sod,amount_local=amount/100,
                cumulative_local=(prior+amount)/100,delivery_local=delivery/100)
            evidence[so]=copy.deepcopy(rows)
        source_evidence[so]=dict(source_history=copy.deepcopy(history_by_so.get(so) or {}),
            before_rows=copy.deepcopy(rows),prior_rows=prior_refs,current_rows=refs,
            historical_received=prior/100,allocated=amount/100)
        if amount:
            orig[so]=allocated_orig;local[so]=amount/100
        cumulative[so]=(prior+amount)/100
        cumulative_orig[so]=round(prior_orig/100+allocated_orig,2)
        full=amount==outstanding
        if amount and not full:partial.append(so)
        allocations.append(dict(so=so,delivery=delivery/100,historical_received=prior/100,
            historical_received_orig=prior_orig/100,historical_received_local=prior/100,
            outstanding_before=outstanding/100,allocated=amount/100,allocated_orig=allocated_orig,allocated_local=amount/100,
            cumulative_after=cumulative[so],status='ledger_already_settled' if outstanding==0 else 'zero' if not amount else 'full' if full else 'partial'))
    payment['_fallback_cumulative_orig_by_so']=dict(cumulative_orig);payment['_fallback_cumulative_local_by_so']=dict(cumulative)
    audit=dict(hexiao_date=posting.isoformat(),basis=basis,parent_amount=parent_amount,
        parent_net_amount=float(payment['amount_local']),parent_charge_amount=float(payment.get('charge_amount_local') or 0),
        allocations=allocations,allocated_sos=list(orig),partial_sos=partial,zero_sos=zero,already_settled_sos=settled_sos,
        unallocated_parent_amount=remaining/100,rule='delivery_amount_ascending_outstanding_waterfall',
        processing_order=dict(rule=FS.RULE,arrival_date=arrival.isoformat(),ar=payment['ar']),
        applied_cases=cases,applied_sos=sorted(evidence),current_material_evidence=evidence,
        current_source_history_evidence=source_evidence,reconstructed_from_current_material=True)
    return orig,local,audit,None
