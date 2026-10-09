"""Original terminal observations survive two real no-op attempts; isolated PG only."""
import hashlib
import json
import os
import unittest
from unittest.mock import patch

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app import ar_process_evidence as evidence
from app import workflow_service as service
from app.ar_execution_contract import CONTRACT_VERSION
from app.ar_execution_runner import ArExecution, execute_phase, transition_phase
from app.ar_execution_safety import current_material_blocker
from app.ar_execution_service import read_execution
from app.ar_process_supervisor import validate_receipt
from app.models import AuditEvent, WorkflowAction, WorkflowSession
from app.workflow_action_state import isolated_action_state

URL = 'postgresql+psycopg://synthetic:synthetic-only@127.0.0.1:5432/material_policy_test'


class TerminalProcessRefsPostgresTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.environ.get('AR_POLICY_SYNTHETIC_DB_URL'), URL)
        # Composition keeps the old 21 cases out of this test collection.
        from test_ar_process_anchor_postgres import ArProcessAnchorPostgresTests
        self.fixture = ArProcessAnchorPostgresTests('test_prepared_reference_and_audit_are_visible_before_popen')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def test_original_terminal_refs_survive_later_attempt_without_original_result(self):
        f = self.fixture
        first = ArExecution(f.db, f.action, f.workflow)
        self.assertEqual(first.script('anchor_probe.py', []).strip(), 'synthetic anchor probe')
        first_produced = json.loads(json.dumps(f.action._ar_process_records[-1]))
        with Session(f.engine) as observer:
            early_workflow = observer.get(WorkflowSession, f.workflow_id)
            early_context = json.loads(early_workflow.context_json)
            early_entry = early_context['execution_safety_v1']['attempts'][0]
            self.assertEqual(early_entry['status'], 'intent_recorded')
            self.assertEqual(json.loads(observer.get(WorkflowAction, f.action_id).result_json), {})
            self.assertNotIn('ar_failure', early_context)
            early_audits = [json.loads(row.details_json) for row in observer.scalars(
                select(AuditEvent).where(AuditEvent.action == 'ar_process_terminal_registered',
                    AuditEvent.resource_type == 'workflow', AuditEvent.resource_id == f.workflow_id))]
        # Record early durability, but defer all new assertions until two no-ops ran.
        f.db.refresh(f.workflow)
        f.db.refresh(f.action)
        f.action.state = isolated_action_state('queued')
        f.action.worker_id, f.action.lease_expires_at = '', None
        f.db.commit()  # Synthetic migration only; no financial task is resumed.
        second_produced = []

        def synthetic_write_ledger(execution):
            self.assertEqual(execution.script('anchor_probe.py', []).strip(), 'synthetic anchor probe')
            second_produced.append(json.loads(json.dumps(execution.action._ar_process_records[-1])))
            return {'synthetic_noop': True}

        with Session(f.engine, expire_on_commit=False) as run_db:
            claimed = service.claim_next_workflow_action(run_db, ('workflow',), 'synthetic-worker-two',
                                                         execution_contracts=(CONTRACT_VERSION,))
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.id, f.action_id)
            self.assertEqual(claimed.attempt_count, 2)
            workflow = run_db.get(WorkflowSession, f.workflow_id)
            # Only the financial writer body is replaced; constructor/gates/ORM stay real.
            with patch.object(ArExecution, 'write_ledger', synthetic_write_ledger):
                result = execute_phase(run_db, claimed, workflow)
            transition_phase(run_db, claimed, workflow, result)
            run_db.commit()

        self.assertEqual(len(second_produced), 1)
        produced = [first_produced, second_produced[0]]
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            context = json.loads(workflow.context_json)
            entries = context['execution_safety_v1']['attempts']
            self.assertEqual(len(entries), 2)
            self.assertEqual([entry['attempt'] for entry in entries], [1, 2])
            self.assertEqual([entry['worker_id'] for entry in entries], ['synthetic-worker', 'synthetic-worker-two'])
            self.assertEqual([entry['status'] for entry in entries], ['intent_recorded', 'phase_completed'])
            self.assertNotIn('ar_failure', context)
            latest = reader.get(WorkflowAction, f.action_id)
            latest_payload = json.loads(latest.result_json)
            self.assertTrue(latest_payload['synthetic_noop'])
            self.assertEqual(len(latest_payload['process_records']), 1)
            self.assertEqual(latest_payload['process_records'][0], produced[1])
            self.assertNotEqual(produced[0]['record_id'], produced[1]['record_id'])
            journal = f.root / 'execution-processes' / f.action_id
            for entry, original in zip(entries, produced):
                anchor = entry['prepared_process_refs'][0]
                self.assertEqual(anchor['record_id'], original['record_id'])
                self.assertEqual(anchor['prepared_sha256'], original['prepared_sha256'])
                record = journal / anchor['record_id']
                prepared = json.loads((record / 'prepared.json').read_text())
                started = json.loads((record / 'started.json').read_text())
                receipt = json.loads((record / 'domain-exited.json').read_text())
                validate_receipt(receipt, token=prepared['domain_token'], supervisor_pid=started['pid'])
                self.assertGreaterEqual(receipt['reaped_count'], 1)
                for name, key in (('started.json', 'started_sha256'), ('exited.json', 'exit_sha256'),
                                  ('domain-exited.json', 'domain_exit_sha256')):
                    self.assertEqual(hashlib.sha256((record / name).read_bytes()).hexdigest(), original[key])
            self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)
            audits = [json.loads(row.details_json) for row in reader.scalars(
                select(AuditEvent).where(AuditEvent.action == 'ar_process_terminal_registered',
                    AuditEvent.resource_type == 'workflow', AuditEvent.resource_id == f.workflow_id))]
            print(json.dumps({'event': 'codex_f4d_two_actual_attempts_before_red',
                'true_noop_outputs': 2, 'original_prepared_records': 2, 'linux_domain_receipts': 2,
                'early_result_empty': True, 'original_business_status': entries[0]['status'],
                'latest_result_only_attempt': 2, 'early_terminal_refs': len(early_entry.get('terminal_process_refs', [])),
                'early_terminal_audits': len(early_audits), 'final_terminal_audits': len(audits),
                'synthetic_material_bytes_unchanged': True, 'financial_writer_invoked': False}, sort_keys=True))

            # First new assertion: current producer loses its original registered terminal refs.
            self.assertEqual(len(early_entry.get('terminal_process_refs', [])), 1,
                             'original terminal ref must be committed before any phase result or failure')
            self.assertEqual(len(early_audits), 1)
            self.assertEqual(entries[0], early_entry)
            self.assertEqual(len(audits), 2)
            expected_fields = {'schema_version', 'record_id', 'prepared_sha256', 'script', 'started_sha256',
                'exit_sha256', 'domain_exit_sha256', 'terminal_state', 'binding_sha256', 'registered_at'}
            for entry, original in zip(entries, produced):
                self.assertEqual(len(entry['terminal_process_refs']), 1)
                terminal = entry['terminal_process_refs'][0]
                self.assertEqual(set(terminal), expected_fields)
                self.assertEqual(terminal['schema_version'], 'ar-process-evidence-v1')
                self.assertEqual(terminal['terminal_state'], 'exited')
                self.assertEqual(terminal['binding_sha256'], entry['binding_sha256'])
                for key in ('record_id', 'prepared_sha256', 'script', 'started_sha256',
                            'exit_sha256', 'domain_exit_sha256'):
                    self.assertEqual(terminal[key], original[key])
                audit = next(item for item in audits if item['record_id'] == original['record_id'])
                self.assertEqual(audit['action_id'], f.action_id)
                self.assertEqual(audit['attempt'], entry['attempt'])
                self.assertEqual(audit['phase'], 'write_ledger')
                self.assertEqual(audit['prepared_sha256'], original['prepared_sha256'])
                self.assertEqual(audit['binding_sha256'], entry['binding_sha256'])
                self.assertIs(audit['late_observation'], False)
                self.assertFalse({'pid', 'host', 'path', 'domain_token', 'arguments', 'stdout'} & set(audit))

            baseline = read_execution(workflow)
            self.assertIsNone(baseline.process_details)
            before_context, before_result = workflow.context_json, latest.result_json
            before_audit_count = reader.scalar(select(func.count()).select_from(AuditEvent))
            blocker = current_material_blocker(reader, workflow.owner_id, workflow.department_id, workflow.skill_id)
            self.assertIsNotNone(blocker)
            self.assertEqual(blocker['reason'], 'unresolved_write')
            mutations = []

            def observe_sql(connection, cursor, statement, parameters, execution_context, executemany):
                if statement.lstrip().split(None, 1)[0].upper() in {'INSERT', 'UPDATE', 'DELETE'}:
                    mutations.append(statement.lstrip().split(None, 1)[0].upper())

            event.listen(f.engine, 'before_cursor_execute', observe_sql)
            try:
                with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('reader must not spawn')):
                    actual = read_execution(workflow, include_process_details=True)
                self.assertFalse(actual.attempt_history.process_evidence_checked)
                self.assertFalse(actual.attempt_history.authorizes_resume)
                self.assertEqual(actual.process_details.whole_workflow_coverage, 'unknown')
                self.assertEqual(actual.process_details.metadata_snapshot_fingerprint,
                                 baseline.attempt_history.snapshot_fingerprint)
                items = {(str(item.action_id), item.attempt): item for item in actual.process_details.items}
                self.assertEqual(set(items), {(f.action_id, 1), (f.action_id, 2)})
                for item in items.values():
                    self.assertEqual(item.inspection_state, 'verified')
                    self.assertTrue(item.coverage_complete)
                    for quantity in ('prepared_record_count', 'registered_terminal_count', 'direct_exit_count',
                                     'descendant_domain_count'):
                        self.assertEqual(getattr(item, quantity), 1)
                self.assertEqual(actual.recovery_allowed, baseline.recovery_allowed)
                self.assertEqual(actual.recovery_reason, baseline.recovery_reason)
                self.assertEqual(actual.checkpoint_fingerprint, baseline.checkpoint_fingerprint)
                self.assertEqual(current_material_blocker(reader, workflow.owner_id, workflow.department_id,
                                                         workflow.skill_id), blocker)
                self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), before_audit_count)
            finally:
                event.remove(f.engine, 'before_cursor_execute', observe_sql)
            self.assertEqual(mutations, [])
            self.assertEqual(workflow.context_json, before_context)
            self.assertEqual(latest.result_json, before_result)
            self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)

    def test_real_pg_terminal_audit_failure_preserves_prepared_and_caller_transaction(self):
        from uuid import uuid4

        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        from app.ar_process_evidence import TerminalProcessRegistrationError
        from app.auth_models import User

        f = self.fixture
        execution = ArExecution(f.db, f.action, f.workflow)
        before = json.loads(f.workflow.context_json)
        original_index = before['execution_safety_v1']
        original_entry = original_index['attempts'][0]
        with f.engine.begin() as setup:
            # A real PG constraint rejects only the terminal Audit INSERT.
            setup.execute(text("ALTER TABLE audit_events ADD CONSTRAINT codex_terminal_audit_failure "
                               "CHECK (action <> 'ar_process_terminal_registered')"))

        flushed_id, pending_id = str(uuid4()), str(uuid4())
        flushed = User(id=flushed_id, username=flushed_id, department_id='finance',
                       role='finance_user', status='active', password_hash='synthetic-unusable')
        pending = User(id=pending_id, username=pending_id, department_id='finance',
                       role='finance_user', status='active', password_hash='synthetic-unusable')
        f.db.add(flushed)
        f.db.flush()
        f.db.add(pending)
        caller_transaction = f.db.get_transaction()
        self.assertIsNotNone(caller_transaction)
        self.assertIn(pending, f.db.new)

        with self.assertRaises(TerminalProcessRegistrationError) as raised:
            execution.script('anchor_probe.py', [])
        error = raised.exception
        self.assertEqual(error.code, 'terminal_registration_failed')
        self.assertEqual(str(error), '原进程终态观察登记失败，不能继续执行。')
        self.assertNotIn('codex_terminal_audit_failure', str(error))
        self.assertNotIn('audit_events', str(error))
        self.assertIsInstance(error.__cause__, IntegrityError)
        self.assertEqual(error.__cause__.orig.sqlstate, '23514')
        self.assertEqual(error.__cause__.orig.diag.constraint_name, 'codex_terminal_audit_failure')
        self.assertIn('INSERT INTO audit_events', error.__cause__.statement)

        # The real no-op exited and all cleanup ran before the failing Audit.
        self.assertEqual(len(f.action._ar_process_records), 1)
        original = json.loads(json.dumps(f.action._ar_process_records[0]))
        self.assertEqual(original['state'], 'exited')
        self.assertTrue(original['direct_process_exit_confirmed'])
        self.assertTrue(f.action._ar_process_exit_confirmed)
        self.assertFalse(hasattr(f.action, '_ar_terminate_process'))
        record = f.root / 'execution-processes' / f.action_id / original['record_id']
        prepared = json.loads((record / 'prepared.json').read_text())
        started = json.loads((record / 'started.json').read_text())
        exited = json.loads((record / 'exited.json').read_text())
        receipt = json.loads((record / 'domain-exited.json').read_text())
        validate_receipt(receipt, token=prepared['domain_token'], supervisor_pid=started['pid'])
        self.assertGreaterEqual(receipt['reaped_count'], 1)
        self.assertEqual(exited['returncode'], 0)
        self.assertTrue(exited['communication_completed'])
        self.assertEqual(exited['stdout_sha256'], hashlib.sha256(b'synthetic anchor probe\n').hexdigest())
        facts = {name: (record / name).read_bytes() for name in
                 ('prepared.json', 'started.json', 'exited.json', 'domain-exited.json')}
        for name, key in (('prepared.json', 'prepared_sha256'), ('started.json', 'started_sha256'),
                          ('exited.json', 'exit_sha256'), ('domain-exited.json', 'domain_exit_sha256')):
            self.assertEqual(hashlib.sha256(facts[name]).hexdigest(), original[key])

        # Neither the failed independent transaction nor cleanup owns caller DML.
        self.assertIs(f.db.get_transaction(), caller_transaction)
        self.assertTrue(f.db.is_active)
        self.assertTrue(caller_transaction.is_active)
        self.assertIn(pending, f.db.new)
        self.assertEqual(flushed.id, flushed_id)
        with f.db.no_autoflush:
            self.assertEqual(f.db.scalar(select(User.id).where(User.id == flushed_id)), flushed_id)
            self.assertIsNone(f.db.scalar(select(User.id).where(User.id == pending_id)))

        with Session(f.engine) as reader:
            self.assertIsNone(reader.get(User, flushed_id))
            self.assertIsNone(reader.get(User, pending_id))
            workflow = reader.get(WorkflowSession, f.workflow_id)
            action = reader.get(WorkflowAction, f.action_id)
            context = json.loads(workflow.context_json)
            index = context['execution_safety_v1']
            entry = index['attempts'][0]
            self.assertEqual(len(index['attempts']), 1)
            self.assertEqual(index['revision'], original_index['revision'] + 1)
            self.assertNotIn('terminal_process_refs', entry)
            self.assertEqual(entry['status'], 'intent_recorded')
            for key, value in original_entry.items():
                self.assertEqual(entry[key], value)
            self.assertEqual(len(entry['prepared_process_refs']), 1)
            anchor = entry['prepared_process_refs'][0]
            self.assertEqual(anchor['record_id'], original['record_id'])
            self.assertEqual(anchor['prepared_sha256'], original['prepared_sha256'])
            self.assertEqual(anchor['binding_sha256'], f.original_binding)
            self.assertEqual(context['ar_execution'], before['ar_execution'])
            self.assertNotIn('ar_failure', context)
            self.assertEqual(action.state, 'running')
            self.assertEqual(action.attempt_count, 1)
            self.assertEqual(action.worker_id, 'synthetic-worker')
            self.assertEqual(json.loads(action.result_json), {})
            self.assertEqual(reader.scalar(select(func.count()).select_from(WorkflowAction)), 1)
            audits = list(reader.scalars(select(AuditEvent).where(AuditEvent.action.in_(
                ['ar_process_prepared_registered', 'ar_process_terminal_registered']))))
            self.assertEqual([row.action for row in audits], ['ar_process_prepared_registered'])
            self.assertEqual(json.loads(audits[0].details_json)['evidence_revision'], index['revision'])

            before_context, before_result = workflow.context_json, action.result_json
            audit_count = reader.scalar(select(func.count()).select_from(AuditEvent))
            mutations = []

            def observe_sql(connection, cursor, statement, parameters, execution_context, executemany):
                if statement.lstrip().split(None, 1)[0].upper() in {'INSERT', 'UPDATE', 'DELETE'}:
                    mutations.append(statement.lstrip().split(None, 1)[0].upper())

            event.listen(f.engine, 'before_cursor_execute', observe_sql)
            try:
                actual = read_execution(workflow, include_process_details=True)
                self.assertFalse(actual.attempt_history.process_evidence_checked)
                self.assertFalse(actual.attempt_history.authorizes_resume)
                self.assertEqual(actual.process_details.whole_workflow_coverage, 'unknown')
                self.assertEqual(len(actual.process_details.items), 1)
                item = actual.process_details.items[0]
                self.assertEqual(item.prepared_record_count, 1)
                self.assertIsNone(item.registered_terminal_count)
                self.assertIsNone(item.direct_exit_count)
                self.assertIsNone(item.descendant_domain_count)
                self.assertFalse(item.coverage_complete)
                self.assertIn('terminal_refs_missing', item.reason_codes)
                self.assertEqual(workflow.context_json, before_context)
                self.assertEqual(action.result_json, before_result)
                self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), audit_count)
            finally:
                event.remove(f.engine, 'before_cursor_execute', observe_sql)
            self.assertEqual(mutations, [])
            reader.expire(workflow, ['context_json'])
            self.assertEqual(workflow.context_json, before_context)

        self.assertIs(f.db.get_transaction(), caller_transaction)
        self.assertIn(pending, f.db.new)
        self.assertEqual({name: (record / name).read_bytes() for name in facts}, facts)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)
        f.db.rollback()  # The isolated caller, not terminal registration, owns cleanup.
        with Session(f.engine) as observer:
            self.assertIsNone(observer.get(User, flushed_id))
            self.assertIsNone(observer.get(User, pending_id))
            retained = json.loads(observer.get(WorkflowSession, f.workflow_id).context_json)
            self.assertEqual(retained['execution_safety_v1']['revision'], original_index['revision'] + 1)
            self.assertEqual(len(retained['execution_safety_v1']['attempts'][0]['prepared_process_refs']), 1)
            self.assertNotIn('terminal_process_refs', retained['execution_safety_v1']['attempts'][0])
            self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent)), audit_count)
        print(json.dumps({'event': 'codex_f4d_real_terminal_audit_failure', 'actual_noop_exits': 1,
                          'postgres_constraint_sqlstate': '23514', 'prepared_retained': 1,
                          'terminal_refs': 0, 'terminal_audits': 0, 'revision_partial_commit': False,
                          'caller_flushed_committed': False, 'caller_pending_preserved': True,
                          'reader_mutations': 0, 'financial_writer_invoked': False}, sort_keys=True))

    def test_identical_concurrent_terminal_registration_is_once_and_changed_observation_conflicts(self):
        from concurrent.futures import ThreadPoolExecutor
        from dataclasses import replace
        from threading import Barrier

        from app.ar_process_evidence import TerminalProcessRegistrationError

        f = self.fixture
        execution = ArExecution(f.db, f.action, f.workflow)
        original_revision = json.loads(f.workflow.context_json)['execution_safety_v1']['revision']
        recorder = execution.record_terminal
        captured, answers = {}, []

        def duplicate_original_callback(anchor, observation):
            captured.update(anchor=anchor, observation=observation)
            start = Barrier(2)

            def register():
                start.wait(timeout=5)
                return recorder(anchor, observation)

            with ThreadPoolExecutor(max_workers=2) as pool:
                calls = [pool.submit(register) for _ in range(2)]
                answers.extend(call.result(timeout=10) for call in calls)
            return answers[0]

        # Instrument the producer callback delivery; both registrars remain real.
        execution.record_terminal = duplicate_original_callback
        self.assertEqual(execution.script('anchor_probe.py', []).strip(), 'synthetic anchor probe')
        anchor, observation = captured['anchor'], captured['observation']
        self.assertEqual(observation.terminal_state, 'exited')
        self.assertEqual(answers[0], answers[1])
        self.assertEqual(recorder(anchor, observation), answers[0])
        changes = (replace(observation, exit_sha256=None),
                   replace(observation, exit_sha256='0' * 64),
                   replace(observation, terminal_state='exit_unconfirmed'))
        for changed in changes:
            with self.subTest(observation=changed):
                with self.assertRaises(TerminalProcessRegistrationError) as raised:
                    recorder(anchor, changed)
                self.assertEqual(raised.exception.code, 'terminal_ref_conflict')
                self.assertEqual(str(raised.exception), '原进程终态引用存在冲突，不能继续执行。')

        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            index = json.loads(workflow.context_json)['execution_safety_v1']
            entry = index['attempts'][0]
            self.assertEqual(index['revision'], original_revision + 2)
            self.assertEqual(len(entry['prepared_process_refs']), 1)
            self.assertEqual(entry['terminal_process_refs'], [answers[0]])
            self.assertEqual(entry['status'], 'intent_recorded')
            self.assertEqual(reader.get(WorkflowAction, f.action_id).state, 'running')
            audits = list(reader.scalars(select(AuditEvent).where(
                AuditEvent.action == 'ar_process_terminal_registered')))
            self.assertEqual(len(audits), 1)
            details = json.loads(audits[0].details_json)
            self.assertEqual(details['evidence_revision'], index['revision'])
            self.assertFalse(details['late_observation'])
            self.assertEqual(details['record_id'], anchor.record_id)
            actual = read_execution(workflow, include_process_details=True)
            self.assertEqual(actual.process_details.items[0].registered_terminal_count, 1)
            self.assertEqual(actual.process_details.items[0].direct_exit_count, 1)
            self.assertEqual(actual.process_details.items[0].descendant_domain_count, 1)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)
        print(json.dumps({'event': 'codex_f4d_duplicate_concurrent', 'actual_noop_exits': 1,
                          'real_concurrent_registrars': 2, 'exact_duplicates': 1,
                          'changed_observation_conflicts': 3, 'terminal_refs': 1,
                          'terminal_audits': 1, 'terminal_revision_increments': 1}, sort_keys=True))

    def test_late_original_callback_preserves_real_second_claim_and_new_context_material(self):
        from uuid import uuid4

        from app.ar_execution_safety import register_effect_intent
        from app.auth_models import UserSkillPermission
        from app.models import WorkflowMaterialSet, WorkflowMaterialSetFile

        f = self.fixture
        execution = ArExecution(f.db, f.action, f.workflow)
        recorder = execution.record_terminal
        captured = {}

        def columns(row, excluded=()):
            return {column.key: getattr(row, column.key) for column in row.__table__.columns
                    if column.key not in excluded}

        def migrate_then_register(anchor, observation):
            self.assertEqual(observation.terminal_state, 'exited')
            self.assertTrue(f.action._ar_process_exit_confirmed)
            self.assertFalse(hasattr(f.action, '_ar_terminate_process'))
            with Session(f.engine) as migration:
                old = migration.get(WorkflowAction, f.action_id)
                old.state = isolated_action_state('queued')
                old.worker_id, old.lease_expires_at = '', None
                migration.commit()
            with Session(f.engine, expire_on_commit=False) as claim_db:
                claimed = service.claim_next_workflow_action(claim_db, ('workflow',), 'synthetic-worker-two',
                                                             execution_contracts=(CONTRACT_VERSION,))
                self.assertIsNotNone(claimed)
                self.assertEqual(claimed.id, f.action_id)
                self.assertEqual(claimed.attempt_count, 2)
                workflow = claim_db.get(WorkflowSession, f.workflow_id)
                context = json.loads(workflow.context_json)
                prior = claim_db.get(WorkflowMaterialSet, workflow.material_set_id)
                prior.state = 'superseded'
                claim_db.flush()
                next_material = WorkflowMaterialSet(id=str(uuid4()), owner_id=workflow.owner_id,
                    department_id=workflow.department_id, skill_id=workflow.skill_id, version=2,
                    parent_set_id=prior.id, state='current')
                claim_db.add(next_material)
                claim_db.flush()
                prior_files = list(claim_db.scalars(select(WorkflowMaterialSetFile).where(
                    WorkflowMaterialSetFile.material_set_id == prior.id)))
                for bound in prior_files:
                    claim_db.add(WorkflowMaterialSetFile(id=str(uuid4()), material_set_id=next_material.id,
                        role=bound.role, year=bound.year, file_id=bound.file_id, sha256=bound.sha256))
                workflow.material_set_id = next_material.id
                context['ar_execution'].update(material_set_id=next_material.id, material_version=2)
                context.update(plan_fingerprint='b' * 64, newer_context_sentinel={'worker': 'two'},
                               stop_after_action=True, ar_failure={'newer_observation': True})
                register_effect_intent(context, workflow, claimed, 'write_ledger')
                workflow.context_json = json.dumps(context)
                claimed.result_json = json.dumps({'newer_attempt_result_sentinel': True})
                permission = claim_db.scalar(select(UserSkillPermission).where(
                    UserSkillPermission.user_id == workflow.owner_id))
                permission.can_run = False
                claim_db.commit()
            with Session(f.engine) as snapshot:
                workflow = snapshot.get(WorkflowSession, f.workflow_id)
                captured['context'] = json.loads(workflow.context_json)
                captured['workflow'] = columns(workflow, ('context_json',))
                captured['action'] = columns(snapshot.get(WorkflowAction, f.action_id))
                captured['materials'] = [columns(row) for row in snapshot.scalars(
                    select(WorkflowMaterialSet).order_by(WorkflowMaterialSet.id))]
                captured['files'] = [columns(row) for row in snapshot.scalars(
                    select(WorkflowMaterialSetFile).order_by(WorkflowMaterialSetFile.id))]
                captured['permissions'] = [columns(row) for row in snapshot.scalars(select(UserSkillPermission))]
            return recorder(anchor, observation)

        # Deliver the original frozen observation after a real new claim commits.
        execution.record_terminal = migrate_then_register
        self.assertEqual(execution.script('anchor_probe.py', []).strip(), 'synthetic anchor probe')
        with Session(f.engine) as observer:
            workflow = observer.get(WorkflowSession, f.workflow_id)
            context = json.loads(workflow.context_json)
            index = context.pop('execution_safety_v1')
            before = captured['context'].copy()
            before_index = before.pop('execution_safety_v1')
            self.assertEqual(context, before)
            self.assertEqual(index['revision'], before_index['revision'] + 1)
            self.assertEqual(index['attempts'][1], before_index['attempts'][1])
            self.assertNotIn('prepared_process_refs', index['attempts'][1])
            self.assertNotIn('terminal_process_refs', index['attempts'][1])
            old_entry = index['attempts'][0].copy()
            terminal = old_entry.pop('terminal_process_refs')
            self.assertEqual(old_entry, before_index['attempts'][0])
            self.assertEqual(len(terminal), 1)
            self.assertEqual(terminal[0]['binding_sha256'], f.original_binding)
            self.assertEqual(columns(observer.get(WorkflowAction, f.action_id)), captured['action'])
            self.assertEqual(columns(workflow, ('context_json',)), captured['workflow'])
            self.assertEqual([columns(row) for row in observer.scalars(
                select(WorkflowMaterialSet).order_by(WorkflowMaterialSet.id))], captured['materials'])
            self.assertEqual([columns(row) for row in observer.scalars(
                select(WorkflowMaterialSetFile).order_by(WorkflowMaterialSetFile.id))], captured['files'])
            self.assertEqual([columns(row) for row in observer.scalars(select(UserSkillPermission))], captured['permissions'])
            audits = list(observer.scalars(select(AuditEvent).where(AuditEvent.action == 'ar_process_terminal_registered')))
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].actor_id, 'system')
            details = json.loads(audits[0].details_json)
            self.assertEqual(details['attempt'], 1)
            self.assertTrue(details['late_observation'])
            self.assertEqual([entry['status'] for entry in index['attempts']], ['intent_recorded', 'intent_recorded'])
        journal = f.root / 'execution-processes' / f.action_id
        self.assertEqual(len(list(journal.glob('*/prepared.json'))), 1)
        self.assertEqual(len(list(journal.glob('*/domain-exited.json'))), 1)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)
        print(json.dumps({'event': 'codex_f4d_late_original_callback', 'actual_noop_exits': 1,
                          'real_second_claim_attempt': 2, 'new_attempt_children': 0,
                          'late_system_audits': 1, 'newer_columns_context_material_permission_preserved': True}, sort_keys=True))

    def test_actual_nonzero_timeout_fsync_and_sticky_loss_preserve_original_observations_and_causes(self):
        import subprocess

        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        from app.ar_execution_contract import ExecutionLeaseLost
        from app.ar_execution_safety import BINDING_FIELDS, _canonical
        from app.ar_process_evidence import TerminalProcessRegistrationError
        from app.registry import hash_skill_directory

        f = self.fixture
        script = f.root / 'skill/vendor/scripts/anchor_probe.py'
        script.write_text("import sys,time\nmode=sys.argv[1]\n"
                          "if mode=='nonzero': print('synthetic nonzero'); raise SystemExit(7)\n"
                          "if mode=='timeout': time.sleep(60)\n"
                          "print('synthetic anchor probe')\n", encoding='utf-8')
        # Pin the synthetic fixture before any prepared record is generated.
        f.workflow.skill_hash = hash_skill_directory(f.root / 'skill')
        context = json.loads(f.workflow.context_json)
        context['ar_execution']['skill_hash'] = f.workflow.skill_hash
        entry = context['execution_safety_v1']['attempts'][0]
        entry['skill_hash'] = f.workflow.skill_hash
        entry['binding_sha256'] = hashlib.sha256(_canonical({key: entry[key] for key in BINDING_FIELDS})).hexdigest()
        f.original_binding = entry['binding_sha256']
        f.workflow.context_json = json.dumps(context)
        f.db.commit()
        initial_revision = context['execution_safety_v1']['revision']
        native_fsync = evidence.os.fsync
        observed, terminal_successes = [], 0

        for mode in ('nonzero', 'timeout', 'fsync', 'fsync_audit', 'sticky'):
            with self.subTest(mode=mode):
                execution = ArExecution(f.db, f.action, f.workflow)
                calls = []
                disk_error = OSError('synthetic exited fsync failure')

                def actual_fsync_with_fault(fd):
                    calls.append(fd)
                    if mode in {'fsync', 'fsync_audit'} and len(calls) == 3:
                        raise disk_error
                    result = native_fsync(fd)
                    if mode == 'sticky' and len(calls) == 2:
                        f.action._ar_lease_lost = True
                    return result

                if mode == 'fsync_audit':
                    with f.engine.begin() as setup:
                        setup.execute(text("ALTER TABLE audit_events ADD CONSTRAINT codex_cleanup_audit_failure "
                            "CHECK (action <> 'ar_process_terminal_registered') NOT VALID"))
                try:
                    with patch.object(evidence.os, 'fsync', side_effect=actual_fsync_with_fault):
                        with self.assertRaises(Exception) as raised:
                            if mode == 'timeout':
                                evidence.run_recorded_script(execution.scripts, 'anchor_probe.py', ['timeout'],
                                    action=f.action, workflow=f.workflow, timeout=0.1,
                                    launch_gate=execution.launch_gate, original_binding_sha256=f.original_binding,
                                    terminal_recorder=execution.record_terminal)
                            else:
                                execution.script('anchor_probe.py', ['timeout' if mode == 'sticky' else mode])
                    error = raised.exception
                    if mode == 'nonzero':
                        self.assertIn('退出码 7', str(error))
                    elif mode == 'timeout':
                        self.assertIsInstance(error, subprocess.TimeoutExpired)
                    elif mode == 'fsync':
                        self.assertIs(error, disk_error)
                    elif mode == 'sticky':
                        self.assertIsInstance(error, ExecutionLeaseLost)
                    else:
                        self.assertIsInstance(error, TerminalProcessRegistrationError)
                        self.assertEqual(str(error), '原进程终态观察登记失败，不能继续执行。')
                        self.assertIs(error.original_error, disk_error)
                        self.assertIsInstance(error.__cause__, IntegrityError)
                        self.assertEqual(error.__cause__.orig.sqlstate, '23514')
                        chain, current = [], error
                        while current is not None and id(current) not in chain:
                            chain.append(id(current))
                            current = current.__cause__ or current.__context__
                        self.assertIn(id(disk_error), chain)
                finally:
                    if mode == 'fsync_audit':
                        with f.engine.begin() as setup:
                            setup.execute(text('ALTER TABLE audit_events DROP CONSTRAINT codex_cleanup_audit_failure'))
                self.assertFalse(hasattr(f.action, '_ar_terminate_process'))
                produced = json.loads(json.dumps(f.action._ar_process_records[-1]))
                observed.append(produced)
                record = f.root / 'execution-processes' / f.action_id / produced['record_id']
                self.assertTrue((record / 'exited.json').is_file())
                self.assertIsNotNone(produced['started_sha256'])
                if mode in {'fsync', 'fsync_audit'}:
                    self.assertEqual(produced['state'], 'exit_unconfirmed')
                    self.assertNotIn('exit_sha256', produced)
                else:
                    self.assertEqual(produced['state'], 'exited')
                if mode != 'fsync_audit':
                    terminal_successes += 1
                with Session(f.engine) as reader:
                    workflow = reader.get(WorkflowSession, f.workflow_id)
                    fresh = json.loads(workflow.context_json)['execution_safety_v1']
                    originals = fresh['attempts'][0]
                    refs = originals.get('terminal_process_refs', [])
                    self.assertEqual(len(refs), terminal_successes)
                    self.assertEqual(len(originals['prepared_process_refs']), len(observed))
                    self.assertEqual(fresh['revision'], initial_revision + len(observed) + terminal_successes)
                    self.assertEqual(originals['status'], 'intent_recorded')
                    matching = [ref for ref in refs if ref['record_id'] == produced['record_id']]
                    if mode == 'fsync_audit':
                        self.assertEqual(matching, [])
                    else:
                        self.assertEqual(len(matching), 1)
                        for key in ('started_sha256', 'exit_sha256', 'domain_exit_sha256'):
                            self.assertEqual(matching[0][key], produced.get(key))
                    self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent).where(
                        AuditEvent.action == 'ar_process_terminal_registered')), terminal_successes)
                    before = workflow.context_json
                    actual = read_execution(workflow, include_process_details=True)
                    if mode == 'nonzero':
                        self.assertTrue(actual.process_details.items[0].coverage_complete)
                        self.assertEqual(actual.process_details.items[0].direct_exit_count, 1)
                    else:
                        self.assertFalse(actual.process_details.items[0].coverage_complete)
                    self.assertEqual(workflow.context_json, before)
                    if mode == 'fsync_audit':
                        self.assertIsNone(actual.process_details.items[0].registered_terminal_count)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)
        print(json.dumps({'event': 'codex_f4d_actual_producer_failures', 'actual_children': len(observed),
                          'nonzero_exits': 1, 'actual_timeouts': 1, 'failed_exit_fsync': 2,
                          'sticky_lease_cleanup': 1, 'combined_cleanup_audit_failure_cause_chain': 1,
                          'registered_observations': terminal_successes, 'material_unchanged': True}, sort_keys=True))

    def test_unconfirmed_prepared_skips_terminal_sql_but_confirmed_gate_and_popen_denials_are_observed(self):
        from contextlib import contextmanager

        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        from app.ar_execution_contract import ExecutionCancelled

        f = self.fixture
        terminal_sql, outcomes = [], []
        native_commit = f.engine.dialect.do_commit

        for mode in ('before_commit', 'lost_ack', 'second_fence', 'popen_os_error'):
            with self.subTest(mode=mode):
                execution = ArExecution(f.db, f.action, f.workflow)
                recorder = execution.record_terminal
                connections, changed = set(), []
                callback_sql = []

                def mark_prepared(connection, cursor, statement, parameters, execution_context, executemany):
                    values = parameters.values() if isinstance(parameters, dict) else parameters
                    if statement.startswith('INSERT INTO audit_events') and 'ar_process_prepared_registered' in values:
                        connections.add(id(connection.connection.dbapi_connection))

                def commit_then_change(connection):
                    physical = getattr(connection, 'dbapi_connection', connection)
                    native_commit(connection)
                    if id(physical) in connections and not changed:
                        changed.append(True)
                        if mode == 'lost_ack':
                            raise RuntimeError('synthetic prepared acknowledgement lost')
                        with Session(f.engine) as editor:
                            workflow = editor.get(WorkflowSession, f.workflow_id)
                            context = json.loads(workflow.context_json)
                            context['stop_after_action'] = True
                            workflow.context_json = json.dumps(context)
                            editor.commit()

                def capture_terminal_sql(anchor, observation):
                    def observe(connection, cursor, statement, parameters, execution_context, executemany):
                        callback_sql.append(statement)

                    event.listen(f.engine, 'before_cursor_execute', observe)
                    try:
                        return recorder(anchor, observation)
                    finally:
                        event.remove(f.engine, 'before_cursor_execute', observe)

                @contextmanager
                def disappearing_cwd(anchor):
                    with execution.launch_gate(anchor):
                        moved = execution.scripts.with_name('temporarily-absent-scripts')
                        execution.scripts.rename(moved)
                        try:
                            yield
                        finally:
                            moved.rename(execution.scripts)

                execution.record_terminal = capture_terminal_sql
                if mode == 'before_commit':
                    with f.engine.begin() as setup:
                        setup.execute(text("ALTER TABLE audit_events ADD CONSTRAINT codex_before_prepared_failure "
                            "CHECK (action <> 'ar_process_prepared_registered') NOT VALID"))
                event.listen(f.engine, 'before_cursor_execute', mark_prepared)
                try:
                    with self.assertRaises(Exception) as raised:
                        if mode in {'lost_ack', 'second_fence'}:
                            with patch.object(f.engine.dialect, 'do_commit', side_effect=commit_then_change):
                                execution.script('anchor_probe.py', [])
                        elif mode == 'popen_os_error':
                            evidence.run_recorded_script(execution.scripts, 'anchor_probe.py', [],
                                action=f.action, workflow=f.workflow, launch_gate=disappearing_cwd,
                                original_binding_sha256=f.original_binding, terminal_recorder=capture_terminal_sql)
                        else:
                            execution.script('anchor_probe.py', [])
                    error = raised.exception
                    if mode == 'before_commit':
                        self.assertIsInstance(error, IntegrityError)
                        self.assertEqual(error.orig.sqlstate, '23514')
                    elif mode == 'lost_ack':
                        self.assertEqual(str(error), 'synthetic prepared acknowledgement lost')
                    elif mode == 'second_fence':
                        self.assertIsInstance(error, ExecutionCancelled)
                    else:
                        self.assertIsInstance(error, FileNotFoundError)
                finally:
                    event.remove(f.engine, 'before_cursor_execute', mark_prepared)
                    if mode == 'before_commit':
                        with f.engine.begin() as setup:
                            setup.execute(text('ALTER TABLE audit_events DROP CONSTRAINT codex_before_prepared_failure'))
                terminal_sql.append(len(callback_sql))
                produced = f.action._ar_process_records[-1]
                record = f.root / 'execution-processes' / f.action_id / produced['record_id']
                self.assertEqual(produced['state'], 'launch_unconfirmed')
                self.assertFalse((record / 'started.json').exists())
                self.assertFalse((record / 'exited.json').exists())
                self.assertFalse(hasattr(f.action, '_ar_terminate_process'))
                with Session(f.engine) as observer:
                    workflow = observer.get(WorkflowSession, f.workflow_id)
                    index = json.loads(workflow.context_json)['execution_safety_v1']
                    entry = index['attempts'][0]
                    prepared = [ref for ref in entry.get('prepared_process_refs', []) if ref['record_id'] == produced['record_id']]
                    terminal = [ref for ref in entry.get('terminal_process_refs', []) if ref['record_id'] == produced['record_id']]
                    self.assertEqual(len(prepared), 0 if mode == 'before_commit' else 1)
                    self.assertEqual(len(terminal), 0 if mode in {'before_commit', 'lost_ack'} else 1)
                    if terminal:
                        self.assertEqual(terminal[0]['terminal_state'], 'launch_unconfirmed')
                        self.assertTrue(all(terminal[0][key] is None for key in
                            ('started_sha256', 'exit_sha256', 'domain_exit_sha256')))
                        self.assertGreater(len(callback_sql), 0)
                    else:
                        self.assertEqual(callback_sql, [], 'unconfirmed preparation must not invoke terminal SQL')
                    self.assertEqual(entry['status'], 'intent_recorded')
                    self.assertEqual(observer.get(WorkflowAction, f.action_id).state, 'running')
                    outcomes.append((len(prepared), len(terminal)))
                if mode == 'second_fence':
                    with Session(f.engine) as editor:
                        workflow = editor.get(WorkflowSession, f.workflow_id)
                        context = json.loads(workflow.context_json)
                        context.pop('stop_after_action')
                        workflow.context_json = json.dumps(context)
                        editor.commit()
                    f.db.refresh(f.workflow)
        self.assertEqual(outcomes, [(0, 0), (1, 0), (1, 1), (1, 1)])
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)
        print(json.dumps({'event': 'codex_f4d_launch_denials', 'actual_children': 0,
                          'before_commit_terminal_sql': terminal_sql[0], 'lost_ack_terminal_sql': terminal_sql[1],
                          'confirmed_launch_unconfirmed_observations': 2, 'actual_popen_os_errors': 1}, sort_keys=True))

    def test_real_pg_caller_row_conflicts_time_out_without_committing_or_rolling_back_caller(self):
        from time import monotonic
        from uuid import uuid4

        from app.ar_process_evidence import TerminalProcessRegistrationError
        from app.auth_models import User

        f = self.fixture
        times = []
        for target, strict in (('action', False), ('workflow', True)):
            with self.subTest(target=target):
                execution = ArExecution(f.db, f.action, f.workflow)
                recorder = execution.record_terminal
                sentinel_id = str(uuid4())
                sentinel = User(id=sentinel_id, username=sentinel_id, department_id='finance',
                    role='finance_user', status='active', password_hash='synthetic-unusable')
                f.db.add(sentinel)
                f.db.flush()
                caller_transaction = f.db.get_transaction()
                limits = []

                def stricter_checkout(connection, record, proxy):
                    with connection.cursor() as cursor:
                        cursor.execute("SET lock_timeout = '250ms'")

                def capture_limits(connection, cursor, statement, parameters, execution_context, executemany):
                    if statement.startswith('SET LOCAL lock_timeout'):
                        limits.append(statement)

                def conflict_after_real_cleanup(anchor, observation):
                    self.assertEqual(observation.terminal_state, 'exited')
                    self.assertFalse(hasattr(f.action, '_ar_terminate_process'))
                    if target == 'action':
                        f.action.result_json = json.dumps({'caller_flushed_sentinel': True})
                    else:
                        f.workflow.error_message = 'synthetic caller-flushed workflow sentinel'
                    f.db.flush()  # The caller now holds the actual conflicting row lock.
                    if strict:
                        event.listen(f.engine, 'checkout', stricter_checkout)
                    event.listen(f.engine, 'before_cursor_execute', capture_limits)
                    started = monotonic()
                    try:
                        return recorder(anchor, observation)
                    finally:
                        times.append(monotonic() - started)
                        event.remove(f.engine, 'before_cursor_execute', capture_limits)
                        if strict:
                            event.remove(f.engine, 'checkout', stricter_checkout)

                execution.record_terminal = conflict_after_real_cleanup
                with self.assertRaises(TerminalProcessRegistrationError) as raised:
                    execution.script('anchor_probe.py', [])
                self.assertEqual(raised.exception.code, 'terminal_registration_lock_timeout')
                self.assertEqual(str(raised.exception), '原进程终态登记锁等待超时，不能继续执行。')
                self.assertEqual(raised.exception.__cause__.orig.sqlstate, '55P03')
                self.assertIs(f.db.get_transaction(), caller_transaction)
                self.assertTrue(caller_transaction.is_active)
                self.assertTrue(f.db.is_active)
                if strict:
                    self.assertEqual(limits, [], 'the smaller session timeout must not be raised')
                    self.assertLess(times[-1], 1)
                    self.assertEqual(f.workflow.error_message, 'synthetic caller-flushed workflow sentinel')
                else:
                    self.assertEqual(len(limits), 1)
                    self.assertGreater(times[-1], 1.5)
                    self.assertLess(times[-1], 3.5)
                    self.assertEqual(json.loads(f.action.result_json), {'caller_flushed_sentinel': True})
                with Session(f.engine) as observer:
                    self.assertIsNone(observer.get(User, sentinel_id))
                    workflow = observer.get(WorkflowSession, f.workflow_id)
                    action = observer.get(WorkflowAction, f.action_id)
                    entry = json.loads(workflow.context_json)['execution_safety_v1']['attempts'][0]
                    self.assertNotIn('terminal_process_refs', entry)
                    self.assertEqual(len(entry['prepared_process_refs']), len(times))
                    self.assertEqual(action.result_json, '{}')
                    self.assertEqual(workflow.error_message, '')
                    self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                        AuditEvent.action == 'ar_process_terminal_registered')), 0)
                f.db.rollback()  # Only this isolated caller releases its DML/row locks.
                with Session(f.engine) as observer:
                    self.assertIsNone(observer.get(User, sentinel_id))
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)
        print(json.dumps({'event': 'codex_f4d_actual_pg_row_conflicts', 'actual_noop_exits': 2,
                          'action_lock_timeout_seconds': times[0], 'workflow_stricter_timeout_seconds': times[1],
                          'caller_transaction_preserved': True, 'terminal_partial_commits': 0}, sort_keys=True))

    def test_bad_current_legacy_result_does_not_erase_valid_original_failure_bridge(self):
        from app.ar_execution_safety import register_effect_intent

        f = self.fixture

        def legacy_v1_producer(execution, binding):
            # Explicit old-v1 producer: no new callback is supplied or erased later.
            return evidence.run_recorded_script(execution.scripts, 'anchor_probe.py', [],
                action=execution.action, workflow=execution.workflow,
                launch_gate=execution.launch_gate, original_binding_sha256=binding,
                terminal_recorder=None)

        self.assertEqual(legacy_v1_producer(ArExecution(f.db, f.action, f.workflow),
                                           f.original_binding).strip(), 'synthetic anchor probe')
        first_record = json.loads(json.dumps(f.action._ar_process_records[-1]))
        f.db.refresh(f.action)
        f.action.state = isolated_action_state('queued')
        f.action.worker_id, f.action.lease_expires_at = '', None
        f.db.commit()
        with Session(f.engine, expire_on_commit=False) as second_db:
            claimed = service.claim_next_workflow_action(second_db, ('workflow',), 'synthetic-worker-two',
                                                         execution_contracts=(CONTRACT_VERSION,))
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.attempt_count, 2)
            workflow = second_db.get(WorkflowSession, f.workflow_id)
            context = json.loads(workflow.context_json)
            register_effect_intent(context, workflow, claimed, 'write_ledger')
            binding = context['execution_safety_v1']['attempts'][1]['binding_sha256']
            workflow.context_json = json.dumps(context)
            second_db.commit()
            second = ArExecution(second_db, claimed, workflow)
            self.assertEqual(legacy_v1_producer(second, binding).strip(), 'synthetic anchor probe')
            second_db.refresh(workflow)
            context = json.loads(workflow.context_json)
            context['ar_failure'] = {'action_id': f.action_id, 'phase': 'write_ledger',
                'process_evidence_version': evidence.SCHEMA_VERSION, 'process_records': [first_record]}
            workflow.context_json = json.dumps(context)
            claimed.result_json = '{synthetic invalid current result'
            second_db.commit()
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            context = json.loads(workflow.context_json)
            self.assertTrue(all('terminal_process_refs' not in entry
                                for entry in context['execution_safety_v1']['attempts']))
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == 'ar_process_terminal_registered')), 0)
            self.assertEqual(len(list((f.root / 'execution-processes' / f.action_id).glob('*/domain-exited.json'))), 2)
            actual = read_execution(workflow, include_process_details=True)
            items = {item.attempt: item for item in actual.process_details.items}
            print(json.dumps({'event': 'codex_f4d_legacy_independent_sources', 'actual_noop_exits': 2,
                              'explicit_legacy_entries': 2, 'valid_original_failure_bridge': 1,
                              'bad_current_result_sources': 1}, sort_keys=True))
            self.assertEqual(set(items), {1, 2})
            self.assertTrue(items[1].coverage_complete, 'bad latest source must not erase valid original failure bridge')
            self.assertEqual(items[1].registered_terminal_count, 1)
            self.assertEqual(items[1].direct_exit_count, 1)
            self.assertEqual(items[1].descendant_domain_count, 1)
            self.assertFalse(items[2].coverage_complete)
            self.assertIn('terminal_refs_missing', items[2].reason_codes)
            self.assertIn('terminal_refs_conflict', actual.process_details.reason_codes)
            self.assertEqual(workflow.context_json, json.dumps(context))
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)

    def test_authoritative_new_refs_ignore_bad_mutable_sources_and_reject_malformed_or_partial_storage(self):
        f = self.fixture
        execution = ArExecution(f.db, f.action, f.workflow)
        self.assertEqual(execution.script('anchor_probe.py', []).strip(), 'synthetic anchor probe')
        produced = json.loads(json.dumps(f.action._ar_process_records[-1]))
        with Session(f.engine) as reader:
            baseline_context = json.loads(reader.get(WorkflowSession, f.workflow_id).context_json)
        record = f.root / 'execution-processes' / f.action_id / produced['record_id']
        before_facts = {path.name: path.read_bytes() for path in record.iterdir()}
        modes = ('invalid_json', 'oversized_payload', 'malformed_new', 'empty_new', 'missing_exit_file')
        observed = []
        for mode in modes:
            with self.subTest(mode=mode):
                context = json.loads(json.dumps(baseline_context))
                entry = context['execution_safety_v1']['attempts'][0]
                # Corrupted/partial storage variants test the reader, not legal registrar upgrades.
                if mode == 'malformed_new':
                    entry['terminal_process_refs'][0]['binding_sha256'] = '0' * 64
                elif mode == 'empty_new':
                    entry['terminal_process_refs'] = []
                context['ar_failure'] = {'action_id': f.action_id, 'phase': 'write_ledger',
                    'process_evidence_version': evidence.SCHEMA_VERSION, 'process_records': [produced]}
                with Session(f.engine) as editor:
                    workflow = editor.get(WorkflowSession, f.workflow_id)
                    workflow.context_json = json.dumps(context)
                    action = editor.get(WorkflowAction, f.action_id)
                    action.result_json = ('{' if mode != 'oversized_payload' else
                                          json.dumps({'synthetic_oversized': 'x' * (256 * 1024)}))
                    editor.commit()
                if mode == 'missing_exit_file':
                    (record / 'exited.json').unlink()
                try:
                    with Session(f.engine) as reader:
                        workflow = reader.get(WorkflowSession, f.workflow_id)
                        before_context = workflow.context_json
                        before_audits = reader.scalar(select(func.count()).select_from(AuditEvent))
                        actual = read_execution(workflow, include_process_details=True)
                        item = actual.process_details.items[0]
                        if mode in {'invalid_json', 'oversized_payload'}:
                            self.assertTrue(item.coverage_complete)
                            self.assertEqual(item.registered_terminal_count, 1)
                            self.assertEqual(item.direct_exit_count, 1)
                            self.assertEqual(item.descendant_domain_count, 1)
                            self.assertNotIn('budget_exceeded', item.reason_codes)
                        elif mode == 'malformed_new':
                            self.assertFalse(item.coverage_complete)
                            self.assertIsNone(item.registered_terminal_count)
                            self.assertIn('terminal_refs_conflict', item.reason_codes)
                        elif mode == 'empty_new':
                            self.assertFalse(item.coverage_complete)
                            self.assertIsNone(item.registered_terminal_count)
                            self.assertIn('terminal_refs_missing', item.reason_codes)
                        else:
                            self.assertFalse(item.coverage_complete)
                            self.assertEqual(item.registered_terminal_count, 1)
                            self.assertIsNone(item.direct_exit_count)
                            self.assertIsNone(item.descendant_domain_count)
                            self.assertIn('fact_missing', item.reason_codes)
                        self.assertEqual(workflow.context_json, before_context)
                        self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), before_audits)
                        observed.append(mode)
                finally:
                    if mode == 'missing_exit_file':
                        (record / 'exited.json').write_bytes(before_facts['exited.json'])
        self.assertEqual({path.name: path.read_bytes() for path in record.iterdir()}, before_facts)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)
        print(json.dumps({'event': 'codex_f4d_authoritative_new_reader', 'actual_noop_exits': 1,
                          'reader_variants_executed': observed, 'mutable_fallback_on_invalid_new': False,
                          'missing_file_registered_count': 1, 'partial_observation_registered_count': None}, sort_keys=True))

    def test_actual_started_fsync_failure_has_known_zero_registration_and_visible_bytes_do_not_repair_sha(self):
        f = self.fixture
        execution = ArExecution(f.db, f.action, f.workflow)
        native_fsync, calls = evidence.os.fsync, []
        failure = OSError('synthetic started fsync failure')

        def fail_started(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise failure
            return native_fsync(fd)

        with patch.object(evidence.os, 'fsync', side_effect=fail_started):
            with self.assertRaises(OSError) as raised:
                execution.script('anchor_probe.py', [])
        self.assertIs(raised.exception, failure)
        self.assertFalse(hasattr(f.action, '_ar_terminate_process'))
        produced = f.action._ar_process_records[-1]
        self.assertNotIn('started_sha256', produced)
        record = f.root / 'execution-processes' / f.action_id / produced['record_id']
        self.assertTrue((record / 'started.json').is_file())
        self.assertGreater((record / 'started.json').stat().st_size, 0)
        files = {path.name: path.read_bytes() for path in record.iterdir()}
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            before = workflow.context_json
            index = json.loads(before)['execution_safety_v1']
            entry = index['attempts'][0]
            self.assertEqual(len(entry['terminal_process_refs']), 1)
            self.assertIsNone(entry['terminal_process_refs'][0]['started_sha256'])
            self.assertEqual(entry['status'], 'intent_recorded')
            audits = reader.scalar(select(func.count()).select_from(AuditEvent))
            actual = read_execution(workflow, include_process_details=True)
            item = actual.process_details.items[0]
            self.assertEqual(item.prepared_record_count, 1)
            self.assertEqual(item.registered_terminal_count, 0)
            self.assertIsNone(item.direct_exit_count)
            self.assertIsNone(item.descendant_domain_count)
            self.assertFalse(item.coverage_complete)
            self.assertIn('terminal_refs_missing', item.reason_codes)
            self.assertEqual(workflow.context_json, before)
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), audits)
            reader.expire(workflow, ['context_json'])
            self.assertEqual(workflow.context_json, before)
        self.assertEqual({path.name: path.read_bytes() for path in record.iterdir()}, files)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)
        print(json.dumps({'event': 'codex_f4d_real_known_zero', 'actual_spawned_cleanup': 1,
                          'started_fact_visible': True, 'original_started_sha': None,
                          'registered_terminal_count': 0, 'reader_sha_repair': False}, sort_keys=True))

    def test_real_terminal_commit_lost_ack_keeps_one_ref_and_audit_without_business_completion(self):
        f = self.fixture
        execution = ArExecution(f.db, f.action, f.workflow)
        recorder = execution.record_terminal
        captured, transactions, lost = {}, set(), []
        native_commit = f.engine.dialect.do_commit

        def mark_terminal(connection, cursor, statement, parameters, execution_context, executemany):
            values = parameters.values() if isinstance(parameters, dict) else parameters
            if statement.startswith('INSERT INTO audit_events') and 'ar_process_terminal_registered' in values:
                transactions.add(id(connection.connection.dbapi_connection))

        def commit_then_lose_ack(connection):
            physical = getattr(connection, 'dbapi_connection', connection)
            native_commit(connection)
            if id(physical) in transactions and not lost:
                lost.append(True)
                raise RuntimeError('synthetic terminal acknowledgement lost')

        def remember_observation(anchor, observation):
            captured.update(anchor=anchor, observation=observation)
            return recorder(anchor, observation)

        execution.record_terminal = remember_observation
        event.listen(f.engine, 'before_cursor_execute', mark_terminal)
        try:
            with patch.object(f.engine.dialect, 'do_commit', side_effect=commit_then_lose_ack):
                with self.assertRaises(evidence.TerminalProcessRegistrationError) as raised:
                    execution.script('anchor_probe.py', [])
        finally:
            event.remove(f.engine, 'before_cursor_execute', mark_terminal)
        self.assertEqual(lost, [True])
        self.assertEqual(raised.exception.code, 'terminal_registration_failed')
        self.assertEqual(str(raised.exception), '原进程终态观察登记失败，不能继续执行。')
        self.assertEqual(str(raised.exception.__cause__), 'synthetic terminal acknowledgement lost')
        self.assertTrue(f.action._ar_process_exit_confirmed)
        self.assertFalse(hasattr(f.action, '_ar_terminate_process'))
        f.db.rollback()  # An outer failure cannot roll back the independent actual commit.
        with Session(f.engine) as observer:
            workflow = observer.get(WorkflowSession, f.workflow_id)
            index = json.loads(workflow.context_json)['execution_safety_v1']
            entry = index['attempts'][0]
            self.assertEqual(entry['status'], 'intent_recorded')
            self.assertNotIn('completed_at', entry)
            self.assertEqual(len(entry['terminal_process_refs']), 1)
            self.assertEqual(index['revision'], 3)
            self.assertEqual(observer.get(WorkflowAction, f.action_id).state, 'running')
            self.assertEqual(observer.get(WorkflowAction, f.action_id).result_json, '{}')
            self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == 'ar_process_terminal_registered')), 1)
            before = workflow.context_json
            actual = read_execution(workflow, include_process_details=True)
            self.assertEqual(actual.process_details.items[0].registered_terminal_count, 1)
            self.assertEqual(actual.process_details.whole_workflow_coverage, 'unknown')
        # Explicit duplicate delivery observes the committed ref; it does not retry a writer.
        self.assertEqual(recorder(captured['anchor'], captured['observation']), entry['terminal_process_refs'][0])
        with Session(f.engine) as observer:
            self.assertEqual(observer.get(WorkflowSession, f.workflow_id).context_json, before)
            self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == 'ar_process_terminal_registered')), 1)
        self.assertEqual(len(list((f.root / 'execution-processes' / f.action_id).glob('*/started.json'))), 1)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)
        print(json.dumps({'event': 'codex_f4d_terminal_commit_lost_ack', 'actual_noop_exits': 1,
                          'real_terminal_commits': 1, 'terminal_refs_audits_once': True,
                          'business_completed': False, 'writer_retries': 0}, sort_keys=True))

    def test_original_terminal_bridge_rejects_cross_scope_missing_pin_and_strict_type_changes(self):
        from dataclasses import replace

        f = self.fixture
        execution = ArExecution(f.db, f.action, f.workflow)
        recorder, captured = execution.record_terminal, {}

        def remember(anchor, observation):
            captured.update(anchor=anchor, observation=observation)
            return recorder(anchor, observation)

        execution.record_terminal = remember
        self.assertEqual(execution.script('anchor_probe.py', []).strip(), 'synthetic anchor probe')
        anchor, observation = captured['anchor'], captured['observation']
        with Session(f.engine) as observer:
            baseline = observer.get(WorkflowSession, f.workflow_id).context_json

        def identity_change(field, value):
            return replace(anchor, prepared_identity=tuple((key, value if key == field else original)
                for key, original in anchor.prepared_identity))

        invalid = (replace(anchor, binding_sha256=None), replace(anchor, binding_sha256='0' * 64),
                   replace(anchor, script_sha256='0' * 64), replace(anchor, arguments_sha256='0' * 64),
                   identity_change('attempt', True), identity_change('action_id', 'synthetic-foreign-action'),
                   identity_change('workflow_id', 'synthetic-foreign-workflow'))
        for changed in invalid:
            with self.subTest(anchor=changed):
                with self.assertRaises(evidence.TerminalProcessRegistrationError) as raised:
                    recorder(changed, observation)
                self.assertIn(raised.exception.code, {'terminal_binding_invalid', 'terminal_registration_failed'})
                self.assertNotIn('synthetic-foreign', str(raised.exception))
                with Session(f.engine) as observer:
                    self.assertEqual(observer.get(WorkflowSession, f.workflow_id).context_json, baseline)
                    self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                        AuditEvent.action == 'ar_process_terminal_registered')), 1)
        skipped_sql = []

        def observe(connection, cursor, statement, parameters, execution_context, executemany):
            skipped_sql.append(statement)

        event.listen(f.engine, 'before_cursor_execute', observe)
        try:
            self.assertIsNone(recorder(replace(anchor, record_id='1' * 32), observation))
        finally:
            event.remove(f.engine, 'before_cursor_execute', observe)
        self.assertEqual(skipped_sql, [], 'unconfirmed record never becomes terminal eligibility')

        for mode in ('prepared_absent', 'stable_department_changed'):
            with self.subTest(storage=mode):
                context = json.loads(baseline)
                if mode == 'prepared_absent':
                    context['execution_safety_v1']['attempts'][0]['prepared_process_refs'] = []
                with Session(f.engine) as editor:
                    workflow = editor.get(WorkflowSession, f.workflow_id)
                    workflow.context_json = json.dumps(context)
                    workflow.department_id = 'synthetic-other-department' if mode != 'prepared_absent' else 'finance'
                    editor.commit()
                with self.assertRaises(evidence.TerminalProcessRegistrationError):
                    recorder(anchor, observation)
                with Session(f.engine) as observer:
                    workflow = observer.get(WorkflowSession, f.workflow_id)
                    self.assertEqual(json.loads(workflow.context_json), context)
                    self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                        AuditEvent.action == 'ar_process_terminal_registered')), 1)
                with Session(f.engine) as editor:
                    workflow = editor.get(WorkflowSession, f.workflow_id)
                    workflow.context_json, workflow.department_id = baseline, 'finance'
                    editor.commit()
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)
        print(json.dumps({'event': 'codex_f4d_strict_original_bridge', 'actual_noop_exits': 1,
                          'changed_frozen_anchor_rejections': len(invalid), 'missing_confirmed_record_sql': 0,
                          'fresh_storage_scope_rejections': 2, 'terminal_refs_audits_unchanged': True}, sort_keys=True))

    def test_actual_supervisor_receipt_validation_failure_preserves_nullable_original_observation(self):
        f = self.fixture
        execution = ArExecution(f.db, f.action, f.workflow)
        original_action_result = f.action.result_json
        native_communicate = evidence.subprocess.Popen.communicate
        completed = []

        def corrupt_owned_receipt_after_real_communicate(process, *args, **kwargs):
            output = native_communicate(process, *args, **kwargs)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(output[0].strip(), 'synthetic anchor probe')
            produced = f.action._ar_process_records[-1]
            record = f.root / 'execution-processes' / f.action_id / produced['record_id']
            self.assertTrue(record.resolve().is_relative_to(f.root.resolve()))
            receipt = record / 'domain-exited.json'
            self.assertTrue(receipt.is_file())
            self.assertFalse(receipt.is_symlink())
            fact = json.loads(receipt.read_bytes())
            prepared = json.loads((record / 'prepared.json').read_bytes())
            self.assertEqual(fact['token'], prepared['domain_token'])
            self.assertEqual(fact['supervisor_pid'], process.pid)
            self.assertTrue(fact['all_descendants_reaped'])
            self.assertEqual(fact['script_returncode'], 0)
            fact['token'] = 'synthetic-invalid-original-domain-token'
            corrupted = json.dumps(fact, sort_keys=True).encode('utf-8')
            with receipt.open('wb') as stream:
                stream.write(corrupted)
                stream.flush()
                os.fsync(stream.fileno())
            completed.append((process, record, produced['started_sha256'], corrupted))
            return output

        with patch.object(evidence.subprocess.Popen, 'communicate', new=corrupt_owned_receipt_after_real_communicate):
            with self.assertRaises(ValueError) as raised:
                execution.script('anchor_probe.py', [])
        self.assertEqual(str(raised.exception), '脚本后代进程退出证明不完整。')
        self.assertEqual(len(completed), 1)
        process, record, original_started_sha, corrupted = completed[0]
        self.assertEqual(process.poll(), 0)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)
        self.assertFalse(hasattr(f.action, '_ar_terminate_process'))
        self.assertFalse(f.action._ar_process_exit_confirmed)
        produced = f.action._ar_process_records[-1]
        self.assertEqual(produced['state'], 'exit_unconfirmed')
        self.assertEqual(produced['started_sha256'], original_started_sha)
        self.assertNotIn('exit_sha256', produced)
        self.assertNotIn('domain_exit_sha256', produced)
        self.assertFalse((record / 'exited.json').exists())
        self.assertEqual((record / 'domain-exited.json').read_bytes(), corrupted)
        files = {path.name: path.read_bytes() for path in record.iterdir()}
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            action = reader.get(WorkflowAction, f.action_id)
            before = workflow.context_json
            entry = json.loads(before)['execution_safety_v1']['attempts'][0]
            self.assertEqual(entry['status'], 'intent_recorded')
            self.assertIsNone(entry.get('completed_at'))
            self.assertIsNone(entry.get('result_sha256'))
            self.assertEqual(action.state, 'running')
            self.assertEqual(action.result_json, original_action_result)
            self.assertEqual(len(entry['prepared_process_refs']), 1)
            self.assertEqual(len(entry['terminal_process_refs']), 1)
            terminal = entry['terminal_process_refs'][0]
            self.assertEqual(terminal['record_id'], produced['record_id'])
            self.assertEqual(terminal['prepared_sha256'], produced['prepared_sha256'])
            self.assertEqual(terminal['binding_sha256'], f.original_binding)
            self.assertEqual(terminal['terminal_state'], 'exit_unconfirmed')
            self.assertEqual(terminal['started_sha256'], original_started_sha)
            self.assertIsNone(terminal['exit_sha256'])
            self.assertIsNone(terminal['domain_exit_sha256'])
            audits = reader.scalar(select(func.count()).select_from(AuditEvent))
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == 'ar_process_terminal_registered')), 1)
            actual = read_execution(workflow, include_process_details=True)
            item = actual.process_details.items[0]
            self.assertEqual(item.prepared_record_count, 1)
            self.assertEqual(item.registered_terminal_count, 0)
            self.assertIsNone(item.direct_exit_count)
            self.assertIsNone(item.descendant_domain_count)
            self.assertFalse(item.coverage_complete)
            self.assertEqual(item.inspection_state, 'unknown')
            self.assertIn('terminal_refs_missing', item.reason_codes)
            self.assertEqual(actual.process_details.whole_workflow_coverage, 'unknown')
            self.assertEqual(workflow.context_json, before)
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), audits)
            reader.expire(workflow, ['context_json'])
            self.assertEqual(workflow.context_json, before)
        self.assertEqual({path.name: path.read_bytes() for path in record.iterdir()}, files)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)
        print(json.dumps({'event': 'codex_f4d_actual_receipt_validation_failure',
                          'actual_noop_exits': 1, 'real_communicate_completed': True,
                          'corrupted_receipt_fsynced': True, 'original_value_error_preserved': True,
                          'pipes_closed_callback_removed': True, 'started_sha_preserved': True,
                          'exit_domain_sha_null': True, 'registered_terminal_count': 0,
                          'reader_mutations': 0, 'material_unchanged': True}, sort_keys=True))
