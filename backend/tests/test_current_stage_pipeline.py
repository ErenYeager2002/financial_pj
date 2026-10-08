"""Opt-in real-export stage pipeline, isolated database and disposable workbooks.

Constructor/source-fetch/worker scheduling are fixture boundaries. All business
CLIs, staging, physical review, reports, publication and completion execute for
real. Invoke with AR_INTEGRATION_SOURCE pointing to a read-only captured day.
"""
import hashlib,json,os,shutil,subprocess,sys,uuid
from datetime import datetime,UTC,timedelta
from pathlib import Path
import pytest
from sqlalchemy.orm import Session
from app import ar_execution_runner as runner,workflow_service as service
from app.models import WorkflowSession,WorkflowAction,FileRecord,WorkflowMaterialSetFile
from app.ar_execution_contract import CONTRACT_VERSION
from test_refactor_event_transactions import database
from test_publication_current_evidence import seed
from test_current_publication_transaction import complete_published_stage


def test_current_business_stages_publish_and_complete(database,tmp_path,monkeypatch):
    source=Path(os.environ.get('AR_INTEGRATION_SOURCE','/missing-integration-source'))
    if not source.is_dir():pytest.skip('read-only captured input not supplied')
    books_source=Path(os.environ['AR_INTEGRATION_BOOKS'])
    inputs={'01_智云导出':source/'01_智云导出','02_我的表副本':books_source}
    root=tmp_path;workspace=root/'work';workspace.mkdir()
    hashes={folder+'/'+p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for folder,directory in inputs.items() for p in directory.glob('*') if p.is_file()}
    for folder,directory in inputs.items():
        shutil.copytree(directory,workspace/folder,ignore=shutil.ignore_patterns('备份'))
    (workspace/'04_产出').mkdir();(workspace/'03_台账').mkdir()
    # Deliberately corrupt audit proves this complete current-policy path never
    # needs it for classification or preflight; the original audit is untouched.
    journal=workspace/'03_台账/父回款顺序分配台账.json';journal.write_text('old audit fixture')
    vendor=Path('/app/skills/ar-hexiao-daily-lab/vendor')
    shutil.copytree(vendor,root/'skill/vendor',ignore=shutil.ignore_patterns('__pycache__'))
    for mod in (runner,service):monkeypatch.setattr(mod,'workflow_root',lambda *_:root)
    monkeypatch.setattr(service,'_workflow_storage_root',lambda *_:root)
    from app import ar_lab_execution
    # Synthetic permission fixture still exercises the lab cache branch.
    monkeypatch.setattr(ar_lab_execution,'AR_LAB_SKILL_ID','synthetic')
    with Session(database) as db:
        seed(db,root);flow=db.get(WorkflowSession,'cancel-workflow')
        flow.state='running';flow.reconciliation_date='2026-08-20'
        action=WorkflowAction(id='d'*32,workflow_id=flow.id,name='ar_classify_receipts',state='running',
            worker_id='test-worker',attempt_count=1,lease_expires_at=datetime.now(UTC)+timedelta(hours=1))
        db.add(action);db.commit()
        book=next((workspace/'02_我的表副本').glob('*盈亏*.xlsx'))
        flowbook=next((workspace/'02_我的表副本').glob('*到账*.xlsx'))
        for key,path in [('annual',book),('receipt',flowbook)]:
            rec=db.get(FileRecord,key);rec.stored_path=str(path);rec.original_name=path.name
            rec.sha256=hashlib.sha256(path.read_bytes()).hexdigest();rec.size_bytes=path.stat().st_size
            db.get(WorkflowMaterialSetFile,key+'-member').sha256=rec.sha256
        obj=object.__new__(runner.ArExecution)
        obj.db,obj.action,obj.workflow,obj.service=db,action,flow,service
        obj.workspace=workspace;obj.date=flow.reconciliation_date;obj.tag='20260820'
        obj.scripts=root/'skill/vendor/scripts';obj.output=workspace/'04_产出'
        obj.ledgers={2026:book};obj.ledger_args=service._annual_ledger_arguments(obj.ledgers)
        obj.execution=dict(schema_version=CONTRACT_VERSION,reconciliation_policy='current-workbook-v1',
            publication='not_published',material_set_id=flow.material_set_id,material_version=1,
            reconciliation_date=obj.date,skill_hash=flow.skill_hash,completed=[],steps={})
        obj.context=dict(workspace=str(workspace),flow_file=str(flowbook),ar_execution=obj.execution)
        flow.context_json=json.dumps(obj.context);db.commit()
        def script(name,arguments,accepted=(0,)):
            name,arguments=ar_lab_execution.cached_command(obj,name,arguments)
            run=subprocess.run([sys.executable,'-B',str(obj.scripts/name),*arguments],cwd=obj.scripts,
                capture_output=True,text=True,timeout=300)
            assert run.returncode in accepted,(name,run.returncode,run.stdout[-1500:],run.stderr[-1500:])
            return run.stdout
        obj.script=script
        script('verify_sources.py',['snapshot','--workspace',str(workspace)])
        phases=('inspect_materials','classify_receipts','review_order_evidence','validate_reconciliation','build_initial_report',
                'stage_reconciliation','write_ledger','write_receipt_flow','verify_reconciliation',
                'rescan_holds','build_final_report','review_final_report')
        for index,phase in enumerate(phases):
            if index:
                action=WorkflowAction(id=uuid.uuid4().hex,workflow_id=flow.id,state='running',
                    worker_id='test-worker',attempt_count=1,lease_expires_at=datetime.now(UTC)+timedelta(hours=1))
                db.add(action)
            action.name='ar_'+phase;obj.action=action;db.flush()
            result=getattr(obj,phase)()
            action.state='succeeded'
            obj.execution['steps'][phase]=result;obj.execution['completed'].append(phase)
            obj.context.update(result);obj.context['ar_execution']=obj.execution
            flow.context_json=json.dumps(obj.context);db.commit()
        assert obj.execution['steps']['verify_reconciliation']['counts']['write']==0
        assert obj.execution['steps']['write_receipt_flow']['flow_written']
        stage,checked=obj.staging()
        assert json.loads(checked.read_text())['business_rules']['reconciliation_policy']=='current-workbook-v1'
        assert journal.read_text()=='old audit fixture'
        action=WorkflowAction(id=uuid.uuid4().hex,workflow_id=flow.id,name='ar_publish_reconciliation',state='running',
            worker_id='test-worker',attempt_count=1,lease_expires_at=datetime.now(UTC)+timedelta(hours=1))
        db.add(action);obj.action=action;db.flush()
        from app.ar_execution_safety import register_effect_intent
        register_effect_intent(obj.context,flow,action,'publish_reconciliation')
        flow.context_json=json.dumps(obj.context);db.commit();db.info.pop('ar_execution_lock',None)
        result=obj.publish_reconciliation()
        obj.execution['steps']['publish_reconciliation']=dict(result)
        obj.execution['completed'].append('publish_reconciliation');obj.execution['publication']='verified'
        result['ar_execution']=obj.execution
        runner.transition_phase(db,action,flow,result);db.commit()
        expected_run=subprocess.run([sys.executable,'-B','-c',
            'import json,sys; from pathlib import Path; import fallback_allocation_ledger as F; p=json.loads(Path(sys.argv[1]).read_text()); print(json.dumps(F.prepare_commit({"version":F.VERSION,"parents":{}},p)[0]["parents"]))',
            str(checked)],cwd=obj.scripts,check=True,capture_output=True,text=True)
        expected_parents=json.loads(expected_run.stdout)
        # Completion resumes the actual runner script/process-evidence boundary.
        del obj.script
        complete_published_stage(db,obj,root,monkeypatch,prepare_synthetic_journals=False,expected_parents=expected_parents)
        assert flow.state=='succeeded'
        from test_current_batch_handoff import assert_published_material_handoff
        assert_published_material_handoff(db,flow,root,monkeypatch)
    assert hashes=={folder+'/'+p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for folder,directory in inputs.items() for p in directory.glob('*') if p.is_file()}
