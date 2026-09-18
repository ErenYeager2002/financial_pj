"""Legacy staged-write orchestration baseline; synthetic script failure injection."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
from openpyxl import load_workbook
from app import workflow_service as service


def test_postwrite_verify_failure_never_archives_and_preserves_sources(tmp_path, monkeypatch):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/refactor'))
    from synthetic_inputs import create
    from verify_isolation import verify
    import os
    # backend conftest creates its data dir underneath the already guarded root.
    verify()
    root=tmp_path/'workflow';root.mkdir()
    workspace=root/'work';manifest=create(workspace,os.environ)
    checked=workspace/'04_产出'/'checked.json';checked.parent.mkdir();checked.write_text('{}')
    originals={name:(workspace/name).read_bytes() for name in [*manifest['ledger_years'].values(),'flow.xlsx']}
    workflow=SimpleNamespace(id='synthetic-workflow',owner_id='synthetic-owner',context_json='{}',batch_id=None)
    action=SimpleNamespace(id='synthetic-action',input_json=json.dumps({'context':{'workspace':str(workspace),'checked_plan':str(checked),'ledger_years':{year:str(workspace/name) for year,name in manifest['ledger_years'].items()},'flow_file':str(workspace/'flow.xlsx')}}))
    monkeypatch.setattr(service,'workflow_root',lambda *args:root)
    monkeypatch.setattr(service,'_workflow_storage_root',lambda *args:root)
    monkeypatch.setattr(service,'_set_progress_step',lambda *args:None)
    state={'wrote':False,'verified_after_write':False,'archives':0}
    def fake_script(_directory,script,arguments,**kwargs):
        if script=='apply_all.py':
            for i,value in enumerate(arguments):
                if value=='--ledger-year':
                    target=Path(arguments[i+1].split('=',1)[1])
                    assert target.is_relative_to(workspace/'03_写入暂存区')
                    wb=load_workbook(target);wb['明细']['H2']=100;wb.save(target);wb.close()
            state['wrote']=True
        if script=='verify_sources.py' and arguments[0]=='verify' and state['wrote']:
            state['verified_after_write']=True
            raise RuntimeError('synthetic post-write readback failure')
        return ''
    def forbidden_archive(*args,**kwargs):
        state['archives']+=1
        raise AssertionError('Unverified result must not be archived')
    monkeypatch.setattr(service,'_run_script',fake_script)
    monkeypatch.setattr(service,'_register_artifact',forbidden_archive)
    with pytest.raises(service.StagedWriteError) as error:
        service._apply_confirmed(SimpleNamespace(),action,workflow)
    assert str(error.value.__cause__)=='synthetic post-write readback failure'
    assert state=={'wrote':True,'verified_after_write':True,'archives':0}
    assert all((workspace/name).read_bytes()==raw for name,raw in originals.items())
    assert not (workspace/'03_写入暂存区'/action.id).exists()
