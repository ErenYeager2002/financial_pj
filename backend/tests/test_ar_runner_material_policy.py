"""Execution boundaries share material policy without committing publication."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from app import ar_execution_runner as runner
from app import ar_execution_safety as safety
from app.models import WorkflowSession
from test_ar_postpublish_occupancy import PostPublishOccupancyTests

class RunnerMaterialPolicyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PostPublishOccupancyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.db, self.flow = self.fixture.db, self.fixture.workflow
        self.flow.state = 'running'
        context = json.loads(self.flow.context_json)
        context['ar_execution'].update(reconciliation_date=self.flow.reconciliation_date,
                                      skill_hash=self.flow.skill_hash)
        self.flow.context_json = json.dumps(context)
        self.db.commit()
        self.execution = object.__new__(runner.ArExecution)
        self.execution.db, self.execution.workflow = self.db, self.flow
        self.execution.execution = context['ar_execution']
        self.execution.date = self.flow.reconciliation_date
        self.execution.action = SimpleNamespace(name='ar_write_ledger')

    def other(self):
        other = WorkflowSession(id='other', owner_id=self.flow.owner_id,
            department_id=self.flow.department_id, skill_id=self.flow.skill_id,
            skill_name='AR', skill_version='1', skill_hash='hash',
            model_connection_id='', model_provider='', model_name='',
            state='failed', stage='failed', material_set_id='published',
            context_json=self.flow.context_json)
        self.db.add(other)
        self.db.commit()

    def test_all_effect_boundaries_use_common_guard_without_commit(self):
        for name, operation in [('ar_write_ledger','resume_phase'),
                ('ar_publish_reconciliation','publish'),
                ('ar_complete_reconciliation','complete_registration')]:
            with self.subTest(name=name):
                self.execution.action.name = name
                with patch.object(safety, 'assert_operation_allowed', wraps=safety.assert_operation_allowed) as guard, \
                     patch.object(self.db, 'commit', side_effect=AssertionError('premature commit')):
                    self.execution._verify_material_binding()
                self.assertEqual(guard.call_args.kwargs['operation'], operation)
                self.assertEqual(guard.call_args.kwargs['exclude_workflow_id'], self.flow.id)
                self.db.rollback()

    def test_conflict_appearing_after_claim_blocks_each_effect_boundary(self):
        self.execution._verify_material_binding()
        self.db.rollback()
        self.other()
        for name in ['ar_write_ledger','ar_publish_reconciliation','ar_complete_reconciliation']:
            with self.subTest(name=name):
                self.execution.action.name = name
                with self.assertRaises(safety.MaterialOccupancyConflict):
                    self.execution._verify_material_binding()
                self.db.rollback()

    def test_guard_flush_does_not_commit_pending_changes(self):
        self.flow.progress = 63
        self.execution._verify_material_binding()
        self.db.rollback()
        self.assertNotEqual(self.flow.progress, 63)

    def test_historical_completion_requires_manifest_and_never_admits_new_write(self):
        self.execution.execution['steps']['publish_reconciliation']['material_set_id'] = 'old'
        self.execution.execution['steps']['publish_reconciliation']['material_version'] = 1
        context = json.loads(self.flow.context_json)
        context['stop_after_action'] = True
        self.flow.context_json = json.dumps(context)
        self.db.commit()
        self.execution.action.name = 'ar_complete_reconciliation'
        with patch('app.ar_publication.publication_manifest', return_value={}) as manifest, \
             patch.object(safety, 'assert_operation_allowed') as guard:
            self.execution._verify_material_binding()
            manifest.assert_called_once_with(self.db, self.flow)
            guard.assert_not_called()
        with patch('app.ar_publication.publication_manifest', side_effect=ValueError('invalid proof')):
            with self.assertRaisesRegex(ValueError, 'invalid proof'):
                self.execution._verify_material_binding()
        for name in ['ar_write_ledger','ar_publish_reconciliation']:
            self.execution.action.name = name
            with self.assertRaisesRegex(ValueError, '版本已改变'):
                self.execution._verify_material_binding()

    def test_historical_completion_without_stop_is_rejected(self):
        self.execution.execution['steps']['publish_reconciliation']['material_set_id'] = 'old'
        self.execution.action.name = 'ar_complete_reconciliation'
        with self.assertRaisesRegex(ValueError, '版本已改变'):
            self.execution._verify_material_binding()

    def test_phase_dispatch_conflict_returns_409_before_queue(self):
        self.other()
        with patch('app.pi_harness_lease.require_harness_lease'), \
             patch('app.workflow_service.workflow_owner_context'), \
             patch('app.workflow_service._queue_action') as enqueue, \
             patch.object(safety,'assert_operation_allowed',wraps=safety.assert_operation_allowed) as guard:
            with self.assertRaises(HTTPException) as caught:
                runner.queue_execution_phase(self.db,self.flow,'write_ledger',{},
                    harness_action_id='agent',worker_id='worker',attempt=1)
            self.assertEqual(caught.exception.status_code,409)
            self.assertEqual(guard.call_args.kwargs['operation'],'resume_phase')
            enqueue.assert_not_called()

if __name__ == '__main__':
    unittest.main()
