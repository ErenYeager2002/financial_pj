"""Read-only receipt ownership reconstructed from current source and workbook.

No previous-run journal is an input. Initial supported proof is a complete
ordinary source prefix already represented by distinct current workbook rows.
"""
import copy
from fx_accrual import accrual_amount
import hashlib
import json
from collections import defaultdict
import baseline_receipts as BR
import common

POLICY = 'current-workbook-receipts-v1'
CODE = 'OK_CURRENT_WORKBOOK_RECEIPT_PRESENT'
FIVE = ('计提', '回款明细', '是否结账', '收款时间', '收款方式')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def source(rec):
    result = {k: rec.get(k) for k in ('ar', 'so', 'sod', 'currency', 'status')}
    for k in ('amount_orig', 'amount_local', 'deliver_local', 'cumulative_received_local'):
        n = BR.cents(rec.get(k))
        result[k] = n / 100 if n is not None else None
    for k in ('shoukuan_date', 'hexiao_date'):
        day = common.norm_date(rec.get(k))
        result[k] = day.isoformat() if day else None
    result['all_sods'] = sorted(set(rec.get('all_sods') or []))
    result['sod_delivery_local'] = {k: v for k,v in (rec.get('sod_delivery_local') or {}).items()}
    result['target_ledger_year'] = rec.get('target_ledger_year')
    result['writeoff_sequence_key'] = [str(v) for v in rec.get('writeoff_sequence_key') or []]
    if 'current_source_history' in rec:
        result['current_source_history'] = copy.deepcopy(rec['current_source_history'])
    for field in ('fx_accrual_source', 'receivable_group_scope'):
        if field in rec:
            result[field] = copy.deepcopy(rec[field])
    return result


def existing_foreign_accrual(records, rows):
    """Prove existing closed foreign values without revaluing them."""
    if not records or any('fx_accrual_source' not in rec or common.is_cny(rec.get('currency')) for rec in records):
        return False
    delivery = BR.cents(records[0].get('deliver_local'))
    if not delivery or any(BR.cents(rec.get('deliver_local')) != delivery for rec in records):
        return False
    values = list(rows.values())
    if not values or any(row['是否结账'] != '是' for row in values):
        return False
    received = sum(BR.cents(row['回款明细']) or 0 for row in values)
    if abs(received - delivery) > BR.SETTLEMENT_CENTS:
        return False
    accrued = [(ref, row) for ref, row in rows.items() if BR.cents(row['计提']) not in (None, 0)]
    if len(accrued) != 1 or (BR.cents(accrued[0][1]['计提']) or 0) <= 0:
        return False
    ref, row = accrued[0]
    if (BR.cents(row['回款明细']) or 0) <= 0:
        return False
    if any(other != ref and BR.cents(value['差异']) not in (None, 0) for other, value in rows.items()):
        return False
    baseline = sum(BR.cents(value['应收金额']) or 0 for value in values)
    difference = baseline - BR.cents(row['计提'])
    return BR.cents(row['差异']) == difference or (difference == 0 and row['差异'] is None)


