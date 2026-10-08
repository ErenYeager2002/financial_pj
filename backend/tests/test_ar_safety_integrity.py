"""Safety evidence corruption must not release a workbook or accept a late result."""
import copy
import hashlib
import json
import unittest
from types import SimpleNamespace

from app.ar_execution_safety import (
    _has_unresolved_effect, register_effect_intent, record_effect_completion,
)


class SafetyIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.workflow = SimpleNamespace(id='wf', owner_id='owner', department_id='finance',
            skill_id='ar-hexiao-daily-lab', skill_hash='skill-hash',
            reconciliation_date='2026-09-01', actions=[])
        self.action = SimpleNamespace(id='action', workflow_id='wf', name='ar_write_ledger',
            state='running', attempt_count=1, worker_id='worker')
        self.context = {'workspace': '/synthetic/wf', 'plan_fingerprint': 'plan-hash',
            'ar_execution': {'material_set_id': 'material', 'material_version': 1}}
        register_effect_intent(self.context, self.workflow, self.action, 'write_ledger')

    def entry(self):
        return self.context['execution_safety_v1']['attempts'][0]

    def assert_blocked(self):
        self.workflow.context_json = json.dumps(self.context)
        self.assertTrue(_has_unresolved_effect(self.workflow))

    def test_valid_intent_survives_missing_action_row(self):
        self.assert_blocked()

    def test_unknown_status_does_not_release_occupancy(self):
        self.entry()['status'] = 'finished'
        self.assert_blocked()

    def test_foreign_workflow_binding_does_not_release_occupancy(self):
        self.entry()['workflow_id'] = 'another-workflow'
        self.assert_blocked()

    def test_corrupt_digest_rejects_completion_without_mutating_evidence(self):
        self.entry()['binding_sha256'] = '0' * 64
        before = copy.deepcopy(self.context)
        with self.assertRaises(ValueError):
            record_effect_completion(self.context, self.action, 'write_ledger', {'ok': True})
        self.assertEqual(self.context, before)

    def test_result_from_other_worker_rejected(self):
        self.action.worker_id = 'reassigned-worker'
        before = copy.deepcopy(self.context)
        with self.assertRaises(ValueError):
            record_effect_completion(self.context, self.action, 'write_ledger', {'ok': True})
        self.assertEqual(self.context, before)

    def test_result_from_other_workflow_rejected(self):
        self.action.workflow_id = 'another-workflow'
        with self.assertRaises(ValueError):
            record_effect_completion(self.context, self.action, 'write_ledger', {'ok': True})

    def test_valid_completion_and_second_attempt_preserve_first(self):
        self.action.state = 'succeeded'  # transition_phase marks this before recording.
        record_effect_completion(self.context, self.action, 'write_ledger', {'ok': True})
        first = copy.deepcopy(self.entry())
        self.action.state = 'running'
        self.action.attempt_count = 2
        register_effect_intent(self.context, self.workflow, self.action, 'write_ledger')
        self.assertEqual(self.entry(), first)
        self.assertEqual(self.context['execution_safety_v1']['revision'], 3)
        self.assert_blocked()

    def test_invalid_phase_rejects_new_intent_without_mutation(self):
        self.entry()['phase'] = 'fetch'
        self.action.attempt_count = 2
        before = copy.deepcopy(self.context)
        with self.assertRaises(ValueError):
            register_effect_intent(self.context, self.workflow, self.action, 'write_ledger')
        self.assertEqual(self.context, before)

    def test_incomplete_completed_record_is_not_free(self):
        self.entry()['status'] = 'phase_completed'
        self.assert_blocked()

    def test_legacy_prewrite_context_remains_readable(self):
        self.workflow.context_json = json.dumps({'ar_execution': {'completed': ['review_order_evidence']}})
        self.assertFalse(_has_unresolved_effect(self.workflow))


if __name__ == '__main__':
    unittest.main()
