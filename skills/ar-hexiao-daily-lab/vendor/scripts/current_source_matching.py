"""Bind audited SO events to current rows for a single-SOD source scope.

Prior events must already be present. Missing prior dates are never added to
this day's writes. No previous execution journal participates in matching.
"""
from collections import defaultdict
import baseline_receipts as BR
import common


def signature(event):
    return tuple(event[k] for k in ('amount_orig','amount_local','currency','arrival_date','posting_date','status'))


def _matching(edges, mandatory, row_refs, forced=None):
    owners = {}
    locked = None
    if forced is not None:
        locked, ref = forced
        owners[ref] = locked
    def augment(event, visited):
        for ref in edges[event]:
            if ref in visited:
                continue
            visited.add(ref)
            owner = owners.get(ref)
            if owner is None or (owner != locked and augment(owner, visited)):
                owners[ref] = event
                return True
        return False
    order = sorted(mandatory) + [i for i in range(len(edges)) if i not in mandatory]
    for event in order:
        if event == locked:
            continue
        ok = augment(event, set())
        if event in mandatory and not ok:
            return None
    if set(owners) != set(row_refs) or not mandatory.issubset(set(owners.values())):
        return None
    return owners


def source_events(records, day, initial, *, source_history=None, source_so=None):
    history = records[0].get('current_source_history') if records else source_history
    so = records[0].get('so') if records else source_so
    if not so:
        return None
    if (not history or any(r.get('current_source_history') != history for r in records)
            or history.get('basis') != 'audited_current_exports'
            or history.get('as_of_date') != day or history.get('unresolved_parent_ars')
            or not history.get('identity_fields_complete')):
        return None
    grouped = {}
    seen = set()
    for raw in history.get('events') or []:
        event = dict(raw)
        key = tuple(str(event.get(k) or '') for k in ('ar','record_id','rowid'))
        posting, arrival = common.norm_date(event.get('posting_date')), common.norm_date(event.get('arrival_date'))
        original, local = BR.cents(event.get('amount_orig')), BR.cents(event.get('amount_local'))
        if (not key[0] or not key[1] or key in seen or event.get('missing_fields')
                or not posting or not arrival or arrival > posting or posting.isoformat() > day
                or event.get('so') != so or not event.get('currency')
                or event.get('status') in ('',None,'已作废')
                or original is None or original <= 0 or local is None or local <= 0
                or (common.is_cny(event['currency']) and original != local)):
            return None
        seen.add(key)
        event.update(amount_orig=original,amount_local=local,
                     posting_date=posting.isoformat(),arrival_date=arrival.isoformat())
        parent_key=(event['ar'],event['posting_date'])
        if parent_key in grouped:
            previous=grouped[parent_key]
            if any(previous[k] != event[k] for k in ('currency','arrival_date','status')):
                return None
            previous['amount_orig']+=original
            previous['amount_local']+=local
        else:
            grouped[parent_key]=event
    current={r['ar']:r for r in records}
    if len(current)!=len(records):
        return None
    events=sorted(grouped.values(),key=lambda e:(e['posting_date'],e['ar']))
    if {e['ar'] for e in events if e['posting_date']==day} != set(current):
        return None
    mandatory=set()
    for index,event in enumerate(events):
        if event['posting_date']<day:
            mandatory.add(index)
        else:
            rec=current[event['ar']]
            expected=(BR.cents(rec['amount_orig']),BR.cents(rec['amount_local']),rec['currency'],rec['shoukuan_date'],rec['hexiao_date'],rec['status'])
            if signature(event)!=expected:
                return None
    if sum(events[i]['amount_local'] for i in mandatory)!=initial:
        return None
    return events,mandatory,current


def bind(records, rows, day, initial, *, source_history=None, source_so=None):
    parsed=source_events(records,day,initial,source_history=source_history,source_so=source_so)
    if parsed is None:return None
    events,mandatory,current=parsed
    import current_fragment_matching as F
    fragmented = F.bind(events, mandatory, rows, signature)
    if fragmented != 'single_rows':
        if fragmented is None:
            return None
        bindings = {BR.event_key(current[e['ar']]):fragmented.get(i,[])
                    for i,e in enumerate(events) if i not in mandatory}
        prior = sorted(ref for i,refs in fragmented.items() if i in mandatory for ref in refs)
        return bindings,prior
    edges=[[ref for ref,row in rows.items() if BR.cents(row['回款明细'])==e['amount_local']
            and row['收款时间'] in (e['arrival_date'],e['posting_date'])] for e in events]
    owners=_matching(edges,mandatory,rows)
    if owners is None:
        return None
    # Alternate feasible owners must be business-equivalent. Different posting
    # dates are not interchangeable even when the bank arrival and amount agree.
    for event, candidates in enumerate(edges):
        for ref in candidates:
            if signature(events[event]) == signature(events[owners[ref]]):
                continue
            if _matching(edges,mandatory,rows,(event,ref)) is not None:
                return None
    event_refs=defaultdict(list)
    for ref,event in owners.items():
        event_refs[event].append(ref)
    bindings={BR.event_key(current[e['ar']]):event_refs.get(i,[])
              for i,e in enumerate(events) if i not in mandatory}
    prior=sorted(ref for ref,i in owners.items() if i in mandatory)
    return bindings,prior
