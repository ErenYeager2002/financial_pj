"""Read-only proof that multiple current receipts were recorded as one sum.

A physical row belongs to one aggregate group. Its amount is never counted once
per member, and all members must stay in the plan for the proof to remain valid.
"""
import baseline_receipts as BR
import common


def bind(records, rows, day, initial):
    if initial or not rows or len(records)<=len(rows):return None
    if len({r['currency'] for r in records})!=1:return None
    if any('current_source_history' in r for r in records):
        import current_source_matching as M
        parsed=M.source_events(records,day,initial)
        if parsed is None or parsed[1]:return None
    if sum(BR.cents(r['amount_local']) for r in records)!=sum(BR.cents(r['回款明细']) for r in rows.values()):return None
    refs=sorted(rows,key=int);amounts=[BR.cents(r['amount_local']) for r in records]
    choices={};budget=[100000]
    def tick():
        budget[0]-=1
        if budget[0]<0:raise OverflowError('aggregate matching unproven')
    try:
        for ref in refs:
            row=rows[ref];options=[]
            def subset(index,left,members):
                tick()
                if left==0:
                    dates={d for i in members for d in (records[i]['shoukuan_date'],records[i]['hexiao_date'])}
                    ways={common.pay_way(records[i]['status'],common.norm_date(records[i]['shoukuan_date']),common.norm_date(records[i]['hexiao_date'])) for i in members}
                    if row['收款时间'] in dates and row['收款方式'] in ways:
                        options.append(tuple(members))
                    return
                if index==len(records) or sum(amounts[index:])<left:return
                if amounts[index]<=left:subset(index+1,left-amounts[index],members+[index])
                subset(index+1,left,members)
            subset(0,BR.cents(row['回款明细']),[])
            if not options:return None
            choices[ref]=options
        signatures=[tuple(r[k] for k in ('amount_orig','amount_local','currency','shoukuan_date','hexiao_date','status')) for r in records]
        first=None;facts=None;assignment={}
        def search(index,used):
            nonlocal first,facts
            tick()
            if index==len(refs):
                if len(used)!=len(records):return
                current={ref:sorted(signatures[i] for i in members) for ref,members in assignment.items()}
                if first is None:first=dict(assignment);facts=current
                elif current!=facts:raise ValueError('different aggregate attribution')
                return
            ref=refs[index]
            for members in choices[ref]:
                if used.intersection(members):continue
                assignment[ref]=members;search(index+1,used|set(members));assignment.pop(ref)
        search(0,set())
        if first is None:return None
        bindings={};groups=[]
        for ref,members in first.items():
            keys=[BR.event_key(records[i]) for i in members]
            groups.append(dict(row=ref,events=keys,amount=rows[ref]['回款明细']))
            for key in keys:bindings[key]=[ref]
        return bindings,groups
    except (OverflowError,ValueError,RecursionError):return None
