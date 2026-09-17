"""Read-only compatibility review for pinned pre-fix receipt-history plans."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

OLD_HASH = 'c4585c5bf7b99444f91172fce0caed1aca69902aae60082c9e6ad2aa2708265e'
NEW_HASH = '6393c88003b6d7c2577b51a8cc08e7010c0075625192806c050ea62c47e3833c'

def digest(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    for name in ('pinned','current','plan'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--ledger',action='append',nargs=2,default=[])
    parser.add_argument('--materialize',action='store_true')
    parser.add_argument('--expected-fingerprint')
    parser.add_argument('--resolved-id',action='append',default=[])
    args=parser.parse_args()
    pinned,current=Path(args.pinned),Path(args.current)
    if digest(pinned/'receipt_history.py')!=OLD_HASH or digest(current/'receipt_history.py')!=NEW_HASH:
        raise ValueError('历史计提兼容复核不适用于当前代码版本')
    sys.path.insert(0,str(current))
    import validate_plan as V
    import receipt_history as H
    plan_path=Path(args.plan)
    original=plan_path.with_name(plan_path.name+'.before-compatibility')
    raw=(original if args.materialize and original.exists() else plan_path).read_bytes()
    if args.materialize and hashlib.sha256(raw).hexdigest()!=args.expected_fingerprint:
        raise ValueError('报告复核来源与已通过的检查点指纹不同')
    plan=json.loads(raw)
    ledgers={int(year):Path(path) for year,path in args.ledger}
    rows={}
    resolved=[]
    for item in plan.get('conflict',[]):
        if ((item.get('receipt_correction') or {}).get('history_mode')!=H.MODE
                or (item.get('so_accrual_audit') or {}).get('all_settled') is not False
                or (item.get('_check') or {}).get('reason')!='历史回款方案不能由原值和取数依据重建'):
            continue
        year=int(item.get('ledger_year') or item.get('target_ledger_year'))
        if year not in rows:rows[year]=V.read_ledger_rows(ledgers[year])
        verdict=V.check_one(item,rows[year])
        if verdict['verdict']!='skip':
            raise ValueError('历史计提兼容复核未能证明已写结果一致：'+verdict['reason'])
        resolved.append(item['case_id'])
    if args.materialize:
        if set(resolved)!=set(args.resolved_id):
            raise ValueError('报告复核结论与已通过的检查点不同')
        corrected=[]
        for item in plan.get('conflict',[]):
            if item['case_id'] in resolved:
                item['_check']={'verdict':'skip','reason':'历史回款及SO计提延后规则复核一致，已写入并幂等跳过'}
                corrected.append(item)
        plan['conflict']=[item for item in plan.get('conflict',[]) if item['case_id'] not in resolved]
        plan.setdefault('skip',[]).extend(corrected)
        plan['counts']={k:len(plan.get(k,[])) for k in ('write','skip','conflict')}
        plan['compatibility_review']={'schema_version':'deferred-history-review-v1',
                                      'original_sha256':args.expected_fingerprint,
                                      'checker_hash':NEW_HASH,'resolved_case_ids':resolved}
        payload=json.dumps(plan,ensure_ascii=False,indent=2).encode()
        if original.exists():
            if plan_path.read_bytes()!=payload:raise ValueError('已保存的兼容复核文件发生变化')
        else:
            original.write_bytes(raw)
            temp=plan_path.with_name(plan_path.name+'.compatibility-new')
            temp.write_bytes(payload);temp.replace(plan_path)
    print(json.dumps({'schema_version':'deferred-history-review-v1','pinned_hash':OLD_HASH,
                      'checker_hash':NEW_HASH,'resolved_case_ids':resolved},ensure_ascii=False))

if __name__=='__main__':main()
