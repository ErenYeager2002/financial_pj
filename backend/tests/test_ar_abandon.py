"""Targeted abandonment gates and actual SQLite disposition transaction."""
from dataclasses import replace
import hashlib
import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import FileRecord, WorkflowAction, WorkflowBatch, WorkflowMaterialSet, WorkflowMaterialSetFile, WorkflowSession
from app.auth import UserContext
from app import ar_abandon as subject
from app.ar_execution_contract import CONTRACT_VERSION
from app.ar_execution_safety import _has_unresolved_effect, current_material_blocker
from app.ar_execution_recovery import recovery_status
from app.ar_material_lifecycle import visible_material_set, _finished


class AbandonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.actor = UserContext('owner', 'Test', 'finance_user', 'finance')
        self.batch = WorkflowBatch(id='batch', owner_id='owner', department_id='finance', skill_id='ar-hexiao-daily-lab', skill_name='AR', skill_version='1', model_connection_id='m', model_provider='p', model_name='m', state='failed')
        self.db.add(self.batch)
        def workflow(identity, state, sequence):
            return WorkflowSession(id=identity, owner_id='owner', department_id='finance', skill_id='ar-hexiao-daily-lab', skill_name='AR', skill_version='1', skill_hash='a'*64, model_connection_id='m', model_provider='p', model_name='m', state=state, stage=state, reconciliation_date='2026-08-30', batch=self.batch, batch_sequence=sequence)
        self.previous = workflow('previous', 'succeeded', 1)
        self.workflow = workflow('failed', 'failed', 2)
        self.next = workflow('next', 'queued', 3)
        self.db.add_all([self.previous, self.workflow, self.next])
        self.material = WorkflowMaterialSet(id='material', owner_id='owner', department_id='finance', skill_id='ar-hexiao-daily-lab', version=344, state='current', source_workflow_id='previous')
        self.db.add(self.material)
        self.workflow.material_set_id='material'
        self.workspace=self.root/'business';self.workspace.mkdir()
        from app.workflow_service import WRITE_STAGING_DIR
        self.stage=self.workspace/WRITE_STAGING_DIR/'stage';self.stage.mkdir(parents=True)
        raw=b'baseline-workbook';sha=hashlib.sha256(raw).hexdigest()
        p=self.root/'original.xlsx';p.write_bytes(raw)
        self.db.add(FileRecord(id='file',owner_id='owner',department_id='finance',original_name='book.xlsx',stored_path=str(p),size_bytes=len(raw),sha256=sha,skill_id='ar-hexiao-daily-lab'))
        self.db.add(WorkflowMaterialSetFile(id='member',material_set=self.material,role='profit_loss_ledgers',year=2026,file_id='file',sha256=sha))
        (self.workspace/'book.xlsx').write_bytes(raw)
        (self.stage/'book.xlsx').write_bytes(b'staged-result')
        manifest={'workflow_id':'failed','material_set_id':'material','files':{'book.xlsx':sha}}
        (self.stage/'execution-manifest.json').write_text(json.dumps(manifest))
        self.action=WorkflowAction(id='write',workflow=self.workflow,name='ar_write_ledger',state='succeeded',attempt_count=1,finished_at=datetime.now(UTC),result_json='{}')
        self.failed=WorkflowAction(id='review',workflow=self.workflow,name='ar_verify_reconciliation',state='failed',attempt_count=1,finished_at=datetime.now(UTC))
        self.db.add_all([self.action,self.failed])
        self.context={'workspace':str(self.workspace),'ar_execution':{'schema_version':CONTRACT_VERSION,'publication':'not_published','material_set_id':'material','material_version':344,'reconciliation_date':self.workflow.reconciliation_date,'skill_hash':self.workflow.skill_hash,'completed':['stage_reconciliation','write_ledger'],'steps':{'stage_reconciliation':{'staging_workspace':str(self.stage),'manifest':manifest}}},'ar_failure':{'action_id':'review'}}
        self.save()
        self.stack.enter_context(patch('app.workflow_service._workflow_storage_root',return_value=self.root))
        self.stack.enter_context(patch('app.workflow_service._controlled_context_workspace',return_value=self.workspace))
        from app.settings import settings
        self.stack.enter_context(patch('app.settings.settings',replace(settings,data_dir=self.root)))
        self.process=self.stack.enter_context(patch('app.ar_process_inspection.inspect_process_evidence',return_value={'verified':True,'total':1,'exited':1,'unconfirmed':0,'descendant_domains_verified':1,'process_evidence_scope':'linux_descendant_tree','fingerprint':'f'*64}))
        for name in ('assert_skill_permission','workflow_owner_context','_assert_single_flight_available','record_audit'):
            self.stack.enter_context(patch('app.workflow_service.'+name))
        self.stack.enter_context(patch('app.workflow_service.refresh_active_user',side_effect=lambda db,user:user))
        self.stack.enter_context(patch('app.scheduler.acquire_claim_lock'))

    def save(self):
        self.workflow.context_json=json.dumps(self.context);self.db.commit()

    def status(self):
        return subject.abandonment_status(self.db,self.workflow)

    def test_disposition_preserves_material_and_completed_dates_and_blocks_old_recovery(self):
        self.assertTrue(_has_unresolved_effect(self.workflow))
        self.assertEqual(current_material_blocker(self.db,'owner','finance','ar-hexiao-daily-lab')['reason'],'unresolved_write')
        state=self.status();self.assertTrue(state['allowed'],state)
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        subject.abandon(self.db,self.workflow,subject.AbandonRequest(checkpoint_fingerprint=state['checkpoint_fingerprint']),self.actor)
        self.assertTrue(subject.is_abandoned(self.workflow))
        self.assertIsNone(current_material_blocker(self.db,'owner','finance','ar-hexiao-daily-lab'))
        self.assertEqual(self.previous.state,'succeeded')
        self.assertEqual(self.next.state,'cancelled')
        self.assertEqual(self.batch.state,'cancelled')
        self.assertEqual(self.workflow.state,'failed')
        self.assertEqual(self.material.version,344)
        self.assertEqual(visible_material_set(self.db,'owner','finance','ar-hexiao-daily-lab').id,'material')
        self.assertFalse(_finished(self.db,self.material))
        self.assertFalse(recovery_status(self.workflow)['allowed'])
        with self.assertRaises(ValueError):subject.require_not_abandoned(self.workflow)
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertTrue(subject.abandon(self.db,self.workflow,subject.AbandonRequest(checkpoint_fingerprint=state['checkpoint_fingerprint']),self.actor)['abandoned'])

    def test_stale_fingerprint_does_not_unlock(self):
        state=self.status();(self.stage/'book.xlsx').write_bytes(b'changed')
        with self.assertRaises(HTTPException):subject.abandon(self.db,self.workflow,subject.AbandonRequest(checkpoint_fingerprint=state['checkpoint_fingerprint']),self.actor)
        self.assertTrue(_has_unresolved_effect(self.workflow));self.assertEqual(self.next.state,'queued')

    def test_cross_owner_rejected(self):
        state=self.status()
        with self.assertRaises(HTTPException) as caught:
            subject.abandon(self.db,self.workflow,subject.AbandonRequest(checkpoint_fingerprint=state['checkpoint_fingerprint']),UserContext('other','Other','finance_user','finance'))
        self.assertEqual(caught.exception.status_code,404)
        self.assertFalse(subject.is_abandoned(self.workflow))

    def test_unconfirmed_process_rejected(self):
        self.process.return_value={'verified':False,'total':1,'fingerprint':'f'*64}
        self.assertFalse(self.status()['allowed'])

    def test_publication_attempt_rejected_even_without_publication_flag(self):
        self.db.add(WorkflowAction(id='publish',workflow=self.workflow,name='ar_publish_reconciliation',state='failed',attempt_count=1))
        self.db.commit();self.assertFalse(self.status()['allowed'])

    def test_published_or_unknown_or_running_rejected(self):
        for publication in ('verified','unknown',''):
            self.context['ar_execution']['publication']=publication;self.save();self.assertFalse(self.status()['allowed'])
        self.context['ar_execution']['publication']='not_published';self.save()
        self.action.state='running';self.db.commit();self.assertFalse(self.status()['allowed'])

    def test_original_file_change_rejected(self):
        (self.root/'original.xlsx').write_bytes(b'changed');self.assertFalse(self.status()['allowed'])

    def test_baseline_copy_change_rejected(self):
        (self.workspace/'book.xlsx').write_bytes(b'changed');self.assertFalse(self.status()['allowed'])

    def test_staging_symlink_rejected(self):
        (self.stage/'link').symlink_to(self.root/'original.xlsx');self.assertFalse(self.status()['allowed'])

    def test_changed_current_material_rejected(self):
        self.material.state='superseded';self.db.commit();self.assertFalse(self.status()['allowed'])

    def test_marker_with_wrong_binding_cannot_unlock(self):
        self.context[subject.KEY]={'schema_version':'ar-abandonment-v1','state':'abandoned','binding':'bad'};self.save()
        self.assertFalse(subject.is_abandoned(self.workflow));self.assertTrue(_has_unresolved_effect(self.workflow))

    def test_later_day_with_started_work_is_not_cancelled(self):
        self.next.state='running';self.db.commit();self.assertFalse(self.status()['allowed'])

if __name__=='__main__':unittest.main()