def prove(records, rows):
    if not records or not rows:
        return None
    if any(r.get('forced_code') or r.get('customer_archive_failed')
           or r.get('parent_allocation_audit') for r in records):
        return None
    records = [source(r) for r in records]
    so, sod = records[0]['so'], records[0]['sod']
    if not so or not sod:
        return None
    if any(r['so'] != so or r['sod'] != sod or sod not in r['all_sods']
           or not r['currency'] or not BR.cents(r['amount_orig'])
           or (common.is_cny(r['currency']) and r['amount_orig'] != r['amount_local'])
           or r['status'] == '已作废'
           for r in records):
        return None
    delivery = BR.cents(records[0]['deliver_local'])
    dates = {r['hexiao_date'] for r in records}
    if not delivery or delivery <= 0 or len(dates) != 1 or None in dates:
        return None
    day = next(iter(dates))
    records.sort(key=lambda r: (BR.cents(r['cumulative_received_local']) or -1, BR.event_key(r)))
    initial = (BR.cents(records[0]['cumulative_received_local']) or 0) - (BR.cents(records[0]['amount_local']) or 0)
    if initial < 0 or len({r['currency'] for r in records}) != 1:
        return None
    total, identities = initial, set()
    for rec in records:
        event, amount = BR.event_key(rec), BR.cents(rec['amount_local'])
        if (not event or event in identities or not amount or amount <= 0
                or not rec['shoukuan_date'] or rec['shoukuan_date'] > day
                or BR.cents(rec['deliver_local']) != delivery):
            return None
        identities.add(event)
        total += amount
        if BR.cents(rec['cumulative_received_local']) != total:
            return None
    if total > delivery + BR.SETTLEMENT_CENTS:
        return None
    rows = {str(ref): BR.normalized(row) for ref, row in rows.items()}
    current, future, unpaid = {}, {}, {}
    existing_fx = existing_foreign_accrual(records, rows)
    tail_rows = []
    for ref, row in rows.items():
        expected, paid = BR.cents(row['应收金额']), BR.cents(row['回款明细'])
        if (row['SO'] != so or row['SOD'] != sod or expected is None or expected <= 0
                or (paid not in (None, 0, expected) and (paid is None or paid <= 0 or abs(paid-expected)>BR.SETTLEMENT_CENTS)) or (BR.cents(row['差异']) not in (None, 0) and not existing_fx)):
            return None
        if not paid:
            if row['是否结账'] != '否' or row['收款时间'] or row['收款方式']:
                return None
            unpaid[ref] = row
        else:
            if (row['是否结账'] != '是' or not row['收款时间']
                    or row['收款方式'] not in ('汇', '冲预收')):
                return None
            (current if row['收款时间'] <= day else future)[ref] = row
            if paid != expected:
                tail_rows.append(ref)
    if sum(BR.cents(r['应收金额']) for r in rows.values()) != delivery:
        return None
    if tail_rows and (len(tail_rows)!=1 or unpaid or future or abs(total-delivery)>BR.SETTLEMENT_CENTS or sum(BR.cents(r['回款明细']) for r in current.values())!=total):
        return None
    import current_aggregate_receipts as G
    aggregate = G.bind(records,current,day,initial)
    # SO source history is sufficient for allocation only in a single-SOD scope.
    source_bound = any('current_source_history' in r for r in records) and all(len(r['all_sods']) == 1 for r in records)
    if aggregate is not None:
        bindings, aggregate_groups = aggregate
        used=set(current);missing=[]
    elif source_bound:
        import current_source_matching as M
        matched = M.bind(records, current, day, initial)
        if matched is None:
            return None
        bindings, prior_refs = matched
        used = {ref for refs in bindings.values() for ref in refs}
        missing = [key for key, refs in bindings.items() if not refs]
        if any(BR.cents(row['回款明细']) == BR.cents(rec['amount_local'])
               for row in future.values() for rec in records if BR.event_key(rec) in missing):
            return None
    else:
        # Later rows and unpaid capacity are protected, never assigned to this prefix.
        bindings, used, missing = {}, set(), []
        for rec in records:
            if BR.event_key(rec) in bindings:
                continue
            days = {rec['shoukuan_date'], rec['hexiao_date']}
            candidates = [ref for ref, row in current.items()
                          if BR.cents(row['回款明细']) == BR.cents(rec['amount_local'])
                          and row['收款时间'] in days]
            if not candidates:
                # A differently dated equal amount is not evidence of a missing event.
                if any(BR.cents(r['回款明细']) == BR.cents(rec['amount_local'])
                       for r in list(current.values()) + list(future.values())):
                    return None
                missing.append(BR.event_key(rec))
                bindings[BR.event_key(rec)] = []
                continue
            if any(ref in used for ref in candidates):
                return None
            signature = lambda r: tuple(r[k] for k in ('amount_local','amount_orig','currency','shoukuan_date','hexiao_date','status'))
            equivalent = [r for r in records if signature(r) == signature(rec)]
            if len(candidates) > 1 or len(equivalent) > 1:
                facts = [current[ref] for ref in candidates]
                # Equivalent events may already use either permitted receipt
                # date representation. Preserve every other financial field.
                arrival = common.norm_date(rec['shoukuan_date'])
                posting = common.norm_date(rec['hexiao_date'])
                allowed = {(rec['shoukuan_date'], '汇'),
                           (rec['hexiao_date'], common.pay_way(rec['status'], arrival, posting))}
                comparable = [{k:v for k,v in f.items() if k not in ('收款时间','收款方式')} for f in facts]
                if (len(equivalent) < len(candidates)
                        or any((f['收款时间'],f['收款方式']) not in allowed for f in facts)
                        or any(f != comparable[0] for f in comparable[1:])
                        or any(BR.event_key(r) in bindings for r in equivalent)):
                    return None
                if len(equivalent) > len(candidates):
                    # A partial equivalent group is a count proof only with no
                    # prior-source amount and no competing current/future owner.
                    if initial or any(BR.cents(row['回款明细']) == BR.cents(rec['amount_local']) for row in future.values()):
                        return None
                    if any(signature(other) != signature(rec)
                           and BR.cents(other['amount_local']) == BR.cents(rec['amount_local'])
                           and any(current[ref]['收款时间'] in (other['shoukuan_date'],other['hexiao_date']) for ref in candidates)
                           for other in records):
                        return None
                members = sorted(equivalent, key=BR.event_key)
                for member, ref in zip(members, sorted(candidates, key=int)):
                    bindings[BR.event_key(member)] = [ref]
                    used.add(ref)
                for member in members[len(candidates):]:
                    bindings[BR.event_key(member)] = []
                    missing.append(BR.event_key(member))
            else:
                bindings[BR.event_key(rec)] = candidates
                used.add(candidates[0])
    prior = {ref: row for ref,row in current.items() if ref not in used}
    if (sum(BR.cents(r['回款明细']) for r in prior.values()) != initial
            or any(r['收款时间'] >= day for r in prior.values())):
        return None
    missing_total = sum(BR.cents(r['amount_local']) for r in records if BR.event_key(r) in missing)
    if sum(BR.cents(r['回款明细']) for r in current.values()) + missing_total != total:
        return None
    if missing:
        if len(unpaid) != 1:
            return None
        target = next(iter(unpaid.values()))
        if (target['计提'] is not None or target['差异'] is not None
                or BR.cents(target['应收金额']) + BR.SETTLEMENT_CENTS < missing_total
                or len({r['ar'] for r in records if BR.event_key(r) in missing}) != len(missing)):
            return None
        if abs(BR.cents(target['应收金额']) - missing_total) <= BR.SETTLEMENT_CENTS and (future or any(BR.cents(r['计提']) not in (None, 0) for r in rows.values())):
            return None
    return dict(**({'aggregate_groups':aggregate_groups} if aggregate is not None else {}), policy_version=POLICY, records=records, before_rows=rows,
                missing_events=missing, protected_prior_rows=sorted(prior),
                event_rows=bindings, protected_future_rows=sorted(future),
                unpaid_rows=sorted(unpaid), source_sha256=digest(records),
                material_rows_sha256=digest(rows))


