"""Bind interchangeable flow rows only after rechecking the complete parent group."""
import copy
from pathlib import Path
import current_parent_receipt_group as G
from flow_ledger import FlowLedger
from flow_monthly import SO


def bind(workspace, items, checked):
    # Monetary adaptation is local to flow planning; the P&L checked plan is immutable.
    adapted=copy.deepcopy(checked)
    groups={}
    for row in adapted.get('skip',[]):
        proof=row.get('current_parent_receipt_group') or {}
        if row.get('flow_parent_group_proof') and proof.get('fingerprint'):
            groups.setdefault(proof['fingerprint'],[]).append(row)
    if not groups:return adapted
    flow=FlowLedger.from_workspace(Path(workspace));book_cache={}
    all_checked=[r for kind in ('write','skip','conflict') for r in adapted.get(kind,[])]
    for members in groups.values():
        proof=members[0]['current_parent_receipt_group'];ars=set(proof['amounts_by_ar'])
        if len(members)!=len(ars) or {r.get('ar') for r in members}!=ars:continue
        if len([r for r in all_checked if r.get('ar') in ars])!=len(ars):continue
        selected=[i for i in items if i.get('ar') in ars]
        if len(selected)!=len(ars) or {i.get('ar') for i in selected}!=ars:continue
        if any(i.get('so_list')!=[proof['so']] or i.get('order_amount_conflicts') for i in selected):continue
        amounts=set(proof['amounts_by_ar'].values())
        if len(amounts)!=1:continue  # Unequal receipts are not interchangeable rows.
        verified={};candidates=None;valid=True
        for member in members:
            if member.get('current_parent_receipt_group')!=proof:valid=False;break
            name=Path(member.get('ledger_path') or '').name
            book=Path(workspace)/'02_我的表副本'/name
            if not name or not book.is_file():valid=False;break
            if book not in book_cache:
                from validate_plan import read_ledger_rows
                book_cache[book]=read_ledger_rows(book)
            receipt=G.check(proof,book_cache[book],member,checked.get('hexiao_date'))
            if not receipt or receipt!=member.get('flow_parent_group_proof'):valid=False;break
            parent=next(p for p in proof['source_payments'] if p['ar']==member['ar'])
            hit=flow.match(parent['arrival_date'],parent['amount_orig'],customer=parent.get('customer') or '',
                           sales_name=parent.get('sales_name') or '',amount_total=parent['total_amount_orig'],order_sos=[proof['so']])
            if hit['hits']!=len(ars):valid=False;break
            current=sorted(hit['rows'],key=lambda r:(r['file'],r['sheet'],r['row_no']))
            if candidates is not None and current!=candidates:valid=False;break
            candidates=current;verified[member['ar']]=receipt
        if not valid or not candidates:continue
        if len({(r['file'],r['sheet'],r['row_no']) for r in candidates})!=len(ars):continue
        if any(r.get('form')=='冲预收' or r.get('amount_formula') or r.get('formula_orig_amount') is not None
               or set(SO.findall(r.get('order_cell') or ''))!={proof['so']} for r in candidates):continue
        signatures=[{k:v for k,v in row.items() if k!='row_no'} for row in candidates]
        if any(s!=signatures[0] for s in signatures[1:]):continue
        # Equal business fields and one row per proven parent make this a count
        # allocation, not a claim that an old row uniquely recorded this AR.
        by_ar={i['ar']:i for i in selected}
        for ar,target in zip(sorted(ars),candidates):
            item=by_ar[ar]
            item.update(file=target['file'],sheet=target['sheet'],row_no=target['row_no'],hits=1,
                matched_by='当前父回款整组等价数量对应',verdict='write',reason='',
                identity={'date':target['date'].isoformat(),'payer':target['payer'],'amount':target['amount']},
                flow_locate=f"{target['file']}#{target['sheet']} 第{target['row_no']}行（整组等价数量对应）",
                flow_group_evidence={'fingerprint':proof['fingerprint'],'ars':sorted(ars),
                    'rows':[r['row_no'] for r in candidates],'basis':'interchangeable_count'})
        for member in members:
            receipt=verified[member['ar']];amount=receipt['amount']
            member['flow_receipt_proof']={**receipt,'sod':member.get('sod')}
            member['split_payment_source']={**(member.get('split_payment_source') or {}),'amount_local':amount}
            member['write_currency_audit']={**(member.get('write_currency_audit') or {}),
                                           'currency':'CNY','amount_orig':amount,'amount_local':amount}
    return adapted
