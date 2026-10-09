"""Read-only attempt metadata via the existing execution seam; synthetic DB only."""
import copy
import json
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import event

from app.ar_execution_contract import CONTRACT_VERSION, PHASES
from app.ar_execution_safety import (
    current_material_blocker, record_effect_completion, register_effect_intent,
)
from app.ar_execution_service import read_execution
from app.models import WorkflowAction, WorkflowSession


class AttemptHistoryTests(unittest.TestCase):
    def setUp(self):
        # Import the fixture inside setUp to avoid collecting its unrelated cases.
        from test_ar_postpublish_occupancy import PostPublishOccupancyTests
        self.fixture = PostPublishOccupancyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.db = self.fixture.db
        self.engine = self.fixture.engine
        self.workflow = self.fixture.workflow

    def registered_two_attempts(self, action_id='11111111-1111-4111-8111-111111111111'):
        context = {
            'workspace': '/synthetic/attempt-history',
            'plan_fingerprint': 'synthetic-plan',
            'ar_execution': {
                'schema_version': CONTRACT_VERSION,
                'material_set_id': 'prior', 'material_version': 1,
                'publication': 'not_published',
                'completed': [phase.name for phase in PHASES[:7]],
            },
        }
        action = WorkflowAction(
            id=action_id, workflow=self.workflow,
            name='ar_write_ledger', state='running', attempt_count=1,
            worker_id='synthetic-worker-first', queued_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
        )
        self.db.add(action)
        self.db.flush()
        register_effect_intent(context, self.workflow, action, 'write_ledger')
        original_first = copy.deepcopy(context['execution_safety_v1']['attempts'][0])
        action.attempt_count = 2
        action.worker_id = 'synthetic-worker-second'
        register_effect_intent(context, self.workflow, action, 'write_ledger')
        record_effect_completion(context, action, 'write_ledger', {'synthetic_result': 'second phase complete'})
        action.state = 'succeeded'
        action.finished_at = datetime.now(UTC)
        self.workflow.context_json = json.dumps(context)
        self.db.commit()

        return action, original_first

    def test_two_registered_attempts_preserve_earlier_unknown_after_latest_success(self):
        action, original_first = self.registered_two_attempts()
        before_context = self.workflow.context_json
        before_action = {column.key: getattr(action, column.key) for column in action.__table__.columns}
        before_occupancy = current_material_blocker(self.db, 'owner', 'finance', 'ar-hexiao-daily-lab')
        self.assertIsNotNone(before_occupancy)
        self.assertEqual(before_occupancy['reason'], 'unresolved_write')
        self.db.commit()
        mutations, commits = [], []
        def observe_sql(connection, cursor, statement, parameters, execution_context, executemany):
            verb = statement.lstrip().split(None, 1)[0].upper()
            if verb in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER'}:
                mutations.append(verb)
        def observe_commit(connection):
            commits.append(True)
        event.listen(self.engine, 'before_cursor_execute', observe_sql)
        event.listen(self.engine, 'commit', observe_commit)
        try:
            view = read_execution(self.workflow)
            after_occupancy = current_material_blocker(self.db, 'owner', 'finance', 'ar-hexiao-daily-lab')
        finally:
            event.remove(self.engine, 'before_cursor_execute', observe_sql)
            event.remove(self.engine, 'commit', observe_commit)
        self.assertEqual(mutations, [])
        self.assertEqual(commits, [])
        self.assertFalse(self.db.new)
        self.assertFalse(self.db.dirty)
        self.assertFalse(self.db.deleted)
        self.assertEqual(self.workflow.context_json, before_context)
        self.assertEqual({column.key: getattr(action, column.key) for column in action.__table__.columns}, before_action)
        self.assertEqual(after_occupancy, before_occupancy)
        self.assertFalse(view.recovery_allowed)

        history = view.attempt_history
        self.assertIsNotNone(history)
        self.assertEqual(history.schema_version, 'ar-attempt-history-metadata-v1')
        self.assertTrue(history.metadata_coverage_complete)
        self.assertFalse(history.process_evidence_checked)
        self.assertFalse(history.authorizes_resume)
        self.assertEqual(history.evidence_revision, 3)
        self.assertEqual(history.registered_attempt_count, 2)
        self.assertEqual(history.missing_attempt_count, 0)
        self.assertEqual(history.scanned_action_count, 1)
        self.assertRegex(history.snapshot_fingerprint, r'^[0-9a-f]{64}$')
        self.assertEqual(len(history.items), 2)
        self.assertEqual([(str(item.action_id), item.attempt, item.record_state) for item in history.items], [
            (action.id, 1, 'intent_recorded'), (action.id, 2, 'phase_completed'),
        ])
        first, second = history.items
        self.assertEqual(first.binding_sha256, original_first['binding_sha256'])
        self.assertEqual(first.material_version, 1)
        self.assertIsNotNone(first.intent_at)
        self.assertIsNone(first.completed_at)
        self.assertEqual(second.material_version, 1)
        self.assertIsNotNone(second.intent_at)
        self.assertIsNotNone(second.completed_at)


    def test_registered_facts_with_counter_reset_or_orphan_have_unknown_gap_counts(self):
        action, original_first = self.registered_two_attempts()
        for mode in ('counter_regression', 'reset_to_unstarted', 'orphan'):
            with self.subTest(mode=mode):
                if mode == 'counter_regression':
                    action.attempt_count = 1
                elif mode == 'reset_to_unstarted':
                    action.state = 'queued'
                    action.attempt_count = 0
                    action.worker_id = ''
                    action.started_at = action.finished_at = None
                else:
                    self.db.delete(action)
                self.db.commit()
                self.db.expire(self.workflow, ['actions'])
                original_context = self.workflow.context_json
                history = read_execution(self.workflow).attempt_history
                self.assertFalse(history.metadata_coverage_complete)
                self.assertIsNone(history.missing_attempt_count)
                self.assertTrue(history.reason_codes)
                self.assertEqual(history.registered_attempt_count, 2)
                registered = [item for item in history.items if item.record_state != 'legacy_unknown']
                self.assertEqual([(str(item.action_id), item.attempt, item.record_state) for item in registered], [
                    ('11111111-1111-4111-8111-111111111111', 1, 'intent_recorded'),
                    ('11111111-1111-4111-8111-111111111111', 2, 'phase_completed'),
                ])
                self.assertEqual(registered[0].binding_sha256, original_first['binding_sha256'])
                self.assertTrue(all(item.missing_attempt_count is None for item in registered))
                self.assertEqual(self.workflow.context_json, original_context)
                self.assertFalse(history.process_evidence_checked)
                self.assertFalse(history.authorizes_resume)


    def test_absent_or_nonobject_context_is_explicitly_invalid_and_closes_controls(self):
        for raw in (None, '', '{', 'null', '[]', '42', '"private-context-sentinel"'):
            with self.subTest(raw=raw):
                workflow = WorkflowSession(
                    id='22222222-2222-4222-8222-222222222222', owner_id='synthetic-owner',
                    department_id='finance', skill_id='ar-hexiao-daily-lab', skill_hash='hash',
                    context_json=raw, actions=[],
                )
                view = read_execution(workflow)
                self.assertFalse(view.available)
                self.assertFalse(view.recovery_allowed)
                self.assertEqual(view.next_tool, '')
                self.assertEqual(view.phases, [])
                self.assertFalse(view.formal_ledgers_registered)
                history = view.attempt_history
                self.assertIn('context_invalid', history.reason_codes)
                self.assertFalse(history.metadata_coverage_complete)
                self.assertIsNone(history.evidence_revision)
                self.assertIsNone(history.missing_attempt_count)
                self.assertEqual(history.registered_attempt_count, 0)
                self.assertEqual(history.items, [])
                self.assertFalse(history.process_evidence_checked)
                self.assertFalse(history.authorizes_resume)
                self.assertNotIn('private-context-sentinel', view.model_dump_json())
                self.assertEqual(workflow.context_json, raw)

        # An existing, valid empty legacy JSON object has a different meaning.
        legacy = WorkflowSession(id='22222222-2222-4222-8222-222222222222',
                                 context_json='{}', actions=[])
        view = read_execution(legacy)
        self.assertFalse(view.available)
        self.assertTrue(view.attempt_history.metadata_coverage_complete)
        self.assertEqual(view.attempt_history.missing_attempt_count, 0)
        self.assertIsNone(view.attempt_history.evidence_revision)
        self.assertEqual(view.attempt_history.items, [])
        self.assertFalse(view.attempt_history.authorizes_resume)


    def test_invalid_action_state_is_unknown_even_with_zero_counter_or_complete_index(self):
        # Counter zero is not proof of unstarted work when its state is invalid.
        workflow = WorkflowSession(
            id='22222222-2222-4222-8222-222222222222', owner_id='synthetic-owner',
            department_id='finance', skill_id='ar-hexiao-daily-lab', skill_hash='hash',
            context_json='{}', actions=[],
        )
        unindexed = WorkflowAction(
            id='33333333-3333-4333-8333-333333333333', workflow=workflow, workflow_id=workflow.id,
            name='ar_write_ledger', state='private-invalid-state-sentinel', attempt_count=0,
            worker_id='', started_at=None, finished_at=None,
        )
        history = read_execution(workflow).attempt_history
        self.assertIn('action_metadata_invalid', history.reason_codes)
        self.assertFalse(history.metadata_coverage_complete)
        self.assertIsNone(history.missing_attempt_count)
        self.assertEqual(len(history.items), 1)
        self.assertEqual(history.items[0].record_state, 'legacy_unknown')
        self.assertIsNone(history.items[0].attempt)
        self.assertIsNone(history.items[0].missing_attempt_count)
        self.assertNotIn('private-invalid-state-sentinel', history.model_dump_json())

        # Valid registered facts remain visible; malformed current state supplies
        # no trustworthy claim that the original metadata gaps are all covered.
        action, original_first = self.registered_two_attempts()
        action.state = 'private-invalid-state-sentinel'
        self.db.commit()
        history = read_execution(self.workflow).attempt_history
        self.assertIn('action_metadata_invalid', history.reason_codes)
        self.assertFalse(history.metadata_coverage_complete)
        self.assertIsNone(history.missing_attempt_count)
        self.assertEqual(history.registered_attempt_count, 2)
        registered = [item for item in history.items if item.record_state != 'legacy_unknown']
        self.assertEqual([(item.attempt, item.record_state) for item in registered],
                         [(1, 'intent_recorded'), (2, 'phase_completed')])
        self.assertEqual(registered[0].binding_sha256, original_first['binding_sha256'])
        self.assertTrue(all(item.missing_attempt_count is None for item in registered))
        self.assertNotIn('private-invalid-state-sentinel', history.model_dump_json())
        self.assertFalse(history.process_evidence_checked)
        self.assertFalse(history.authorizes_resume)


    def test_fixed_workflow_date_conflict_preserves_registered_facts_with_unknown_gaps(self):
        action, original_first = self.registered_two_attempts()
        self.workflow.reconciliation_date = '2026-08-31'
        self.assertNotEqual(original_first['reconciliation_date'], self.workflow.reconciliation_date)
        self.db.commit()
        history = read_execution(self.workflow).attempt_history
        self.assertFalse(history.metadata_coverage_complete)
        self.assertIn('attempt_identity_conflict', history.reason_codes)
        self.assertIsNone(history.missing_attempt_count)
        self.assertEqual(history.registered_attempt_count, 2)
        registered = [item for item in history.items if item.record_state != 'legacy_unknown']
        self.assertEqual([(item.attempt, item.record_state) for item in registered],
                         [(1, 'intent_recorded'), (2, 'phase_completed')])
        self.assertEqual(registered[0].binding_sha256, original_first['binding_sha256'])
        self.assertTrue(all(item.missing_attempt_count is None for item in registered))
        self.assertFalse(history.authorizes_resume)


    def scan_cap_workflow(self):
        action, original_first = self.registered_two_attempts()
        clone = WorkflowSession(**{column.key: getattr(self.workflow, column.key)
                                   for column in self.workflow.__table__.columns})
        registered_action = WorkflowAction(**{column.key: getattr(action, column.key)
                                             for column in action.__table__.columns})
        # Non-effect actions count towards the detailed metadata scan cap too.
        ordinary = [WorkflowAction(
            id=str(UUID(int=number + 1)), workflow_id=clone.id,
            name='ar_check_input_files', state='queued', attempt_count=0, worker_id='', queued_at=action.queued_at,
        ) for number in range(2048)]
        self.assertTrue(all(item.id < registered_action.id for item in ordinary))
        clone.actions = ordinary + [registered_action]
        return clone, ordinary, registered_action, original_first

    def test_detailed_action_scan_cap_is_stable_and_cannot_prove_indexed_action_missing(self):
        clone, ordinary, registered_action, original_first = self.scan_cap_workflow()
        forward = read_execution(clone).attempt_history
        clone.actions = list(reversed(clone.actions))
        reverse = read_execution(clone).attempt_history
        self.assertEqual(forward.scanned_action_count, 2048)
        self.assertFalse(forward.metadata_coverage_complete)
        self.assertIsNone(forward.missing_attempt_count)
        self.assertIn('action_scan_truncated', forward.reason_codes)
        with self.subTest(contract='same truncated collection reordered'):
            self.assertEqual(forward.snapshot_fingerprint, reverse.snapshot_fingerprint)
            self.assertEqual(forward.model_dump(), reverse.model_dump())
        with self.subTest(contract='registered action outside sample remains unknown'):
            self.assertEqual(len(forward.items), 2)
            for item in forward.items:
                self.assertNotIn('action_missing', item.reason_codes)
                self.assertIn('action_scan_truncated', item.reason_codes)
                self.assertIsNone(item.missing_attempt_count)
            self.assertEqual(forward.items[0].binding_sha256, original_first['binding_sha256'])
        with self.subTest(contract='exact detailed metadata boundary is complete'):
            clone.actions = ordinary[:2047] + [registered_action]
            exact = read_execution(clone).attempt_history
            self.assertEqual(exact.scanned_action_count, 2048)
            self.assertTrue(exact.metadata_coverage_complete)
            self.assertEqual(exact.missing_attempt_count, 0)
            self.assertEqual(len(exact.items), 2)
            self.assertEqual(exact.reason_codes, [])
        self.assertFalse(forward.process_evidence_checked)
        self.assertFalse(forward.authorizes_resume)


    def test_unscanned_registered_action_is_not_reported_as_proven_missing(self):
        clone, ordinary, registered_action, original_first = self.scan_cap_workflow()
        history = read_execution(clone).attempt_history
        self.assertEqual(history.registered_attempt_count, 2)
        self.assertEqual(len(history.items), 2)
        self.assertEqual(history.items[0].binding_sha256, original_first['binding_sha256'])
        for item in history.items:
            self.assertNotIn('action_missing', item.reason_codes)
            self.assertIn('action_scan_truncated', item.reason_codes)
            self.assertIsNone(item.missing_attempt_count)
        self.assertFalse(history.metadata_coverage_complete)
        self.assertFalse(history.authorizes_resume)


    def test_legacy_gaps_use_one_unknown_item_and_invalid_counters_never_claim_complete(self):
        workflow = WorkflowSession(
            id='22222222-2222-4222-8222-222222222222', owner_id='synthetic-owner',
            department_id='finance', skill_id='ar-hexiao-daily-lab', skill_hash='hash',
            context_json='{}', actions=[],
        )
        for phase in ('write_ledger', 'write_receipt_flow', 'publish_reconciliation',
                      'complete_reconciliation'):
            action = WorkflowAction(
                id='33333333-3333-4333-8333-333333333333', workflow_id=workflow.id,
                name='ar_' + phase, state='failed', attempt_count=10**9,
                worker_id='private-worker-sentinel', queued_at=datetime.now(UTC),
                started_at=datetime.now(UTC),
            )
            workflow.actions = [action]
            history = read_execution(workflow).attempt_history
            self.assertEqual(len(history.items), 1)
            self.assertEqual(history.items[0].record_state, 'legacy_unknown')
            self.assertEqual(history.items[0].phase, phase)
            self.assertIsNone(history.items[0].attempt)
            self.assertEqual(history.items[0].missing_attempt_count, 10**9)
            self.assertEqual(history.missing_attempt_count, 10**9)
            self.assertIn('index_missing', history.reason_codes)
            self.assertFalse(history.metadata_coverage_complete)
            self.assertFalse(history.authorizes_resume)
            self.assertNotIn('private-worker-sentinel', history.model_dump_json())

        for invalid in (True, -1, 1.5, None, 'private-counter-sentinel'):
            action.attempt_count = invalid
            history = read_execution(workflow).attempt_history
            self.assertIn('action_counter_invalid', history.reason_codes)
            self.assertIsNone(history.missing_attempt_count)
            self.assertEqual(len(history.items), 1)
            self.assertIsNone(history.items[0].missing_attempt_count)
            self.assertFalse(history.metadata_coverage_complete)
            self.assertNotIn('private-counter-sentinel', history.model_dump_json())

        action.attempt_count = 0
        action.state = 'queued'
        action.worker_id = ''
        action.started_at = None
        history = read_execution(workflow).attempt_history
        self.assertTrue(history.metadata_coverage_complete)
        self.assertEqual(history.items, [])
        self.assertEqual(history.missing_attempt_count, 0)
        self.assertIsNone(history.evidence_revision)

    def test_one_later_counter_gap_does_not_overwrite_two_registered_facts(self):
        action, original_first = self.registered_two_attempts()
        action.attempt_count = 3
        action.state = 'failed'
        action.worker_id = 'synthetic-third-worker'
        self.db.commit()
        history = read_execution(self.workflow).attempt_history
        self.assertEqual(history.registered_attempt_count, 2)
        self.assertEqual(len(history.items), 3)
        self.assertEqual([(item.attempt, item.record_state) for item in history.items],
                         [(1, 'intent_recorded'), (2, 'phase_completed'), (None, 'legacy_unknown')])
        self.assertEqual(history.items[0].binding_sha256, original_first['binding_sha256'])
        self.assertEqual(history.missing_attempt_count, 1)
        self.assertEqual(history.items[-1].missing_attempt_count, 1)
        self.assertIn('attempt_history_missing', history.reason_codes)
        self.assertFalse(history.metadata_coverage_complete)
        self.assertFalse(history.authorizes_resume)


    def test_index_integrity_and_128_129_record_boundaries_reject_unverified_facts(self):
        action, original_first = self.registered_two_attempts()
        valid = json.loads(self.workflow.context_json)
        action.state = 'running'
        for attempt in range(3, 129):
            action.attempt_count = attempt
            action.worker_id = 'synthetic-limit-worker'
            register_effect_intent(valid, self.workflow, action, 'write_ledger')
        action.state = 'failed'
        self.workflow.context_json = json.dumps(valid)
        self.db.commit()
        exact = read_execution(self.workflow).attempt_history
        self.assertTrue(exact.metadata_coverage_complete)
        self.assertEqual(exact.registered_attempt_count, 128)
        self.assertEqual(len(exact.items), 128)
        self.assertEqual(exact.missing_attempt_count, 0)
        self.assertEqual(exact.items[0].binding_sha256, original_first['binding_sha256'])

        for mode in ('over_limit', 'duplicate', 'bad_schema', 'bad_revision',
                     'wrong_digest', 'foreign_workflow', 'boolean_attempt', 'bad_shape'):
            broken = copy.deepcopy(valid)
            index = broken['execution_safety_v1']
            if mode == 'over_limit':
                index['attempts'].append(copy.deepcopy(index['attempts'][0]))
            elif mode == 'duplicate':
                index['attempts'][-1] = copy.deepcopy(index['attempts'][0])
            elif mode == 'bad_schema':
                index['schema_version'] = 'private-index-schema-sentinel'
            elif mode == 'bad_revision':
                index['revision'] = True
            elif mode == 'wrong_digest':
                index['attempts'][0]['binding_sha256'] = '0' * 64
            elif mode == 'foreign_workflow':
                index['attempts'][0]['workflow_id'] = 'private-foreign-workflow-sentinel'
            elif mode == 'boolean_attempt':
                index['attempts'][0]['attempt'] = True
            else:
                index['attempts'] = ['private-index-shape-sentinel']
            self.workflow.context_json = json.dumps(broken)
            self.db.commit()
            raw = self.workflow.context_json
            history = read_execution(self.workflow).attempt_history
            self.assertFalse(history.metadata_coverage_complete, mode)
            self.assertIn('index_invalid', history.reason_codes, mode)
            self.assertIsNone(history.evidence_revision, mode)
            self.assertIsNone(history.missing_attempt_count, mode)
            self.assertEqual(history.registered_attempt_count, 0, mode)
            self.assertEqual(len(history.items), 1, mode)
            self.assertEqual(history.items[0].record_state, 'legacy_unknown', mode)
            self.assertIsNone(history.items[0].attempt, mode)
            self.assertIsNone(history.items[0].missing_attempt_count, mode)
            self.assertNotIn('private-', history.model_dump_json(), mode)
            self.assertEqual(self.workflow.context_json, raw, mode)
            self.assertFalse(history.authorizes_resume, mode)

    def test_256_item_output_boundary_preserves_registered_facts_first(self):
        action, original_first = self.registered_two_attempts()
        clone = WorkflowSession(**{column.key: getattr(self.workflow, column.key)
                                   for column in self.workflow.__table__.columns})
        registered_action = WorkflowAction(**{column.key: getattr(action, column.key)
                                             for column in action.__table__.columns})
        ordinary = [WorkflowAction(
            id=str(UUID(int=number + 1)), workflow_id=clone.id,
            name='ar_write_receipt_flow', state='failed', attempt_count=1,
            worker_id='private-output-worker-sentinel', queued_at=action.queued_at,
            started_at=action.started_at,
        ) for number in range(255)]
        clone.actions = ordinary + [registered_action]
        capped = read_execution(clone).attempt_history
        self.assertEqual(capped.scanned_action_count, 256)
        self.assertEqual(len(capped.items), 256)
        self.assertEqual(capped.registered_attempt_count, 2)
        self.assertIn('history_output_truncated', capped.reason_codes)
        self.assertFalse(capped.metadata_coverage_complete)
        self.assertIsNone(capped.missing_attempt_count)
        self.assertEqual([(item.attempt, item.record_state) for item in capped.items[:2]],
                         [(1, 'intent_recorded'), (2, 'phase_completed')])
        self.assertEqual(capped.items[0].binding_sha256, original_first['binding_sha256'])
        self.assertTrue(all(item.record_state == 'legacy_unknown' for item in capped.items[2:]))
        clone.actions = list(reversed(clone.actions))
        self.assertEqual(read_execution(clone).attempt_history.model_dump(), capped.model_dump())
        clone.actions = ordinary[:254] + [registered_action]
        exact = read_execution(clone).attempt_history
        self.assertEqual(len(exact.items), 256)
        self.assertNotIn('history_output_truncated', exact.reason_codes)
        self.assertEqual(exact.missing_attempt_count, 254)
        self.assertNotIn('private-output-worker-sentinel', capped.model_dump_json())
        self.assertFalse(capped.authorizes_resume)


    def test_invalid_opaque_action_id_is_not_echoed_even_when_index_binding_is_valid(self):
        action, original_first = self.registered_two_attempts(action_id='private-action-id-sentinel')
        history = read_execution(self.workflow).attempt_history
        self.assertEqual(history.registered_attempt_count, 2)
        self.assertEqual(history.scanned_action_count, 1)
        self.assertEqual(history.items, [])
        self.assertIn('action_identity_invalid', history.reason_codes)
        self.assertFalse(history.metadata_coverage_complete)
        self.assertIsNone(history.missing_attempt_count)
        self.assertNotIn('private-action-id-sentinel', history.model_dump_json())
        self.assertFalse(history.authorizes_resume)

    def test_history_privacy_fingerprint_and_execution_schema_compatibility(self):
        action, original_first = self.registered_two_attempts()
        baseline = read_execution(self.workflow)
        self.assertTrue(baseline.available)
        top_fields = {'schema_version', 'metadata_coverage_complete', 'process_evidence_checked',
                      'authorizes_resume', 'evidence_revision', 'snapshot_fingerprint',
                      'registered_attempt_count', 'missing_attempt_count', 'scanned_action_count',
                      'items', 'reason_codes'}
        item_fields = {'action_id', 'attempt', 'phase', 'record_state', 'binding_sha256',
                       'material_version', 'intent_at', 'completed_at', 'missing_attempt_count',
                       'reason_codes'}
        self.assertEqual(set(baseline.attempt_history.model_dump()), top_fields)
        self.assertTrue(all(set(item.model_dump()) == item_fields for item in baseline.attempt_history.items))
        context = json.loads(self.workflow.context_json)
        context['private_diagnostics'] = {
            'input': 'private-input-sentinel', 'result': 'private-result-sentinel',
            'order': 'private-so-sentinel', 'amount': 'private-amount-sentinel',
            'path': '/private/path-sentinel', 'host': 'private-host-sentinel', 'pid': 991994,
        }
        self.workflow.context_json = json.dumps(context)
        self.db.commit()
        private_view = read_execution(self.workflow)
        self.assertEqual(private_view.model_dump(exclude={'attempt_history'}),
                         baseline.model_dump(exclude={'attempt_history'}))
        self.assertNotEqual(private_view.attempt_history.snapshot_fingerprint,
                            baseline.attempt_history.snapshot_fingerprint)
        self.assertEqual(read_execution(self.workflow).attempt_history.model_dump(),
                         private_view.attempt_history.model_dump())
        action.queued_at += timedelta(seconds=1)
        action.input_json = json.dumps({'value': 'private-action-input-sentinel'})
        action.result_json = json.dumps({'value': 'private-action-result-sentinel'})
        self.db.commit()
        metadata_changed = read_execution(self.workflow).attempt_history
        self.assertNotEqual(metadata_changed.snapshot_fingerprint,
                            private_view.attempt_history.snapshot_fingerprint)

        # Latest context may move to new materials; immutable old binding stays.
        context['workspace'] = '/private/latest-workspace-sentinel'
        context['plan_fingerprint'] = 'private-latest-plan-sentinel'
        context['ar_execution']['material_set_id'] = 'private-latest-material-sentinel'
        context['ar_execution']['material_version'] = 42
        self.workflow.context_json = json.dumps(context)
        self.db.commit()
        latest = read_execution(self.workflow).attempt_history
        self.assertTrue(latest.metadata_coverage_complete)
        self.assertEqual([item.material_version for item in latest.items], [1, 1])
        self.assertEqual(latest.items[0].binding_sha256, original_first['binding_sha256'])

        context['ar_execution']['schema_version'] = 'future-execution-schema'
        self.workflow.context_json = json.dumps(context)
        self.db.commit()
        unsupported = read_execution(self.workflow)
        self.assertFalse(unsupported.available)
        self.assertFalse(unsupported.recovery_allowed)
        self.assertEqual(unsupported.phases, [])
        self.assertEqual([item.model_dump() for item in unsupported.attempt_history.items],
                         [item.model_dump() for item in latest.items])
        self.assertTrue(unsupported.attempt_history.metadata_coverage_complete)

        context['execution_safety_v1']['attempts'][0]['intent_at'] = '2026-10-08T01:00:00'
        context['execution_safety_v1']['attempts'][1]['completed_at'] = 'private-invalid-time-sentinel'
        self.workflow.context_json = json.dumps(context)
        self.db.commit()
        raw = self.workflow.context_json
        invalid_time = read_execution(self.workflow).attempt_history
        self.assertFalse(invalid_time.metadata_coverage_complete)
        self.assertIn('timestamp_invalid', invalid_time.reason_codes)
        self.assertIsNone(invalid_time.items[0].intent_at)
        self.assertIsNone(invalid_time.items[1].completed_at)
        self.assertEqual(invalid_time.missing_attempt_count, 0)
        self.assertEqual(self.workflow.context_json, raw)
        for forbidden in (*context['private_diagnostics'].values(),
                          'synthetic-worker-first', 'synthetic-worker-second',
                          '/synthetic/attempt-history', 'synthetic-plan',
                          'private-action-input-sentinel', 'private-action-result-sentinel',
                          '/private/latest-workspace-sentinel', 'private-latest-plan-sentinel',
                          'private-latest-material-sentinel', 'private-invalid-time-sentinel'):
            self.assertNotIn(str(forbidden), invalid_time.model_dump_json())
        self.assertFalse(invalid_time.process_evidence_checked)
        self.assertFalse(invalid_time.authorizes_resume)


if __name__ == '__main__':
    unittest.main()
