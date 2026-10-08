"""Material safety queries and locked admission share one decision surface."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import event, update
from app.models import WorkflowSession
from app import ar_execution_safety as safety
from app.workflow_material_lock import material_edit_state, assert_material_editable
from app.workflow_material_service import MaterialVersionConflict
from test_ar_postpublish_occupancy import PostPublishOccupancyTests


class MaterialPolicyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = PostPublishOccupancyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.db = self.fixture.db
        self.workflow = self.fixture.workflow
        self.user = SimpleNamespace(user_id='owner', department_id='finance')

    def view(self, **kwargs):
        return safety.get_safety_view(self.db, 'owner', 'finance', 'ar-hexiao-daily-lab', **kwargs)

    def guard(self, **kwargs):
        return safety.assert_operation_allowed(self.db, 'owner', 'finance', 'ar-hexiao-daily-lab', **kwargs)

    def test_published_unregistered_has_separate_effect_and_process_facts(self):
        view = self.view(operation='create_run')
        self.assertFalse(view['material_admission_allowed'])
        self.assertEqual(view['occupancy_state'], 'needs_investigation')
        self.assertEqual(view['execution']['effect_state'], 'published_verified')
        self.assertEqual(view['execution']['process_state'], 'unknown')
        self.assertEqual(view['blocker']['workflow_id'], self.workflow.id)

    def test_query_does_not_flush_or_overwrite_pending_changes(self):
        self.workflow.owner_name = 'pending-local-edit'
        statements = []
        def observed(conn, cursor, statement, parameters, context, many):
            statements.append(statement.lstrip().split()[0].upper())
        event.listen(self.fixture.engine, 'before_cursor_execute', observed)
        self.addCleanup(event.remove, self.fixture.engine, 'before_cursor_execute', observed)
        self.view(operation='create_run')
        self.assertNotIn('UPDATE', statements)
        self.assertNotIn('INSERT', statements)
        self.assertEqual(self.workflow.owner_name, 'pending-local-edit')
        self.assertTrue(self.db.is_modified(self.workflow))

    def test_view_uses_database_facts_instead_of_cached_workflow(self):
        context = json.loads(self.workflow.context_json)
        context['ar_execution']['completed'].append('complete_reconciliation')
        context['formal_ledgers'] = {'file_id': 'formal', 'sha256': 'c'*64}
        self.db.execute(update(WorkflowSession).where(WorkflowSession.id == self.workflow.id)
            .values(context_json=json.dumps(context)).execution_options(synchronize_session=False))
        self.assertNotIn('formal_ledgers', self.workflow.context_json)
        view = self.view(operation='create_run')
        self.assertTrue(view['material_admission_allowed'])
        self.assertIsNone(view['execution'])

    def test_mutation_gate_takes_lock_and_never_commits(self):
        from app.scheduler import acquire_claim_lock
        with patch('app.scheduler.acquire_claim_lock', wraps=acquire_claim_lock) as lock, \
             patch.object(self.db, 'commit', wraps=self.db.commit) as commit:
            with self.assertRaises(safety.MaterialOccupancyConflict) as caught:
                self.guard(operation='create_run')
            lock.assert_called_once_with(self.db)
            commit.assert_not_called()
        self.assertEqual(caught.exception.view['reason'], 'unresolved_write')

    def test_create_cannot_exclude_a_workflow(self):
        with self.assertRaises(ValueError):
            self.guard(operation='create_run', exclude_workflow_id=self.workflow.id)

    def test_resume_can_exclude_itself_but_not_other_scopes(self):
        view = self.guard(operation='resume_phase', exclude_workflow_id=self.workflow.id)
        self.assertTrue(view['material_admission_allowed'])
        other = safety.get_safety_view(self.db, 'different-owner', 'finance',
                                     'ar-hexiao-daily-lab', operation='create_run')
        self.assertTrue(other['material_admission_allowed'])

    def test_unknown_operation_is_rejected(self):
        with self.assertRaises(ValueError):
            self.guard(operation='force_unlock')

    def test_material_page_and_mutation_share_same_block_reason(self):
        view = self.view(operation='replace_materials')
        state = material_edit_state(self.db, self.user, 'ar-hexiao-daily-lab')
        self.assertEqual(state['reason'], view['message'])
        self.assertTrue(state['locked'])
        with self.assertRaises(MaterialVersionConflict) as caught:
            assert_material_editable(self.db, self.user, 'ar-hexiao-daily-lab')
        self.assertEqual(str(caught.exception), view['message'])

    def test_clear_read_view_is_not_an_execution_ticket(self):
        clear = safety.get_safety_view(self.db, 'different-owner', 'finance',
            'ar-hexiao-daily-lab', operation='create_run')
        self.assertTrue(clear['material_admission_allowed'])
        # Guard recomputes from its own owner/scope; no client view is accepted.
        with self.assertRaises(safety.MaterialOccupancyConflict):
            self.guard(operation='create_run')


if __name__ == '__main__':
    unittest.main()
