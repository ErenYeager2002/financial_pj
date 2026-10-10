"""Quarantine delivery estimates that conflict with explicit current SO receipts.

Amounts and source coverage remain intact. Only conflicting estimates are left
out of the cumulative proof, and they cannot authorize workbook deductions.
"""
from collections import defaultdict
import baseline_receipts as BR
import common


def identify(logical_rows, parents, audits, target_date):
    by_so=defaultdict(list)
    for row in logical_rows:
        if target_date and row.get('date') and row['date']>target_date:
            continue
        by_so[row['so']].append(row)
    conflicts={}
    for so,rows in by_so.items():
        estimates=[r for r in rows if audits.get(r['ar'],{}).get('status')=='delivery_fallback']
        explicit=[r for r in rows if r not in estimates]
        if not estimates or not explicit:
            continue
        # This comparison needs one unambiguous local delivery baseline. An
        # unknown amount or changing delivery is handled by existing guards.
        capacities={BR.cents(o.get('deliver_local')) for r in rows
                    for o in parents.get(r['ar'],{}).get('orders') or [] if o.get('so')==so}
        amounts=[BR.cents(r.get('_resolved_amount_local')) for r in rows]
        if (len(capacities)!=1 or None in capacities or next(iter(capacities))<=0
                or any(v is None or v<0 for v in amounts)):
            continue
        capacity=next(iter(capacities))
        if sum(amounts)<=capacity+BR.SETTLEMENT_CENTS:
            continue
        strong_ars=sorted({r['ar'] for r in explicit})
        for row in estimates:
            conflicts[(row['ar'],so)]=dict(
                so=so,ar=row['ar'],basis='delivery_estimate_conflicts_with_explicit_receipts',
                estimated_amount_local=row['_resolved_amount_local'],
                explicit_ars=strong_ars,delivery_local=capacity/100,
                combined_receipts_local=sum(amounts)/100,
                reason='没有逐SO实际核销金额；交付额推算与明确核销明细累计冲突，'
                       '本笔金额保留待核对，不据此认定重复回款或占用明确回款的核销额度。')
    return conflicts
