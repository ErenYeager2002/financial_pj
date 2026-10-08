"""Prove a visible cumulative carry, without charging overlapping partial rows."""
from __future__ import annotations

import copy
import re
from decimal import Decimal


def row_facts(ws, cols, row, opening):
    import common
    import flow_monthly as M
    try:
        day=common.norm_date(M.value(ws,row,cols,'日期'))
        if not day or str(M.value(ws,row,cols,'收款形式') or '').strip()!='冲预收':return None
        parsed=M.parsed_balance(M.value(ws,row,cols,'预收'))
        if parsed.get('credit') or parsed.get('opening')!=M.money(opening):return None
        deductions=parsed.get('deductions') or []
        if not deductions or any(x<=0 for x in deductions) or parsed['remaining']<0:return None
        amount=M.money(M.value(ws,row,cols,'金额'))
        if amount!=M.money(opening) and M.legacy_period_opening('冲预收',amount,parsed)!=M.money(opening):return None
        text=str(M.value(ws,row,cols,'单号') or '')
        matches=list(M.SO.finditer(text));orders=[]
        for i,match in enumerate(matches):
            tail=text[match.end():matches[i+1].start() if i+1<len(matches) else len(text)]
            numeric=re.fullmatch(r'\s*('+M.BALANCE_NUMBER+r')\s*(?:追加\s*[：:]?\s*)?',tail)
            if not numeric:return None
            orders.append((match.group().upper(),M.money(numeric[1])))
        if not orders or len({so for so,_ in orders})!=len(orders) or any(n<=0 for _,n in orders):return None
        if sum((n for _,n in orders),Decimal(0))!=sum(deductions,Decimal(0)):return None
        return dict(row=row,date=day.isoformat(),opening=M.money(opening),remaining=parsed['remaining'],
                    deductions=deductions,orders=orders,payer=str(M.value(ws,row,cols,'公司名称') or '').strip())
    except (ValueError,KeyError,TypeError):
        return None


def source_prefix(facts, history):
    """Only bind fetched current events; trailing visible deductions stay anonymous."""
    import common
    import flow_monthly as M
    if not facts or not history or history.get('basis')!='current_source_reconcile' or not history.get('fetched_history'):return None
    try:
        if M.money(history['opening'])!=facts['opening']:return None
        sources=history.get('entries') or []
        if not sources or len({e['key'] for e in sources})!=len(sources):return None
        if any(not isinstance(e['key'],str) or not e['key'].startswith('source|') or M.money(e['amount'])<=0 for e in sources):return None
        by_so={str(e['so']).upper():M.money(e['amount']) for e in sources}
        if len(by_so)!=len(sources):return None
        dates=[common.norm_date(e['date']) for e in sources]
        cutoff=common.norm_date(history['date']);first=common.norm_date(facts['date'])
        if not cutoff or not first or any(not d or d>cutoff or d<first or d.strftime('%Y-%m')!=first.strftime('%Y-%m') for d in dates):return None
        if min(dates)!=first:return None
        # Do not match a convenient subset in the middle or sum delivery notes.
        shown=dict(facts['orders'])
        if any(shown.get(so)!=amount for so,amount in by_so.items()):return None
        total=sum(by_so.values(),Decimal(0));running=Decimal(0)
        for index,amount in enumerate(facts['deductions']):
            running+=amount
            if running==total:
                return dict(entries=copy.deepcopy(sources),tail=facts['deductions'][index+1:])
            if running>total:return None
    except (ValueError,KeyError,TypeError):
        return None
    return None


def choose(ws, cols, candidates, item, opening):
    """Select one full cumulative representation; never merge or delete rows."""
    import flow_monthly as M
    facts=[row_facts(ws,cols,row,opening) for row in candidates]
    if any(f is None for f in facts):return None
    accepted=[]
    for full in facts:
        history=M.source_history_for_row(ws,full['row'],cols,item)
        if not source_prefix(full,history):continue
        full_orders=dict(full['orders'])
        alternatives=[]
        for other in facts:
            if other is full:continue
            # A strict matching subset is a partial representation, not a second
            # event to append. Independent equal complete rows remain ambiguous.
            other_orders=dict(other['orders'])
            if (other['payer']!=full['payer'] or other['date'][:7]!=full['date'][:7]
                    or other['date']<full['date'] or len(other_orders)>=len(full_orders)
                    or any(full_orders.get(so)!=amount for so,amount in other_orders.items())):break
            alternatives.append(other['row'])
        else:
            accepted.append((full['row'],alternatives))
    return accepted[0] if len(accepted)==1 else None
