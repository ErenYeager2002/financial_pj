"""Reconstruct multi-SOD accrual from the current SO snapshot and source groups."""
import copy
import baseline_receipts as BR
import fx_accrual as FX


def project(scope):
    from classification_ledger import LedgerIndex
    from classification_accrual import _apply_so_accrual_gate
    import current_workbook_receipts as W
    aliases = dict(zip(BR.FIELDS, ('so','sod','yingshou','jiti','huikuan','jiezhang','shoukuan_time','shoukuan_way','chayi')))
    raw = {int(ref): {aliases[k]:v for k,v in row.items()} for ref,row in scope['rows'].items()}
    by_so, by_sod = {}, {}
    for ref,row in raw.items():
        by_so.setdefault(row['so'],[]).append(ref)
        by_sod.setdefault(row['sod'],[]).append(ref)
    ledger = LedgerIndex(synthetic={'so':by_so,'sod':by_sod,'rows':raw})
    results=[]
    with FX.provisional_planning():
        for proof in scope['groups']:
            for rec in proof['records']:
                event=BR.event_key(rec)
                result=dict(ar=rec['ar'],so=rec['so'],sod=rec['sod'],
                            case_id='|'.join(rec[k] for k in ('ar','so','sod')),
                            ledger_year=rec.get('target_ledger_year'),
                            split_payment_source=dict(amount_local=rec['amount_local'],
                                cumulative_local=rec['cumulative_received_local'],delivery_local=rec['deliver_local'],
                                all_sods=rec['all_sods'],sod_delivery_local=rec['sod_delivery_local'],
                                writeoff_sequence_key=rec['writeoff_sequence_key']))
                if 'fx_accrual_source' in rec:
                    result['fx_accrual_source'] = copy.deepcopy(rec['fx_accrual_source'])
                    result['split_payment_source']['fx_accrual_source'] = copy.deepcopy(rec['fx_accrual_source'])
                if 'receivable_group_scope' in rec:
                    result['split_payment_source']['receivable_group_scope'] = copy.deepcopy(rec['receivable_group_scope'])
                W.apply({**rec,'_current_workbook_receipts':proof},result)
                results.append(result)
        _apply_so_accrual_gate(results,ledger,0.011)
    # Provisional values only allow the whole-SO gate to defer accrual. A
    # surviving new accrual still requires a genuine fixed quote. Existing
    # verified receipt values are preserved independently of today's quote.
    for result in results:
        op = result.get('row_operation') or {}
        planned = [result.get('five_cols') or {}, op.get('target_five_cols') or {}]
        planned.extend(step.get('five_cols') or {} for step in op.get('steps') or [])
        new_accrual = result.get('fx_accrual_applied') and any(
            BR.cents(five.get('计提')) is not None for five in planned)
        if FX.source_for(result) and (new_accrual or result.get('so_accrual_backfills')):
            FX.quote_rate(FX.source_for(result))
    return {r['current_workbook_event']:r for r in results}


def validate(scope, rows):
    import current_workbook_receipts as W
    try:
        so=scope['so']
        current={str(ref):BR.normalized(row) for ref,row in rows.items() if row.get('SO')==so}
        if current!=scope['rows'] or not scope['groups']:
            return False
        events=set()
        for proof in scope['groups']:
            records=proof['records']
            if not records or any(r['so']!=so for r in records):return False
            sod=records[0]['sod']
            subset={ref:row for ref,row in current.items() if row['SOD']==sod}
            if W.rebuild(proof,subset)!=proof:return False
            keys=set(proof['event_rows'])
            if keys & events:return False
            events.update(keys)
        return True
    except (KeyError,TypeError,ValueError):
        return False
