"""Queued work is rechecked against shared material before an attempt starts."""
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.ar_execution_contract import CONTRACT_VERSION, INVESTIGATION_ACTION
from app.models import WorkflowAction, WorkflowBatch, WorkflowSession
from app.workflow_service import claim_next_workflow_action
from test_ar_postpublish_occupancy import PostPublishOccupancyTests


class ClaimMaterialPolicyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PostPublishOccupancyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.db = self.fixture.db
        self.blocker = self.fixture.workflow

    def action(self, workflow, name='ar_write_ledger', offset=0):
        action = WorkflowAction(id='action-'+workflow.id, workflow=workflow, name=name,
            queued_at=datetime.now(UTC)+timedelta(seconds=offset))
        action._stored_state = 'ar_v2:queued'
        self.db.add(action)
        self.db.commit()
        return action

    def candidate(self, identity='candidate', owner='owner'):
        workflow = WorkflowSession(id=identity, owner_id=owner, owner_name='Synthetic',
            department_id='finance', skill_id='ar-hexiao-daily-lab', skill_name='AR',
            skill_version='1', skill_hash='hash', execution_mode='workflow',
            model_connection_id='', model_provider='', model_name='',
            state='running', stage='applying', reconciliation_date='2026-09-01',
            material_set_id='published', concurrency_limit=1)
        self.db.add(workflow)
        self.db.commit()
        return workflow

    def claim(self):
        with patch('app.workflow_service.recover_expired_jobs'), \
             patch('app.ar_execution_runner.execution_version', return_value=CONTRACT_VERSION), \
             patch('app.workflow_service.workflow_owner_context'), \
             patch('app.workflow_service.active_task_discovery_count', return_value=0), \
             patch('app.workflow_service.active_workflow_count', return_value=0):
            return claim_next_workflow_action(self.db, ('workflow',), 'synthetic-worker',
                                              execution_contracts=(CONTRACT_VERSION,))

    def test_conflicting_write_remains_unstarted_without_consuming_attempt(self):
        workflow = self.candidate()
        action = self.action(workflow)
        self.assertIsNone(self.claim())
        self.db.refresh(action)
        self.assertEqual(action.state, 'queued')
        self.assertEqual(action.attempt_count, 0)
        self.assertFalse(action.worker_id)
        self.assertIsNone(action.started_at)
        self.assertIn('尚未开始', workflow.progress_message)

    def test_blocked_candidate_does_not_starve_independent_owner(self):
        blocked = self.action(self.candidate())
        independent = self.action(self.candidate('independent', 'another-owner'), offset=1)
        selected = self.claim()
        self.assertEqual(selected.id, independent.id)
        self.assertEqual(blocked.state, 'queued')
        self.assertEqual(blocked.attempt_count, 0)

    def test_own_publication_can_finish_registration(self):
        self.blocker.state, self.blocker.stage = 'running', 'applying'
        action = self.action(self.blocker, 'ar_complete_reconciliation')
        self.assertEqual(self.claim().id, action.id)
        self.assertEqual(action.attempt_count, 1)

    def test_investigation_is_not_blocked_by_material_it_must_investigate(self):
        other = self.candidate('other-unresolved')
        other.state, other.stage = 'failed', 'failed'
        other.context_json = self.blocker.context_json
        self.db.commit()
        action = self.action(self.blocker, INVESTIGATION_ACTION)
        self.assertEqual(self.claim().id, action.id)

    def test_range_report_remains_available_despite_another_material_blocker(self):
        workflow = self.candidate('report')
        batch = WorkflowBatch(id='report-batch', owner_id='owner', owner_name='Synthetic',
            department_id='finance', skill_id='ar-hexiao-daily-lab', skill_name='AR',
            skill_version='1', execution_mode='workflow', model_connection_id='',
            model_provider='', model_name='', state='finalizing')
        self.db.add(batch)
        workflow.batch = batch
        workflow.state, workflow.stage = 'succeeded', 'completed'
        self.db.commit()
        action = self.action(workflow, 'finalize_batch')
        self.assertEqual(self.claim().id, action.id)

    def test_unresolved_cancelled_workflow_still_blocks_claim(self):
        self.blocker.state = 'cancelled'
        self.db.commit()
        self.action(self.candidate())
        self.assertIsNone(self.claim())


if __name__ == '__main__':
    unittest.main()
