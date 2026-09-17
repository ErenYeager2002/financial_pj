"""Bind verified current parent allocations to flow receipt evidence."""
from decimal import Decimal
import common
import baseline_receipts as BR


def proof(row, ledger_rows, day, parents):
    if (row.get('_check') or {}).get('verdict')!='skip':return {}
    ar,so,sod=row.get('ar'),row.get('so'),row.get('sod')
    parent=parents.get(ar) or {}
    if not parent.get('reconstructed_from_current_material') or parent.get('basis')!='local':return {}
    try:
        import flow_monthly as F
        posting=common.norm_date(day)
        if not posting or common.norm_date(parent.get('hexiao_date'))!=posting:return {}
        if (parent.get('processing_order') or {}).get('ar')!=ar:return {}
        source=(row.get('source_lineage') or {}).get('source') or {}
        if source.get('ar')!=ar or source.get('so')!=so or common.norm_date(source.get('reconciliation_date'))!=posting:return {}
        total=F.money(parent['parent_amount'])
        if total<=0 or F.money(source.get('parent_amount_local'))!=total:return {}
        allocations=parent.get('allocations') or []
        if len({a['so'] for a in allocations})!=len(allocations):return {}
        if any(F.money(a['allocated_local'])<=0 for a in allocations):return {}
        if sum((F.money(a['allocated_local']) for a in allocations),Decimal(0))!=total:return {}
        allocation=next((a for a in allocations if a['so']==so),None)
        source_amount=source.get('order_writeoff_local')
        if source_amount is None:
            source_amount=(row.get('split_payment_source') or {}).get('so_delivery_local')
        if not allocation or F.money(source_amount)!=F.money(allocation['allocated_local']):return {}
        before=(parent.get('current_material_evidence') or {}).get(so)
        current={str(ref):BR.normalized(r) for ref,r in ledger_rows.items() if r.get('SO')==so}
        if not before or current!=before:return {}
        cases={k:v for k,v in (parent.get('applied_cases') or {}).items() if v.get('so')==so}
        case=cases.get(row.get('case_id'))
        amount=F.actual_amount(row)
        if not case or case.get('sod')!=sod or F.money(case.get('amount_local'))!=amount or amount<=0:return {}
        if sum((F.money(c['amount_local']) for c in cases.values()),Decimal(0))!=F.money(allocation['allocated_local']):return {}
        arrival=common.norm_date((row.get('flow_identity') or {}).get('date'))
        expected_day=common.receipt_time(arrival,posting)
        expected_way=common.pay_way(row.get('status') or '',arrival,posting)
        exact=[r for r in current.values() if r['SOD']==sod and r['是否结账']=='是'
               and F.money(r['回款明细'])==amount and common.norm_date(r['收款时间'])==expected_day and r['收款方式']==expected_way]
        if len(exact)!=1:return {}
        return {'basis':'current_material_parent_case','ar':ar,'so':so,'sod':sod,'date':posting.isoformat(),'amount':F.number(amount)}
    except (ValueError,TypeError,KeyError):return {}
