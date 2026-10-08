"""Actual batch advance and next-day input copy against isolated material records."""
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import workflow_service as service
from app.models import WorkflowBatch, WorkflowSession, WorkflowAction, FileRecord
from test_refactor_event_transactions import database
from test_publication_current_evidence import seed


def assert_published_material_handoff(db, flow, root, monkeypatch):
    """Called after real publication/completion as well as a small DB fixture."""
    class SettingsProxy:
        workflow_dir = root
        def __getattr__(self, key): return getattr(original_settings, key)
    original_settings = service.settings
    monkeypatch.setattr(service, 'settings', SettingsProxy())
    fields = {key: getattr(flow, key) for key in (
        'owner_id', 'department_id', 'skill_id', 'skill_name', 'skill_version',
        'execution_mode', 'model_connection_id', 'model_provider', 'model_name')}
    batch = WorkflowBatch(id='handoff-batch', **fields, state='running',
                          material_set_id=flow.material_set_id)
    db.add(batch); db.flush()
    flow.batch_id=batch.id; flow.batch_sequence=1
    published=flow.material_set_id
    expected=service._authoritative_material_bindings(db, flow)
    original_dates=[]
    for offset in (1,2):
        day=(date.fromisoformat(flow.reconciliation_date)+timedelta(days=offset)).isoformat()
        original_dates.append(day)
        db.add(WorkflowSession(id=f'handoff-day-{offset+1}', **fields,
            skill_hash=flow.skill_hash, batch_id=batch.id, batch_sequence=offset+1,
            reconciliation_date=day, material_set_id=None, state='queued',
            files_json=json.dumps({'obsolete': [{'file_id': 'must-not-use'}]}),
            context_json=json.dumps({'workspace':'obsolete-workspace','workspace_state':'obsolete'})))
    db.commit(); db.expire_all()
    flow=db.get(WorkflowSession,flow.id)
    # A stale next_files field must never override the authoritative published set.
    service._advance_batch(db,flow,{'material_set_id':published,'next_files':{'obsolete':[]}})
    db.commit(); db.expire_all()
    child=db.get(WorkflowSession,'handoff-day-2')
    later=db.get(WorkflowSession,'handoff-day-3')
    assert child.material_set_id==published==db.get(WorkflowBatch,batch.id).material_set_id
    assert json.loads(child.files_json)==expected
    assert child.reconciliation_date==original_dates[0] and later.reconciliation_date==original_dates[1]
    assert child.state=='running' and later.state=='queued' and later.material_set_id is None
    assert 'workspace' not in json.loads(child.context_json)
    actions=list(db.scalars(select(WorkflowAction).where(WorkflowAction.workflow_id==child.id)))
    assert len(actions)==1 and actions[0].name=='prepare_workspace' and actions[0].state=='queued'
    assert json.loads(actions[0].input_json)['reconciliation_date']==original_dates[0]
    assert not list(db.scalars(select(WorkflowAction).where(WorkflowAction.workflow_id==later.id)))
    copied=service._copy_inputs(db,actions[0],child,root/'next-day-work')
    for role,entries in expected.items():
        hashes=sorted(db.get(FileRecord,item['file_id']).sha256 for item in entries)
        assert sorted(hashlib.sha256(p.read_bytes()).hexdigest() for p in copied[role])==hashes
    return child, actions[0]


def test_batch_next_day_uses_authoritative_material_bytes(database,tmp_path,monkeypatch):
    with Session(database) as db:
        seed(db,tmp_path)
        flow=db.get(WorkflowSession,'cancel-workflow');flow.state='succeeded';db.commit()
        child,action=assert_published_material_handoff(db,flow,tmp_path,monkeypatch)
        # Re-reading the handed-off files still verifies bytes at the copy boundary.
        path=Path(db.get(FileRecord,'annual').stored_path)
        path.write_bytes(b'tampered after handoff')
        import pytest
        with pytest.raises(RuntimeError,match='完整性'):
            service._copy_inputs(db,action,child,tmp_path/'rejected-copy')
