"""Bind a visible numeric deduction prefix to the complete current source prefix.

The workbook can already contain later deductions than the requested day. Those
remain anonymous and unchanged; their money must never be charged a second time.
"""
import copy
import re


def bind(chain, item):
    from flow_monthly import money, SO, current_source_balance_matches
    history=item.get('monthly_receipt_history') or {}
    if history.get('basis')!='current_source_reconcile' or not history.get('fetched_history'):
        return chain
    sources=history.get('entries') or []
    if not sources or any(not e['key'].startswith('source|') or money(e['amount'])<=0 for e in sources):return chain
    wanted=item.get('monthly_entries') or []
    source_map={e['key']:e for e in sources}
    if len(source_map)!=len(sources) or not wanted or any(source_map.get(e['key'])!=e for e in wanted):return chain
    # Scope to a single visible row; multi-row carry chains have their own proof.
    if len(chain['months'])!=1:return chain
    month=chain['months'][0];entries=month['entries']
    if not entries or any(not e['key'].startswith('legacy:') and source_map.get(e['key'])!=e for e in entries):return chain
    shown=SO.findall(str(month['signature'][4]).upper())
    known={e['so'].upper() for e in sources}
    if len(shown)!=len(set(shown)) or not known.issubset(shown):return chain
    if not current_source_balance_matches(' '.join(sorted(known)),history):return chain
    if money(history['opening'])!=money(month['start']):return chain
    target=sum((money(e['amount']) for e in sources),money(0));subtotal=money(0);ends=[]
    for index,entry in enumerate(entries):
        if money(entry['amount'])<=0:return chain
        subtotal+=money(entry['amount'])
        if subtotal==target:ends.append(index+1)
    if len(ends)!=1:return chain
    end=ends[0]
    if any(not e['key'].startswith('legacy:') for e in entries[end:]):return chain
    # Complete row requires complete SO coverage. A shortened prefix must leave
    # both visible unbound SOs and corresponding positive deductions untouched.
    if (end==len(entries)) != (known==set(shown)):return chain
    if end<len(entries):
        text=str(month['signature'][4]).upper()
        already={e['key'] for e in entries if not e['key'].startswith('legacy:')}
        for source in wanted:
            if source['key'] in already:continue
            fragment=text.split(source['so'].upper(),1)[1].split('SO',1)[0]
            amounts=re.findall(r'(?<![\d.])\d+(?:\.\d{1,2})?(?![\d.])',fragment.replace(',',''))
            if not any(money(token)==money(source['amount']) for token in amounts):return chain

    if target>money(month['start']) or subtotal!=money(month['start'])-money(month['remaining']):return chain
    if any(e['date']>history['date'] for e in sources):return chain
    result=copy.deepcopy(chain);m=result['months'][0]
    m['entries']=copy.deepcopy(sources)+m['entries'][end:]
    m['legacy_sos']=sorted(set(m.get('legacy_sos') or [])-known)
    m['_visible_source_prefix']=dict(date=history['date'],amount=str(target))
    return result
