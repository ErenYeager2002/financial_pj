"""Separate settled source business from absent material history.

Run after batch composition so current batch receipts are not mistaken for
missing historical receipts. A business-only skip never proves a ledger write.
"""
from collections import defaultdict
import copy
import baseline_receipts as BR
import amount_policy

CODE = 'OK_SOURCE_SETTLED_MATERIAL_GAP'
WRITE_KEYS = ('five_cols','derived_cols','row_operation','so_accrual_backfills',
              'ordinary_receipt_proof','current_receipt_group','receipt_correction',
              'baseline_receipt_audit','flow_receipt_proof')

def source(item):
    return {k:item.get(k) for k in ('case_id','ar','so','sod','split_payment_source')}

def inspect(sources, before):
    if not sources or not before:return None
    parsed=[]
    for item in sources:
        s=item.get('split_payment_source') or {}
        amount,cumulative,delivery=[BR.cents(s.get(k)) for k in ('amount_local','cumulative_local','delivery_local')]
        if amount is None or amount<=0 or cumulative is None or delivery is None or delivery<=0:return None
        parsed.append((amount,cumulative,delivery))
    if len({d for _,_,d in parsed})!=1:return None
    cumulative=max(c for _,c,_ in parsed);delivery=parsed[0][2]
    if not amount_policy.within_business_tolerance(cumulative/100,delivery/100):return None
    # Earliest running cumulative excludes its current event. Later events in
    # this very batch are therefore not counted as absent historical material.
    running=0;required=0
    for amount,cumulative,_ in sorted(parsed,key=lambda entry:entry[1]):
        running+=amount
        required=max(required,cumulative-running)
    observed=sum(BR.cents(r.get('回款明细')) or 0 for r in before.values())
    if required-observed<=1:return None
    return dict(delivery_local=delivery/100,cumulative_local=cumulative/100,
                required_prior_local=required/100,material_received_local=observed/100,
                missing_prior_local=(required-observed)/100)

def apply(results,ledger):
    if ledger is None:return
    groups=defaultdict(list)
    for item in results:
        if item.get('bucket')=='auto' and item.get('five_cols'):
            groups[(item.get('so'),item.get('sod'))].append(item)
    for (so,sod),items in groups.items():
        if not so or not sod:continue
        before=BR.ledger_rows(ledger,so,sod)
        sources=[source(item) for item in items]
        finding=inspect(sources,before)
        if not finding:continue
        proof=dict(sources=copy.deepcopy(sources),before_rows=before,**finding)
        for item in items:
            for key in WRITE_KEYS:item.pop(key,None)
            item.update(code=CODE,source_business_status='settled',material_registration_status='incomplete',
                        source_history_gap=copy.deepcopy(proof),
                        reason=f"智云累计核销{finding['cumulative_local']:g}元，交付{finding['delivery_local']:g}元，业务已核销完成；盈亏材料缺少此前{finding['missing_prior_local']:g}元登记。本次不自动补写，不登记本次流转完成或扣减余额。")

def check(item,rows,by_case):
    def bad():return dict(verdict='conflict',reason='业务已完成但材料历史缺失的依据或写入指令发生变化，请重新判定')
    proof=item.get('source_history_gap') or {}
    if any(item.get(k) for k in WRITE_KEYS):return bad()
    try:
        members=[by_case[s['case_id']] for s in proof['sources']]
        if any(m.get('code')!=CODE or m.get('source_history_gap')!=proof for m in members):return bad()
        if [source(m) for m in members]!=proof['sources'] or item['case_id'] not in [m['case_id'] for m in members]:return bad()
        current={str(ref):BR.normalized(row) for ref,row in rows.items() if row.get('SO')==item.get('so') and row.get('SOD')==item.get('sod')}
        if current!=proof['before_rows']:return bad()
        finding=inspect(proof['sources'],current)
        if not finding or proof!={**finding,'sources':proof['sources'],'before_rows':current}:return bad()
        return dict(verdict='skip',reason=item['reason'])
    except (KeyError,TypeError,ValueError):return bad()

def unsafe_write(item,items,rows):
    if item.get('code')==CODE or not item.get('five_cols'):return ''
    members=[m for m in items if (m.get('so'),m.get('sod'))==(item.get('so'),item.get('sod')) and m.get('five_cols')]
    before={str(ref):BR.normalized(row) for ref,row in rows.items() if row.get('SO')==item.get('so') and row.get('SOD')==item.get('sod')}
    return ('智云业务已完成，但盈亏历史登记缺失；当前计划仍包含自动写入，请重新判定' if inspect([source(m) for m in members],before) else '')
