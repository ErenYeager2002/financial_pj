from app.ar_material_rebinding import rebind_missing_baseline_events
import copy


def fixture():
    event={"event_key":"identity", "so":"SO_TEST", "sod":"SOD_TEST", "回款明细":30,
           "收款时间":"2026-09-03", "收款方式":"冲预收", "slot":0}
    ledger={"parents":{}, "baseline_receipts":{"group":{"baseline_receivable":100,
        "receivable_group_scope":{"basis":"so_latest_delivery"}, "events":{"identity":event},
        "ordinary_events":{"earlier":{"signature":[20,"2026-08-01","汇"]}},
        "settled":True,"accrual":50}}}
    difference={"year":2026,"so":"SO_TEST","sod":"SOD_TEST","status":"missing","count":1,
        "expected":{"so":"SO_TEST","sod":"SOD_TEST","amount":"30.00","date":"2026-09-03","method":"冲预收"},
        "current_rows":[{"so":"SO_TEST","sod":"SOD_TEST","amount":"20.00","date":"2026-08-01","method":"汇"}]}
    return ledger,difference


def test_only_absent_published_event_is_unbound_in_new_material():
    ledger,diff=fixture();original=copy.deepcopy(ledger)
    updated,audit=rebind_missing_baseline_events(ledger,[diff])
    group=updated['baseline_receipts']['group']
    assert not group['events'] and group['scope_only'] is True
    assert 'settled' not in group and 'accrual' not in group
    assert group['ordinary_events']==original['baseline_receipts']['group']['ordinary_events']
    assert group['unbound_events']['identity']==original['baseline_receipts']['group']['events']['identity']
    assert len(audit)==1 and ledger==original
    again,records=rebind_missing_baseline_events(updated,[diff])
    assert again==updated and records==[]


def test_conflicts_and_current_matching_receipts_keep_history():
    ledger,diff=fixture()
    for change in [{'status':'conflict'}, {'current_rows':[diff['expected']]}]:
        altered={**diff,**change}
        updated,audit=rebind_missing_baseline_events(ledger,[altered])
        assert updated==ledger and not audit


def test_other_group_and_ambiguous_missing_count_are_preserved():
    ledger,diff=fixture()
    other=copy.deepcopy(ledger);other['baseline_receipts']['group']['events']['second']=copy.deepcopy(other['baseline_receipts']['group']['events']['identity'])
    updated,audit=rebind_missing_baseline_events(other,[diff]);assert updated==other and not audit
    updated,audit=rebind_missing_baseline_events(ledger,[{**diff,'expected':{**diff['expected'],'so':'OTHER'}}]);assert updated==ledger and not audit


def test_inheritance_writes_rebound_copy_and_preserves_registered_bundle(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace as NS
    from app import ar_formal_ledger_service as service, ar_material_history
    from app.models import WorkflowSession
    ledger,diff=fixture();original=copy.deepcopy(ledger)
    scope=dict(owner_id='owner',department_id='department',skill_id='ar-hexiao-daily')
    source=NS(id='source',context_json='{"ar_execution":{}}',**scope)
    source.context_json='{"ar_execution":{"schema_version":"ar-execution-v2"}}'
    import hashlib
    current_path=tmp_path/'selected.xlsx';current_path.write_bytes(b'fixture')
    member=NS(role='profit_loss_ledgers',year=2026,file_id='current',sha256=hashlib.sha256(b'fixture').hexdigest())
    material=NS(id='material',source_workflow_id='source',files=[member],parent_set_id=None,**scope)
    current=NS(stored_path=str(current_path),**scope)
    monkeypatch.setattr(ar_material_history,'receipt_rows',lambda path:diff['current_rows'])
    workflow=NS(material_set=material,reconciliation_date='2026-08-01',**scope)
    ledgers={'父回款顺序分配台账.json':ledger,'跑批台账.json':{'runs':{}}}
    contents={name:json.dumps(value).encode() for name,value in ledgers.items()}
    original_bytes=contents['父回款顺序分配台账.json']
    monkeypatch.setattr(service,'read_formal_ledger_bundle',lambda *args: (
        {'publication':{'files':[vars(member)]},'json_ledgers':ledgers},NS(id='file',sha256='hash'),dict(contents)))
    def verify(*args,differences):
        differences.append(diff)
        return [2026]
    monkeypatch.setattr(ar_material_history,'verify_updated_annual_materials',verify)
    db=NS(get=lambda model,key:source if model==WorkflowSession and key=='source' else current if key=='current' else None)
    result=service.inherit_formal_ledgers(db,workflow,tmp_path)
    actual=json.loads((tmp_path/'03_台账/父回款顺序分配台账.json').read_bytes())
    assert actual['baseline_receipts']['group']['events']=={}
    assert result['history_rebindings']
    assert ledger==original and contents['父回款顺序分配台账.json']==original_bytes


def test_current_material_proof_excludes_unknown_receipts_and_missing_year():
    from app.ar_material_rebinding import differences_from_current_rows
    ledger,diff=fixture()
    assert differences_from_current_rows(ledger,diff['current_rows'])
    assert not differences_from_current_rows(ledger,[])
    assert not differences_from_current_rows(ledger,[{**diff['expected'],'amount':'29.00'}])
    assert not differences_from_current_rows(ledger,[{**diff['expected'],'amount':'0.00'}])
    assert not differences_from_current_rows(ledger,[diff['expected']])
