"""A published AR date stays occupied until its formal ledger is registered."""

import json
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ar_execution_safety import current_material_blocker
from app.models import (Base, FileRecord, WorkflowAction, WorkflowBatch,
                        WorkflowMaterialSet, WorkflowMaterialSetFile, WorkflowSession)
from app.workflow_service import queue_pi_harness_tool, retry_workflow_batch


class PostPublishOccupancyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        prior = WorkflowMaterialSet(id='prior', owner_id='owner', department_id='finance',
            skill_id='ar-hexiao-daily-lab', version=1, source_workflow_id='', state='superseded')
        current = WorkflowMaterialSet(id='published', owner_id='owner', department_id='finance',
            skill_id='ar-hexiao-daily-lab', version=2, source_workflow_id='unfinished',
            parent_set_id='prior', state='current')
        self.db.add_all([prior, current,
            FileRecord(id='prior-file', owner_id='owner', department_id='finance', kind='input',
                original_name='prior.xlsx', stored_path='/controlled/prior.xlsx', size_bytes=1, sha256='a'*64),
            FileRecord(id='published-file', owner_id='owner', department_id='finance', kind='input',
                original_name='published.xlsx', stored_path='/controlled/published.xlsx', size_bytes=1, sha256='b'*64),
            WorkflowMaterialSetFile(id='prior-member', material_set=prior, role='receipt_flow_table',
                year=0, file_id='prior-file', sha256='a'*64),
            WorkflowMaterialSetFile(id='published-member', material_set=current, role='receipt_flow_table',
                year=0, file_id='published-file', sha256='b'*64)])
        self.workflow = WorkflowSession(id='unfinished', display_id='AR-Test', owner_id='owner',
            owner_name='Tester', department_id='finance', skill_id='ar-hexiao-daily-lab',
            skill_name='AR', skill_version='1', execution_mode='workflow', skill_hash='hash',
            model_connection_id='', model_provider='', model_name='', state='failed', stage='failed',
            reconciliation_date='2026-08-30', material_set_id=current.id,
            context_json=json.dumps({'ar_execution': {'material_set_id': prior.id,
                'material_version': 1, 'publication': 'verified',
                'completed': ['write_ledger', 'write_receipt_flow', 'publish_reconciliation'],
                'steps': {'publish_reconciliation': {'material_set_id': current.id,
                                                      'material_version': 2}}}}))
        self.db.add(self.workflow)
        self.db.commit()

    def blocker(self):
        return current_material_blocker(self.db, 'owner', 'finance', 'ar-hexiao-daily-lab')

    def test_published_workbooks_without_formal_ledger_still_block(self):
        self.assertEqual(self.blocker()['workflow_id'], self.workflow.id)

    def test_formal_registration_releases_published_material(self):
        context = json.loads(self.workflow.context_json)
        context['formal_ledgers'] = {'file_id': 'formal', 'sha256': 'c'*64}
        context['ar_execution']['completed'].append('complete_reconciliation')
        self.workflow.context_json = json.dumps(context)
        self.workflow.state = 'succeeded'
        self.db.commit()
        self.assertIsNone(self.blocker())

    def test_unrelated_owner_is_not_blocked(self):
        self.assertIsNone(current_material_blocker(self.db, 'another', 'finance',
                                                   'ar-hexiao-daily-lab'))


    def _queue_pi_completion(self):
        self.workflow.execution_mode = 'pi_harness'
        self.workflow.state = 'running'
        self.db.commit()
        actor = SimpleNamespace(user_id='owner', department_id='finance')
        lease = SimpleNamespace(queued_at=datetime.now(UTC))
        with patch('app.workflow_service.acquire_claim_lock'), \
             patch('app.workflow_service.workflow_owner_context', return_value=actor), \
             patch('app.workflow_service.assert_skill_permission'), \
             patch('app.pi_harness_lease.require_harness_lease', return_value=lease), \
             patch('app.ar_execution_runner.queue_execution_phase', return_value='queued'):
            return queue_pi_harness_tool(self.db, self.workflow, 'complete_reconciliation', {},
                                         harness_action_id='agent', worker_id='worker', attempt=1)

    def test_pi_completion_can_pass_its_own_publication_occupancy(self):
        self.assertEqual(self._queue_pi_completion(), 'queued')

    def test_pi_completion_still_blocks_another_unresolved_workflow(self):
        other = WorkflowSession(id='other', display_id='AR-Other', owner_id='owner',
            owner_name='Tester', department_id='finance', skill_id='ar-hexiao-daily-lab',
            skill_name='AR', skill_version='1', execution_mode='workflow', skill_hash='hash',
            model_connection_id='', model_provider='', model_name='', state='failed', stage='failed',
            reconciliation_date='2026-08-31', material_set_id='published',
            context_json=json.dumps({'ar_execution': {'material_set_id': 'published',
                'material_version': 2, 'publication': 'verified',
                'completed': ['write_ledger', 'publish_reconciliation']}}))
        self.db.add(other)
        self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            self._queue_pi_completion()
        self.assertEqual(caught.exception.status_code, 409)


    def test_batch_retry_rejects_another_workflow_unresolved_on_current_material(self):
        batch = WorkflowBatch(id='retry-batch', owner_id='owner', owner_name='Tester',
            department_id='finance', skill_id='ar-hexiao-daily-lab', skill_name='AR',
            skill_version='1', execution_mode='workflow', model_connection_id='',
            model_provider='', model_name='', state='failed', material_set_id='published')
        child = WorkflowSession(id='retry-child', display_id='AR-Retry', owner_id='owner',
            owner_name='Tester', department_id='finance', skill_id='ar-hexiao-daily-lab',
            skill_name='AR', skill_version='1', execution_mode='workflow', skill_hash='hash',
            model_connection_id='', model_provider='', model_name='', state='failed', stage='failed',
            reconciliation_date='2026-09-01', batch=batch, batch_sequence=1,
            material_set_id='published')
        action = WorkflowAction(id='failed-prewrite', workflow=child,
                                name='prepare_workspace', state='failed', finished_at=datetime.now(UTC))
        self.db.add_all([batch, child, action])
        self.db.commit()
        actor = SimpleNamespace(user_id='owner', department_id='finance', is_admin=False)
        with patch('app.workflow_service.acquire_claim_lock'), \
             patch('app.workflow_service.execution_actor', return_value=actor), \
             patch('app.workflow_service.workflow_owner_context', return_value=actor), \
             patch('app.ar_report_recovery.recover_report', return_value=False), \
             patch('app.workflow_service._reject_superseded_batch_material'), \
             patch('app.workflow_service._assert_single_flight_available'), \
             patch('app.workflow_service.assert_workflow_skill_execution_enabled'), \
             patch('app.workflow_service._cleanup_terminal_fetched_snapshot') as cleanup:
            with self.assertRaises(HTTPException) as caught:
                retry_workflow_batch(self.db, batch, actor)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn('当前材料存在未核清', caught.exception.detail)
        cleanup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
