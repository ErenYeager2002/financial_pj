"""Opt-in original-attempt process observation; real isolated PG and no-op children only."""
from functools import wraps
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
from app.ar_execution_safety import _prepared_process_refs, _state, current_material_blocker
from app.ar_execution_service import read_execution
from app.models import AuditEvent, WorkflowAction, WorkflowSession
from app.workflow_action_state import isolated_action_state

URL = 'postgresql+psycopg://synthetic:synthetic-only@127.0.0.1:5432/material_policy_test'


def legacy_terminal_payload_fixture(builder):
    """Construct pre-terminal-ref producers; preserve all real gates, facts and payloads.

    The old producer API had no terminal registration callback. Reproduce that
    opt-out while constructing this declared legacy fixture; never remove fresh
    immutable references after production. New registration is tested separately.
    """
    @wraps(builder)
    def build_legacy(*args, **kwargs):
        recorded_script = evidence.run_recorded_script

        def legacy_recorded_script(*script_args, **script_kwargs):
            script_kwargs.pop('terminal_recorder', None)
            return recorded_script(*script_args, **script_kwargs)

        with patch.object(evidence, 'run_recorded_script', legacy_recorded_script):
            return builder(*args, **kwargs)

    return build_legacy


class AttemptProcessDetailsPostgresTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.environ.get('AR_POLICY_SYNTHETIC_DB_URL'), URL)
        # Composition avoids collecting the existing 21 tests or changing their fixture source.
        from test_ar_process_anchor_postgres import ArProcessAnchorPostgresTests
        self.fixture = ArProcessAnchorPostgresTests('test_prepared_reference_and_audit_are_visible_before_popen')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    @legacy_terminal_payload_fixture
    def registered_two_attempts(self):
        f = self.fixture
        first = ArExecution(f.db, f.action, f.workflow)
        self.assertEqual(first.script('anchor_probe.py', []).strip(), 'synthetic anchor probe')
        # The earlier no-op exited, but its terminal payload was never committed.
        # Files existing on disk do not replace the original registered fingerprints.
        f.db.refresh(f.workflow)
        f.db.refresh(f.action)
        prior = json.loads(f.workflow.context_json)['execution_safety_v1']['attempts'][0]
        self.assertEqual(prior['status'], 'intent_recorded')
        self.assertEqual(len(prior['prepared_process_refs']), 1)
        self.assertNotIn('terminal_process_refs', prior)
        self.assertEqual(json.loads(f.action.result_json), {})
        f.action.state = isolated_action_state('queued')
        f.action.worker_id, f.action.lease_expires_at = '', None
        f.db.commit()

        def synthetic_write_ledger(execution):
            self.assertEqual(execution.script('anchor_probe.py', []).strip(), 'synthetic anchor probe')
            return {'synthetic_noop': True}

        with Session(f.engine, expire_on_commit=False) as run_db:
            claimed = service.claim_next_workflow_action(run_db, ('workflow',), 'synthetic-worker-two',
                                                        execution_contracts=(CONTRACT_VERSION,))
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.id, f.action_id)
            self.assertEqual(claimed.attempt_count, 2)
            workflow = run_db.get(WorkflowSession, f.workflow_id)
            # Preserve claim/permission/material/safety/execute_phase/transition wiring.
            # The financial writer alone is replaced by a fixed no-op handler.
            with patch.object(ArExecution, 'write_ledger', synthetic_write_ledger):
                result = execute_phase(run_db, claimed, workflow)
            transition_phase(run_db, claimed, workflow, result)
            run_db.commit()

        return prior

    def test_latest_terminal_proof_preserves_earlier_unknown_original_attempt(self):
        f = self.fixture
        prior = self.registered_two_attempts()

        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            context = json.loads(workflow.context_json)
            index = _state(context, workflow.id)
            refs = _prepared_process_refs(index)
            self.assertEqual(len(index['attempts']), 2)
            self.assertEqual(index['attempts'][0], prior)
            self.assertEqual(index['attempts'][1]['status'], 'phase_completed')
            self.assertNotEqual(index['attempts'][0]['binding_sha256'], index['attempts'][1]['binding_sha256'])
            self.assertEqual(len(refs), 2)
            latest = reader.get(WorkflowAction, f.action_id)
            self.assertEqual(latest.attempt_count, 2)
            terminal_payload = json.loads(latest.result_json)
            self.assertTrue(terminal_payload['synthetic_noop'])
            self.assertEqual(len(terminal_payload['process_records']), 1)
            current_record = terminal_payload['process_records'][0]
            self.assertEqual(current_record['record_id'], index['attempts'][1]['prepared_process_refs'][0]['record_id'])
            self.assertNotIn('attempt', terminal_payload)
            self.assertNotIn('worker_id', terminal_payload)
            for key in ('started_sha256', 'exit_sha256', 'domain_exit_sha256'):
                self.assertEqual(len(current_record[key]), 64)
            journal = f.root / 'execution-processes' / f.action_id
            self.assertEqual({path.name for path in journal.iterdir()}, {ref['record_id'] for _, ref in refs})
            before_files = {str(path.relative_to(journal)): path.read_bytes()
                            for path in journal.rglob('*') if path.is_file()}
            for _, ref in refs:
                for fact_name in ('prepared.json', 'started.json', 'exited.json', 'domain-exited.json'):
                    self.assertTrue((journal / ref['record_id'] / fact_name).is_file())
            before_context = workflow.context_json
            before_action = {column.key: getattr(latest, column.key) for column in latest.__table__.columns}
            before_audits = reader.scalar(select(func.count()).select_from(AuditEvent))
            baseline = read_execution(workflow)
            before_occupancy = current_material_blocker(reader, workflow.owner_id, workflow.department_id,
                                                        workflow.skill_id)
            self.assertIsNotNone(before_occupancy)
            self.assertEqual(before_occupancy['reason'], 'unresolved_write')
            print(json.dumps({'event': 'codex_f4c_two_attempt_fixture', 'registered_attempt_count': 2,
                              'prepared_records': 2, 'latest_terminal_refs': 1,
                              'earlier_terminal_refs_registered': False, 'true_noop_outputs': 2,
                              'linux_domain_receipts': 2, 'financial_writer_invoked': False}, sort_keys=True))
            mutations, commits = [], []

            def observe_sql(connection, cursor, statement, parameters, execution_context, executemany):
                verb = statement.lstrip().split(None, 1)[0].upper()
                if verb in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER'}:
                    mutations.append(verb)

            def observe_commit(connection):
                commits.append(True)

            event.listen(f.engine, 'before_cursor_execute', observe_sql)
            event.listen(f.engine, 'commit', observe_commit)
            try:
                with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('read must not spawn')) as popen:
                    actual = read_execution(workflow, include_process_details=True)
                    self.assertEqual(popen.call_count, 0)
                self.assertIsNotNone(actual.process_details)
                details = actual.process_details
                self.assertEqual(details.schema_version, 'ar-attempt-process-details-v1')
                self.assertEqual(details.metadata_snapshot_fingerprint, baseline.attempt_history.snapshot_fingerprint)
                self.assertEqual(details.evidence_revision, index['revision'])
                self.assertFalse(details.registered_effect_coverage_complete)
                self.assertEqual(details.whole_workflow_coverage, 'unknown')
                items = {(str(item.action_id), item.attempt): item for item in details.items}
                self.assertEqual(set(items), {(f.action_id, 1), (f.action_id, 2)})
                earlier, current = items[(f.action_id, 1)], items[(f.action_id, 2)]
                self.assertEqual(earlier.inspection_state, 'unknown')
                self.assertEqual(earlier.prepared_record_count, 1)
                self.assertFalse(earlier.coverage_complete)
                for quantity in ('registered_terminal_count', 'direct_exit_count', 'descendant_domain_count'):
                    self.assertIsNone(getattr(earlier, quantity))
                self.assertIn('terminal_refs_missing', earlier.reason_codes)
                self.assertEqual(current.inspection_state, 'verified')
                self.assertTrue(current.coverage_complete)
                for quantity in ('prepared_record_count', 'registered_terminal_count', 'direct_exit_count',
                                 'descendant_domain_count'):
                    self.assertEqual(getattr(current, quantity), 1)
                self.assertNotIn('directory_extra', details.reason_codes)
                for item in details.items:
                    self.assertNotIn('directory_extra', item.reason_codes)
                self.assertEqual(actual.attempt_history, baseline.attempt_history)
                self.assertFalse(actual.attempt_history.process_evidence_checked)
                self.assertFalse(actual.attempt_history.authorizes_resume)
                self.assertEqual(actual.model_dump(exclude={'process_details'}),
                                 baseline.model_dump(exclude={'process_details'}))
                self.assertEqual(read_execution(workflow).model_dump(), baseline.model_dump())
                self.assertEqual(current_material_blocker(reader, workflow.owner_id, workflow.department_id,
                                                         workflow.skill_id), before_occupancy)
                self.assertEqual(workflow.context_json, before_context)
                self.assertEqual({column.key: getattr(latest, column.key) for column in latest.__table__.columns},
                                 before_action)
                self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), before_audits)
            finally:
                event.remove(f.engine, 'before_cursor_execute', observe_sql)
                event.remove(f.engine, 'commit', observe_commit)
            self.assertEqual(mutations, [])
            self.assertEqual(commits, [])
            self.assertEqual({str(path.relative_to(journal)): path.read_bytes()
                              for path in journal.rglob('*') if path.is_file()}, before_files)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)


    def test_registered_terminal_count_is_preserved_when_exit_fact_is_missing(self):
        f = self.fixture
        self.registered_two_attempts()
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            action = reader.get(WorkflowAction, f.action_id)
            context = json.loads(workflow.context_json)
            index = _state(context, workflow.id)
            _prepared_process_refs(index)
            original = index['attempts'][1]
            payload = json.loads(action.result_json)
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
            self.assertEqual(hashlib.sha256(canonical).hexdigest(), original['result_sha256'])
            self.assertEqual(len(payload['process_records']), 1)
            ref = payload['process_records'][0]
            self.assertEqual(ref['record_id'], original['prepared_process_refs'][0]['record_id'])
            self.assertEqual(ref['prepared_sha256'], original['prepared_process_refs'][0]['prepared_sha256'])
            directory = f.root / 'execution-processes' / f.action_id / ref['record_id']
            self.assertTrue(directory.resolve().is_relative_to(f.root.resolve()))
            for name, field in (('prepared.json', 'prepared_sha256'), ('started.json', 'started_sha256'),
                                ('exited.json', 'exit_sha256'), ('domain-exited.json', 'domain_exit_sha256')):
                self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), ref[field])
            baseline = read_execution(workflow)
            before_context, before_result = workflow.context_json, action.result_json
            before_audits = reader.scalar(select(func.count()).select_from(AuditEvent))
            before_occupancy = current_material_blocker(reader, workflow.owner_id, workflow.department_id,
                                                        workflow.skill_id)
            # Only an owned synthetic tmpfs fact is removed; all registered hashes remain intact.
            missing = directory / 'exited.json'
            missing.unlink()
            before_files = {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}
            mutations, commits = [], []

            def observe_sql(connection, cursor, statement, parameters, execution_context, executemany):
                verb = statement.lstrip().split(None, 1)[0].upper()
                if verb in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER'}:
                    mutations.append(verb)

            def observe_commit(connection):
                commits.append(True)

            event.listen(f.engine, 'before_cursor_execute', observe_sql)
            event.listen(f.engine, 'commit', observe_commit)
            try:
                with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('missing-fact read must not spawn')) as popen:
                    actual = read_execution(workflow, include_process_details=True)
                    self.assertEqual(popen.call_count, 0)
                current = next(item for item in actual.process_details.items
                               if str(item.action_id) == f.action_id and item.attempt == 2)
                self.assertEqual(current.registered_terminal_count, 1,
                                 'Missing fact cannot erase the uniquely attributable registered terminal reference')
                self.assertEqual(current.prepared_record_count, 1)
                self.assertIsNone(current.direct_exit_count)
                self.assertIsNone(current.descendant_domain_count)
                self.assertEqual(current.inspection_state, 'unknown')
                self.assertIn('fact_missing', current.reason_codes)
                self.assertFalse(current.coverage_complete)
                self.assertFalse(actual.process_details.registered_effect_coverage_complete)
                self.assertEqual(actual.process_details.whole_workflow_coverage, 'unknown')
                self.assertEqual(actual.model_dump(exclude={'process_details'}), baseline.model_dump(exclude={'process_details'}))
                self.assertEqual(current_material_blocker(reader, workflow.owner_id, workflow.department_id,
                                                         workflow.skill_id), before_occupancy)
                self.assertEqual(workflow.context_json, before_context)
                self.assertEqual(action.result_json, before_result)
                self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), before_audits)
            finally:
                event.remove(f.engine, 'before_cursor_execute', observe_sql)
                event.remove(f.engine, 'commit', observe_commit)
            self.assertEqual(mutations, [])
            self.assertEqual(commits, [])
            self.assertFalse(missing.exists())
            self.assertEqual({path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}, before_files)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)


    def test_existing_execution_get_is_opt_in_and_owner_isolated(self):
        from uuid import uuid4
        from fastapi.testclient import TestClient
        from app import ar_execution_service
        from app.auth import UserContext, get_current_user
        from app.auth_models import User
        from app.database import get_db
        from app.main import app

        f = self.fixture
        self.registered_two_attempts()
        foreign_id = str(uuid4())
        f.db.add(User(id=foreign_id, username=foreign_id, display_name='Other synthetic user',
                      department_id='finance', role='finance_user', status='active',
                      password_hash='synthetic-unusable'))
        f.db.commit()
        owner, foreign = f.db.get(User, f.owner_id), f.db.get(User, foreign_id)
        actors = [UserContext(owner.id, owner.display_name, owner.role, owner.department_id),
                  UserContext(foreign.id, foreign.display_name, foreign.role, foreign.department_id)]
        self.assertEqual({actor.role for actor in actors}, {'finance_user'})
        current_actor = [actors[0]]
        original_overrides = dict(app.dependency_overrides)

        def connection():
            with Session(f.engine) as db:
                yield db

        def actor():
            return current_actor[0]

        journal = f.root / 'execution-processes' / f.action_id
        before_files = {str(path.relative_to(journal)): path.read_bytes()
                        for path in journal.rglob('*') if path.is_file()}
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            action = reader.get(WorkflowAction, f.action_id)
            before_context, before_result = workflow.context_json, action.result_json
            before_audits = reader.scalar(select(func.count()).select_from(AuditEvent))
            before_occupancy = current_material_blocker(reader, workflow.owner_id,
                                                        workflow.department_id, workflow.skill_id)
        mutations, commits = [], []

        def observe_sql(connection, cursor, statement, parameters, execution_context, executemany):
            verb = statement.lstrip().split(None, 1)[0].upper()
            if verb in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER'}:
                mutations.append(verb)

        def observe_commit(connection):
            commits.append(True)

        app.dependency_overrides[get_db] = connection
        app.dependency_overrides[get_current_user] = actor
        # As in existing HTTP tests, avoid startup lifecycle tasks; the GET itself is real.
        client = TestClient(app)
        event.listen(f.engine, 'before_cursor_execute', observe_sql)
        event.listen(f.engine, 'commit', observe_commit)
        endpoint = f'/api/workflows/{f.workflow_id}/execution'
        try:
            with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('GET must not spawn')) as popen:
                with patch.object(ar_execution_service, 'read_attempt_process_details',
                                  side_effect=AssertionError('default GET must not read process details')) as details_reader:
                    omitted = client.get(endpoint)
                    explicit_false = client.get(endpoint, params={'include_process_details': 'false'})
                    self.assertEqual(omitted.status_code, 200, omitted.text)
                    self.assertEqual(explicit_false.status_code, 200, explicit_false.text)
                    self.assertEqual(details_reader.call_count, 0)
                baseline = omitted.json()
                self.assertEqual(explicit_false.json(), baseline)
                self.assertIsNone(baseline['process_details'])

                # No reader/guard/recovery replacement: opt-in traverses the actual facts.
                requested = client.get(endpoint, params={'include_process_details': 'true'})
                self.assertEqual(requested.status_code, 200, requested.text)
                body = requested.json()
                details = body.pop('process_details')
                self.assertEqual(body, {key: value for key, value in baseline.items() if key != 'process_details'})
                self.assertEqual(details['schema_version'], 'ar-attempt-process-details-v1')
                items = {(item['action_id'], item['attempt']): item for item in details['items']}
                self.assertEqual(set(items), {(f.action_id, 1), (f.action_id, 2)})
                self.assertEqual(items[(f.action_id, 1)]['inspection_state'], 'unknown')
                self.assertIn('terminal_refs_missing', items[(f.action_id, 1)]['reason_codes'])
                self.assertEqual(items[(f.action_id, 2)]['inspection_state'], 'verified')
                self.assertEqual(items[(f.action_id, 2)]['registered_terminal_count'], 1)
                self.assertFalse(details['registered_effect_coverage_complete'])
                self.assertEqual(details['whole_workflow_coverage'], 'unknown')

                current_actor[0] = actors[1]
                with patch.object(ar_execution_service, 'read_attempt_process_details',
                                  side_effect=AssertionError('foreign user must be rejected before details')) as details_reader:
                    denied = client.get(endpoint, params={'include_process_details': 'true'})
                    self.assertEqual(denied.status_code, 404)
                    self.assertEqual(denied.json(), {'detail': '对话任务不存在。'})
                    self.assertEqual(details_reader.call_count, 0)
                self.assertEqual(popen.call_count, 0)
        finally:
            client.close()
            app.dependency_overrides.clear()
            app.dependency_overrides.update(original_overrides)
            event.remove(f.engine, 'before_cursor_execute', observe_sql)
            event.remove(f.engine, 'commit', observe_commit)
        self.assertEqual(mutations, [])
        self.assertEqual(commits, [])
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            action = reader.get(WorkflowAction, f.action_id)
            self.assertEqual(workflow.context_json, before_context)
            self.assertEqual(action.result_json, before_result)
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), before_audits)
            self.assertEqual(current_material_blocker(reader, workflow.owner_id,
                                                     workflow.department_id, workflow.skill_id), before_occupancy)
        self.assertEqual({str(path.relative_to(journal)): path.read_bytes()
                          for path in journal.rglob('*') if path.is_file()}, before_files)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)


    def test_directory_budget_counts_unregistered_entries_and_preserves_unknown(self):
        f = self.fixture
        self.registered_two_attempts()
        journal = f.root / 'execution-processes'
        self.assertTrue(journal.resolve().is_relative_to(f.root.resolve()))
        self.assertEqual({path.name for path in journal.iterdir()}, {f.action_id})
        # The registered action plus 1024 unregistered entries reaches the real 1025 sentinel.
        # No budget constant, directory enumerator or registered evidence is replaced.
        for number in range(1024):
            (journal / f'synthetic-unregistered-{number:04d}').mkdir()
        self.assertEqual(sum(1 for _ in journal.iterdir()), 1025)
        before_entries = {str(path.relative_to(journal)) for path in journal.rglob('*')}
        before_files = {str(path.relative_to(journal)): path.read_bytes()
                        for path in journal.rglob('*') if path.is_file()}
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            action = reader.get(WorkflowAction, f.action_id)
            before_context, before_result = workflow.context_json, action.result_json
            baseline = read_execution(workflow)
            before_audits = reader.scalar(select(func.count()).select_from(AuditEvent))
            before_occupancy = current_material_blocker(reader, workflow.owner_id,
                                                        workflow.department_id, workflow.skill_id)
            mutations, commits = [], []

            def observe_sql(connection, cursor, statement, parameters, execution_context, executemany):
                verb = statement.lstrip().split(None, 1)[0].upper()
                if verb in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER'}:
                    mutations.append(verb)

            def observe_commit(connection):
                commits.append(True)

            event.listen(f.engine, 'before_cursor_execute', observe_sql)
            event.listen(f.engine, 'commit', observe_commit)
            try:
                with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('truncated read must not spawn')) as popen:
                    actual = read_execution(workflow, include_process_details=True)
                    self.assertEqual(popen.call_count, 0)
                details = actual.process_details
                self.assertFalse(details.registered_effect_coverage_complete)
                self.assertEqual(details.whole_workflow_coverage, 'unknown')
                self.assertIn('scan_truncated', details.reason_codes)
                self.assertNotIn('fact_missing', details.reason_codes)
                self.assertEqual({(str(item.action_id), item.attempt) for item in details.items},
                                 {(f.action_id, 1), (f.action_id, 2)})
                for item in details.items:
                    self.assertEqual(item.inspection_state, 'unknown')
                    self.assertFalse(item.coverage_complete)
                    self.assertEqual(item.prepared_record_count, 1)
                    self.assertIn('scan_truncated', item.reason_codes)
                    self.assertNotIn('fact_missing', item.reason_codes)
                    self.assertEqual(item.liveness, {})
                    for quantity in ('registered_terminal_count', 'direct_exit_count', 'descendant_domain_count'):
                        self.assertIsNone(getattr(item, quantity))
                self.assertEqual(actual.model_dump(exclude={'process_details'}), baseline.model_dump(exclude={'process_details'}))
                self.assertEqual(read_execution(workflow).model_dump(), baseline.model_dump())
                self.assertEqual(current_material_blocker(reader, workflow.owner_id,
                                                         workflow.department_id, workflow.skill_id), before_occupancy)
                self.assertEqual(workflow.context_json, before_context)
                self.assertEqual(action.result_json, before_result)
                self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), before_audits)
            finally:
                event.remove(f.engine, 'before_cursor_execute', observe_sql)
                event.remove(f.engine, 'commit', observe_commit)
            self.assertEqual(mutations, [])
            self.assertEqual(commits, [])
        self.assertEqual({str(path.relative_to(journal)) for path in journal.rglob('*')}, before_entries)
        self.assertEqual({str(path.relative_to(journal)): path.read_bytes()
                          for path in journal.rglob('*') if path.is_file()}, before_files)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)


    def test_original_terminal_digest_mismatch_is_not_recomputed_as_authority(self):
        f = self.fixture
        self.registered_two_attempts()
        with Session(f.engine) as fixture_db:
            workflow = fixture_db.get(WorkflowSession, f.workflow_id)
            action = fixture_db.get(WorkflowAction, f.action_id)
            original_context = workflow.context_json
            original = json.loads(original_context)['execution_safety_v1']['attempts'][1]
            payload = json.loads(action.result_json)
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
            self.assertEqual(hashlib.sha256(canonical).hexdigest(), original['result_sha256'])
            original_records = payload['process_records']
            # Tamper only a synthetic result field; no original hash/ref/fact is updated.
            payload['synthetic_noop'] = False
            changed = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            self.assertNotEqual(hashlib.sha256(changed.encode('utf-8')).hexdigest(), original['result_sha256'])
            self.assertEqual(payload['process_records'], original_records)
            action.result_json = changed
            fixture_db.commit()
        journal = f.root / 'execution-processes' / f.action_id
        before_files = {str(path.relative_to(journal)): path.read_bytes()
                        for path in journal.rglob('*') if path.is_file()}
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            action = reader.get(WorkflowAction, f.action_id)
            self.assertEqual(workflow.context_json, original_context)
            self.assertEqual(json.loads(action.result_json)['process_records'], original_records)
            baseline = read_execution(workflow)
            before_audits = reader.scalar(select(func.count()).select_from(AuditEvent))
            before_occupancy = current_material_blocker(reader, workflow.owner_id,
                                                        workflow.department_id, workflow.skill_id)
            mutations, commits = [], []

            def observe_sql(connection, cursor, statement, parameters, execution_context, executemany):
                verb = statement.lstrip().split(None, 1)[0].upper()
                if verb in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER'}:
                    mutations.append(verb)

            def observe_commit(connection):
                commits.append(True)

            event.listen(f.engine, 'before_cursor_execute', observe_sql)
            event.listen(f.engine, 'commit', observe_commit)
            try:
                with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('conflicting read must not spawn')) as popen:
                    actual = read_execution(workflow, include_process_details=True)
                    self.assertEqual(popen.call_count, 0)
                details = actual.process_details
                current = next(item for item in details.items if item.attempt == 2)
                self.assertEqual(current.inspection_state, 'invalid')
                self.assertIn('terminal_refs_conflict', current.reason_codes)
                self.assertFalse(current.coverage_complete)
                self.assertEqual(current.prepared_record_count, 1)
                for quantity in ('registered_terminal_count', 'direct_exit_count', 'descendant_domain_count'):
                    self.assertIsNone(getattr(current, quantity))
                self.assertTrue(all(item.inspection_state != 'verified' for item in details.items))
                self.assertFalse(details.registered_effect_coverage_complete)
                self.assertEqual(details.whole_workflow_coverage, 'unknown')
                self.assertIn('terminal_refs_conflict', details.reason_codes)
                self.assertEqual(actual.model_dump(exclude={'process_details'}), baseline.model_dump(exclude={'process_details'}))
                self.assertEqual(read_execution(workflow).model_dump(), baseline.model_dump())
                self.assertEqual(current_material_blocker(reader, workflow.owner_id,
                                                         workflow.department_id, workflow.skill_id), before_occupancy)
                self.assertEqual(workflow.context_json, original_context)
                self.assertEqual(action.result_json, changed)
                self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), before_audits)
            finally:
                event.remove(f.engine, 'before_cursor_execute', observe_sql)
                event.remove(f.engine, 'commit', observe_commit)
            self.assertEqual(mutations, [])
            self.assertEqual(commits, [])
        self.assertEqual({str(path.relative_to(journal)): path.read_bytes()
                          for path in journal.rglob('*') if path.is_file()}, before_files)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)


    def test_registered_action_and_record_symlinks_are_not_followed(self):
        f = self.fixture
        self.registered_two_attempts()
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            index = json.loads(workflow.context_json)['execution_safety_v1']
            record_id = index['attempts'][1]['prepared_process_refs'][0]['record_id']
        journal = f.root / 'execution-processes' / f.action_id
        original_files = {str(path.relative_to(journal)): path.read_bytes()
                          for path in journal.rglob('*') if path.is_file()}
        mutations, commits = [], []

        def observe_sql(connection, cursor, statement, parameters, execution_context, executemany):
            verb = statement.lstrip().split(None, 1)[0].upper()
            if verb in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER'}:
                mutations.append(verb)

        def observe_commit(connection):
            commits.append(True)

        event.listen(f.engine, 'before_cursor_execute', observe_sql)
        event.listen(f.engine, 'commit', observe_commit)
        try:
            with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('symlink read must not spawn')) as popen:
                for boundary in ('action', 'record'):
                    with self.subTest(boundary=boundary):
                        original = journal if boundary == 'action' else journal / record_id
                        held = f.root / ('synthetic-held-' + boundary)
                        self.assertTrue(original.resolve().is_relative_to(f.root.resolve()))
                        self.assertFalse(original.is_symlink())
                        original.rename(held)
                        original.symlink_to(held, target_is_directory=True)
                        before_held = {str(path.relative_to(held)): path.read_bytes()
                                       for path in held.rglob('*') if path.is_file()}
                        try:
                            with Session(f.engine) as reader:
                                workflow = reader.get(WorkflowSession, f.workflow_id)
                                action = reader.get(WorkflowAction, f.action_id)
                                before_context, before_result = workflow.context_json, action.result_json
                                baseline = read_execution(workflow)
                                before_audits = reader.scalar(select(func.count()).select_from(AuditEvent))
                                before_occupancy = current_material_blocker(reader, workflow.owner_id,
                                                                            workflow.department_id, workflow.skill_id)
                                actual = read_execution(workflow, include_process_details=True)
                                current = next(item for item in actual.process_details.items if item.attempt == 2)
                                self.assertEqual(current.inspection_state, 'invalid')
                                self.assertIn('fact_invalid', current.reason_codes)
                                self.assertFalse(current.coverage_complete)
                                for quantity in ('registered_terminal_count', 'direct_exit_count', 'descendant_domain_count'):
                                    self.assertIsNone(getattr(current, quantity))
                                self.assertFalse(actual.process_details.registered_effect_coverage_complete)
                                self.assertEqual(actual.process_details.whole_workflow_coverage, 'unknown')
                                self.assertEqual(actual.model_dump(exclude={'process_details'}), baseline.model_dump(exclude={'process_details'}))
                                self.assertEqual(current_material_blocker(reader, workflow.owner_id,
                                                                         workflow.department_id, workflow.skill_id), before_occupancy)
                                self.assertEqual(workflow.context_json, before_context)
                                self.assertEqual(action.result_json, before_result)
                                self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), before_audits)
                            self.assertTrue(original.is_symlink())
                            self.assertEqual(original.readlink(), held)
                            self.assertEqual({str(path.relative_to(held)): path.read_bytes()
                                              for path in held.rglob('*') if path.is_file()}, before_held)
                        finally:
                            original.unlink()
                            held.rename(original)
                self.assertEqual(popen.call_count, 0)
        finally:
            event.remove(f.engine, 'before_cursor_execute', observe_sql)
            event.remove(f.engine, 'commit', observe_commit)
        self.assertEqual(mutations, [])
        self.assertEqual(commits, [])
        self.assertEqual({str(path.relative_to(journal)): path.read_bytes()
                          for path in journal.rglob('*') if path.is_file()}, original_files)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)


    def test_prepared_binding_bool_does_not_equal_original_integer_version(self):
        f = self.fixture
        self.registered_two_attempts()
        with Session(f.engine) as fixture_db:
            workflow = fixture_db.get(WorkflowSession, f.workflow_id)
            context = json.loads(workflow.context_json)
            old = context['execution_safety_v1']['attempts'][0]
            anchor = old['prepared_process_refs'][0]
            original_binding = old['binding_sha256']
            prepared_path = f.root / 'execution-processes' / f.action_id / anchor['record_id'] / 'prepared.json'
            prepared = json.loads(prepared_path.read_bytes())
            self.assertIs(type(old['material_version']), int)
            self.assertEqual(old['material_version'], 1)
            self.assertIs(type(prepared['material_version']), int)
            prepared['material_version'] = True
            self.assertEqual(prepared['material_version'], old['material_version'])
            # Malformed persisted metadata fault injection, not a claim the normal gate allows it.
            # Matching file SHA ensures the oracle reaches typed original-binding validation.
            raw = json.dumps(prepared, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
            prepared_path.write_bytes(raw)
            anchor['prepared_sha256'] = hashlib.sha256(raw).hexdigest()
            self.assertEqual(anchor['binding_sha256'], original_binding)
            self.assertEqual(old['binding_sha256'], original_binding)
            _prepared_process_refs(_state(context, workflow.id))
            workflow.context_json = json.dumps(context)
            fixture_db.commit()
        journal = f.root / 'execution-processes' / f.action_id
        before_files = {str(path.relative_to(journal)): path.read_bytes()
                        for path in journal.rglob('*') if path.is_file()}
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            action = reader.get(WorkflowAction, f.action_id)
            before_context, before_result = workflow.context_json, action.result_json
            baseline = read_execution(workflow)
            before_audits = reader.scalar(select(func.count()).select_from(AuditEvent))
            before_occupancy = current_material_blocker(reader, workflow.owner_id,
                                                        workflow.department_id, workflow.skill_id)
            mutations, commits = [], []

            def observe_sql(connection, cursor, statement, parameters, execution_context, executemany):
                verb = statement.lstrip().split(None, 1)[0].upper()
                if verb in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER'}:
                    mutations.append(verb)

            def observe_commit(connection):
                commits.append(True)

            event.listen(f.engine, 'before_cursor_execute', observe_sql)
            event.listen(f.engine, 'commit', observe_commit)
            try:
                with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('type-conflict read must not spawn')) as popen:
                    actual = read_execution(workflow, include_process_details=True)
                    self.assertEqual(popen.call_count, 0)
                items = {item.attempt: item for item in actual.process_details.items}
                self.assertEqual(items[1].inspection_state, 'invalid')
                self.assertIn('binding_invalid', items[1].reason_codes)
                self.assertNotIn('fact_invalid', items[1].reason_codes)
                self.assertFalse(items[1].coverage_complete)
                self.assertEqual(items[1].prepared_record_count, 1)
                self.assertIsNone(items[1].registered_terminal_count)
                self.assertIsNone(items[1].direct_exit_count)
                self.assertIsNone(items[1].descendant_domain_count)
                self.assertEqual(items[2].inspection_state, 'verified')
                self.assertTrue(items[2].coverage_complete)
                self.assertFalse(actual.process_details.registered_effect_coverage_complete)
                self.assertEqual(actual.process_details.whole_workflow_coverage, 'unknown')
                self.assertEqual(actual.model_dump(exclude={'process_details'}), baseline.model_dump(exclude={'process_details'}))
                self.assertEqual(current_material_blocker(reader, workflow.owner_id,
                                                         workflow.department_id, workflow.skill_id), before_occupancy)
                self.assertEqual(workflow.context_json, before_context)
                self.assertEqual(action.result_json, before_result)
                self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), before_audits)
            finally:
                event.remove(f.engine, 'before_cursor_execute', observe_sql)
                event.remove(f.engine, 'commit', observe_commit)
            self.assertEqual(mutations, [])
            self.assertEqual(commits, [])
        self.assertEqual({str(path.relative_to(journal)): path.read_bytes()
                          for path in journal.rglob('*') if path.is_file()}, before_files)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)


    def test_legacy_and_unavailable_get_keep_missing_evidence_unknown(self):
        from fastapi.testclient import TestClient
        from app.auth import UserContext, get_current_user
        from app.database import get_db
        from app.main import app

        f = self.fixture
        initial = json.loads(f.workflow.context_json)
        legacy = {key: value for key, value in initial.items() if key != 'execution_safety_v1'}
        original_overrides = dict(app.dependency_overrides)

        def connection():
            with Session(f.engine) as db:
                yield db

        def actor():
            return UserContext(f.owner_id, 'Synthetic owner', 'finance_user', 'finance')

        before_files = {str(path.relative_to(f.root)): path.read_bytes()
                        for path in f.root.rglob('*') if path.is_file()}
        app.dependency_overrides[get_db] = connection
        app.dependency_overrides[get_current_user] = actor
        client = TestClient(app)
        endpoint = f'/api/workflows/{f.workflow_id}/execution'
        try:
            for case, context, available in (('legacy', legacy, True), ('unavailable', {}, False)):
                with self.subTest(case=case):
                    with Session(f.engine) as fixture_db:
                        workflow = fixture_db.get(WorkflowSession, f.workflow_id)
                        workflow.context_json = json.dumps(context)
                        fixture_db.commit()
                    with Session(f.engine) as reader:
                        workflow = reader.get(WorkflowSession, f.workflow_id)
                        action = reader.get(WorkflowAction, f.action_id)
                        before_context, before_result = workflow.context_json, action.result_json
                        before_audits = reader.scalar(select(func.count()).select_from(AuditEvent))
                        before_occupancy = current_material_blocker(reader, workflow.owner_id,
                                                                    workflow.department_id, workflow.skill_id)
                    mutations, commits = [], []

                    def observe_sql(connection, cursor, statement, parameters, execution_context, executemany):
                        verb = statement.lstrip().split(None, 1)[0].upper()
                        if verb in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER'}:
                            mutations.append(verb)

                    def observe_commit(connection):
                        commits.append(True)

                    event.listen(f.engine, 'before_cursor_execute', observe_sql)
                    event.listen(f.engine, 'commit', observe_commit)
                    try:
                        with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('legacy GET must not spawn')) as popen:
                            omitted = client.get(endpoint)
                            requested = client.get(endpoint, params={'include_process_details': 'true'})
                            self.assertEqual(omitted.status_code, 200, omitted.text)
                            self.assertEqual(requested.status_code, 200, requested.text)
                            self.assertEqual(popen.call_count, 0)
                        baseline, body = omitted.json(), requested.json()
                        self.assertEqual(body['available'], available)
                        self.assertIsNone(baseline['process_details'])
                        details = body.pop('process_details')
                        self.assertEqual(body, {key: value for key, value in baseline.items() if key != 'process_details'})
                        self.assertIsNone(details['evidence_revision'])
                        self.assertFalse(details['registered_effect_coverage_complete'])
                        self.assertEqual(details['whole_workflow_coverage'], 'unknown')
                        self.assertEqual(len(details['items']), 1)
                        item = details['items'][0]
                        self.assertEqual(item['action_id'], f.action_id)
                        self.assertIsNone(item['attempt'])
                        self.assertEqual(item['inspection_state'], 'unknown')
                        self.assertFalse(item['coverage_complete'])
                        self.assertIn('attempt_unregistered', item['reason_codes'])
                        self.assertEqual(item['liveness'], {})
                        for quantity in ('prepared_record_count', 'registered_terminal_count', 'direct_exit_count', 'descendant_domain_count'):
                            self.assertIsNone(item[quantity])
                        self.assertFalse(body['attempt_history']['process_evidence_checked'])
                        self.assertFalse(body['attempt_history']['authorizes_resume'])
                        with Session(f.engine) as reader:
                            workflow = reader.get(WorkflowSession, f.workflow_id)
                            action = reader.get(WorkflowAction, f.action_id)
                            self.assertEqual(workflow.context_json, before_context)
                            self.assertEqual(action.result_json, before_result)
                            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), before_audits)
                            self.assertEqual(current_material_blocker(reader, workflow.owner_id,
                                                                     workflow.department_id, workflow.skill_id), before_occupancy)
                    finally:
                        event.remove(f.engine, 'before_cursor_execute', observe_sql)
                        event.remove(f.engine, 'commit', observe_commit)
                    self.assertEqual(mutations, [])
                    self.assertEqual(commits, [])
        finally:
            client.close()
            app.dependency_overrides.clear()
            app.dependency_overrides.update(original_overrides)
        self.assertEqual({str(path.relative_to(f.root)): path.read_bytes()
                          for path in f.root.rglob('*') if path.is_file()}, before_files)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)


    @legacy_terminal_payload_fixture
    def registered_failure_one_attempt(self):
        from dataclasses import replace
        from app import workflow_execution_policy as policy

        f = self.fixture
        context = json.loads(f.workflow.context_json)
        context.pop('execution_safety_v1')
        f.workflow.context_json = json.dumps(context)
        f.action.state = isolated_action_state('queued')
        f.action.attempt_count = 0
        f.action.worker_id, f.action.lease_expires_at = '', None
        f.db.commit()

        def synthetic_failed_writer(execution):
            self.assertEqual(execution.script('anchor_probe.py', []).strip(), 'synthetic anchor probe')
            raise RuntimeError('synthetic phase failure after the benign child exited')

        with Session(f.engine, expire_on_commit=False) as run_db:
            action = service.claim_next_workflow_action(run_db, ('workflow',), 'synthetic-failure-worker',
                                                       execution_contracts=(CONTRACT_VERSION,))
            self.assertIsNotNone(action)
            self.assertEqual(action.id, f.action_id)
            self.assertEqual(action.attempt_count, 1)
            # Scoped setting is authorized only in network-none synthetic PG; financial body replaced.
            isolated_settings = replace(service.settings, ar_hexiao_execution_enabled=True)
            with patch.object(service, 'settings', isolated_settings), \
                    patch.object(policy, 'settings', isolated_settings), \
                    patch.object(ArExecution, 'write_ledger', synthetic_failed_writer):
                service.execute_workflow_action(run_db, action)
            run_db.commit()
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            action = reader.get(WorkflowAction, f.action_id)
            self.assertEqual(action.state, 'failed')
            self.assertEqual(workflow.state, 'failed')
            context = json.loads(workflow.context_json)
            self.assertEqual(len(context['execution_safety_v1']['attempts']), 1)
            self.assertEqual(context['execution_safety_v1']['attempts'][0]['status'], 'intent_recorded')
            self.assertNotIn('terminal_process_refs', context['execution_safety_v1']['attempts'][0])
            failure = context['ar_failure']
            self.assertEqual(failure['action_id'], f.action_id)
            self.assertEqual(failure['phase'], 'write_ledger')
            self.assertEqual(failure['error_type'], 'RuntimeError')
            self.assertTrue(failure['process_exit_confirmed'])
            self.assertEqual(len(failure['process_records']), 1)
            self.assertEqual(json.loads(action.result_json), {})
            return failure

    def test_real_failure_handler_refs_uniquely_verify_original_attempt(self):
        f = self.fixture
        failure = self.registered_failure_one_attempt()
        journal = f.root / 'execution-processes' / f.action_id
        before_files = {str(path.relative_to(journal)): path.read_bytes()
                        for path in journal.rglob('*') if path.is_file()}
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            action = reader.get(WorkflowAction, f.action_id)
            before_context, before_result = workflow.context_json, action.result_json
            original = json.loads(before_context)['execution_safety_v1']['attempts'][0]
            anchor, terminal = original['prepared_process_refs'][0], failure['process_records'][0]
            self.assertEqual(terminal['record_id'], anchor['record_id'])
            self.assertEqual(terminal['prepared_sha256'], anchor['prepared_sha256'])
            self.assertNotIn('attempt', failure)
            self.assertNotIn('worker_id', failure)
            for name, field in (('prepared.json', 'prepared_sha256'), ('started.json', 'started_sha256'),
                                ('exited.json', 'exit_sha256'), ('domain-exited.json', 'domain_exit_sha256')):
                self.assertEqual(hashlib.sha256((journal / anchor['record_id'] / name).read_bytes()).hexdigest(), terminal[field])
            baseline = read_execution(workflow)
            before_audits = reader.scalar(select(func.count()).select_from(AuditEvent))
            before_occupancy = current_material_blocker(reader, workflow.owner_id,
                                                        workflow.department_id, workflow.skill_id)
            mutations, commits = [], []

            def observe_sql(connection, cursor, statement, parameters, execution_context, executemany):
                verb = statement.lstrip().split(None, 1)[0].upper()
                if verb in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER'}:
                    mutations.append(verb)

            def observe_commit(connection):
                commits.append(True)

            event.listen(f.engine, 'before_cursor_execute', observe_sql)
            event.listen(f.engine, 'commit', observe_commit)
            try:
                with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('failure read must not spawn')) as popen:
                    actual = read_execution(workflow, include_process_details=True)
                    self.assertEqual(popen.call_count, 0)
                details = actual.process_details
                self.assertEqual(len(details.items), 1)
                item = details.items[0]
                self.assertEqual(str(item.action_id), f.action_id)
                self.assertEqual(item.attempt, 1)
                self.assertEqual(item.inspection_state, 'verified')
                self.assertTrue(item.coverage_complete)
                self.assertEqual(item.reason_codes, [])
                for quantity in ('prepared_record_count', 'registered_terminal_count', 'direct_exit_count', 'descendant_domain_count'):
                    self.assertEqual(getattr(item, quantity), 1)
                self.assertTrue(details.registered_effect_coverage_complete)
                self.assertEqual(details.whole_workflow_coverage, 'unknown')
                self.assertEqual(actual.model_dump(exclude={'process_details'}), baseline.model_dump(exclude={'process_details'}))
                self.assertEqual(current_material_blocker(reader, workflow.owner_id,
                                                         workflow.department_id, workflow.skill_id), before_occupancy)
                self.assertEqual(workflow.context_json, before_context)
                self.assertEqual(action.result_json, before_result)
                self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), before_audits)
            finally:
                event.remove(f.engine, 'before_cursor_execute', observe_sql)
                event.remove(f.engine, 'commit', observe_commit)
            self.assertEqual(mutations, [])
            self.assertEqual(commits, [])
        self.assertEqual({str(path.relative_to(journal)): path.read_bytes()
                          for path in journal.rglob('*') if path.is_file()}, before_files)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)


    def test_mixed_and_duplicate_failure_refs_cannot_select_latest_success(self):
        f = self.fixture
        self.registered_two_attempts()
        # Both refs came from true recorded no-op producers, not hashes guessed from files.
        earlier = json.loads(json.dumps(f.action._ar_process_records[0]))
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            action = reader.get(WorkflowAction, f.action_id)
            base_context = workflow.context_json
            unchanged_result = action.result_json
            latest = json.loads(unchanged_result)['process_records'][0]
            attempts = json.loads(base_context)['execution_safety_v1']['attempts']
            self.assertEqual(earlier['record_id'], attempts[0]['prepared_process_refs'][0]['record_id'])
            self.assertEqual(latest['record_id'], attempts[1]['prepared_process_refs'][0]['record_id'])
            self.assertNotEqual(earlier['record_id'], latest['record_id'])
        journal = f.root / 'execution-processes' / f.action_id
        before_files = {str(path.relative_to(journal)): path.read_bytes()
                        for path in journal.rglob('*') if path.is_file()}
        for case, refs in (('mixed', [earlier, latest]), ('duplicate', [latest, latest])):
            with self.subTest(case=case):
                context = json.loads(base_context)
                # Deliberately malformed retained source; individual underlying producer refs remain real.
                context['ar_failure'] = {'action_id': f.action_id, 'phase': 'write_ledger',
                    'process_evidence_version': evidence.SCHEMA_VERSION, 'process_exit_confirmed': True,
                    'process_records': refs, 'error_type': 'SyntheticMalformedSource'}
                with Session(f.engine) as fixture_db:
                    fixture_db.get(WorkflowSession, f.workflow_id).context_json = json.dumps(context)
                    fixture_db.commit()
                with Session(f.engine) as reader:
                    workflow = reader.get(WorkflowSession, f.workflow_id)
                    action = reader.get(WorkflowAction, f.action_id)
                    before_context = workflow.context_json
                    self.assertEqual(action.result_json, unchanged_result)
                    baseline = read_execution(workflow)
                    before_audits = reader.scalar(select(func.count()).select_from(AuditEvent))
                    before_occupancy = current_material_blocker(reader, workflow.owner_id,
                                                                workflow.department_id, workflow.skill_id)
                    mutations, commits = [], []

                    def observe_sql(connection, cursor, statement, parameters, execution_context, executemany):
                        verb = statement.lstrip().split(None, 1)[0].upper()
                        if verb in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER'}:
                            mutations.append(verb)

                    def observe_commit(connection):
                        commits.append(True)

                    event.listen(f.engine, 'before_cursor_execute', observe_sql)
                    event.listen(f.engine, 'commit', observe_commit)
                    try:
                        with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('ambiguous read must not spawn')) as popen:
                            actual = read_execution(workflow, include_process_details=True)
                            self.assertEqual(popen.call_count, 0)
                        details = actual.process_details
                        current = next(item for item in details.items if item.attempt == 2)
                        self.assertEqual(current.inspection_state, 'invalid')
                        self.assertIn('terminal_refs_conflict', current.reason_codes)
                        self.assertFalse(current.coverage_complete)
                        for quantity in ('registered_terminal_count', 'direct_exit_count', 'descendant_domain_count'):
                            self.assertIsNone(getattr(current, quantity))
                        self.assertFalse(details.registered_effect_coverage_complete)
                        self.assertEqual(details.whole_workflow_coverage, 'unknown')
                        self.assertEqual(actual.model_dump(exclude={'process_details'}), baseline.model_dump(exclude={'process_details'}))
                        self.assertEqual(current_material_blocker(reader, workflow.owner_id,
                                                                 workflow.department_id, workflow.skill_id), before_occupancy)
                        self.assertEqual(workflow.context_json, before_context)
                        self.assertEqual(action.result_json, unchanged_result)
                        self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), before_audits)
                    finally:
                        event.remove(f.engine, 'before_cursor_execute', observe_sql)
                        event.remove(f.engine, 'commit', observe_commit)
                    self.assertEqual(mutations, [])
                    self.assertEqual(commits, [])
        self.assertEqual({str(path.relative_to(journal)): path.read_bytes()
                          for path in journal.rglob('*') if path.is_file()}, before_files)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)


    def test_unique_failure_missing_required_terminal_fingerprint_has_known_zero_count(self):
        f = self.fixture
        failure = self.registered_failure_one_attempt()
        ref = failure['process_records'][0]
        self.assertEqual(len(ref['domain_exit_sha256']), 64)
        with Session(f.engine) as fixture_db:
            workflow = fixture_db.get(WorkflowSession, f.workflow_id)
            context = json.loads(workflow.context_json)
            original_index = json.dumps(context['execution_safety_v1'], sort_keys=True)
            anchor = context['execution_safety_v1']['attempts'][0]['prepared_process_refs'][0]
            self.assertEqual(ref['record_id'], anchor['record_id'])
            self.assertEqual(ref['prepared_sha256'], anchor['prepared_sha256'])
            prepared = f.root / 'execution-processes' / f.action_id / ref['record_id'] / 'prepared.json'
            self.assertEqual(hashlib.sha256(prepared.read_bytes()).hexdigest(), anchor['prepared_sha256'])
            self.assertEqual(json.loads(prepared.read_bytes())['execution_domain_schema'], 'ar-linux-subreaper-v1')
            # One complete, uniquely attributable registered set remains, with a known absent required hash.
            del context['ar_failure']['process_records'][0]['domain_exit_sha256']
            workflow.context_json = json.dumps(context)
            fixture_db.commit()
        journal = f.root / 'execution-processes' / f.action_id
        before_files = {str(path.relative_to(journal)): path.read_bytes()
                        for path in journal.rglob('*') if path.is_file()}
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            action = reader.get(WorkflowAction, f.action_id)
            before_context, before_result = workflow.context_json, action.result_json
            self.assertEqual(json.dumps(json.loads(before_context)['execution_safety_v1'], sort_keys=True), original_index)
            baseline = read_execution(workflow)
            before_audits = reader.scalar(select(func.count()).select_from(AuditEvent))
            before_occupancy = current_material_blocker(reader, workflow.owner_id,
                                                        workflow.department_id, workflow.skill_id)
            mutations, commits = [], []

            def observe_sql(connection, cursor, statement, parameters, execution_context, executemany):
                verb = statement.lstrip().split(None, 1)[0].upper()
                if verb in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER'}:
                    mutations.append(verb)

            def observe_commit(connection):
                commits.append(True)

            event.listen(f.engine, 'before_cursor_execute', observe_sql)
            event.listen(f.engine, 'commit', observe_commit)
            try:
                with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('missing-reference read must not spawn')) as popen:
                    actual = read_execution(workflow, include_process_details=True)
                    self.assertEqual(popen.call_count, 0)
                item = actual.process_details.items[0]
                self.assertEqual(item.registered_terminal_count, 0,
                                 'Unique complete source with a known absent required hash has zero complete terminal registrations')
                self.assertEqual(item.prepared_record_count, 1)
                self.assertEqual(item.inspection_state, 'unknown')
                self.assertIn('terminal_refs_missing', item.reason_codes)
                self.assertFalse(item.coverage_complete)
                self.assertIsNone(item.direct_exit_count)
                self.assertIsNone(item.descendant_domain_count)
                self.assertEqual(item.liveness, {})
                self.assertFalse(actual.process_details.registered_effect_coverage_complete)
                self.assertEqual(actual.process_details.whole_workflow_coverage, 'unknown')
                self.assertEqual(actual.model_dump(exclude={'process_details'}), baseline.model_dump(exclude={'process_details'}))
                self.assertEqual(current_material_blocker(reader, workflow.owner_id,
                                                         workflow.department_id, workflow.skill_id), before_occupancy)
                self.assertEqual(workflow.context_json, before_context)
                self.assertEqual(action.result_json, before_result)
                self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), before_audits)
            finally:
                event.remove(f.engine, 'before_cursor_execute', observe_sql)
                event.remove(f.engine, 'commit', observe_commit)
            self.assertEqual(mutations, [])
            self.assertEqual(commits, [])
        self.assertEqual({str(path.relative_to(journal)): path.read_bytes()
                          for path in journal.rglob('*') if path.is_file()}, before_files)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)


    def test_oversized_retained_failure_scalar_is_rejected_before_json_encoding(self):
        import sys
        from app import ar_attempt_process_details as details_module

        f = self.fixture
        self.registered_failure_one_attempt()
        with Session(f.engine) as fixture_db:
            workflow = fixture_db.get(WorkflowSession, f.workflow_id)
            context = json.loads(workflow.context_json)
            original_index = json.dumps(context['execution_safety_v1'], sort_keys=True)
            context['ar_failure']['oversized_probe_scalar'] = 'x' * (128 * 1024 + 1)
            workflow.context_json = json.dumps(context)
            fixture_db.commit()
        journal = f.root / 'execution-processes' / f.action_id
        before_files = {str(path.relative_to(journal)): path.read_bytes()
                        for path in journal.rglob('*') if path.is_file()}
        over_budget_encoder_inputs = []
        original_iterencode = json.JSONEncoder.iterencode

        def observe_iterencode(encoder, value, *args, **kwargs):
            # Observe this new reader's payload encoding only; legacy GET encoding is outside its budget.
            # Delegate unchanged, never fabricate a failure or bypass actual readers/guards.
            caller = sys._getframe(1)
            if caller.f_code is details_module._Budget.payload.__code__ and isinstance(value, dict):
                scalar = value.get('oversized_probe_scalar')
                if isinstance(scalar, str) and len(scalar) > 128 * 1024:
                    over_budget_encoder_inputs.append(len(scalar))
            return original_iterencode(encoder, value, *args, **kwargs)

        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            action = reader.get(WorkflowAction, f.action_id)
            before_context, before_result = workflow.context_json, action.result_json
            self.assertEqual(json.dumps(json.loads(before_context)['execution_safety_v1'], sort_keys=True), original_index)
            baseline = read_execution(workflow)
            before_audits = reader.scalar(select(func.count()).select_from(AuditEvent))
            before_occupancy = current_material_blocker(reader, workflow.owner_id,
                                                        workflow.department_id, workflow.skill_id)
            mutations, commits = [], []

            def observe_sql(connection, cursor, statement, parameters, execution_context, executemany):
                verb = statement.lstrip().split(None, 1)[0].upper()
                if verb in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER'}:
                    mutations.append(verb)

            def observe_commit(connection):
                commits.append(True)

            event.listen(f.engine, 'before_cursor_execute', observe_sql)
            event.listen(f.engine, 'commit', observe_commit)
            try:
                with patch.object(json.JSONEncoder, 'iterencode', observe_iterencode), \
                        patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('budget read must not spawn')) as popen:
                    actual = read_execution(workflow, include_process_details=True)
                    self.assertEqual(popen.call_count, 0)
                details = actual.process_details
                item = details.items[0]
                self.assertEqual(item.inspection_state, 'unknown')
                self.assertIn('budget_exceeded', item.reason_codes)
                self.assertFalse(item.coverage_complete)
                for quantity in ('registered_terminal_count', 'direct_exit_count', 'descendant_domain_count'):
                    self.assertIsNone(getattr(item, quantity))
                self.assertFalse(details.registered_effect_coverage_complete)
                self.assertEqual(details.whole_workflow_coverage, 'unknown')
                self.assertEqual(actual.model_dump(exclude={'process_details'}), baseline.model_dump(exclude={'process_details'}))
                self.assertEqual(current_material_blocker(reader, workflow.owner_id,
                                                         workflow.department_id, workflow.skill_id), before_occupancy)
                self.assertEqual(workflow.context_json, before_context)
                self.assertEqual(action.result_json, before_result)
                self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), before_audits)
            finally:
                event.remove(f.engine, 'before_cursor_execute', observe_sql)
                event.remove(f.engine, 'commit', observe_commit)
            self.assertEqual(mutations, [])
            self.assertEqual(commits, [])
        self.assertEqual({str(path.relative_to(journal)): path.read_bytes()
                          for path in journal.rglob('*') if path.is_file()}, before_files)
        self.assertEqual({path: path.read_bytes() for path in f.material_bytes}, f.material_bytes)
        self.assertEqual(over_budget_encoder_inputs, [],
                         'An already over-budget retained scalar must be rejected before entering JSONEncoder.iterencode')
