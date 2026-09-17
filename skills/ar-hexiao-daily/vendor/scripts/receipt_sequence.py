"""Keep every slice of an itemized SO allocation in one validation group."""

def guard(items, *, checked=False, universe=None):
    universe = items if universe is None else universe
    if not checked:
        affected = {r.get('so') for r in universe if r.get('ambiguous_sod_waterfall')}
        for so in affected:
            group = [r for r in universe if r.get('so') == so]
            members = sorted({r['case_id'] for r in group})
            for r in group:
                r['receipt_sequence_cases'] = members
    by_case = {r.get('case_id'): r for r in universe}
    def good(r):
        return (r.get('_check') or {}).get('verdict') in {'write', 'skip'} if checked else r.get('bucket') == 'auto'
    failed = set()
    for r in items:
        required = r.get('receipt_sequence_cases') or []
        if any(key not in by_case or not good(by_case[key]) for key in required):
            failed.update(required)
    for r in items:
        if r.get('case_id') not in failed or not good(r):
            continue
        reason = '同一 SO 顺序分配的关联核销尚未全部通过，不能只写其中部分 SOD'
        if checked:
            r['_check'] = {'verdict': 'conflict', 'reason': reason}
        else:
            r.update(bucket='hold', code='E_RECEIPT_SEQUENCE_DEPENDENCY', reason=reason, five_cols={}, derived_cols={})
            r.pop('row_operation', None)
