"""Receipt completion from the same verified cases used for flow registration."""

def bind(item, rows):
    ar=str(item.get('ar') or '').strip()
    outcomes=item.get('so_outcomes') or [
        {'so':so,'buckets':['auto'],'case_ids':[]} for so in item.get('so_list',[])]
    good={}
    for _,row in rows:
        if str(row.get('ar') or '').strip()!=ar or row.get('bucket') not in ('auto','ready'):
            continue
        so=str(row.get('so') or '').strip()
        good.setdefault(so,set()).add(str(row.get('case_id') or '').strip())
    for outcome in outcomes:
        so=str(outcome.get('so') or '').strip()
        cases={str(c).strip() for c in outcome.get('case_ids',[]) if str(c).strip()}
        eligible=bool(so and so in good) and all(b in ('auto','ready') for b in outcome.get('buckets',[]))
        outcome['completed']=bool(eligible and (not cases or cases <= good[so]))
        outcome['updated']=bool(cases & good.get(so,set())) if cases else bool(good.get(so))
    item['so_outcomes']=outcomes
    item['updated_suggest']=status(item)
    item['phase']='post_ledger'


def status(item, unresolved=()):
    outcomes=item.get('so_outcomes') or []
    if not outcomes:
        return ''
    if any(not isinstance(o.get('completed'),bool) for o in outcomes):
        raise ValueError('流转完成状态缺少已验证的本次核销事项')
    completed=[o for o in outcomes if o['completed']]
    if not any(o.get('updated',o['completed']) for o in outcomes):
        return ''
    return '是' if len(completed)==len(outcomes) and not unresolved else '部分'
