"""Correct only dates/ways after a complete source group uniquely matches amounts."""
import copy
import baseline_receipts as BR
import common


def prove(records, rows):
    import current_workbook_receipts as W
    if not records or len(records)!=len(rows):return None
    delivery=BR.cents(records[0].get('deliver_local'))
    amounts=[BR.cents(r.get('amount_local')) for r in records]
    if not delivery or any(not n or n<=0 for n in amounts) or len(set(amounts))!=len(amounts) or sum(amounts)!=delivery:return None
    before={str(k):BR.normalized(v) for k,v in rows.items()}
    if sum(BR.cents(r['应收金额']) or 0 for r in before.values())!=delivery:return None
    if any(r['是否结账']!='是' or BR.cents(r['回款明细'])!=BR.cents(r['应收金额']) or r['收款方式'] not in ('','汇','冲预收') for r in before.values()):return None
    shadow=copy.deepcopy(before);changes={};used=set()
    for rec in records:
        event=BR.event_key(rec);amount=BR.cents(rec.get('amount_local'))
        candidates=[ref for ref,row in before.items() if BR.cents(row['回款明细'])==amount]
        if not event or len(candidates)!=1 or candidates[0] in used:return None
        ref=candidates[0];used.add(ref)
        arrival,posting=common.norm_date(rec.get('shoukuan_date')),common.norm_date(rec.get('hexiao_date'))
        if not arrival or not posting or arrival>posting:return None
        actual=before[ref]
        if actual['收款时间'] in (arrival.isoformat(),posting.isoformat()) and actual['收款方式']:
            continue
        expected={'收款时间':common.receipt_time(arrival,posting).isoformat(),
                  '收款方式':common.pay_way(rec.get('status') or '',arrival,posting)}
        if not expected['收款方式']:return None
        shadow[ref].update(expected)
        changes[event]=dict(row=ref,before={k:actual[k] for k in expected},after=expected)
    if not changes:return None
    ordinary=W.prove(records,shadow)
    if ordinary is None or ordinary['missing_events'] or ordinary['protected_prior_rows'] or ordinary['protected_future_rows']:return None
    return {**ordinary,'before_rows':before,'material_rows_sha256':W.digest(before),'date_corrections':changes}
