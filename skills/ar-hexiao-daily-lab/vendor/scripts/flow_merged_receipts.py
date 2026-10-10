"""Unique, same-day CNY bank arrivals shared by multiple complete AR receipts."""
import copy
from collections import defaultdict
import baseline_receipts as BR
import common

BASIS='同日同付款方多AR合并到账'
POLICY='merged-bank-receipt-v1'


def subsets(amounts, target):
    # Retain two alternatives, enough to reject ambiguity without choosing one.
    states={0:[()]}
    for ar,amount in amounts:
        for total,choices in sorted(states.items(), reverse=True):
            next_total=total+amount
            if next_total>target:continue
            candidates=states.setdefault(next_total,[])
            for choice in choices:
                candidate=choice+(ar,)
                if candidate not in candidates and len(candidates)<2:candidates.append(candidate)
        if len(states)>50000:return []
    return [choice for choice in states.get(target,[]) if len(choice)>1]


def annotate(records, flow):
    from flow_ledger import normalize_name, FlowLedger
    by_ar=defaultdict(list)
    for rec in records:by_ar[rec.get('ar')].append(rec)
    reserved={(r.get('flow_file'),r.get('flow_sheet'),r.get('flow_row_no'))
              for r in records if r.get('flow_hits')}
    groups=defaultdict(dict)
    for ar,rows in by_ar.items():
        first=rows[0];arrival=common.norm_date(first.get('shoukuan_date'));posting=common.norm_date(first.get('hexiao_date'))
        amounts={BR.cents(r.get('arrival_total')) for r in rows}
        if (not ar or not arrival or not posting or not first.get('customer') or len(amounts)!=1
                or None in amounts or next(iter(amounts))<=0 or any(r.get('flow_hits') for r in rows)
                or any(not common.is_cny(r.get('currency')) or any(common.to_number(r.get(k)) not in (None,0)
                       for k in ('fee','tax','other_fee','fee_local','tax_local','other_fee_local'))
                       or common.norm_date(r.get('shoukuan_date'))!=arrival
                       or common.norm_date(r.get('hexiao_date'))!=posting
                       or normalize_name(r.get('customer'))!=normalize_name(first['customer']) for r in rows)):
            continue
        groups[(arrival,posting,normalize_name(first['customer']))][ar]=(next(iter(amounts)),rows)
    candidates=[]
    for (arrival,posting,_),parents in groups.items():
        if not 2<=len(parents)<=18:continue
        customer=next(iter(parents.values()))[1][0]['customer']
        for row in flow.rows:
            loc=(row.get('file'),row.get('sheet'),row.get('row_no'))
            target=BR.cents(row.get('amount'))
            if (loc in reserved or row.get('date')!=arrival or row.get('form')!='汇款'
                    or row.get('formula_orig_amount') is not None or not target or target<=0):continue
            hit=flow.match(arrival,target/100,customer=customer)
            if hit['hits']!=1 or hit['matched_by'] not in ('三键','三键(中英文对照)') or hit['rows'][0]!=row:continue
            choices=subsets([(ar,value[0]) for ar,value in sorted(parents.items())],target)
            if len(choices)!=1:continue
            ars=choices[0]
            proof=dict(policy=POLICY,arrival_date=arrival.isoformat(),posting_date=posting.isoformat(),
                       identity=dict(date=arrival.isoformat(),payer=row['payer'],amount=row['amount']),
                       members=[dict(ar=ar,net_amount=parents[ar][0]/100,currency='CNY',fee=0,
                                     so_list=sorted({r['so'] for r in parents[ar][1] if r.get('so')})) for ar in ars])
            candidates.append((loc,set(ars),row,proof,parents))
    for loc,ars,row,proof,parents in candidates:
        if any(other_loc!=loc and ars & other_ars for other_loc,other_ars,*_ in candidates):continue
        if sum(other_loc==loc for other_loc,*_ in candidates)!=1:continue
        for ar in sorted(ars):
            for rec in parents[ar][1]:
                rec.update(flow_hits=1,flow_matched_by=BASIS,flow_file=row['file'],flow_sheet=row['sheet'],
                           flow_row_no=row['row_no'],flow_order_existing=row.get('order_cell') or '',
                           flow_identity=copy.deepcopy(proof['identity']),flow_receipt_group=copy.deepcopy(proof),
                           flow_locate=FlowLedger.locate_text(dict(hits=1,rows=[row],matched_by=BASIS)))
    return records


def member_ars(item):
    group=item.get('receipt_group')
    return [m['ar'] for m in group['members']] if group else [item.get('ar')]


def validate(item):
    group=item.get('receipt_group')
    if not group:return
    from flow_monthly import money
    members=group.get('members') or []
    ars=[m.get('ar') for m in members]
    if (group.get('policy')!=POLICY or len(ars)<2 or not all(ars) or ars!=sorted(set(ars))
            or item.get('ar')!=ars[0] or item.get('matched_by')!=BASIS
            or group.get('identity')!=item.get('identity')
            or group.get('arrival_date')!=item['identity'].get('date')
            or group.get('posting_date')!=item.get('monthly_date')):
        raise ValueError('合并到账成员、日期或定位证明不一致')
    totals={ar:money(0) for ar in ars};sos={ar:set() for ar in ars}
    for source in item.get('source_receipts') or []:
        ar=source.get('ar')
        if ar not in totals or source.get('date')!=group['posting_date'] or not common.is_cny(source.get('currency')):
            raise ValueError('合并到账来源身份、日期或币种不一致')
        totals[ar]+=money(source.get('amount'));sos[ar].add(source.get('so'))
    for m in members:
        if (not common.is_cny(m.get('currency')) or money(m.get('fee'))!=0 or money(m.get('net_amount'))<=0
                or totals[m['ar']]!=money(m['net_amount']) or sorted(sos[m['ar']])!=m.get('so_list')):
            raise ValueError('合并到账各AR实际核销来源未完整对应父金额，不能推算扣款')
    if sum(totals.values(),money(0))!=money(item['identity']['amount']):
        raise ValueError('合并到账合计与流转到账金额不一致')
