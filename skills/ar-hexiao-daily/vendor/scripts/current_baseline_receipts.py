"""Current-table proof for installments preserving the original receivable.

Virtual rows are used only to reuse receipt matching. All financial instructions
retain the actual receivable and operate through the existing baseline writer.
"""
import copy
import baseline_receipts as BR
import common


def prove(records, rows):
    import current_workbook_receipts as W
    if not records or any(not r.get('all_sods') or r.get('receivable_group_scope') for r in records):
        return None
    rows={str(k):BR.normalized(v) for k,v in rows.items()}
    anchors=[ref for ref,row in rows.items() if row['应收金额'] is not None]
    if len(anchors)!=1:return None
    anchor=anchors[0];baseline=BR.cents(rows[anchor]['应收金额'])
    delivery=BR.cents(records[0].get('deliver_local'))
    if not baseline or baseline<=0 or not delivery or delivery<=0:return None
    if len(rows)==1 and delivery<=baseline:return None
    paid=sum(BR.cents(row['回款明细']) or 0 for row in rows.values())
    if paid>delivery+BR.SETTLEMENT_CENTS or rows[anchor]['回款明细'] not in (None,0):return None
    closed=paid>0 and abs(paid-delivery)<=BR.SETTLEMENT_CENTS
    if rows[anchor]['是否结账']!=('是' if closed else '否'):return None
    if rows[anchor]['收款时间'] or rows[anchor]['收款方式']:return None
    accrual=sum(BR.cents(row['计提']) or 0 for row in rows.values())
    difference=sum(BR.cents(row['差异']) or 0 for row in rows.values())
    if accrual not in (0,delivery) or difference not in (0,baseline-delivery):return None
    if not closed and (accrual or difference):return None
    if any(BR.cents(row['计提']) not in (None,0,delivery) or BR.cents(row['差异']) not in (None,0,baseline-delivery) for row in rows.values()):return None
    virtual={}
    for ref,row in rows.items():
        if row['SO']!=records[0].get('so') or row['SOD']!=records[0].get('sod'):return None
        if ref==anchor:continue
        amount=BR.cents(row['回款明细'])
        if not amount or amount<=0 or row['是否结账']!='是':return None
        virtual[ref]={**row,'应收金额':amount/100,'差异':None}
    if closed and virtual:
        last=max(virtual,key=int)
        virtual[last]['应收金额']+=(delivery-paid)/100
    if not closed:
        virtual[anchor]={**rows[anchor],'应收金额':(delivery-paid)/100,'差异':None}
    ordinary=W.prove(records,virtual)
    if ordinary is None:return None
    return {**ordinary,'before_rows':rows,'material_rows_sha256':W.digest(rows),
            'baseline_layout':{'anchor':anchor,'baseline':baseline/100}}


def action(proof,event):
    rows=proof['before_rows'];layout=proof['baseline_layout']
    records=proof['records'];rec=next(r for r in records if BR.event_key(r)==event)
    refs=proof['event_rows'][event]
    if refs:
        ref=refs[0]
        return dict(ledger_row_ref=int(ref),five_cols={**{k:rows[ref][k] for k in ('计提','回款明细','是否结账','收款时间','收款方式')},'实收SOD':rec['sod']})
    pending=sorted((r for r in records if BR.event_key(r) in proof['missing_events']),key=lambda r:r['writeoff_sequence_key'])
    delivery=BR.cents(rec['deliver_local']);baseline=BR.cents(layout['baseline'])
    received=sum(BR.cents(row['回款明细']) or 0 for row in rows.values())
    steps=[]
    for index,member in enumerate(pending):
        amount=BR.cents(member['amount_local']);prior=received;received+=amount
        settled=index==len(pending)-1 and abs(received-delivery)<=BR.SETTLEMENT_CENTS
        arrival,posting=common.norm_date(member['shoukuan_date']),common.norm_date(member['hexiao_date'])
        five={'回款明细':amount/100,'收款时间':common.receipt_time(arrival,posting).isoformat(),
              '收款方式':common.pay_way(member['status'],arrival,posting),'是否结账':'是',
              '计提':delivery/100 if settled else None,'实收SOD':member['sod']}
        steps.append(dict(event_key=BR.event_key(member),case_id='|'.join(member[k] for k in ('ar','so','sod')),
                          ar=member['ar'],so=member['so'],sod=member['sod'],order=member['writeoff_sequence_key'],
                          historical_received=prior/100,current_received=amount/100,cumulative_received=received/100,
                          remaining=(delivery-received)/100,settled=settled,five_cols=five,
                          derived_cols={'差异':(baseline-delivery)/100} if settled else {}))
    index=next(i for i,s in enumerate(steps) if s['event_key']==event)
    step=steps[index];key=BR.group_key(rec['so'],rec['sod'])
    audit=dict(mode=BR.OPERATION,baseline_receivable=baseline/100,latest_delivery=delivery/100,
               current_received=step['current_received'],event_key=event,historical_received=step['historical_received'],
               remaining=step['remaining'],receivable_group_scope={},before_rows=copy.deepcopy(rows),group_key=key,
               disposition='write',reason='按当前来源和当前表补缺失回款，保留原始应收')
    return dict(ledger_row_ref=int(layout['anchor']),five_cols=step['five_cols'],derived_cols=step['derived_cols'],
                baseline_receipt_audit=audit,split_chain_group_id=BR.OPERATION+'|'+key,
                split_chain_index=index,split_chain_count=len(steps),
                row_operation=dict(type=BR.OPERATION,schema_version=1,group_key=key,
                    baseline_receivable=baseline/100,latest_delivery=delivery/100,before_rows=copy.deepcopy(rows),
                    anchor_row=int(layout['anchor']),insert_after=max(map(int,rows)),steps=steps,settled=steps[-1]['settled']))