def prepare(records, ledger):
    if ledger is None:
        return {}
    groups = defaultdict(list)
    for rec in records:
        groups[(rec.get('so'), rec.get('sod'))].append(rec)
    result = {}
    for (so, sod), members in groups.items():
        if not so or not sod:
            continue
        try:
            proof = prove(members, BR.ledger_rows(ledger, so, sod))
            if proof is None:
                import current_baseline_receipts as B
                proof = B.prove(members, BR.ledger_rows(ledger, so, sod))
            if proof is None:
                import current_workbook_existing as E
                proof = E.prove(members, BR.ledger_rows(ledger, so, sod))
            if proof is None:
                import current_date_correction as D
                proof = D.prove(members, BR.ledger_rows(ledger, so, sod))
        except (KeyError, TypeError, ValueError):
            proof = None
        if proof:
            for event in proof['event_rows']:
                result[event] = proof
    # A multi-SOD action must carry the whole current SO snapshot so that
    # the accrual gate can be independently reconstructed by the validator.
    aliases = dict(zip(BR.FIELDS, ('so','sod','yingshou','jiti','huikuan','jiezhang','shoukuan_time','shoukuan_way','chayi')))
    for so in {r.get('so') for r in records}:
        members=[r for r in records if r.get('so')==so]
        if not any(len(r.get('all_sods') or [])>1 for r in members):continue
        if any(BR.event_key(r) not in result for r in members):
            for r in members:
                proof=result.get(BR.event_key(r))
                if proof and proof['missing_events']:
                    result.pop(BR.event_key(r),None)
            continue
        unique={result[BR.event_key(r)]['source_sha256']:result[BR.event_key(r)] for r in members}
        before={str(ref):BR.normalized({k:ledger.row_snapshot[ref].get(alias) for k,alias in aliases.items()})
                for ref in ledger.so_index.get(so,[])}
        scope=dict(so=so,rows=before,groups=copy.deepcopy(list(unique.values())))
        for r in members:
            event=BR.event_key(r)
            result[event]={**result[event], 'so_scope':scope}
    return result


