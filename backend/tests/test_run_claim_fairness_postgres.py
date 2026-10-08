"""Ordinary Run claims against disposable PostgreSQL; no adapter is executed."""
import io
import json
import os
import shutil
import tempfile
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from contextlib import redirect_stdout
from uuid import uuid4
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError

from app.auth_models import User, UserSkillPermission
from app.models import Base, RunEvent, RunRecord, SchedulerLock, StepRun
from app.modules.execution.authorization import ExecutionPhase, execution_owner
from app.modules.execution.input_snapshot import input_snapshot_hash
from app.modules.execution.preconditions import assert_run_confirmation
from app.modules.execution.run_snapshot import assert_execution_snapshot
from app.registry import SkillManifest, hash_skill_directory
from app.run_service import persist_run
from app.scheduler import acquire_claim_lock
from app.worker import claim_next_run
from test_parallel_workers import _manifest
from test_refactor_event_transactions import prepared_submission

URL = 'postgresql+psycopg://synthetic:synthetic-only@127.0.0.1:5432/material_policy_test'


@unittest.skipUnless(os.environ.get('AR_POLICY_SYNTHETIC_DB_URL') == URL,
                     'isolated PostgreSQL only')
class RunClaimFairnessPostgresTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.environ.get('FINANCIAL_ENV'), 'test')
        self.assertEqual(os.environ.get('FINANCIAL_DATABASE_URL'), URL)
        sandbox = Path(os.environ['REFACTOR_TEST_ROOT'])
        self.assertTrue(sandbox.name.startswith('financial-refactor-'))
        self.assertEqual((sandbox / '.refactor-isolated').read_text(), 'synthetic-only-v1')
        self.temp = tempfile.TemporaryDirectory(prefix='claim-fairness-', dir=sandbox)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.admin = create_engine(URL, connect_args={'options': '-c statement_timeout=10000'})
        self.addCleanup(self.admin.dispose)
        self.schema = 'run_claim_fairness_' + uuid4().hex
        with self.admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.addCleanup(self.drop_schema)
        self.engine = create_engine(URL, connect_args={
            'options': '-csearch_path=' + self.schema + ' -c statement_timeout=10000'})
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.addCleanup(self.db.close)
        self.assertIsNone(self.db.scalar(select(RunRecord.id).limit(1)),
                          'The fairness canary requires an empty, disposable database')
        self.db.add(User(id='synthetic-owner', username='synthetic-owner',
                         department_id='finance', role='finance_user', status='active',
                         password_hash='synthetic-unusable-password'))
        self.db.flush()
        self.packages = {}
        for skill_id in ('codex-fair-busy', 'codex-fair-ready'):
            self.db.add(UserSkillPermission(id=skill_id, user_id='synthetic-owner',
                                            skill_id=skill_id, can_run=True,
                                            can_upload=False, can_create_draft=False))
            manifest = json.loads(_manifest(concurrency_limit=1))
            manifest.update(id=skill_id, name='codex测试领取公平性')
            SkillManifest.model_validate(manifest)
            package = self.root / skill_id
            (package / 'scripts').mkdir(parents=True)
            (package / 'tool.yaml').write_text(yaml.safe_dump(manifest, allow_unicode=True),
                                              encoding='utf-8')
            (package / 'scripts/entry.py').write_text("print('{}')\n", encoding='utf-8')
            self.packages[skill_id] = (package, manifest, hash_skill_directory(package))
        self.db.add(SchedulerLock(name='global'))
        self.db.commit()

    def drop_schema(self):
        with self.admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))

    def queued_run(self, identity, skill_id, queued_at, *, concurrency_limit=1, owner_id='synthetic-owner', worker_pool='python', requires_confirmation=False):
        prepared = prepared_submission()
        run = prepared.run
        package, manifest, skill_hash = self.packages[skill_id]
        if concurrency_limit != 1 or worker_pool != 'python' or requires_confirmation:
            manifest = json.loads(json.dumps(manifest))
            manifest['runtime']['concurrency_limit'] = concurrency_limit
            manifest['handler']['worker_pool'] = worker_pool
            manifest['risk']['requires_confirmation'] = requires_confirmation
            manifest['version'] = '1.0.1'
            variant = self.root / (skill_id + '-limit-' + str(concurrency_limit) + '-pool-' + worker_pool + '-confirmation-' + str(requires_confirmation))
            if not variant.exists():
                shutil.copytree(package, variant)
                (variant / 'tool.yaml').write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding='utf-8')
            package, skill_hash = variant, hash_skill_directory(variant)
        run.id = identity
        run.owner_id = owner_id
        run.worker_pool = worker_pool
        run.skill_id = skill_id
        run.skill_name = manifest['name']
        run.skill_version = manifest['version']
        run.skill_commit = 'a' * 40
        run.skill_hash = skill_hash
        run.manifest_path = str(package / 'tool.yaml')
        run.manifest_snapshot = json.dumps(manifest, ensure_ascii=False)
        run.concurrency_limit = concurrency_limit
        run.confirmation_required = requires_confirmation
        if requires_confirmation:
            run.confirmed_by = owner_id
            run.confirmed_at = datetime.now(UTC)
        run.message = 'codex测试：只测试领取，不执行适配器'
        run.parameters_json = '{}'
        run.files_json = '{}'
        run.input_hash = input_snapshot_hash(run.parameters_json, {}, run.skill_hash)
        run.queued_at = run.created_at = queued_at
        return persist_run(self.db, prepared)

    def test_independent_skill_after_one_hundred_saturated_candidates_is_claimed(self):
        now = datetime.now(UTC)
        busy = self.queued_run('codex-busy-running', 'codex-fair-busy', now - timedelta(seconds=1))
        busy.state = 'running'
        busy.worker_id = 'codex-busy-worker'
        busy.attempt_count = 1
        busy.started_at = busy.heartbeat_at = now
        busy.lease_expires_at = now + timedelta(minutes=10)
        saturated = [self.queued_run(f'codex-busy-{index:03d}', 'codex-fair-busy',
                                    now + timedelta(microseconds=index)) for index in range(100)]
        ready = self.queued_run('codex-ready-101', 'codex-fair-ready',
                                now + timedelta(microseconds=100))
        self.db.commit()
        # Prove all fixtures pass the real owner, grant, manifest and intent guards.
        # No claim or security collaborator is mocked, and no adapter runs.
        for run in (busy, *saturated, ready):
            manifest = SkillManifest.model_validate(json.loads(run.manifest_snapshot))
            execution_owner(self.db, run, ExecutionPhase.CLAIM)
            assert_run_confirmation(run, manifest, ExecutionPhase.CLAIM)
            assert_execution_snapshot(self.db, run, ExecutionPhase.CLAIM)
        self.db.commit()

        saturated_ids = [run.id for run in saturated]
        saturated_events = select(func.count()).select_from(RunEvent).where(
            RunEvent.run_id.in_(saturated_ids))
        original_event_count = self.db.scalar(saturated_events)
        self.assertEqual(original_event_count, 100)
        self.db.commit()

        claimed = claim_next_run(self.db, ('python',), 'codex-fair-worker')
        self.assertIsNotNone(claimed, 'An independent eligible Run after 100 saturated candidates must be claimed')
        self.assertEqual(claimed.id, ready.id)
        self.assertEqual(claimed.state, 'running')
        self.assertEqual(claimed.attempt_count, 1)
        self.assertTrue(all(run.state == 'queued' and run.attempt_count == 0 for run in saturated))
        self.assertEqual(busy.state, 'running')
        self.assertEqual(self.db.scalar(saturated_events), original_event_count)


    def test_denied_candidate_budget_is_observed_and_next_claim_makes_progress(self):
        now = datetime.now(UTC)
        rejected = [self.queued_run(f'codex-denied-{index:03d}', 'codex-fair-busy',
                                   now + timedelta(microseconds=index)) for index in range(100)]
        ready = self.queued_run('codex-ready-after-denials', 'codex-fair-ready',
                                now + timedelta(microseconds=100))
        permission = self.db.scalar(select(UserSkillPermission).where(
            UserSkillPermission.user_id == 'synthetic-owner',
            UserSkillPermission.skill_id == 'codex-fair-busy'))
        permission.can_run = False
        self.db.commit()

        output = io.StringIO()
        with redirect_stdout(output):
            claimed = claim_next_run(self.db, ('python',), 'codex-budget-worker')
        self.assertIsNone(claimed)
        self.assertTrue(all(run.state == 'failed' and run.attempt_count == 0 for run in rejected))
        self.assertEqual(ready.state, 'queued')
        self.assertEqual(ready.attempt_count, 0)

        observations = [json.loads(line) for line in output.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(observations), 1, 'One bounded claim scan must emit one aggregate JSON observation')
        observation = observations[0]
        self.assertEqual(observation['event'], 'run_claim_scan')
        self.assertEqual(observation['candidate_filter'], 'skill_capacity')
        self.assertEqual(observation['checked_count'], 100)
        self.assertEqual(observation['outcome'], 'candidate_budget_reached')
        self.assertEqual(observation['invalid_snapshot_count'], 0)
        self.assertEqual(observation['claim_denied_count'], 100)
        for key in ('query_elapsed_ms', 'elapsed_ms'):
            self.assertIn(type(observation[key]), (int, float))
            self.assertGreaterEqual(observation[key], 0)
        self.assertFalse({'run_id', 'owner_id', 'workflow_id', 'skill_id', 'parameters', 'files'} & observation.keys())
        self.assertNotIn('synthetic-owner', output.getvalue())
        self.assertNotIn('codex-denied-', output.getvalue())
        self.assertNotIn('codex-ready-after-denials', output.getvalue())

        with redirect_stdout(io.StringIO()):
            next_claim = claim_next_run(self.db, ('python',), 'codex-budget-worker')
        self.assertIsNotNone(next_claim)
        self.assertEqual(next_claim.id, ready.id)
        self.assertEqual(next_claim.attempt_count, 1)


    def test_two_postgres_workers_claim_distinct_eligible_runs_once(self):
        now = datetime.now(UTC)
        first = self.queued_run('codex-race-first', 'codex-fair-busy', now)
        second = self.queued_run('codex-race-second', 'codex-fair-ready', now + timedelta(microseconds=1))
        self.db.commit()
        barrier = threading.Barrier(3)

        def claim(worker_id):
            barrier.wait(timeout=5)
            with Session(self.engine, expire_on_commit=False) as db:
                run = claim_next_run(db, ('python',), worker_id)
                return None if run is None else (run.id, run.worker_id, run.attempt_count)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim, 'codex-claimer-' + str(index)) for index in range(2)]
            barrier.wait(timeout=5)
            results = [future.result(timeout=10) for future in futures]
        self.assertTrue(all(result is not None for result in results))
        self.assertEqual({result[0] for result in results}, {first.id, second.id})
        self.assertEqual({result[1] for result in results}, {'codex-claimer-0', 'codex-claimer-1'})
        self.assertTrue(all(result[2] == 1 for result in results))
        for identity in (first.id, second.id):
            actual = self.db.get(RunRecord, identity, populate_existing=True)
            self.assertEqual(actual.state, 'running')
            self.assertEqual(actual.attempt_count, 1)


        # A second actual race has only one eligible Run: one owner may claim it,
        # while the other must return None without another event or attempt.
        # Synthetic completions free capacity; no adapter is executed.
        first.state = second.state = 'succeeded'
        only = self.queued_run('codex-race-only-eligible', 'codex-fair-ready',
                                datetime.now(UTC))
        self.db.commit()
        barrier = threading.Barrier(3)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim, 'codex-single-claimer-' + str(index)) for index in range(2)]
            barrier.wait(timeout=5)
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(results.count(None), 1)
        successful = [result for result in results if result is not None]
        self.assertEqual(len(successful), 1)
        self.assertEqual(successful[0][0], only.id)
        self.assertEqual(successful[0][2], 1)
        self.db.refresh(only)
        self.assertEqual(only.state, 'running')
        self.assertEqual(only.attempt_count, 1)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(RunEvent).where(
            RunEvent.run_id == only.id, RunEvent.state == 'running')), 1)


    def test_unknown_lease_stays_counted_and_each_run_limit_is_respected(self):
        now = datetime.now(UTC)
        unknown = self.queued_run('codex-unknown-running', 'codex-fair-busy', now - timedelta(seconds=1))
        unknown.state = 'running'
        unknown.worker_id = 'codex-original-worker'
        unknown.attempt_count = 1
        unknown.started_at = now - timedelta(minutes=1)
        unknown.lease_expires_at = None
        blocked = self.queued_run('codex-limit-one', 'codex-fair-busy', now)
        eligible = self.queued_run('codex-limit-two', 'codex-fair-busy', now + timedelta(microseconds=1),
                                   concurrency_limit=2)
        self.db.commit()

        claimed = claim_next_run(self.db, ('python',), 'codex-capacity-worker')
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.id, eligible.id)
        self.assertEqual(blocked.state, 'queued')
        self.assertEqual(blocked.attempt_count, 0)
        self.assertEqual(unknown.state, 'running')
        self.assertEqual(unknown.worker_id, 'codex-original-worker')
        self.assertIsNone(unknown.lease_expires_at)
        self.assertEqual(unknown.attempt_count, 1)


    def test_null_queue_dates_sort_last_and_equal_dates_use_stable_run_identity(self):
        now = datetime.now(UTC)
        # Reverse insertion must not determine the order of otherwise equal rows.
        later_id = self.queued_run('codex-sort-z', 'codex-fair-ready', now, concurrency_limit=2)
        earlier_id = self.queued_run('codex-sort-a', 'codex-fair-ready', now, concurrency_limit=2)
        null_date = self.queued_run('codex-sort-null', 'codex-fair-busy', None)
        null_date.created_at = now - timedelta(days=1)
        self.db.commit()

        observed = []
        for index in range(3):
            claimed = claim_next_run(self.db, ('python',), 'codex-order-worker-' + str(index))
            self.assertIsNotNone(claimed)
            observed.append(claimed.id)
        self.assertEqual(observed, [earlier_id.id, later_id.id, null_date.id])


    def test_postgres_commit_failure_leaves_no_partial_claim_or_consumed_attempt(self):
        run = self.queued_run('codex-commit-fault', 'codex-fair-ready', datetime.now(UTC))
        run_id = run.id
        self.db.commit()
        steps_query = select(StepRun.id, StepRun.state, StepRun.attempt_count,
                             StepRun.worker_id, StepRun.started_at).where(
            StepRun.run_id == run.id).order_by(StepRun.id)
        original_steps = self.db.execute(steps_query).all()
        self.db.commit()
        with self.engine.begin() as connection:
            connection.execute(text("CREATE FUNCTION codex_reject_claim() RETURNS trigger LANGUAGE plpgsql "
                                    "AS $$ BEGIN RAISE EXCEPTION 'codex synthetic claim commit fault' "
                                    "USING ERRCODE = '23514'; END; $$"))
            connection.execute(text("CREATE CONSTRAINT TRIGGER codex_deferred_claim_fault "
                                    "AFTER UPDATE ON runs DEFERRABLE INITIALLY DEFERRED "
                                    "FOR EACH ROW WHEN (NEW.state = 'running') "
                                    "EXECUTE FUNCTION codex_reject_claim()"))
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(DBAPIError) as failure:
            claim_next_run(self.db, ('python',), 'codex-fault-worker')
        self.assertEqual(failure.exception.orig.sqlstate, '23514')
        self.db.rollback()
        with Session(self.engine) as observer:
            original = observer.get(RunRecord, run_id)
            self.assertEqual(original.state, 'queued')
            self.assertEqual(original.attempt_count, 0)
            self.assertEqual(original.worker_id, '')
            self.assertIsNone(original.started_at)
            self.assertIsNone(original.lease_expires_at)
            self.assertEqual(observer.execute(steps_query).all(), original_steps)
            self.assertEqual(list(observer.scalars(select(RunEvent.state).where(RunEvent.run_id == run_id))),
                             ['queued'])
        observation = json.loads(output.getvalue())
        self.assertEqual(observation['outcome'], 'claim_error')
        self.assertEqual(observation['checked_count'], 1)
        self.assertNotIn('codex-commit-fault', output.getvalue())
        self.db.rollback()
        with self.engine.begin() as connection:
            connection.execute(text('DROP TRIGGER codex_deferred_claim_fault ON runs'))
        claimed = claim_next_run(self.db, ('python',), 'codex-after-fault-worker')
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.id, run.id)
        self.assertEqual(claimed.attempt_count, 1)


    def test_expired_cross_pool_owner_stays_occupied_and_repeated_full_scans_are_quiet(self):
        self.db.add(User(id='synthetic-other-owner', username='synthetic-other-owner',
                         department_id='finance', role='finance_user', status='active',
                         password_hash='synthetic-unusable-password'))
        self.db.flush()
        self.db.add(UserSkillPermission(id='other-owner-busy', user_id='synthetic-other-owner',
                                       skill_id='codex-fair-busy', can_run=True))
        self.db.commit()
        now = datetime.now(UTC)
        expired = self.queued_run('codex-expired-other-pool', 'codex-fair-busy', now - timedelta(seconds=1),
                                  owner_id='synthetic-other-owner', worker_pool='other-python')
        expired.state = 'running'
        expired.worker_id = 'codex-original-other-worker'
        expired.attempt_count = 1
        expired.started_at = expired.heartbeat_at = now - timedelta(minutes=2)
        expired.lease_expires_at = now - timedelta(seconds=1)
        blocked = self.queued_run('codex-busy-after-expiry', 'codex-fair-busy', now)
        ready = self.queued_run('codex-ready-during-expiry', 'codex-fair-ready', now + timedelta(microseconds=1))
        waiting_ready = self.queued_run('codex-ready-now-full', 'codex-fair-ready', now + timedelta(microseconds=2))
        self.db.commit()
        manifest = SkillManifest.model_validate(json.loads(expired.manifest_snapshot))
        execution_owner(self.db, expired, ExecutionPhase.CLAIM)
        assert_run_confirmation(expired, manifest, ExecutionPhase.CLAIM)
        assert_execution_snapshot(self.db, expired, ExecutionPhase.CLAIM)
        self.db.commit()

        claimed = claim_next_run(self.db, ('python',), 'codex-expiry-worker')
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.id, ready.id)
        self.assertEqual(expired.state, 'running')
        self.assertEqual(expired.worker_id, 'codex-original-other-worker')
        self.assertEqual(expired.attempt_count, 1)
        self.assertIsNone(expired.lease_expires_at)
        self.assertEqual(blocked.state, 'queued')
        event_count = len(list(self.db.scalars(select(RunEvent.id))))
        output = io.StringIO()
        with redirect_stdout(output):
            for _ in range(3):
                self.assertIsNone(claim_next_run(self.db, ('python',), 'codex-idle-worker'))
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(len(list(self.db.scalars(select(RunEvent.id)))), event_count)
        self.assertEqual(blocked.attempt_count, 0)
        self.assertEqual(waiting_ready.state, 'queued')
        self.assertEqual(waiting_ready.attempt_count, 0)


    def test_candidate_query_faults_roll_back_and_local_timeout_preserves_stricter_setting(self):
        ready = self.queued_run('codex-query-fault', 'codex-fair-ready', datetime.now(UTC))
        ready_id = ready.id
        self.db.commit()
        with self.engine.connect() as connection, Session(connection, expire_on_commit=False) as db:
            db.execute(text("SET statement_timeout = '100ms'"))
            db.commit()
            for fault_sql, sqlstate, outcome in (
                ('SELECT pg_sleep(0.15)', '57014', 'candidate_query_timeout'),
                ('SELECT 1 / 0', '22012', 'candidate_query_error'),
            ):
                with self.subTest(sqlstate=sqlstate):
                    applied = []
                    def inject(conn, cursor, statement, parameters, context, executemany):
                        if statement.startswith('SELECT runs.id') and 'LEFT OUTER JOIN' in statement:
                            cursor.execute("SELECT setting FROM pg_settings WHERE name='statement_timeout'")
                            applied.append(int(cursor.fetchone()[0]))
                            return fault_sql, ()
                        return statement, parameters
                    event.listen(connection, 'before_cursor_execute', inject, retval=True)
                    output = io.StringIO()
                    try:
                        with redirect_stdout(output), self.assertRaises(DBAPIError) as failure:
                            claim_next_run(db, ('python',), 'codex-query-worker')
                        self.assertEqual(failure.exception.orig.sqlstate, sqlstate)
                    finally:
                        event.remove(connection, 'before_cursor_execute', inject)
                        db.rollback()
                    self.assertEqual(applied, [100])
                    observation = json.loads(output.getvalue())
                    self.assertEqual(observation['outcome'], outcome)
                    self.assertEqual(observation['checked_count'], 0)
                    self.assertGreaterEqual(observation['query_elapsed_ms'], 0)
                    self.assertEqual(connection.scalar(text('SHOW statement_timeout')), '100ms')
                    connection.commit()
                    with Session(self.engine) as observer:
                        unchanged = observer.get(RunRecord, ready_id)
                        self.assertEqual(unchanged.state, 'queued')
                        self.assertEqual(unchanged.attempt_count, 0)

            applied, restored_before_guard = [], []
            def observe_timeout(conn, cursor, statement, parameters, context, executemany):
                if statement.startswith('SELECT runs.id') and 'LEFT OUTER JOIN' in statement:
                    cursor.execute("SELECT setting FROM pg_settings WHERE name='statement_timeout'")
                    applied.append(int(cursor.fetchone()[0]))
                elif applied and statement.startswith('SELECT count(runs.id)'):
                    cursor.execute("SELECT setting FROM pg_settings WHERE name='statement_timeout'")
                    restored_before_guard.append(int(cursor.fetchone()[0]))
                return statement, parameters
            event.listen(connection, 'before_cursor_execute', observe_timeout, retval=True)
            try:
                claimed = claim_next_run(db, ('python',), 'codex-after-query-fault')
            finally:
                event.remove(connection, 'before_cursor_execute', observe_timeout)
            self.assertEqual(claimed.id, ready_id)
            self.assertEqual(applied, [100])
            self.assertTrue(restored_before_guard)
            self.assertEqual(restored_before_guard[0], 100)
            self.assertEqual(connection.scalar(text('SHOW statement_timeout')), '100ms')
            connection.commit()

            other = self.queued_run('codex-query-default-cap', 'codex-fair-busy', datetime.now(UTC))
            self.db.commit()
            connection.execute(text("SET statement_timeout = '0'"))
            connection.commit()
            applied.clear()
            restored_before_guard.clear()
            event.listen(connection, 'before_cursor_execute', observe_timeout, retval=True)
            try:
                claimed = claim_next_run(db, ('python',), 'codex-default-timeout-worker')
            finally:
                event.remove(connection, 'before_cursor_execute', observe_timeout)
            self.assertEqual(claimed.id, other.id)
            self.assertEqual(applied, [2000])
            self.assertTrue(restored_before_guard)
            self.assertEqual(restored_before_guard[0], 0)
            self.assertEqual(connection.scalar(text('SHOW statement_timeout')), '0')
            connection.commit()


    def test_real_scheduler_lock_waits_and_same_skill_limit_two_allows_only_two_claims(self):
        now = datetime.now(UTC)
        queued = [self.queued_run('codex-limit-race-' + str(index), 'codex-fair-ready',
                                  now + timedelta(microseconds=index), concurrency_limit=2)
                  for index in range(3)]
        self.db.commit()
        barrier = threading.Barrier(3)
        pids = []
        holder = Session(self.engine)
        self.addCleanup(holder.close)
        acquire_claim_lock(holder)

        def claim(worker_id):
            with Session(self.engine, expire_on_commit=False) as db:
                pids.append(db.scalar(text('SELECT pg_backend_pid()')))
                barrier.wait(timeout=5)
                actual = claim_next_run(db, ('python',), worker_id)
                return None if actual is None else actual.id

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim, 'codex-limit-claimer-' + str(index)) for index in range(2)]
            barrier.wait(timeout=5)
            observed = False
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with self.admin.connect() as observer:
                        count = observer.scalar(text("SELECT count(*) FROM pg_stat_activity "
                                                     "WHERE pid IN (:first, :second) AND wait_event_type='Lock'"),
                                                 {'first':pids[0], 'second':pids[1]})
                    if count == 2:
                        observed = True
                        break
                    time.sleep(0.02)
                self.assertTrue(observed, 'Both real claimers must wait for the held scheduler row lock')
            finally:
                holder.rollback()
            claimed_ids = [future.result(timeout=10) for future in futures]
        self.assertEqual(set(claimed_ids), {queued[0].id, queued[1].id})
        self.assertEqual(len(set(claimed_ids)), 2)
        for run in queued:
            self.db.refresh(run)
        self.assertEqual([run.state for run in queued], ['running', 'running', 'queued'])
        self.assertEqual([run.attempt_count for run in queued], [1, 1, 0])
        self.assertIsNone(claim_next_run(self.db, ('python',), 'codex-third-capacity-worker'))


    def test_full_capacity_defers_invalid_manifest_then_fails_when_capacity_frees(self):
        now = datetime.now(UTC)
        busy = self.queued_run('codex-full-invalid-running', 'codex-fair-busy', now)
        busy.state = 'running'
        busy.worker_id = 'codex-full-invalid-worker'
        busy.attempt_count = 1
        busy.started_at = busy.heartbeat_at = now
        busy.lease_expires_at = now + timedelta(minutes=10)
        invalid = self.queued_run('codex-full-invalid-queued', 'codex-fair-busy', now + timedelta(microseconds=1))
        invalid.manifest_snapshot = '{}'
        self.db.commit()
        original_events = len(list(self.db.scalars(select(RunEvent.id))))
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIsNone(claim_next_run(self.db, ('python',), 'codex-invalid-scan-worker'))
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(invalid.state, 'queued')
        self.assertEqual(invalid.attempt_count, 0)
        self.assertEqual(len(list(self.db.scalars(select(RunEvent.id)))), original_events)

        # Synthetic completion only; no adapter or financial operation is executed.
        busy.state = 'succeeded'
        self.db.commit()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIsNone(claim_next_run(self.db, ('python',), 'codex-invalid-free-worker'))
        self.assertEqual(invalid.state, 'failed')
        self.assertEqual(invalid.attempt_count, 0)
        self.assertEqual(invalid.worker_id, '')
        observation = json.loads(output.getvalue())
        self.assertEqual(observation['checked_count'], 1)
        self.assertEqual(observation['invalid_snapshot_count'], 1)
        self.assertEqual(observation['claim_denied_count'], 0)
        failure = self.db.scalar(select(RunEvent).where(RunEvent.run_id == invalid.id,
                                                       RunEvent.state == 'failed'))
        self.assertEqual(json.loads(failure.data_json)['error']['error_code'], 'WORKFLOW_STEP_FAILED')
        step = self.db.scalar(select(StepRun).where(StepRun.run_id == invalid.id,
                                                   StepRun.error_code == 'invalid_skill_snapshot'))
        self.assertEqual(step.error_code, 'invalid_skill_snapshot')
        self.assertEqual(step.attempt_count, 0)

    def test_confirmation_and_input_snapshot_rejections_do_not_consume_attempts(self):
        now = datetime.now(UTC)
        confirmation = self.queued_run('codex-confirmation-rejected', 'codex-fair-busy', now,
                                       requires_confirmation=True)
        changed_input = self.queued_run('codex-input-rejected', 'codex-fair-ready', now + timedelta(microseconds=1))
        self.db.commit()
        # All initial records, grants and immutable snapshots are valid.
        for run in (confirmation, changed_input):
            manifest = SkillManifest.model_validate(json.loads(run.manifest_snapshot))
            execution_owner(self.db, run, ExecutionPhase.CLAIM)
            assert_run_confirmation(run, manifest, ExecutionPhase.CLAIM)
            assert_execution_snapshot(self.db, run, ExecutionPhase.CLAIM)
        self.db.commit()
        confirmation.confirmed_by = ''
        confirmation.confirmed_at = None
        changed_input.parameters_json = '{"synthetic_changed":true}'
        self.db.commit()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIsNone(claim_next_run(self.db, ('python',), 'codex-guard-worker'))
        observation = json.loads(output.getvalue())
        self.assertEqual(observation['checked_count'], 2)
        self.assertEqual(observation['claim_denied_count'], 2)
        self.assertEqual(observation['invalid_snapshot_count'], 0)
        for run, expected_code in ((confirmation, 'CONFIRMATION_INVALID'),
                                    (changed_input, 'INPUT_SNAPSHOT_CHANGED')):
            self.assertEqual(run.state, 'failed')
            self.assertEqual(run.attempt_count, 0)
            self.assertEqual(run.worker_id, '')
            self.assertIsNone(run.started_at)
            failure = self.db.scalar(select(RunEvent).where(RunEvent.run_id == run.id,
                                                           RunEvent.state == 'failed'))
            self.assertEqual(json.loads(failure.data_json)['code'], expected_code)
            step = self.db.scalar(select(StepRun).where(StepRun.run_id == run.id,
                                                       StepRun.error_code == expected_code))
            self.assertEqual(step.error_code, expected_code)
            self.assertEqual(step.attempt_count, 0)


if __name__ == '__main__':
    unittest.main()
