"""Preserve audited current-export events; never assert historical coverage.

These SO-level facts are not allocations to SODs or proof that a workbook row
belongs to an AR. Consumers must verify coverage and workbook bindings.
"""
import copy
import common


def day(value):
    parsed = common.norm_date(value)
    return parsed.isoformat() if parsed else None


def attach(payments, parents, logical_rows, unresolved_sos, target_date):
    by_so = {}
    cutoff = day(target_date)
    for row in logical_rows:
        posting = day(row.get('date'))
        if cutoff and posting and posting > cutoff:
            continue
        parent = parents.get(row.get('ar')) or {}
        event = dict(
            ar=row.get('ar'), so=row.get('so'),
            record_id=row.get('record_id'), rowid=row.get('rowid'),
            posting_date=posting, arrival_date=day(parent.get('arrival_date')),
            amount_orig=common.to_number(row.get('amount')),
            amount_local=common.to_number(row.get('_resolved_amount_local')),
            currency=row.get('currency') or parent.get('currency') or '',
            status=parent.get('status') or '',
        )
        event['missing_fields'] = [key for key in (
            'ar','so','record_id','posting_date','arrival_date','currency','status'
        ) if not event[key]]
        event['missing_fields'] += [key for key in ('amount_orig','amount_local') if event[key] is None]
        by_so.setdefault(event['so'], []).append(event)
    for p in payments:
        sos = {str(o.get('so') or '').strip() for o in p.get('orders') or []}
        sos.update(p.get('writeoffs') or {})
        p['_current_source_history_by_so'] = {}
        for so in sorted(sos - {''}):
            events = copy.deepcopy(by_so.get(so, []))
            events.sort(key=lambda e: tuple(str(e.get(k) or '') for k in ('posting_date','record_id','rowid','ar','so')))
            unresolved = sorted(set(unresolved_sos.get(so) or []))
            p['_current_source_history_by_so'][so] = dict(
                basis='audited_current_exports', as_of_date=cutoff,
                events=events, unresolved_parent_ars=unresolved,
                identity_fields_complete=bool(events) and not unresolved and all(not e['missing_fields'] for e in events),
            )
