"""Recognize incomplete current receipt rows from source totals and current facts."""
import copy
import common
import baseline_receipts as BR


def select(rows, arrival, posting, total, cumulative):
    paid={ref:row for ref,row in rows.items() if (BR.cents(row.get('回款明细')) or 0)>0}
    if not paid or any((BR.cents(row.get('回款明细')) or 0)<0 for row in rows.values()):return None
    if any(not row.get('收款方式') or row.get('是否结账')!='是' for row in paid.values()):return None
    days={arrival,posting,common.receipt_time(arrival,posting)}
    invalid={ref for ref,row in paid.items() if not common.norm_date(row.get('收款时间'))}
    if not invalid:return None
    # All undated paid rows must be explained together; never pick a convenient subset.
    cohort={ref:row for ref,row in paid.items() if ref in invalid or common.norm_date(row['收款时间']) in days}
    if sum(BR.cents(row['回款明细']) for row in cohort.values())!=total:return None
    if len({row['SOD'] for row in cohort.values()})!=len(cohort):return None
    if any(common.norm_date(row['收款时间'])>posting for ref,row in paid.items() if ref not in invalid):return None
    if sum(BR.cents(row['回款明细']) for row in paid.values())!=cumulative:return None
    return cohort


def target(rec, rows):
    audit=rec.get('existing_sod_receipt_audit') or {}
    before=audit.get('before_so_rows') or {}
    source=rec.get('so_receipt_source') or {}
    if not source.get('itemized_cumulative_authoritative'):return None
    total,cumulative=BR.cents(source.get('amount_local')),BR.cents(source.get('cumulative_local'))
    arrival,posting=common.norm_date(rec.get('shoukuan_date')),common.norm_date(rec.get('hexiao_date'))
    if total is None or cumulative is None or not arrival or not posting:return None
    if {k:v for k,v in before.items() if v.get('SO')==rec.get('so') and v.get('SOD')==rec.get('sod')}!=rows:return None
    if any(row.get('SO')!=rec.get('so') for row in before.values()):return None
    cohort=select(before,arrival,posting,total,cumulative)
    if not cohort or set(cohort)!=set(audit.get('matched_rows') or []):return None
    matches=[ref for ref,row in cohort.items() if row['SOD']==rec.get('sod') and BR.cents(row['回款明细'])==BR.cents(rec.get('amount_local'))]
    if len(matches)!=1:return None
    actual_cumulative=sum(BR.cents(row['回款明细']) or 0 for row in before.values() if row['SOD']==rec.get('sod'))
    if actual_cumulative!=BR.cents(rec.get('cumulative_received_local')):return None
    return matches[0]


def expand(records,ledger):
    if ledger is None:return records
    import receipt_history as H
    out=[];resolved={}
    for rec in records:
        source=rec.get('so_receipt_source') or {}
        key=(rec.get('ar'),rec.get('so'),tuple(rec.get('writeoff_sequence_key') or []))
        if key in resolved:
            if resolved[key]==source:continue
            out.append(rec);continue
        if not source.get('itemized_cumulative_authoritative') or rec.get('forced_code') not in (None,'','E5'):
            out.append(rec);continue
        rows={}
        for sod in source.get('all_sods') or []:rows.update(BR.ledger_rows(ledger,rec.get('so'),sod))
        arrival,posting=common.norm_date(rec.get('shoukuan_date')),common.norm_date(rec.get('hexiao_date'))
        total,cumulative=BR.cents(source.get('amount_local')),BR.cents(source.get('cumulative_local'))
        if not arrival or not posting or total is None or cumulative is None or not select(rows,arrival,posting,total,cumulative):
            out.append(rec);continue
        seed={**rec,'default_amount_local':source.get('amount_local'),'default_amount_orig':source.get('amount_orig'),
              'default_cumulative_received_local':source.get('cumulative_local'),
              'default_sod_lines':[{'sod':sod,'deliver_local':amount} for sod,amount in (source.get('sod_delivery_local') or {}).items()]}
        slices=H.existing_sod_slices(seed,ledger)
        if slices:out.extend(slices);resolved[key]=copy.deepcopy(source)
        else:out.append(rec)
    return out