def action(proof, event):
    if proof.get('so_scope'):
        import current_workbook_accrual as A
        projected=A.project(proof['so_scope'])[event]
        keys=('ledger_row_ref','five_cols','row_operation','split_chain_group_id','split_chain_index',
              'so_accrual_backfills','derived_cols','baseline_receipt_audit','split_chain_count','fx_accrual_applied')
        return {k:copy.deepcopy(projected[k]) for k in keys if k in projected}
    if proof.get('baseline_layout'):
        import current_baseline_receipts as B
        return B.action(proof, event)
    rec = next(r for r in proof['records'] if BR.event_key(r) == event)
    refs = proof['event_rows'][event]
    if refs:
        ref = refs[0]
        corrected=(proof.get('date_corrections') or {}).get(event) or {}
        return dict(ledger_row_ref=int(ref),
                    five_cols={**{k: proof['before_rows'][ref][k] for k in FIVE}, **corrected.get('after',{}), '实收SOD': rec['sod']})
    ref = proof['unpaid_rows'][0]
    before = proof['before_rows'][ref]
    pending = sorted((r for r in proof['records'] if BR.event_key(r) in proof['missing_events']),
                     key=lambda r: r['writeoff_sequence_key'])
    source_amount = BR.cents(before['应收金额'])
    delivery = BR.cents(rec['deliver_local'])
    initial = delivery - source_amount
    remaining = source_amount
    steps = []
    baseline = sum(BR.cents(row['应收金额']) or 0 for row in proof['before_rows'].values())
    for index, member in enumerate(pending):
        amount = BR.cents(member['amount_local'])
        before_amount = remaining
        remaining -= amount
        settled = index == len(pending)-1 and abs(remaining) <= BR.SETTLEMENT_CENTS
        arrival = common.norm_date(member['shoukuan_date'])
        posting = common.norm_date(member['hexiao_date'])
        accrual = accrual_amount(member, delivery/100) if settled else None
        five = {'计提': accrual, '回款明细': amount/100, '是否结账': '是',
                '收款时间': common.receipt_time(arrival, posting).isoformat(),
                '收款方式': common.pay_way(member['status'] or '', arrival, posting),
                '实收SOD': member['sod']}
        derived = {'差异': (baseline-BR.cents(accrual))/100} if settled and BR.cents(accrual) != delivery else {}
        steps.append(dict(index=index, case_id='|'.join(member[k] for k in ('ar','so','sod')),
                          ar=member['ar'], so=member['so'], sod=member['sod'],
                          writeoff_sequence_key=member['writeoff_sequence_key'], sequence_basis='writeoff_record',
                          current_received=amount/100, cumulative_received=(delivery-remaining)/100,
                          receivable=(before_amount if settled else amount)/100, remaining_after=remaining/100, settled=settled,
                          five_cols=five, derived_cols=derived))
    index = next(i for i, r in enumerate(pending) if BR.event_key(r) == event)
    result = dict(ledger_row_ref=int(ref), five_cols=steps[index]['five_cols'])
    if steps[index]['derived_cols']:
        result['derived_cols'] = steps[index]['derived_cols']
    if steps[index]['five_cols']['计提'] is not None and rec.get('fx_accrual_source'):
        result['fx_accrual_applied'] = True
    blank = {'计提':None,'回款明细':None,'是否结账':'否','收款时间':None,'收款方式':None,'实收SOD':rec['sod']}
    if len(steps) == 1 and steps[-1]['settled']:
        return result
    if len(steps) == 1:
        result['row_operation'] = dict(type='split_below', source_receivable=source_amount/100,
            paid_receivable=steps[0]['receivable'], unpaid_receivable=remaining/100,
            latest_delivery=delivery/100, cumulative_received=(delivery-remaining)/100,
            existing_received=initial/100, current_received=steps[0]['current_received'],
            baseline_receivable=delivery/100, paid_side_receivable_total=(delivery-remaining)/100,
            business_rows=list(map(int, proof['before_rows'])), inserted_five_cols=blank)
    else:
        result.update(split_chain_group_id=POLICY+'|'+proof['source_sha256'], split_chain_index=index,
            row_operation=dict(type='split_payment_chain', source_receivable=source_amount/100,
                initial_cumulative=initial/100, latest_delivery=delivery/100,
                steps=steps, final_unpaid=dict(receivable=remaining/100, five_cols=blank) if not steps[-1]['settled'] else None))
    return result


