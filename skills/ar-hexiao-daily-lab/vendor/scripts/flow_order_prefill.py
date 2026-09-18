"""Append pending order presentation without inventing receipt allocations."""
import copy
import re
import xlsx_patch


def pending_sos(item):
    return {str(o.get('so') or '').strip().upper() for o in item.get('so_outcomes', [])
            if 'hold' in (o.get('buckets') or []) and set(o.get('codes') or []) & {'E2', 'E3'}}


def entries(item):
    from build_flow_plan import STRONG
    from flow_monthly import money, number
    if item.get('hits') != 1 or item.get('matched_by') not in STRONG:
        raise ValueError('订单信息必须强三键唯一命中')
    if item.get('order_amount_conflicts'):
        raise ValueError('同一订单的金额依据冲突，需人工核对')
    wanted=pending_sos(item)
    if not wanted:raise ValueError('没有可单独登记的待处理订单')
    values={}
    for entry in item.get('so_entries') or []:
        so=str(entry.get('so') or '').strip().upper()
        if so not in wanted:continue
        amount=money(entry.get('delivery_amount'))
        if amount < 0:raise ValueError('订单金额不能为负数')
        if so in values and values[so] != number(amount):raise ValueError('订单金额依据不唯一')
        values[so]=number(amount)
    if set(values)!=wanted:raise ValueError('待处理订单缺少明确的本币金额依据')
    return values


def merge(current, amounts):
    from flow_monthly import money
    from apply_flow import _rich_signature
    text=str(current or '')
    additions=[]
    for so,amount in amounts.items():
        matches=list(re.finditer(re.escape(so)+r'(?![A-Z0-9])',text,re.I))
        if len(matches)>1:raise ValueError('已有订单重复出现，需人工核对')
        if matches:
            suffix=text[matches[0].end():].split('\n',1)[0]
            if not re.fullmatch(r'\s*[0-9,]+(?:\.\d{1,2})?\s*',suffix):
                raise ValueError('已有订单金额无法唯一解析，需人工核对')
            if money(suffix.strip())!=money(amount):raise ValueError('已有订单金额发生变化，需人工核对')
        else:additions.append(f'{so}  {money(amount):,.2f}')
    if not additions:return current,False
    tail=('' if not text or text.endswith('\n') else '\n')+'\n'.join(additions)
    runs=[xlsx_patch.RichTextRun(fragment,color) for fragment,color in _rich_signature(current)]
    runs.append(xlsx_patch.RichTextRun(tail))
    return xlsx_patch.RichTextValue(tuple(runs)),True


def record(item, ws, cols, state):
    from flow_monthly import signature, value
    amounts=entries(item)
    row=int(item['row_no']);ar=item['ar'];sig=signature(ws,row,cols)
    if any(other!=ar and chain['sheet']==ws.title and row in {m['row'] for m in chain['months'] if '_insert_after' not in m}
           for other,chain in state['receipts'].items()):
        raise ValueError('原始行已关联另一笔到账，不能追加订单')
    records=state.setdefault('order_prefills',{})
    for other,old in records.items():
        if other!=ar and old['sheet']==ws.title and old['signature']==sig:
            raise ValueError('待处理订单行已属于另一笔到账')
    old=records.get(ar)
    if old and (old['sheet']!=ws.title or old['signature']!=sig):
        raise ValueError('待处理订单登记后流转行已改变，需重新核对')
    current=value(ws,row,cols,'单号')
    desired,changed=merge(current,amounts)
    if old is None:
        old={'sheet':ws.title,'row':row,'signature':sig,
             'original_text':str(current or ''),'pending':{}}
        records[ar]=old
    for so,amount in amounts.items():
        previous=old['pending'].get(so)
        if previous is not None and previous!=amount:raise ValueError('已登记待处理订单金额发生变化')
        old['pending'][so]=amount
    return desired,changed,old


def prefill_items(items):
    selected=[]
    for source in items:
        if source.get('verdict')!='write' or not pending_sos(source):continue
        item=copy.deepcopy(source)
        item.update(order_only=True,monthly_entries=[],monthly_require_existing=[])
        entries(item)
        selected.append(item)
    return selected


def check_completion_basis(item, pending):
    from flow_monthly import money
    if item.get('order_amount_conflicts'):raise ValueError('同一订单金额依据冲突，需人工核对')
    current={str(x.get('so') or '').upper():x.get('delivery_amount') for x in item.get('so_entries',[])}
    for entry in item.get('monthly_entries',[]):
        so=entry['so']
        if so in pending['pending'] and money(current.get(so))!=money(pending['pending'][so]):
            raise ValueError('待处理订单的同口径金额依据发生变化，需人工核对')
