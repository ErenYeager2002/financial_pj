"""Prove a complete current receipt group without consulting historical journals.

Keep every receivable row. A fragmented payment may occupy several rows; its
source identity belongs to their combined amount, never to an arbitrary part.
"""
import copy
from collections import defaultdict
import baseline_receipts as BR
import common

OPERATION = 'current_receipt_group'
FIVE = ('计提','回款明细','是否结账','收款时间','收款方式')

def build(records, rows):
    if len(records)<2 or not rows:return None
    so,sod=records[0].get('so'),records[0].get('sod')
    if not so or not sod or any(r.get('so')!=so or r.get('sod')!=sod for r in records):return None
    # Initially cover only a complete single-SOD SO, so no other delivery can be
    # mistaken for this group's accrual or cumulative amount.
    if any(not common.is_cny(r.get('currency') or '') or set(r.get('all_sods') or [])!={sod} or r.get('forced_code') or r.get('customer_archive_failed') or r.get('parent_allocation_audit') for r in records):return None
    delivery=BR.cents(records[0].get('deliver_local'))
    if not delivery or any(BR.cents(r.get('deliver_local'))!=delivery for r in records):return None
    if any(row.get('SO')!=so or row.get('SOD')!=sod for row in rows.values()):return None
    if sum(BR.cents(row.get('应收金额')) or 0 for row in rows.values())!=delivery:return None
    for row in rows.values():
        ar,paid=BR.cents(row.get('应收金额')),BR.cents(row.get('回款明细'))
        if ar is None or ar<=0 or paid not in (None,0,ar) or BR.cents(row.get('差异')) not in (None,0):return None
    ordered=sorted(records,key=lambda r:BR.cents(r.get('cumulative_received_local')) or -1)
    total=0;events={};signatures={}
    for rec in ordered:
        identity=BR.event_key(rec);amount=BR.cents(rec.get('amount_local'))
        arrival,posting=common.norm_date(rec.get('shoukuan_date')),common.norm_date(rec.get('hexiao_date'))
        if not identity or identity in events or not amount or amount<=0 or not arrival or not posting:return None
        total+=amount
        if BR.cents(rec.get('cumulative_received_local'))!=total:return None
        day=common.receipt_time(arrival,posting).isoformat();way=common.pay_way(rec.get('status') or '',arrival,posting)
        if not way:return None
        events[identity]=rec
        signatures[identity]=(amount,day,way,arrival.isoformat(),posting.isoformat())
    if total!=delivery or len({str(r.get('hexiao_date')) for r in ordered})!=1:return None
    groups=defaultdict(list)
    for identity,(amount,day,way,arrival,posting) in signatures.items():groups[(amount,day,way,arrival,posting)].append(identity)
    # Distinct arrival dates that collapse to the same posting signature cannot
    # be uniquely reconstructed on the next run without auxiliary identity.
    signatures_after=[key[:3] for key in groups]
    if len(signatures_after)!=len(set(signatures_after)):return None
    available=set(rows);bindings={};missing=[]
    for signature,ids in groups.items():
        amount,day,way,arrival,posting=signature
        candidates=[ref for ref in available if BR.cents(rows[ref]['回款明细'])==amount and rows[ref]['是否结账']=='是' and rows[ref]['收款方式'] and rows[ref]['收款时间'] in (arrival,posting,day)]
        if not candidates:
            # A wrong date is repairable only with a unique amount in both the
            # complete source chain and the fully conserved current workbook.
            other=[key for key,s in signatures.items() if s[0]==amount]
            candidates=[ref for ref in available if BR.cents(rows[ref]['回款明细'])==amount and rows[ref]['是否结账']=='是' and rows[ref]['收款方式']]
            if len(ids)!=1 or len(other)!=1 or len(candidates)!=1:candidates=[]
        if len(candidates)==len(ids):
            # Equal events are interchangeable only when their complete current
            # accounting facts match. Never infer different dates from row order.
            facts=[{k:rows[ref].get(k) for k in BR.FIELDS} for ref in candidates]
            if len(ids)>1 and any(f!=facts[0] for f in facts[1:]):return None
            for identity,ref in zip(ids,sorted(candidates,key=int)):
                bindings[identity]=[ref];available.remove(ref)
        else:missing.extend(ids)
    if missing:
        if len(missing)!=1 or not available:return None
        identity=missing[0];amount,day,way,arrival,posting=signatures[identity]
        if sum(BR.cents(rows[ref]['应收金额']) for ref in available)!=amount:return None
        if any(rows[ref]['收款时间'] not in (None,'',arrival,posting,day) for ref in available):return None
        bindings[identity]=sorted(available,key=int);available.clear()
    if available or set(bindings)!=set(events):return None
    after=copy.deepcopy(rows)
    for identity,refs in bindings.items():
        _,day,way,_,_=signatures[identity]
        for ref in refs:
            after[ref].update(计提=None,回款明细=after[ref]['应收金额'],是否结账='是',收款时间=day,收款方式=way)
    last=BR.event_key(ordered[-1]);accrual_ref=max(bindings[last],key=int)
    after[accrual_ref]['计提']=delivery/100
    # Do not redistribute an unrelated existing accrual across receipt rows.
    if any(BR.cents(row.get('计提')) not in (None,0) and row.get('计提')!=after[ref].get('计提') for ref,row in rows.items()):return None
    return dict(policy=OPERATION,records=copy.deepcopy(ordered),before_rows=copy.deepcopy(rows),after_rows=after,event_rows=bindings,delivery=delivery/100)