def apply(rec, result):
    proof = rec.get('_current_workbook_receipts')
    if not proof:
        return None
    event = BR.event_key(rec)
    missing = event in proof['missing_events']
    result.update(bucket='auto', code='E5' if missing or event in (proof.get('date_corrections') or {}) else CODE,
                  reason=('当前表缺少本笔回款，仅从当前未收余额补写，保留其他回款'
                          if missing else '当前来源与表内回款逐笔对应，保留已有登记、后续回款和未收余额，不重复写入'),
                  current_workbook_receipts=copy.deepcopy(proof), current_workbook_event=event,
                  **action(proof, event))
    if event in (proof.get('date_corrections') or {}):
        result['reason'] = '当前来源完整覆盖已登记金额并唯一对应，仅纠正本笔日期或收款方式，保留金额及已有计提'
    if proof.get('read_only_subset'):
        result['reason'] = '本次回款在当前表按金额和日期唯一对应，保留其他已收行，不重复写入'
    if proof.get('aggregate_groups'):
        result['reason'] = '当前表已合并登记本组回款，整组金额及来源范围核验一致，保留原行并跳过'
    rec = next(r for r in proof['records'] if BR.event_key(r) == event)
    delta = BR.cents(rec['deliver_local']) - BR.cents(rec['cumulative_received_local'])
    last_missing = max((r for r in proof['records'] if BR.event_key(r) in proof['missing_events']), key=lambda r: BR.cents(r['cumulative_received_local']), default=None)
    if missing and last_missing is not None and BR.event_key(last_missing) == event and delta and abs(delta) <= BR.SETTLEMENT_CENTS:
        result['settlement_tolerance_audit'] = dict(latest_delivery=rec['deliver_local'],
            cumulative_received=rec['cumulative_received_local'],exact_delta=delta/100,
            business_tolerance=BR.SETTLEMENT_CENTS/100,technical_equal=abs(delta)<=1,business_equal=True)
        result['reason'] += f'；实际累计回款与交付额相差{delta/100:.2f}元，按既有尾差规则结清，实际回款金额不变'
    return result


def check(item, rows):
    proof = item.get('current_workbook_receipts')
    if not proof:
        return None
    def bad(reason):
        return dict(verdict='conflict', reason=reason)
    try:
        current = {str(ref): BR.normalized(row) for ref, row in rows.items()
                   if row.get('SO') == item['so'] and row.get('SOD') == item['sod']}
        unscoped = {k:v for k,v in proof.items() if k != 'so_scope'}
        if rebuild(unscoped, current) != unscoped:
            return bad('当前表回款证明无法重建，材料或来源已变化')
        if proof.get('so_scope'):
            import current_workbook_accrual as A
            if not A.validate(proof['so_scope'],rows):
                return bad('整单当前材料或SOD来源范围发生变化')
        event = item['current_workbook_event']
        rec = next(r for r in proof['records'] if BR.event_key(r) == event)
        s = item.get('split_payment_source') or {}
        if (any(rec[k] != item.get(k) for k in ('ar','so','sod'))
                or rec['writeoff_sequence_key'] != [str(v) for v in s.get('writeoff_sequence_key') or []]
                or BR.cents(s.get('amount_local')) != BR.cents(rec['amount_local'])
                or BR.cents(s.get('cumulative_local')) != BR.cents(rec['cumulative_received_local'])
                or BR.cents(s.get('delivery_local')) != BR.cents(rec['deliver_local'])):
            return bad('当前表跳过证明与计划来源不一致')
        if 'fx_accrual_source' in rec and (s.get('fx_accrual_source') != rec['fx_accrual_source'] or item.get('fx_accrual_source') != rec['fx_accrual_source']):
            return bad('当前表回款证明与计提汇率来源不一致')
        wanted = action(proof, event)
        keys = ('ledger_row_ref','five_cols','row_operation','split_chain_group_id','split_chain_index','split_chain_count','so_accrual_backfills','derived_cols','baseline_receipt_audit','fx_accrual_applied')
        if any((item.get(k) or None) != (wanted.get(k) or None) for k in keys):
            return bad('当前表回款计划包含证明以外的写入指令')
        return dict(verdict='write' if event in proof['missing_events'] or event in (proof.get('date_corrections') or {}) else 'skip',
                    reason='当前来源与当前表逐笔核验，仅补已确认缺失回款')
    except (KeyError, TypeError, ValueError, StopIteration):
        return bad('当前表回款证明字段不完整')


