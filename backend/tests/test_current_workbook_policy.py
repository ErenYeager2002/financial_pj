import json
import pytest
from app.ar_execution_contract import CONTRACT_VERSION,PHASES
from app.ar_snapshot_contract import snapshot_reconciliation_policy,SnapshotCompatibilityError

@pytest.mark.parametrize("value,expected",[(None,"legacy"),("current-workbook-v1","current-workbook-v1"),("future",None)])
def test_policy_is_read_from_fixed_snapshot(tmp_path,value,expected):
    folder=tmp_path/'config';folder.mkdir()
    payload={'schema_version':CONTRACT_VERSION,'phases':[p.name for p in PHASES]}
    if value is not None:payload['reconciliation_policy']=value
    (folder/'execution-pipeline.json').write_text(json.dumps(payload))
    if expected is None:
        with pytest.raises(SnapshotCompatibilityError):snapshot_reconciliation_policy(tmp_path)
    else:assert snapshot_reconciliation_policy(tmp_path)==expected


def test_current_material_ignores_old_parent_but_checks_actual_bytes(tmp_path):
    import hashlib
    from types import SimpleNamespace as NS
    from app.models import FileRecord
    from app.ar_formal_ledger_service import inherit_formal_ledgers
    scope=dict(owner_id='owner',department_id='department',skill_id='ar-hexiao-daily')
    path=tmp_path/'current.xlsx';path.write_bytes(b'current material')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    record=NS(stored_path=str(path),sha256=digest,**scope)
    member=NS(file_id='file',sha256=digest,role='profit_loss_ledgers',year=2026)
    material=NS(id='selected',parent_set_id='missing old parent',source_workflow_id='missing old task',files=[member],**scope)
    workflow=NS(material_set=material,**scope)
    class DB:
        def get(self,model,key):
            assert model is FileRecord and key=='file'
            return record
    result=inherit_formal_ledgers(DB(),workflow,tmp_path,policy='current-workbook-v1')
    assert result['mode']=='current_workbook'
    assert not (tmp_path/'03_台账').exists()
    path.write_bytes(b'tampered')
    with pytest.raises(ValueError,match='实际指纹'):
        inherit_formal_ledgers(DB(),workflow,tmp_path,policy='current-workbook-v1')


def test_batch_rejects_different_reconciliation_policy(tmp_path,monkeypatch):
    from types import SimpleNamespace as NS
    from app import ar_execution_runner as runner
    common=dict(owner_id='owner',department_id='dept',skill_id='ar-hexiao-daily',skill_hash='samehash',execution_mode='workflow',batch_id='batch',context_json='{}')
    first=NS(id='first',batch_sequence=1,**common);later=NS(id='later',batch_sequence=2,**common)
    batch=NS(workflows=[first,later]);first.batch=batch;later.batch=batch
    monkeypatch.setattr(runner,'workflow_root',lambda owner,ident:tmp_path/ident)
    for item,policy in ((first,'current-workbook-v1'),(later,'legacy')):
        folder=tmp_path/item.id/'skill'/'config';folder.mkdir(parents=True)
        (folder/'execution-pipeline.json').write_text(json.dumps({'schema_version':CONTRACT_VERSION,'phases':[p.name for p in PHASES],'reconciliation_policy':policy}))
    with pytest.raises(ValueError,match='策略'):
        runner.execution_version(later)


@pytest.mark.parametrize('skill',['ar-hexiao-daily','ar-hexiao-daily-lab'])
def test_current_snapshot_requires_matching_modules(tmp_path,skill):
    import shutil
    from pathlib import Path
    from app.ar_snapshot_contract import validate_snapshot
    source=Path(__file__).resolve().parents[2]/'skills'/skill
    root=tmp_path/'skill';shutil.copytree(source,root)
    assert validate_snapshot(root)==CONTRACT_VERSION
    (root/'vendor/scripts/current_workbook_receipts.py').unlink()
    with pytest.raises(SnapshotCompatibilityError,match='current_workbook_receipts'):
        validate_snapshot(root)


@pytest.mark.parametrize('skill',['ar-hexiao-daily','ar-hexiao-daily-lab'])
def test_execution_initialization_binds_current_material_without_old_task_lookup(tmp_path,monkeypatch,skill):
    import hashlib,openpyxl
    from types import SimpleNamespace as NS
    from app import ar_execution_runner as runner,workflow_service
    from app.models import FileRecord
    task=tmp_path/'task';config=task/'skill/config';config.mkdir(parents=True)
    (config/'execution-pipeline.json').write_text(json.dumps({'schema_version':CONTRACT_VERSION,'phases':[p.name for p in PHASES],'reconciliation_policy':'current-workbook-v1'}))
    business=task/'business';folder=business/'02_我的表副本';folder.mkdir(parents=True)
    book=folder/'2026年盈亏.xlsx';flow=folder/'到账.xlsx'
    wb=openpyxl.Workbook();wb.save(book);wb.save(flow);wb.close()
    scope=dict(owner_id='owner',department_id='dept',skill_id=skill)
    records={};members=[]
    for ident,path,role,year in [('ledger',book,'profit_loss_ledgers',2026),('flow',flow,'receipt_flow',None)]:
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        records[ident]=NS(stored_path=str(path),sha256=digest,**scope)
        members.append(NS(file_id=ident,sha256=digest,role=role,year=year))
    material=NS(id='selected',version=7,files=members,parent_set_id='unavailable-old-material',source_workflow_id='unavailable-old-workflow',**scope)
    workflow=NS(id='task',batch_id=None,context_json=json.dumps({'fetched_data':{'review_status':'confirmed'}}),material_set=material,skill_hash='a'*64,reconciliation_date='2026-08-25',**scope)
    class DB:
        def get(self,model,key):
            assert model is FileRecord, 'must not query old tasks or parent material'
            return records[key]
    monkeypatch.setattr(runner,'workflow_root',lambda owner,ident:task)
    monkeypatch.setattr(workflow_service,'workflow_owner_context',lambda db,workflow:None)
    initialized=runner.initialize_execution(DB(),workflow,business,{2026:book},flow)
    assert initialized['inherited_formal_ledgers']['mode']=='current_workbook'
    assert len(initialized['inherited_formal_ledgers']['verified_files'])==2
    assert initialized['ar_execution']['reconciliation_policy']=='current-workbook-v1'
    assert initialized['ar_execution']['material_set_id']=='selected'
    assert initialized['ar_execution']['publication']=='not_published'
    assert not (business/'03_台账').exists()
    workflow.context_json=json.dumps(initialized)
    assert runner.execution_version(workflow)==CONTRACT_VERSION
    with pytest.raises(ValueError,match='不能覆盖'):
        runner.initialize_execution(DB(),workflow,business,{2026:book},flow)
    workflow.context_json=json.dumps({'ar_execution':{**initialized['ar_execution'],'reconciliation_policy':'legacy'}})
    with pytest.raises(ValueError,match='策略'):runner.execution_version(workflow)
    workflow.context_json=json.dumps({'fetched_data':{'review_status':'confirmed'}})
    flow.write_bytes(flow.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='实际指纹'):
        runner.initialize_execution(DB(),workflow,business,{2026:book},flow)