def attach(results,records,ledger):
    if ledger is None:return
    grouped=defaultdict(list)
    for rec,result in zip(records,results):grouped[(rec.get('so'),rec.get('sod'))].append((rec,result))
    for (so,sod),pairs in grouped.items():
        if any(r.get('bucket')!='auto' and r.get('code') not in ('E5','E8') for _,r in pairs):continue
        try:
            rows=BR.ledger_rows(ledger,so,sod)
            if set(map(int,rows))!=set(ledger.so_index.get(so,[])):continue
            proof=build([rec for rec,_ in pairs],rows)
        except (KeyError,TypeError,ValueError):continue
        if not proof:continue
        cases=[r['case_id'] for _,r in pairs]
        for rec,result in pairs:
            identity=BR.event_key(rec);refs=proof['event_rows'][identity]
            primary=max(refs,key=lambda ref:(BR.cents(rows[ref].get('回款明细')) or 0,-int(ref)))
            for key in ('receipt_correction','baseline_receipt_audit','row_operation','so_accrual_backfills'):result.pop(key,None)
            result.update(bucket='auto',code='E5',ledger_row_ref=int(primary),five_cols={**{k:proof['after_rows'][primary][k] for k in FIVE},'实收SOD':sod},derived_cols={},current_receipt_group=copy.deepcopy(proof),current_receipt_event=identity,receipt_sequence_cases=cases,row_operation={'type':OPERATION},reason='当前整组来源累计与应收总额一致，按完整回款组纠正日期及拆散记录，不重复计款')

def check(item,rows):
    proof=item.get('current_receipt_group')
    if not proof:return None
    def bad(reason):return {'verdict':'conflict','reason':reason}
    try:
        expected=build(proof['records'],proof['before_rows'])
        if expected!=proof:return bad('整组回款依据无法由当前原值和完整来源重建')
        identity=item['current_receipt_event'];rec=next(r for r in proof['records'] if BR.event_key(r)==identity)
        source=item.get('split_payment_source') or {}
        if any(item.get(k)!=rec.get(k) for k in ('ar','so','sod')):return bad('整组回款身份发生变化')
        if source.get('writeoff_sequence_key')!=rec.get('writeoff_sequence_key'):return bad('整组核销来源顺序发生变化')
        for field,key in [('amount_local','amount_local'),('delivery_local','deliver_local'),('cumulative_local','cumulative_received_local')]:
            if BR.cents(source.get(field))!=BR.cents(rec.get(key)):return bad('整组核销来源金额发生变化')
        primary=str(item['ledger_row_ref']);refs=proof['event_rows'][identity]
        wanted={**{k:proof['after_rows'][primary][k] for k in FIVE},'实收SOD':item['sod']}
        if primary not in refs or item.get('five_cols')!=wanted or item.get('derived_cols') or item.get('row_operation')!={'type':OPERATION}:return bad('整组回款写入指令与当前证据不一致')
        current={str(ref):BR.normalized(row) for ref,row in rows.items() if row.get('SO')==item['so']}
        if current==proof['after_rows']:return {'verdict':'skip','reason':'整组当前回款已一致，无需重复写入'}
        if current!=proof['before_rows']:return bad('整组当前表在计划后被修改')
        return {'verdict':'write','reason':'整组应收、逐笔来源及累计金额守恒，纠正现有行'}
    except (KeyError,TypeError,ValueError,StopIteration):return bad('整组回款核验依据不完整')

def source_error(item,by_case):
    proof=item.get('current_receipt_group')
    if not proof:return ''
    members=[by_case.get(k) for k in item.get('receipt_sequence_cases') or []]
    if not members or any(not m or m.get('current_receipt_group')!=proof for m in members):return '整组回款关联计划不完整'
    if {m.get('current_receipt_event') for m in members}!=set(proof['event_rows']):return '整组回款来源覆盖不完整'
    if len(members)!=len(proof['event_rows']):return '整组回款来源重复'
    return ''
