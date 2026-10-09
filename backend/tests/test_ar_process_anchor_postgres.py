"""Prepared anchors must be committed before a synthetic process may start."""
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import yaml
from sqlalchemy import create_engine, event, func, select, text
from psycopg.errors import DivisionByZero
from sqlalchemy.orm import Session

from app import ar_process_evidence as evidence
from app.ar_execution_contract import CONTRACT_VERSION, PHASES
from app.ar_execution_runner import ArExecution
from app.ar_execution_safety import register_effect_intent
from app.auth_models import User, UserSkillPermission
from app.models import (AuditEvent, Base, FileRecord, SchedulerLock, WorkflowAction,
                        WorkflowMaterialSet, WorkflowMaterialSetFile, WorkflowSession)
from app.registry import SkillManifest, hash_skill_directory
from app.resource_policy import workflow_root

URL = 'postgresql+psycopg://synthetic:synthetic-only@127.0.0.1:5432/material_policy_test'


@unittest.skipUnless(os.environ.get('AR_POLICY_SYNTHETIC_DB_URL') == URL,
                     'isolated PostgreSQL only')
class ArProcessAnchorPostgresTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.environ.get('FINANCIAL_ENV'), 'test')
        self.assertEqual(os.environ.get('FINANCIAL_DATABASE_URL'), URL)
        self.assertEqual(os.environ.get('REFACTOR_REAL_CONNECTORS'), 'disabled')
        sandbox = Path(os.environ['REFACTOR_TEST_ROOT'])
        self.assertTrue(sandbox.name.startswith('financial-refactor-'))
        self.assertEqual((sandbox / '.refactor-isolated').read_text(), 'synthetic-only-v1')
        self.temp = tempfile.TemporaryDirectory(prefix='process-anchor-', dir=sandbox)
        self.addCleanup(self.temp.cleanup)
        self.admin = create_engine(URL, connect_args={'options': '-c statement_timeout=10000'})
        self.addCleanup(self.admin.dispose)
        self.schema = 'ar_process_anchor_' + uuid4().hex
        with self.admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.addCleanup(self.drop_schema)
        self.engine = create_engine(URL, connect_args={
            'options': '-csearch_path=' + self.schema + ' -c statement_timeout=10000'})
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.addCleanup(self.db.close)
        self.assertIsNone(self.db.scalar(select(WorkflowSession.id).limit(1)))

        self.owner_id, self.workflow_id, self.action_id = (str(uuid4()) for _ in range(3))
        self.root = workflow_root(self.owner_id, self.workflow_id)
        self.assertTrue(self.root.is_relative_to(sandbox.resolve()))
        self.root.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(self.root))
        skill = self.root / 'skill'
        scripts = skill / 'vendor' / 'scripts'
        scripts.mkdir(parents=True)
        (skill / 'config').mkdir()
        (skill / 'config' / 'execution-pipeline.json').write_text(json.dumps({
            'schema_version': CONTRACT_VERSION, 'phases': [phase.name for phase in PHASES],
            'reconciliation_policy': 'legacy',
        }), encoding='utf-8')
        (scripts / 'anchor_probe.py').write_text("print('synthetic anchor probe')\n", encoding='utf-8')
        from test_parallel_workers import _manifest
        manifest = json.loads(_manifest(risk='write'))
        manifest.update(id='ar-hexiao-daily', name='codex测试启动引用')
        manifest['handler']['entrypoint'] = 'vendor/scripts/anchor_probe.py'
        manifest['risk']['requires_confirmation'] = True
        SkillManifest.model_validate(manifest)
        (skill / 'tool.yaml').write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding='utf-8')
        skill_hash = hash_skill_directory(skill)

        workspace = self.root / 'work'
        copy_dir = workspace / '02_我的表副本'
        copy_dir.mkdir(parents=True)
        annual = copy_dir / 'codex测试盈亏2026.xlsx'
        receipt = copy_dir / 'codex测试到账.xlsx'
        annual.write_bytes(b'synthetic annual placeholder; no workbook parser or writer')
        receipt.write_bytes(b'synthetic receipt placeholder; no workbook parser or writer')
        self.material_bytes = {annual: annual.read_bytes(), receipt: receipt.read_bytes()}
        self.db.add(User(id=self.owner_id, username=self.owner_id, department_id='finance',
                         role='finance_user', status='active', password_hash='synthetic-unusable'))
        self.db.add(UserSkillPermission(id=str(uuid4()), user_id=self.owner_id,
                                       skill_id='ar-hexiao-daily', can_run=True,
                                       can_upload=False, can_create_draft=False))
        self.db.add(SchedulerLock(name='global'))
        self.workflow = WorkflowSession(
            id=self.workflow_id, owner_id=self.owner_id, owner_name='codex测试',
            department_id='finance', skill_id='ar-hexiao-daily', skill_name=manifest['name'],
            skill_version=manifest['version'], skill_hash=skill_hash, execution_mode='workflow',
            model_connection_id='synthetic-model', model_provider='synthetic', model_name='synthetic',
            state='running', stage='applying', reconciliation_date='2026-09-01', context_json='{}',
        )
        self.db.add(self.workflow)
        self.db.flush()
        material = WorkflowMaterialSet(id=str(uuid4()), owner_id=self.owner_id,
            department_id='finance', skill_id='ar-hexiao-daily', version=1, state='current')
        self.db.add(material)
        self.db.flush()
        for path, role, year in ((annual, 'profit_loss_ledgers', 2026),
                                 (receipt, 'receipt_flow_table', 0)):
            file_id = str(uuid4())
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.db.add(FileRecord(id=file_id, owner_id=self.owner_id, department_id='finance',
                skill_id='ar-hexiao-daily', workflow_id=self.workflow_id, kind='input',
                original_name=path.name, stored_path=str(path), size_bytes=path.stat().st_size,
                sha256=digest))
            self.db.flush()
            self.db.add(WorkflowMaterialSetFile(id=str(uuid4()), material_set_id=material.id,
                role=role, year=year, file_id=file_id, sha256=digest))
        self.workflow.material_set_id = material.id
        now = datetime.now(UTC)
        self.action = WorkflowAction(
            id=self.action_id, workflow_id=self.workflow_id, name='ar_write_ledger',
            state='running', attempt_count=1, worker_id='synthetic-worker',
            queued_at=now, started_at=now, heartbeat_at=now,
            lease_expires_at=now + timedelta(minutes=5),
        )
        self.db.add(self.action)
        write_index = next(index for index, phase in enumerate(PHASES) if phase.name == 'write_ledger')
        mapping = {'2026': str(annual)}
        context = {
            'workspace': str(workspace), 'ledger_years': mapping, 'flow_file': str(receipt),
            'plan_fingerprint': 'a' * 64,
            'ar_execution': {'schema_version': CONTRACT_VERSION, 'reconciliation_policy': 'legacy',
                'reconciliation_date': self.workflow.reconciliation_date,
                'skill_hash': skill_hash, 'material_set_id': material.id, 'material_version': 1,
                'ledger_years': mapping, 'publication': 'not_published',
                'completed': [phase.name for phase in PHASES[:write_index]], 'steps': {}},
        }
        register_effect_intent(context, self.workflow, self.action, 'write_ledger')
        self.original_binding = context['execution_safety_v1']['attempts'][0]['binding_sha256']
        self.workflow.context_json = json.dumps(context)
        self.db.commit()

    def drop_schema(self):
        with self.admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))

    def test_prepared_reference_and_audit_are_visible_before_popen(self):
        # No constructor, owner/material/claim/safety/commit collaborator is mocked.
        execution = ArExecution(self.db, self.action, self.workflow)
        self.assertIs(type(execution), ArExecution)
        self.assertEqual(execution.scripts, self.root / 'skill' / 'vendor' / 'scripts')
        self.assertEqual(execution.ledgers, {2026: next(iter(self.material_bytes))})
        original_popen = evidence.subprocess.Popen
        launches = []

        def inspect_committed_anchor(*args, **kwargs):
            prepared = self.action._ar_process_records[-1]
            fact = self.root / 'execution-processes' / self.action_id / prepared['record_id'] / 'prepared.json'
            self.assertTrue(fact.is_file())
            self.assertEqual(hashlib.sha256(fact.read_bytes()).hexdigest(), prepared['prepared_sha256'])
            with Session(self.engine) as observer:
                fresh = observer.get(WorkflowSession, self.workflow_id)
                context = json.loads(fresh.context_json)
                entry = context['execution_safety_v1']['attempts'][0]
                self.assertEqual(entry['binding_sha256'], self.original_binding)
                self.assertEqual(entry['status'], 'intent_recorded')
                refs = entry.get('prepared_process_refs', [])
                self.assertEqual(len(refs), 1, 'Popen requires the prepared anchor committed in another PG Session')
                anchor = refs[0]
                self.assertEqual(set(anchor), {'schema_version', 'record_id', 'prepared_sha256', 'script',
                    'script_sha256', 'arguments_sha256', 'binding_sha256', 'registered_at'})
                self.assertEqual(anchor['record_id'], prepared['record_id'])
                self.assertEqual(anchor['prepared_sha256'], prepared['prepared_sha256'])
                self.assertEqual(anchor['binding_sha256'], self.original_binding)
                self.assertEqual(anchor['schema_version'], 'ar-process-evidence-v1')
                self.assertEqual(anchor['script'], 'anchor_probe.py')
                self.assertEqual(anchor['script_sha256'], hashlib.sha256(
                    (execution.scripts / 'anchor_probe.py').read_bytes()).hexdigest())
                self.assertEqual(anchor['arguments_sha256'], hashlib.sha256(b'[]').hexdigest())
                self.assertIsNotNone(datetime.fromisoformat(anchor['registered_at']).utcoffset())
                audits = list(observer.scalars(select(AuditEvent).where(
                    AuditEvent.action == 'ar_process_prepared_registered',
                    AuditEvent.resource_type == 'workflow', AuditEvent.resource_id == self.workflow_id)))
                self.assertEqual(len(audits), 1)
                details = json.loads(audits[0].details_json)
                self.assertEqual(details, {'action_id': self.action_id, 'attempt': 1,
                    'phase': 'write_ledger', 'record_id': anchor['record_id'],
                    'prepared_sha256': anchor['prepared_sha256'], 'binding_sha256': self.original_binding,
                    'evidence_revision': context['execution_safety_v1']['revision']})
            launches.append(anchor['record_id'])
            return original_popen(*args, **kwargs)

        with patch.object(evidence.subprocess, 'Popen', side_effect=inspect_committed_anchor):
            self.assertEqual(execution.script('anchor_probe.py', []).strip(), 'synthetic anchor probe')
        self.assertEqual(len(launches), 1)
        with Session(self.engine) as observer:
            entry = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)['execution_safety_v1']['attempts'][0]
            self.assertEqual(entry['binding_sha256'], self.original_binding)
            self.assertEqual(len(entry['prepared_process_refs']), 1)
            self.assertEqual(entry['status'], 'intent_recorded')
            self.assertEqual(observer.scalar(select(func.count()).select_from(FileRecord)), 2)
        self.assertTrue(self.action._ar_process_exit_confirmed)
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)

        from app.ar_execution_runner import transition_phase
        with Session(self.engine) as observer:
            before = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)
        original_entry = before['execution_safety_v1']['attempts'][0]
        state = before['ar_execution']
        state['completed'] = [*state['completed'], 'write_ledger']
        state['steps']['write_ledger'] = {'synthetic_noop': True}
        # This synthetic result tests metadata publication, not the financial writer.
        result = {'ar_execution': state, 'synthetic_noop': True,
                  'process_records': self.action._ar_process_records,
                  'process_evidence_version': evidence.SCHEMA_VERSION}
        transition_phase(self.db, self.action, self.workflow, result)
        self.db.commit()
        with Session(self.engine) as observer:
            after = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)
            completed_entry = after['execution_safety_v1']['attempts'][0]
            self.assertEqual(completed_entry['status'], 'phase_completed')
            self.assertEqual(completed_entry['prepared_process_refs'], original_entry['prepared_process_refs'])
            self.assertEqual(completed_entry['binding_sha256'], self.original_binding)
            for key, value in original_entry.items():
                if key != 'status':
                    self.assertEqual(completed_entry[key], value)
            self.assertEqual(after['execution_safety_v1']['revision'],
                             before['execution_safety_v1']['revision'] + 1)
            self.assertEqual(observer.get(WorkflowAction, self.action_id).state, 'succeeded')
            self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == 'ar_process_prepared_registered')), 1)
            next_action = observer.scalar(select(WorkflowAction).where(
                WorkflowAction.workflow_id == self.workflow_id,
                WorkflowAction.name == 'ar_write_receipt_flow'))
            self.assertIsNotNone(next_action)
            self.assertEqual(next_action.state, 'queued')
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_real_pg_audit_insert_fault_denies_spawn_and_rolls_back_anchor(self):
        execution = ArExecution(self.db, self.action, self.workflow)
        original = json.loads(self.workflow.context_json)['execution_safety_v1']
        injected = []

        def reject_anchor_audit(connection, cursor, statement, parameters, execution_context, executemany):
            values = parameters.values() if isinstance(parameters, dict) else parameters
            if (statement.startswith('INSERT INTO audit_events')
                    and 'ar_process_prepared_registered' in values):
                injected.append(True)
                # The server rejects this transaction; no guard/audit/commit is mocked.
                cursor.execute('SELECT 1 / 0')

        event.listen(self.engine, 'before_cursor_execute', reject_anchor_audit)
        try:
            with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('spawn after failed audit')) as popen:
                with self.assertRaises(DivisionByZero):
                    execution.script('anchor_probe.py', [])
                self.assertEqual(popen.call_count, 0)
        finally:
            event.remove(self.engine, 'before_cursor_execute', reject_anchor_audit)
        self.assertEqual(injected, [True])
        with Session(self.engine) as observer:
            fresh = observer.get(WorkflowSession, self.workflow_id)
            self.assertEqual(json.loads(fresh.context_json)['execution_safety_v1'], original)
            self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent)), 0)
            self.assertEqual(observer.get(WorkflowAction, self.action_id).state, 'running')
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)
        prepared = list((self.root / 'execution-processes' / self.action_id).glob('*/prepared.json'))
        self.assertEqual(len(prepared), 1)
        self.assertFalse(any(path.with_name('started.json').exists() for path in prepared))


    def test_real_commit_with_lost_acknowledgement_preserves_anchor_but_denies_spawn(self):
        execution = ArExecution(self.db, self.action, self.workflow)
        original_revision = json.loads(self.workflow.context_json)['execution_safety_v1']['revision']
        anchor_connections, lost_acks = set(), []

        def mark_anchor_transaction(connection, cursor, statement, parameters, execution_context, executemany):
            values = parameters.values() if isinstance(parameters, dict) else parameters
            if (statement.startswith('INSERT INTO audit_events')
                    and 'ar_process_prepared_registered' in values):
                anchor_connections.add(id(connection.connection.dbapi_connection))

        original_commit = self.engine.dialect.do_commit

        def commit_then_lose_acknowledgement(connection):
            physical = getattr(connection, 'dbapi_connection', connection)
            original_commit(connection)
            if id(physical) in anchor_connections and not lost_acks:
                lost_acks.append(True)
                # The actual PostgreSQL COMMIT succeeded; only its response is lost.
                raise RuntimeError('synthetic commit acknowledgement lost')

        event.listen(self.engine, 'before_cursor_execute', mark_anchor_transaction)
        try:
            with patch.object(self.engine.dialect, 'do_commit', side_effect=commit_then_lose_acknowledgement):
                with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('spawn after ambiguous commit')) as popen:
                    with self.assertRaisesRegex(RuntimeError, 'commit acknowledgement lost'):
                        execution.script('anchor_probe.py', [])
                    self.assertEqual(popen.call_count, 0)
        finally:
            event.remove(self.engine, 'before_cursor_execute', mark_anchor_transaction)
        self.assertEqual(lost_acks, [True])
        with Session(self.engine) as observer:
            context = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)
            index = context['execution_safety_v1']
            self.assertEqual(index['revision'], original_revision + 1)
            entry = index['attempts'][0]
            self.assertEqual(entry['binding_sha256'], self.original_binding)
            self.assertEqual(entry['status'], 'intent_recorded')
            self.assertEqual(len(entry['prepared_process_refs']), 1)
            audits = list(observer.scalars(select(AuditEvent).where(
                AuditEvent.action == 'ar_process_prepared_registered')))
            self.assertEqual(len(audits), 1)
            self.assertEqual(json.loads(audits[0].details_json)['record_id'],
                             entry['prepared_process_refs'][0]['record_id'])
        prepared = list((self.root / 'execution-processes' / self.action_id).glob('*/prepared.json'))
        self.assertEqual(len(prepared), 1)
        self.assertFalse(any(path.with_name('started.json').exists() for path in prepared))
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_abandoned_between_transactions_keeps_anchor_but_denies_spawn(self):
        from app.ar_abandon import KEY, binding, is_abandoned
        execution = ArExecution(self.db, self.action, self.workflow)
        original_revision = json.loads(self.workflow.context_json)['execution_safety_v1']['revision']
        anchor_connections, marker_commits = set(), []

        def mark_anchor_transaction(connection, cursor, statement, parameters, execution_context, executemany):
            values = parameters.values() if isinstance(parameters, dict) else parameters
            if (statement.startswith('INSERT INTO audit_events')
                    and 'ar_process_prepared_registered' in values):
                anchor_connections.add(id(connection.connection.dbapi_connection))

        original_commit = self.engine.dialect.do_commit

        def commit_then_change_eligibility(connection):
            physical = getattr(connection, 'dbapi_connection', connection)
            original_commit(connection)
            if id(physical) in anchor_connections and not marker_commits:
                marker_commits.append(True)
                # Another real PG connection changes only the fresh task eligibility.
                # This legacy display marker is not a process-stop proof or an unlock.
                with Session(self.engine) as editor:
                    fresh = editor.get(WorkflowSession, self.workflow_id)
                    context = json.loads(fresh.context_json)
                    self.assertEqual(len(context['execution_safety_v1']['attempts'][0]['prepared_process_refs']), 1)
                    context[KEY] = {'schema_version': 'ar-abandonment-v1',
                                    'state': 'abandoned', 'binding': binding(fresh, context)}
                    self.assertTrue(is_abandoned(fresh, context))
                    fresh.context_json = json.dumps(context)
                    editor.commit()

        event.listen(self.engine, 'before_cursor_execute', mark_anchor_transaction)
        try:
            with patch.object(self.engine.dialect, 'do_commit', side_effect=commit_then_change_eligibility):
                with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('spawn after abandonment')) as popen:
                    with self.assertRaisesRegex(ValueError, '封存'):
                        execution.script('anchor_probe.py', [])
                    self.assertEqual(popen.call_count, 0)
        finally:
            event.remove(self.engine, 'before_cursor_execute', mark_anchor_transaction)
        self.assertEqual(marker_commits, [True])
        with Session(self.engine) as observer:
            fresh = observer.get(WorkflowSession, self.workflow_id)
            context = json.loads(fresh.context_json)
            self.assertTrue(is_abandoned(fresh, context))
            self.assertEqual(context['execution_safety_v1']['revision'], original_revision + 1)
            entry = context['execution_safety_v1']['attempts'][0]
            self.assertEqual(entry['binding_sha256'], self.original_binding)
            self.assertEqual(entry['status'], 'intent_recorded')
            self.assertEqual(len(entry['prepared_process_refs']), 1)
            audits = list(observer.scalars(select(AuditEvent).where(
                AuditEvent.action == 'ar_process_prepared_registered',
                AuditEvent.resource_id == self.workflow_id)))
            self.assertEqual(len(audits), 1)
            self.assertEqual(json.loads(audits[0].details_json)['record_id'],
                             entry['prepared_process_refs'][0]['record_id'])
            self.assertEqual(observer.get(WorkflowAction, self.action_id).state, 'running')
        prepared = list((self.root / 'execution-processes' / self.action_id).glob('*/prepared.json'))
        self.assertEqual(len(prepared), 1)
        self.assertFalse(any(path.with_name('started.json').exists() for path in prepared))
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_real_action_lock_wait_rechecks_expired_database_lease(self):
        import threading
        import time
        from app.ar_execution_contract import ExecutionLeaseLost
        execution = ArExecution(self.db, self.action, self.workflow)
        anchor_connections, holder_started, threads, failures, observations = set(), [], [], [], []
        ready = threading.Event()

        def hold_action_until_waiter_and_expiry():
            try:
                with Session(self.engine) as holder:
                    action = holder.scalar(select(WorkflowAction).where(
                        WorkflowAction.id == self.action_id).with_for_update())
                    now = holder.scalar(select(func.clock_timestamp()))
                    expires = now + timedelta(milliseconds=150)
                    action.lease_expires_at = expires
                    holder.flush()
                    holder_pid = holder.scalar(select(func.pg_backend_pid()))
                    ready.set()
                    bounded = time.monotonic() + 1.5
                    while time.monotonic() < bounded:
                        waiting = holder.scalar(text("SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname = current_database() AND pid != :pid "
                            "AND wait_event_type = 'Lock' AND query LIKE '%workflow_actions%'"),
                            {'pid': holder_pid})
                        current = holder.scalar(select(func.clock_timestamp()))
                        if waiting and current >= expires:
                            observations.append({'waiting': waiting, 'expired_at_release': current >= expires})
                            holder.commit()
                            return
                        time.sleep(0.01)
                    raise AssertionError('the second gate never actually waited on the action row')
            except BaseException as exc:
                failures.append(exc)
                ready.set()

        def mark_anchor_transaction(connection, cursor, statement, parameters, execution_context, executemany):
            values = parameters.values() if isinstance(parameters, dict) else parameters
            if (statement.startswith('INSERT INTO audit_events')
                    and 'ar_process_prepared_registered' in values):
                anchor_connections.add(id(connection.connection.dbapi_connection))

        original_commit = self.engine.dialect.do_commit

        def commit_then_hold_action(connection):
            physical = getattr(connection, 'dbapi_connection', connection)
            original_commit(connection)
            if id(physical) in anchor_connections and not holder_started:
                holder_started.append(True)
                thread = threading.Thread(target=hold_action_until_waiter_and_expiry)
                threads.append(thread)
                thread.start()
                self.assertTrue(ready.wait(2), 'the independent lock holder must be ready')
                if failures:
                    raise failures[0]

        event.listen(self.engine, 'before_cursor_execute', mark_anchor_transaction)
        try:
            with patch.object(self.engine.dialect, 'do_commit', side_effect=commit_then_hold_action):
                with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('spawn after lease expiry')) as popen:
                    with self.assertRaises(ExecutionLeaseLost):
                        execution.script('anchor_probe.py', [])
                    self.assertEqual(popen.call_count, 0)
        finally:
            event.remove(self.engine, 'before_cursor_execute', mark_anchor_transaction)
            for thread in threads:
                thread.join(3)
                self.assertFalse(thread.is_alive(), 'owned lock holder must finish')
        if failures:
            raise failures[0]
        self.assertEqual(holder_started, [True])
        self.assertEqual(len(observations), 1)
        self.assertGreater(observations[0]['waiting'], 0)
        self.assertTrue(observations[0]['expired_at_release'])
        with Session(self.engine) as observer:
            context = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)
            entry = context['execution_safety_v1']['attempts'][0]
            self.assertEqual(entry['binding_sha256'], self.original_binding)
            self.assertEqual(entry['status'], 'intent_recorded')
            self.assertEqual(len(entry['prepared_process_refs']), 1)
            self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == 'ar_process_prepared_registered')), 1)
            self.assertEqual(observer.get(WorkflowAction, self.action_id).state, 'running')
        prepared = list((self.root / 'execution-processes' / self.action_id).glob('*/prepared.json'))
        self.assertEqual(len(prepared), 1)
        self.assertFalse(any(path.with_name('started.json').exists() for path in prepared))
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_flushed_caller_business_change_is_not_committed_or_rolled_back(self):
        execution = ArExecution(self.db, self.action, self.workflow)
        record = self.db.scalar(select(FileRecord).where(FileRecord.workflow_id == self.workflow_id).limit(1))
        record_id, original_name = record.id, record.original_name
        record.original_name = '未提交材料-codex测试.xlsx'
        self.db.flush()
        self.assertTrue(self.db.in_transaction())
        caller_commits, caller_rollbacks, launches = [], [], []
        original_popen = evidence.subprocess.Popen

        def on_commit(session):
            caller_commits.append(True)

        def on_rollback(session):
            caller_rollbacks.append(True)

        def inspect_caller_isolation(*args, **kwargs):
            with Session(self.engine) as observer:
                self.assertEqual(observer.get(FileRecord, record_id).original_name, original_name)
                context = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)
                self.assertEqual(len(context['execution_safety_v1']['attempts'][0]['prepared_process_refs']), 1)
                self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                    AuditEvent.action == 'ar_process_prepared_registered')), 1)
            launches.append(True)
            return original_popen(*args, **kwargs)

        event.listen(self.db, 'after_commit', on_commit)
        event.listen(self.db, 'after_rollback', on_rollback)
        try:
            with patch.object(evidence.subprocess, 'Popen', side_effect=inspect_caller_isolation):
                self.assertEqual(execution.script('anchor_probe.py', []).strip(), 'synthetic anchor probe')
            self.assertEqual(caller_commits, [])
            self.assertEqual(caller_rollbacks, [])
            self.assertTrue(self.db.in_transaction())
            self.assertEqual(record.original_name, '未提交材料-codex测试.xlsx')
        finally:
            event.remove(self.db, 'after_commit', on_commit)
            event.remove(self.db, 'after_rollback', on_rollback)
        self.assertEqual(launches, [True])
        self.assertTrue(self.action._ar_process_exit_confirmed)
        self.db.rollback()  # Only this explicit test cleanup discards the caller's business write.
        with Session(self.engine) as observer:
            self.assertEqual(observer.get(FileRecord, record_id).original_name, original_name)
            entry = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)['execution_safety_v1']['attempts'][0]
            self.assertEqual(entry['binding_sha256'], self.original_binding)
            self.assertEqual(entry['status'], 'intent_recorded')
            self.assertEqual(len(entry['prepared_process_refs']), 1)
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_caller_action_row_conflict_preserves_stricter_lock_timeout_and_pending_write(self):
        from sqlalchemy.exc import OperationalError
        execution = ArExecution(self.db, self.action, self.workflow)
        with Session(self.engine) as observer:
            original_heartbeat = observer.get(WorkflowAction, self.action_id).heartbeat_at
            original_index = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)['execution_safety_v1']
        self.action.heartbeat_at = datetime.now(UTC) + timedelta(seconds=1)
        self.db.flush()  # The caller now genuinely owns the action row lock.
        caller_commits, caller_rollbacks, observed_limits = [], [], []

        def configure_stricter_limit(connection, record, proxy):
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '75ms'")

        def observe_gate_limit(connection, cursor, statement, parameters, execution_context, executemany):
            if "FROM pg_settings WHERE name = 'lock_timeout'" in statement:
                cursor.execute('SHOW lock_timeout')
                observed_limits.append(cursor.fetchone()[0])

        def on_commit(session):
            caller_commits.append(True)

        def on_rollback(session):
            caller_rollbacks.append(True)

        event.listen(self.engine, 'checkout', configure_stricter_limit)
        event.listen(self.engine, 'before_cursor_execute', observe_gate_limit)
        event.listen(self.db, 'after_commit', on_commit)
        event.listen(self.db, 'after_rollback', on_rollback)
        try:
            with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('spawn through caller conflict')) as popen:
                with self.assertRaises(OperationalError) as rejected:
                    execution.script('anchor_probe.py', [])
                self.assertEqual(rejected.exception.orig.sqlstate, '55P03')
                self.assertEqual(popen.call_count, 0)
            self.assertEqual(observed_limits, ['75ms'])
            self.assertEqual(caller_commits, [])
            self.assertEqual(caller_rollbacks, [])
            self.assertTrue(self.db.in_transaction())
            with Session(self.engine) as observer:
                self.assertEqual(observer.get(WorkflowAction, self.action_id).heartbeat_at, original_heartbeat)
                self.assertEqual(json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)['execution_safety_v1'], original_index)
                self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                    AuditEvent.action == 'ar_process_prepared_registered')), 0)
        finally:
            event.remove(self.engine, 'checkout', configure_stricter_limit)
            event.remove(self.engine, 'before_cursor_execute', observe_gate_limit)
            event.remove(self.db, 'after_commit', on_commit)
            event.remove(self.db, 'after_rollback', on_rollback)
        self.db.rollback()
        with Session(self.engine) as observer:
            self.assertEqual(observer.get(WorkflowAction, self.action_id).heartbeat_at, original_heartbeat)
        prepared = list((self.root / 'execution-processes' / self.action_id).glob('*/prepared.json'))
        self.assertEqual(len(prepared), 1)
        self.assertFalse(any(path.with_name('started.json').exists() for path in prepared))
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_real_heartbeat_loss_between_scripts_is_sticky_in_worker_dispatch(self):
        import threading
        from sqlalchemy.orm import sessionmaker
        from dataclasses import replace
        from app import leases, workflow_service as service, workflow_execution_policy as policy
        from app.ar_execution_contract import ExecutionLeaseLost
        from app.settings import settings
        from app.workflow_action_state import isolated_action_state
        context = json.loads(self.workflow.context_json)
        context.pop('execution_safety_v1')  # A fresh queued synthetic fixture has not started an effect.
        self.workflow.context_json = json.dumps(context)
        self.action.state = isolated_action_state('queued')
        self.action.attempt_count, self.action.worker_id = 0, ''
        self.action.started_at, self.action.heartbeat_at, self.action.lease_expires_at = None, None, None
        self.db.commit()
        callback_seen = threading.Event()
        heartbeats, launches, observations = [], [], {}
        real_heartbeat = leases.LeaseHeartbeat
        original_popen = evidence.subprocess.Popen

        def capture_real_heartbeat(*args, **kwargs):
            heartbeat = real_heartbeat(*args, **kwargs)
            self.assertIs(type(heartbeat), real_heartbeat)
            original_callback = heartbeat._on_lease_lost

            def observe_loss_callback():
                original_callback()
                callback_seen.set()

            heartbeat._on_lease_lost = observe_loss_callback
            heartbeats.append(heartbeat)
            return heartbeat

        def only_first_spawn(*args, **kwargs):
            launches.append(True)
            if len(launches) > 1:
                raise AssertionError('a known heartbeat loss must deny the second spawn')
            return original_popen(*args, **kwargs)

        def synthetic_phase(execution):
            # Replace only the financial writer; constructor, execute_phase and all guards remain real.
            observations['first_stdout'] = execution.script('anchor_probe.py', []).strip()
            observations['no_active_process_callback'] = not hasattr(execution.action, '_ar_terminate_process')
            with Session(self.engine) as editor:
                action = editor.get(WorkflowAction, self.action_id)
                action.lease_expires_at = editor.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
                editor.commit()
            observations['callback_seen'] = callback_seen.wait(2)
            observations['heartbeat_lost'] = heartbeats[0].lease_lost
            observations['latch_before_second'] = getattr(execution.action, '_ar_lease_lost', False)
            # Restore a valid synthetic DB lease to isolate the sticky in-memory loss rule.
            with Session(self.engine) as editor:
                action = editor.get(WorkflowAction, self.action_id)
                action.lease_expires_at = editor.scalar(select(func.clock_timestamp())) + timedelta(minutes=5)
                editor.commit()
            try:
                execution.script('anchor_probe.py', [])
            except ExecutionLeaseLost:
                observations['second_blocked'] = True
                observations['latch_after_second'] = getattr(execution.action, '_ar_lease_lost', False)
                raise
            observations['second_blocked'] = False
            raise AssertionError('second script returned despite known lease loss')

        isolated_settings = replace(settings, ar_hexiao_execution_enabled=True, worker_heartbeat_seconds=0.01)
        with patch.object(policy, 'settings', isolated_settings), patch.object(service, 'settings', isolated_settings):
            with patch.object(leases, 'settings', isolated_settings):
                with patch.object(leases, 'SessionLocal', sessionmaker(self.engine, expire_on_commit=False)):
                    with patch.object(service, 'LeaseHeartbeat', capture_real_heartbeat):
                        with patch.object(ArExecution, 'write_ledger', synthetic_phase):
                            with patch.object(evidence.subprocess, 'Popen', side_effect=only_first_spawn):
                                self.assertTrue(service.run_workflow_action_once(
                                    self.db, ('workflow',), 'synthetic-worker', execution_contracts=(CONTRACT_VERSION,)))
        self.assertEqual(len(heartbeats), 1)
        self.assertFalse(heartbeats[0]._thread.is_alive())
        self.assertEqual(observations['first_stdout'], 'synthetic anchor probe')
        self.assertTrue(observations['no_active_process_callback'])
        self.assertTrue(observations['callback_seen'])
        self.assertTrue(observations['heartbeat_lost'])
        self.assertTrue(observations['latch_before_second'], 'the real Worker heartbeat callback must latch loss between scripts')
        self.assertTrue(observations.get('second_blocked'), 'a fresh valid row cannot authorize after known lease loss')
        self.assertTrue(observations.get('latch_after_second'), 'a later script must never reset the sticky loss flag')
        self.assertEqual(launches, [True])
        with Session(self.engine) as observer:
            action = observer.get(WorkflowAction, self.action_id)
            self.assertEqual(action.state, 'running')
            self.assertEqual(action.worker_id, 'synthetic-worker')
            self.assertEqual(action.attempt_count, 1)
            self.assertIsNotNone(action.lease_expires_at)
            entry = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)['execution_safety_v1']['attempts'][0]
            self.assertEqual(entry['status'], 'intent_recorded')
            self.assertEqual(len(entry['prepared_process_refs']), 1)
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_gate_cancellation_old_worker_cannot_overwrite_new_owner(self):
        self._assert_cancel_fence_preserves_changed_identity()

    def test_gate_cancellation_old_phase_cannot_cancel_changed_action_name(self):
        self._assert_cancel_fence_preserves_changed_identity(change_name=True)

    def _assert_cancel_fence_preserves_changed_identity(self, *, change_name=False):
        from dataclasses import replace
        from sqlalchemy.orm import sessionmaker
        from app import leases, workflow_service as service, workflow_execution_policy as policy
        from app.ar_execution_contract import ExecutionCancelled
        from app.scheduler import acquire_claim_lock
        from app.settings import settings
        from app.workflow_action_state import isolated_action_state
        context = json.loads(self.workflow.context_json)
        context.pop('execution_safety_v1')
        self.workflow.context_json = json.dumps(context)
        self.action.state = isolated_action_state('queued')
        self.action.attempt_count, self.action.worker_id = 0, ''
        self.action.started_at, self.action.heartbeat_at, self.action.lease_expires_at = None, None, None
        self.db.commit()
        anchor_connections, cancellations, observations = set(), [], {}
        original_commit = self.engine.dialect.do_commit

        def mark_anchor_transaction(connection, cursor, statement, parameters, execution_context, executemany):
            values = parameters.values() if isinstance(parameters, dict) else parameters
            if (statement.startswith('INSERT INTO audit_events')
                    and 'ar_process_prepared_registered' in values):
                anchor_connections.add(id(connection.connection.dbapi_connection))

        def commit_then_cancel(connection):
            physical = getattr(connection, 'dbapi_connection', connection)
            original_commit(connection)
            if id(physical) in anchor_connections and not cancellations:
                cancellations.append(True)
                with Session(self.engine) as editor:
                    fresh = editor.get(WorkflowSession, self.workflow_id)
                    context = json.loads(fresh.context_json)
                    context['stop_after_action'] = True
                    fresh.context_json = json.dumps(context)
                    fresh.state = 'cancelling'
                    editor.commit()

        def synthetic_phase(execution):
            try:
                execution.script('anchor_probe.py', [])
            except ExecutionCancelled:
                observations['outer_lock_absent'] = not execution.db.info.get('ar_execution_lock')
                # Only after the real launch gate releases both locks can a new owner take over.
                with Session(self.engine) as takeover:
                    takeover.execute(text("SET LOCAL lock_timeout = '250ms'"))
                    acquire_claim_lock(takeover)
                    action = takeover.scalar(select(WorkflowAction).where(
                        WorkflowAction.id == self.action_id).with_for_update())
                    fresh = takeover.get(WorkflowSession, self.workflow_id)
                    now = takeover.scalar(select(func.clock_timestamp()))
                    if change_name:
                        # Defensive metadata corruption, not a supported production action rename.
                        action.name = 'ar_write_receipt_flow'
                    else:
                        action.worker_id, action.attempt_count = 'synthetic-new-worker', 2
                        action.heartbeat_at, action.lease_expires_at = now, now + timedelta(minutes=5)
                    action.state = 'running'
                    context = json.loads(fresh.context_json)
                    context.pop('stop_after_action')
                    fresh.context_json = json.dumps(context)
                    fresh.state, fresh.stage = 'running', 'applying'
                    fresh.progress_message = 'codex测试新Worker接管状态'
                    observations['new_lease'] = action.lease_expires_at
                    takeover.commit()
                    observations['new_owner_committed'] = True
                raise
            raise AssertionError('the real fresh cancellation guard did not stop the script')

        isolated_settings = replace(settings, ar_hexiao_execution_enabled=True, worker_heartbeat_seconds=3600)
        event.listen(self.engine, 'before_cursor_execute', mark_anchor_transaction)
        try:
            with patch.object(policy, 'settings', isolated_settings), patch.object(service, 'settings', isolated_settings):
                with patch.object(leases, 'settings', isolated_settings):
                    with patch.object(leases, 'SessionLocal', sessionmaker(self.engine, expire_on_commit=False)):
                        with patch.object(self.engine.dialect, 'do_commit', side_effect=commit_then_cancel):
                            with patch.object(ArExecution, 'write_ledger', synthetic_phase):
                                with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('spawn despite cancellation')) as popen:
                                    self.assertTrue(service.run_workflow_action_once(
                                        self.db, ('workflow',), 'synthetic-worker', execution_contracts=(CONTRACT_VERSION,)))
                                    self.assertEqual(popen.call_count, 0)
        finally:
            event.remove(self.engine, 'before_cursor_execute', mark_anchor_transaction)
        self.assertEqual(cancellations, [True])
        self.assertTrue(observations.get('outer_lock_absent'))
        self.assertTrue(observations.get('new_owner_committed'))
        with Session(self.engine) as observer:
            action = observer.get(WorkflowAction, self.action_id)
            self.assertEqual(action.worker_id, 'synthetic-worker' if change_name else 'synthetic-new-worker')
            self.assertEqual(action.attempt_count, 1 if change_name else 2)
            self.assertEqual(action.name, 'ar_write_receipt_flow' if change_name else 'ar_write_ledger')
            self.assertEqual(action.state, 'running', 'the old cancellation handler must not overwrite the new owner')
            self.assertEqual(action.lease_expires_at, observations['new_lease'])
            fresh = observer.get(WorkflowSession, self.workflow_id)
            self.assertEqual((fresh.state, fresh.stage, fresh.progress_message),
                             ('running', 'applying', 'codex测试新Worker接管状态'))
            context = json.loads(fresh.context_json)
            self.assertNotIn('stop_after_action', context)
            entry = context['execution_safety_v1']['attempts'][0]
            self.assertEqual(entry['attempt'], 1)
            self.assertEqual(entry['status'], 'intent_recorded')
            self.assertEqual(len(entry['prepared_process_refs']), 1)
        prepared = list((self.root / 'execution-processes' / self.action_id).glob('*/prepared.json'))
        self.assertEqual(len(prepared), 1)
        self.assertFalse(any(path.with_name('started.json').exists() for path in prepared))
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_gate_cancellation_current_owner_is_saved_with_prepared_reference(self):
        from dataclasses import replace
        from sqlalchemy.orm import sessionmaker
        from app import leases, workflow_service as service, workflow_execution_policy as policy
        from app.settings import settings
        from app.workflow_action_state import isolated_action_state
        context = json.loads(self.workflow.context_json)
        context.pop('execution_safety_v1')
        self.workflow.context_json = json.dumps(context)
        self.action.state = isolated_action_state('queued')
        self.action.attempt_count, self.action.worker_id = 0, ''
        self.action.started_at, self.action.heartbeat_at, self.action.lease_expires_at = None, None, None
        self.db.commit()
        anchor_connections, cancellations = set(), []
        original_commit = self.engine.dialect.do_commit

        def mark_anchor_transaction(connection, cursor, statement, parameters, execution_context, executemany):
            values = parameters.values() if isinstance(parameters, dict) else parameters
            if (statement.startswith('INSERT INTO audit_events')
                    and 'ar_process_prepared_registered' in values):
                anchor_connections.add(id(connection.connection.dbapi_connection))

        def commit_then_cancel(connection):
            physical = getattr(connection, 'dbapi_connection', connection)
            original_commit(connection)
            if id(physical) in anchor_connections and not cancellations:
                cancellations.append(True)
                with Session(self.engine) as editor:
                    fresh = editor.get(WorkflowSession, self.workflow_id)
                    context = json.loads(fresh.context_json)
                    context['stop_after_action'] = True
                    fresh.context_json = json.dumps(context)
                    fresh.state = 'cancelling'
                    editor.commit()

        def synthetic_phase(execution):
            execution.script('anchor_probe.py', [])
            raise AssertionError('the fresh cancellation guard did not stop the script')

        isolated_settings = replace(settings, ar_hexiao_execution_enabled=True, worker_heartbeat_seconds=3600)
        event.listen(self.engine, 'before_cursor_execute', mark_anchor_transaction)
        try:
            with patch.object(policy, 'settings', isolated_settings), patch.object(service, 'settings', isolated_settings):
                with patch.object(leases, 'settings', isolated_settings):
                    with patch.object(leases, 'SessionLocal', sessionmaker(self.engine, expire_on_commit=False)):
                        with patch.object(self.engine.dialect, 'do_commit', side_effect=commit_then_cancel):
                            with patch.object(ArExecution, 'write_ledger', synthetic_phase):
                                with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('spawn despite cancellation')) as popen:
                                    self.assertTrue(service.run_workflow_action_once(
                                        self.db, ('workflow',), 'synthetic-worker', execution_contracts=(CONTRACT_VERSION,)))
                                    self.assertEqual(popen.call_count, 0)
        finally:
            event.remove(self.engine, 'before_cursor_execute', mark_anchor_transaction)
        self.assertEqual(cancellations, [True])
        with Session(self.engine) as observer:
            action = observer.get(WorkflowAction, self.action_id)
            self.assertEqual((action.worker_id, action.attempt_count, action.state), ('synthetic-worker', 1, 'cancelled'))
            self.assertIsNone(action.lease_expires_at)
            fresh = observer.get(WorkflowSession, self.workflow_id)
            self.assertEqual((fresh.state, fresh.stage), ('cancelled', 'cancelled'))
            context = json.loads(fresh.context_json)
            self.assertTrue(context['stop_after_action'])
            entry = context['execution_safety_v1']['attempts'][0]
            self.assertEqual(entry['status'], 'intent_recorded')
            self.assertEqual(len(entry['prepared_process_refs']), 1)
            self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == 'ar_process_prepared_registered')), 1)
        prepared = list((self.root / 'execution-processes' / self.action_id).glob('*/prepared.json'))
        self.assertEqual(len(prepared), 1)
        self.assertFalse(any(path.with_name('started.json').exists() for path in prepared))
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_malformed_historical_reference_identity_denies_another_spawn(self):
        execution = ArExecution(self.db, self.action, self.workflow)
        original_gate = execution.launch_gate
        anchors = []

        def capture_original_anchor(anchor):
            anchors.append(anchor)
            return original_gate(anchor)

        with patch.object(execution, 'launch_gate', side_effect=capture_original_anchor):
            self.assertEqual(execution.script('anchor_probe.py', []).strip(), 'synthetic anchor probe')
        self.assertEqual(len(anchors), 1)
        with Session(self.engine) as observer:
            original = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)['execution_safety_v1']
        self.assertEqual(len(original['attempts'][0]['prepared_process_refs']), 1)
        self.assertEqual(original['attempts'][0]['status'], 'intent_recorded')
        permits = []
        with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('spawn after anchor replay')) as popen:
            with self.assertRaisesRegex(ValueError, '已登记'):
                # Exact immutable anchor captured at the real first script gate;
                # still an intent, not a completed-phase shortcut rejection.
                with original_gate(anchors[0]):
                    permits.append(True)
                    evidence.subprocess.Popen(['synthetic-no-launch'])
            self.assertEqual(popen.call_count, 0)
        self.assertEqual(permits, [])
        with Session(self.engine) as observer:
            self.assertEqual(json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)['execution_safety_v1'], original)
            self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == 'ar_process_prepared_registered')), 1)
        cases = (('NUL', {'script': chr(0)}), ('dot', {'script': '.'}), ('duplicate', None),
                 ('digest', {'prepared_sha256': 'bad-digest'}), ('binding', {'binding_sha256': 'f' * 64}))
        for label, fields in cases:
            with self.subTest(invalid_reference=label):
                # A controlled malformed persisted record, not a fabricated valid process fact.
                corrupted = json.loads(json.dumps(original))
                refs = corrupted['attempts'][0]['prepared_process_refs']
                if fields is None:
                    refs.append(dict(refs[0]))
                else:
                    refs[0].update(fields)
                with Session(self.engine) as editor:
                    fresh = editor.get(WorkflowSession, self.workflow_id)
                    context = json.loads(fresh.context_json)
                    context['execution_safety_v1'] = corrupted
                    fresh.context_json = json.dumps(context)
                    editor.commit()
                with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('spawn with malformed historical ref')) as popen:
                    with self.assertRaisesRegex(ValueError, '引用'):
                        execution.script('anchor_probe.py', [])
                    self.assertEqual(popen.call_count, 0)
                with Session(self.engine) as observer:
                    self.assertEqual(json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)['execution_safety_v1'], corrupted)
                    self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                        AuditEvent.action == 'ar_process_prepared_registered')), 1)
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_boolean_fresh_material_version_denies_spawn_without_replacing_anchor(self):
        execution = ArExecution(self.db, self.action, self.workflow)
        original_revision = json.loads(self.workflow.context_json)['execution_safety_v1']['revision']
        anchor_connections, changes = set(), []

        def mark_anchor_transaction(connection, cursor, statement, parameters, execution_context, executemany):
            values = parameters.values() if isinstance(parameters, dict) else parameters
            if (statement.startswith('INSERT INTO audit_events')
                    and 'ar_process_prepared_registered' in values):
                anchor_connections.add(id(connection.connection.dbapi_connection))

        original_commit = self.engine.dialect.do_commit

        def commit_then_corrupt_type(connection):
            physical = getattr(connection, 'dbapi_connection', connection)
            original_commit(connection)
            if id(physical) in anchor_connections and not changes:
                changes.append(True)
                with Session(self.engine) as editor:
                    fresh = editor.get(WorkflowSession, self.workflow_id)
                    context = json.loads(fresh.context_json)
                    context['ar_execution']['material_version'] = True
                    fresh.context_json = json.dumps(context)
                    editor.commit()

        event.listen(self.engine, 'before_cursor_execute', mark_anchor_transaction)
        try:
            with patch.object(self.engine.dialect, 'do_commit', side_effect=commit_then_corrupt_type):
                with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('spawn with boolean material version')) as popen:
                    with self.assertRaises(ValueError):
                        execution.script('anchor_probe.py', [])
                    self.assertEqual(popen.call_count, 0)
        finally:
            event.remove(self.engine, 'before_cursor_execute', mark_anchor_transaction)
        self.assertEqual(changes, [True])
        with Session(self.engine) as observer:
            context = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)
            self.assertIs(context['ar_execution']['material_version'], True)
            index = context['execution_safety_v1']
            self.assertEqual(index['revision'], original_revision + 1)
            entry = index['attempts'][0]
            self.assertIs(type(entry['material_version']), int)
            self.assertEqual(entry['binding_sha256'], self.original_binding)
            self.assertEqual(entry['status'], 'intent_recorded')
            self.assertEqual(len(entry['prepared_process_refs']), 1)
            self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == 'ar_process_prepared_registered')), 1)
        prepared = list((self.root / 'execution-processes' / self.action_id).glob('*/prepared.json'))
        self.assertEqual(len(prepared), 1)
        self.assertFalse(any(path.with_name('started.json').exists() for path in prepared))
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_started_window_loss_callback_releases_gate_before_termination_and_wait(self):
        self._assert_loss_cleanup_releases_launch_locks(window='started')

    def test_real_heartbeat_loss_during_communicate_terminates_promptly_outside_gate(self):
        self._assert_loss_cleanup_releases_launch_locks(window='communicate')

    def test_started_fact_fsync_failure_cleans_up_child_outside_launch_gate(self):
        self._assert_loss_cleanup_releases_launch_locks(window='started_fact_failure')

    def _assert_loss_cleanup_releases_launch_locks(self, *, window):
        import threading
        import time
        from dataclasses import replace
        from sqlalchemy.exc import OperationalError
        from sqlalchemy.orm import sessionmaker
        from app import leases, workflow_service as service, workflow_execution_policy as policy
        from app.scheduler import acquire_claim_lock
        from app.settings import settings
        from app.workflow_action_state import isolated_action_state
        script = self.root / 'skill' / 'vendor' / 'scripts' / 'anchor_probe.py'
        script.write_text("import time\ntime.sleep(10)\nprint('synthetic anchor probe')\n", encoding='utf-8')
        skill_hash = hash_skill_directory(self.root / 'skill')
        context = json.loads(self.workflow.context_json)
        context.pop('execution_safety_v1')
        context['ar_execution']['skill_hash'] = skill_hash
        self.workflow.skill_hash, self.workflow.context_json = skill_hash, json.dumps(context)
        self.action.state = isolated_action_state('queued')
        self.action.attempt_count, self.action.worker_id = 0, ''
        self.action.started_at, self.action.heartbeat_at, self.action.lease_expires_at = None, None, None
        self.db.commit()
        heartbeats, children, callbacks, lock_observations, communication_callbacks = [], [], [], [], []
        communicating = threading.Event()
        fact_faults = []
        real_heartbeat, real_popen = leases.LeaseHeartbeat, evidence.subprocess.Popen
        real_wait, real_terminate, real_write = real_popen.wait, evidence._terminate_process_group, evidence._write_fact
        real_communicate = real_popen._communicate

        def capture_real_heartbeat(*args, **kwargs):
            heartbeat = real_heartbeat(*args, **kwargs)
            if window == 'communicate':
                callback = heartbeat._on_lease_lost

                def observe_real_callback():
                    callbacks.append(True)
                    communication_callbacks.append(communicating.is_set())
                    callback()

                heartbeat._on_lease_lost = observe_real_callback
            heartbeats.append(heartbeat)
            return heartbeat

        def capture_child(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        def observe_lock_release(stage):
            released = True
            with Session(self.engine) as observer:
                try:
                    observer.execute(text("SET LOCAL lock_timeout = '75ms'"))
                    acquire_claim_lock(observer)
                    observer.scalar(select(WorkflowAction.id).where(
                        WorkflowAction.id == self.action_id).with_for_update())
                except OperationalError as error:
                    if error.orig.sqlstate != '55P03':
                        raise
                    released = False
                finally:
                    observer.rollback()
            lock_observations.append((stage, released))

        def trace_terminate(child):
            observe_lock_release('terminate')
            return real_terminate(child)

        def trace_wait(child, *args, **kwargs):
            observe_lock_release('wait')
            return real_wait(child, *args, **kwargs)

        def inject_callback_before_started(path, fact):
            if window == 'started' and path.name == 'started.json' and not callbacks:
                self.assertIsNone(children[0].poll())
                callbacks.append(True)
                # A fault-window injection of the real closure. Normally _touch first waits on this row lock.
                heartbeats[0]._on_lease_lost()
            if window == 'started_fact_failure' and path.name == 'started.json':
                def reject_started_fsync(fd):
                    fact_faults.append(True)
                    raise OSError('synthetic started fsync refused')

                with patch.object(evidence.os, 'fsync', side_effect=reject_started_fsync):
                    return real_write(path, fact)
            return real_write(path, fact)

        def trace_communicate(child, *args, **kwargs):
            if window != 'communicate':
                return real_communicate(child, *args, **kwargs)
            communicating.set()
            try:
                with Session(self.engine) as editor:
                    action = editor.get(WorkflowAction, self.action_id)
                    action.lease_expires_at = editor.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
                    editor.commit()
                return real_communicate(child, *args, **kwargs)
            finally:
                communicating.clear()

        def synthetic_phase(execution):
            execution.script('anchor_probe.py', [], accepted=(0, 143, -15))
            raise AssertionError('a known lease loss cannot become a successful financial phase')

        began = time.monotonic()
        isolated_settings = replace(settings, ar_hexiao_execution_enabled=True,
                                    worker_heartbeat_seconds=0.01 if window == 'communicate' else 3600)
        with patch.object(policy, 'settings', isolated_settings), patch.object(service, 'settings', isolated_settings):
            with patch.object(leases, 'settings', isolated_settings):
                with patch.object(leases, 'SessionLocal', sessionmaker(self.engine, expire_on_commit=False)):
                    with patch.object(service, 'LeaseHeartbeat', capture_real_heartbeat):
                        with patch.object(ArExecution, 'write_ledger', synthetic_phase):
                            with patch.object(real_popen, 'wait', trace_wait), patch.object(real_popen, '_communicate', trace_communicate):
                                with patch.object(evidence.subprocess, 'Popen', side_effect=capture_child):
                                    with patch.object(evidence, '_terminate_process_group', trace_terminate):
                                        with patch.object(evidence, '_write_fact', inject_callback_before_started):
                                            self.assertTrue(service.run_workflow_action_once(
                                                self.db, ('workflow',), 'synthetic-worker', execution_contracts=(CONTRACT_VERSION,)))
        if window == 'communicate':
            self.assertEqual(communication_callbacks, [True])
            self.assertTrue(heartbeats[0].lease_lost)
            self.assertLess(time.monotonic() - began, 5, 'the real loss callback must promptly stop the ten-second no-op')
        self.assertEqual(callbacks, [] if window == 'started_fact_failure' else [True])
        self.assertEqual(fact_faults, [True] if window == 'started_fact_failure' else [])
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertFalse(heartbeats[0]._thread.is_alive())
        self.assertEqual(getattr(self.action, '_ar_lease_lost', False), window != 'started_fact_failure')
        self.assertTrue(any(stage == 'terminate' for stage, _ in lock_observations))
        self.assertTrue(any(stage == 'wait' for stage, _ in lock_observations))
        self.assertTrue(all(released for _, released in lock_observations),
                        'TERM/wait cleanup must begin only after both independent launch locks are released: ' + repr(lock_observations))
        self.assertFalse(hasattr(self.action, '_ar_terminate_process'))
        with Session(self.engine) as observer:
            entry = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)['execution_safety_v1']['attempts'][0]
            self.assertEqual(entry['status'], 'intent_recorded')
            self.assertEqual(len(entry['prepared_process_refs']), 1)
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_sqlite_file_shared_pool_is_rejected_without_committing_caller(self):
        from sqlalchemy.pool import SingletonThreadPool
        sqlite = create_engine('sqlite:///' + str(Path(self.temp.name) / 'shared-pool.sqlite'),
                               poolclass=SingletonThreadPool)
        self.addCleanup(sqlite.dispose)
        Base.metadata.create_all(sqlite)
        models = (User, UserSkillPermission, SchedulerLock, WorkflowMaterialSet,
                  WorkflowSession, WorkflowAction, FileRecord, WorkflowMaterialSetFile)
        # Copy only this isolated synthetic schema's legitimate metadata to the unsupported engine.
        with sqlite.begin() as connection:
            for model in models:
                rows = [dict(row) for row in self.db.execute(select(model.__table__)).mappings()]
                if rows:
                    connection.execute(model.__table__.insert(), rows)
        gate_connections = []

        def record_gate_connection(connection, cursor, statement, parameters, context, executemany):
            gate_connections.append(id(connection.connection.dbapi_connection))

        with Session(sqlite, expire_on_commit=False) as caller:
            action = caller.get(WorkflowAction, self.action_id)
            workflow = caller.get(WorkflowSession, self.workflow_id)
            execution = ArExecution(caller, action, workflow)
            self.assertIs(type(execution), ArExecution)
            record = caller.scalar(select(FileRecord).where(FileRecord.workflow_id == self.workflow_id).limit(1))
            original_name = record.original_name
            record.original_name = '共享连接未提交-codex测试.xlsx'
            caller.flush()
            physical = id(caller.connection().connection.dbapi_connection)
            def reject_shared_spawn(*args, **kwargs):
                self.assertTrue(gate_connections)
                self.assertTrue(all(value == physical for value in gate_connections))
                raise AssertionError('spawn through a proven shared physical connection')

            event.listen(sqlite, 'before_cursor_execute', record_gate_connection)
            try:
                with patch.object(evidence.subprocess, 'Popen', side_effect=reject_shared_spawn) as popen:
                    with self.assertRaisesRegex(ValueError, '独立数据库连接'):
                        execution.script('anchor_probe.py', [])
                    self.assertEqual(popen.call_count, 0)
                self.assertTrue(caller.in_transaction())
                self.assertEqual(record.original_name, '共享连接未提交-codex测试.xlsx')
            finally:
                event.remove(sqlite, 'before_cursor_execute', record_gate_connection)
            self.assertTrue(all(value == physical for value in gate_connections))
            observer_engine = create_engine(sqlite.url)
            try:
                with Session(observer_engine) as observer:
                    self.assertNotEqual(id(observer.connection().connection.dbapi_connection), physical)
                    self.assertEqual(observer.get(FileRecord, record.id).original_name, original_name)
            finally:
                observer_engine.dispose()
            caller.rollback()
        # This case covers SQLite pool compatibility only; PG-lock and atomicity evidence are separate.
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_action_reference_cap_is_shared_across_attempts_and_preserves_history(self):
        from app import workflow_service as service
        from app.workflow_action_state import isolated_action_state
        execution = ArExecution(self.db, self.action, self.workflow)
        # These 127 bounded OS faults construct genuine historical prepared refs only.
        # They do not represent permission to retry production financial writes or prove exit.
        with patch.object(evidence.subprocess, 'Popen', side_effect=OSError('synthetic capacity seeding; no child')) as popen:
            for _ in range(127):
                with self.assertRaises(OSError):
                    execution.script('anchor_probe.py', [])
            self.assertEqual(popen.call_count, 127)
        with Session(self.engine) as observer:
            prior = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)['execution_safety_v1']['attempts'][0]
        self.assertEqual(len(prior['prepared_process_refs']), 127)
        self.assertEqual(prior['status'], 'intent_recorded')
        self.assertEqual(prior['binding_sha256'], self.original_binding)

        self.action.state = isolated_action_state('queued')
        self.action.worker_id, self.action.lease_expires_at = '', None
        self.db.commit()
        claimed = service.claim_next_workflow_action(self.db, ('workflow',), 'synthetic-worker-two',
                                                     execution_contracts=(CONTRACT_VERSION,))
        self.assertIs(claimed, self.action)
        self.assertEqual(claimed.attempt_count, 2)
        self.db.refresh(self.workflow)
        context = json.loads(self.workflow.context_json)
        register_effect_intent(context, self.workflow, claimed, 'write_ledger')
        self.workflow.context_json = json.dumps(context)
        self.db.commit()
        execution = ArExecution(self.db, claimed, self.workflow)
        # Registration 128 remains allowed through the real public seam and actual no-op child.
        self.assertEqual(execution.script('anchor_probe.py', []).strip(), 'synthetic anchor probe')
        with Session(self.engine) as observer:
            expected = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)['execution_safety_v1']
        self.assertEqual(expected['attempts'][0], prior)
        self.assertEqual(len(expected['attempts']), 2)
        self.assertEqual(len(expected['attempts'][1]['prepared_process_refs']), 1)
        self.assertEqual(sum(len(entry['prepared_process_refs']) for entry in expected['attempts']), 128)
        self.assertEqual(len({ref['record_id'] for entry in expected['attempts']
                             for ref in entry['prepared_process_refs']}), 128)
        with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('spawn above cross-attempt cap')) as popen:
            with self.assertRaisesRegex(ValueError, '上限'):
                execution.script('anchor_probe.py', [])
            self.assertEqual(popen.call_count, 0)
        with Session(self.engine) as observer:
            self.assertEqual(json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)['execution_safety_v1'], expected)
            self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == 'ar_process_prepared_registered')), 128)
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_prepared_fact_fsync_failure_denies_registration_and_spawn(self):
        execution = ArExecution(self.db, self.action, self.workflow)
        original_index = json.loads(self.workflow.context_json)['execution_safety_v1']
        with patch.object(evidence.os, 'fsync', side_effect=OSError('synthetic prepared fsync refused')) as fsync:
            with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('spawn before durable prepared fact')) as popen:
                with self.assertRaisesRegex(OSError, 'prepared fsync refused'):
                    execution.script('anchor_probe.py', [])
                self.assertEqual(fsync.call_count, 1)
                self.assertEqual(popen.call_count, 0)
        with Session(self.engine) as observer:
            self.assertEqual(json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)['execution_safety_v1'], original_index)
            self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == 'ar_process_prepared_registered')), 0)
        prepared = list((self.root / 'execution-processes' / self.action_id).glob('*/prepared.json'))
        self.assertEqual(len(prepared), 1)  # Bytes can exist without successful durability acknowledgement.
        self.assertFalse(any(path.with_name('started.json').exists() for path in prepared))
        self.assertFalse(self.action._ar_process_exit_confirmed)
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_fresh_worker_attempt_permission_material_and_plan_changes_deny_spawn(self):
        from fastapi import HTTPException
        from app.ar_execution_contract import ExecutionLeaseLost
        execution = ArExecution(self.db, self.action, self.workflow)
        kinds = (('worker', ExecutionLeaseLost), ('attempt', ExecutionLeaseLost),
                 ('permission', HTTPException), ('material', ValueError), ('plan', ValueError))
        prior_ids = []
        for count, (kind, exception_type) in enumerate(kinds, 1):
            with self.subTest(change=kind):
                anchor_connections, changes, new_material_ids = set(), [], []
                original_commit = self.engine.dialect.do_commit

                def mark_anchor_transaction(connection, cursor, statement, parameters, execution_context, executemany):
                    values = parameters.values() if isinstance(parameters, dict) else parameters
                    if statement.startswith('INSERT INTO audit_events') and 'ar_process_prepared_registered' in values:
                        anchor_connections.add(id(connection.connection.dbapi_connection))

                def commit_then_change_qualification(connection):
                    physical = getattr(connection, 'dbapi_connection', connection)
                    original_commit(connection)
                    if id(physical) not in anchor_connections or changes:
                        return
                    changes.append(True)
                    with Session(self.engine) as editor:
                        action = editor.get(WorkflowAction, self.action_id)
                        fresh = editor.get(WorkflowSession, self.workflow_id)
                        if kind == 'worker':
                            action.worker_id = 'synthetic-different-worker'
                        elif kind == 'attempt':
                            action.attempt_count = 2
                        elif kind == 'permission':
                            editor.scalar(select(UserSkillPermission).where(UserSkillPermission.user_id == self.owner_id)).can_run = False
                        elif kind == 'material':
                            material = editor.get(WorkflowMaterialSet, fresh.material_set_id)
                            material.state = 'superseded'
                            editor.flush()
                            material_id = str(uuid4())
                            new_material_ids.append(material_id)
                            editor.add(WorkflowMaterialSet(id=material_id, owner_id=self.owner_id,
                                department_id='finance', skill_id='ar-hexiao-daily', version=2, state='current'))
                        else:
                            context = json.loads(fresh.context_json)
                            context['plan_fingerprint'] = 'b' * 64
                            fresh.context_json = json.dumps(context)
                        editor.commit()

                event.listen(self.engine, 'before_cursor_execute', mark_anchor_transaction)
                try:
                    with patch.object(self.engine.dialect, 'do_commit', side_effect=commit_then_change_qualification):
                        with patch.object(evidence.subprocess, 'Popen', side_effect=AssertionError('spawn after qualification changed')) as popen:
                            with self.assertRaises(exception_type) as rejected:
                                execution.script('anchor_probe.py', [])
                            self.assertEqual(popen.call_count, 0)
                    self.assertEqual(changes, [True])
                    if kind == 'permission':
                        self.assertEqual(rejected.exception.status_code, 403)
                    with Session(self.engine) as observer:
                        entry = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)['execution_safety_v1']['attempts'][0]
                        self.assertEqual(entry['binding_sha256'], self.original_binding)
                        self.assertEqual(entry['status'], 'intent_recorded')
                        ids = [ref['record_id'] for ref in entry['prepared_process_refs']]
                        self.assertEqual(len(ids), count)
                        self.assertEqual(ids[:-1], prior_ids)
                        prior_ids = ids
                        self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                            AuditEvent.action == 'ar_process_prepared_registered')), count)
                finally:
                    event.remove(self.engine, 'before_cursor_execute', mark_anchor_transaction)
                    # Reset only this synthetic fixture between independent fault cases, preserving all original refs.
                    with Session(self.engine) as editor:
                        action = editor.get(WorkflowAction, self.action_id)
                        action.worker_id, action.attempt_count = 'synthetic-worker', 1
                        editor.scalar(select(UserSkillPermission).where(UserSkillPermission.user_id == self.owner_id)).can_run = True
                        fresh = editor.get(WorkflowSession, self.workflow_id)
                        for material_id in new_material_ids:
                            editor.get(WorkflowMaterialSet, material_id).state = 'superseded'
                        editor.flush()
                        editor.get(WorkflowMaterialSet, fresh.material_set_id).state = 'current'
                        context = json.loads(fresh.context_json)
                        context['plan_fingerprint'] = 'a' * 64
                        fresh.context_json = json.dumps(context)
                        editor.commit()
        self.assertEqual(len(prior_ids), 5)
        self.assertEqual(len(set(prior_ids)), 5)
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


    def test_legacy_non_effect_script_signature_remains_compatible(self):
        self.action.name = 'ar_inspect_materials'
        context = json.loads(self.workflow.context_json)
        context.pop('execution_safety_v1')
        context['ar_execution']['completed'] = []
        self.workflow.context_json = json.dumps(context)
        self.db.commit()
        execution = ArExecution(self.db, self.action, self.workflow)
        original_recorded_script = evidence.run_recorded_script
        invocations = []

        def invoke_existing_signature(*args, **kwargs):
            self.assertIsNone(kwargs.pop('launch_gate'))
            invocations.append(True)
            # True constructor and non-effect guards remain; invoke the real
            # existing recorded-process signature without the optional gate.
            return original_recorded_script(*args, **kwargs)

        with patch.object(evidence, 'run_recorded_script', side_effect=invoke_existing_signature):
            self.assertEqual(execution.script('anchor_probe.py', []).strip(), 'synthetic anchor probe')
        self.assertEqual(invocations, [True])
        self.assertTrue(self.action._ar_process_exit_confirmed)
        self.assertEqual(len(self.action._ar_process_records), 1)
        record = self.action._ar_process_records[0]
        facts = self.root / 'execution-processes' / self.action_id / record['record_id']
        self.assertTrue((facts / 'prepared.json').is_file())
        self.assertTrue((facts / 'started.json').is_file())
        self.assertTrue((facts / 'exited.json').is_file())
        with Session(self.engine) as observer:
            fresh_context = json.loads(observer.get(WorkflowSession, self.workflow_id).context_json)
            self.assertNotIn('execution_safety_v1', fresh_context)
            self.assertEqual(observer.get(WorkflowAction, self.action_id).state, 'running')
            self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == 'ar_process_prepared_registered')), 0)
        self.assertEqual({path: path.read_bytes() for path in self.material_bytes}, self.material_bytes)


if __name__ == '__main__':
    unittest.main()