def source_error(item, items):
    proof = item.get('current_workbook_receipts')
    if not proof:
        return ''
    scope = proof.get('so_scope')
    if scope:
        wanted = {key for group in scope['groups'] for key in group['event_rows']}
        peers = [m.get('current_workbook_event') for m in items
                 if (m.get('current_workbook_receipts') or {}).get('so_scope') == scope]
        if set(peers) != wanted or len(peers) != len(wanted):
            return '整单计提证明缺少SOD计划成员或包含重复事件'
    expected = set(proof.get('event_rows') or {})
    members = [m for m in items if m.get('current_workbook_receipts') == proof]
    actual = [m.get('current_workbook_event') for m in members]
    if set(actual) != expected or len(actual) != len(expected):
        return '当前表整组证明缺少来源成员或包含重复事件'
    return ''


def rejection(rec, ledger):
    """Do not repair dates through an old identity path after current proof fails.

    This gate applies to the current supported normal row shape. Changed delivery
    and aggregate receivable layouts still need their dedicated migration.
    """
    if (ledger is None or not rec.get('current_source_history')
            or rec.get('forced_code') or rec.get('customer_archive_failed')
            or rec.get('parent_allocation_audit') or len(rec.get('all_sods') or [])!=1):
        return None
    rows=BR.ledger_rows(ledger,rec.get('so'),rec.get('sod'))
    delivery=BR.cents(rec.get('deliver_local'))
    if not rows or not delivery or sum(BR.cents(r.get('应收金额')) or 0 for r in rows.values())!=delivery:
        return None
    for row in rows.values():
        expected,paid=BR.cents(row.get('应收金额')),BR.cents(row.get('回款明细'))
        if not expected or expected<0 or paid not in (None,0,expected) or BR.cents(row.get('差异')) not in (None,0):
            return None
    history=rec['current_source_history']
    missing=sorted({k for e in history.get('events') or [] for k in e.get('missing_fields') or []})
    detail='；来源缺字段：'+','.join(missing) if missing else ''
    unresolved=history.get('unresolved_parent_ars') or []
    if unresolved:detail+='；来源审计未解决父回款：'+','.join(unresolved)
    paid=[f"第{ref}行 {row['回款明细']:g}元/{row['收款时间'] or '无日期'}" for ref,row in rows.items() if row.get('回款明细')]
    reason=(f"当前来源与当前表未能建立唯一且完整的回款对应：本次{rec.get('amount_local')}元，"
            f"来源累计{rec.get('cumulative_received_local')}元；表内已收："+('、'.join(paid) or '无')+detail+
            '。未重复补写或修改已有日期；候选行及逐笔来源已附在判定证据中。')
    return dict(reason=reason,rows=copy.deepcopy(rows),source=copy.deepcopy(history),
                amount_local=rec.get('amount_local'),cumulative_local=rec.get('cumulative_received_local'))


def rebuild(proof, rows):
    if proof.get('date_corrections'):
        import current_date_correction as module
    elif proof.get('baseline_layout'):
        import current_baseline_receipts as module
    elif proof.get('read_only_subset'):
        import current_workbook_existing as module
    else:
        return prove(proof['records'],rows)
    return module.prove(proof['records'],rows)
