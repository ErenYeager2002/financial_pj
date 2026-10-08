"""Run only in the disposable, network-isolated material-policy PostgreSQL canary."""
import json
import os
import threading
import time
import unittest

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from app.models import Base, SchedulerLock, WorkflowSession
from app.scheduler import acquire_claim_lock
from app.ar_execution_safety import get_safety_view, assert_operation_allowed, MaterialOccupancyConflict
from test_ar_postpublish_occupancy import PostPublishOccupancyTests

URL = 'postgresql+psycopg://synthetic:synthetic-only@127.0.0.1:5432/material_policy_test'


@unittest.skipUnless(os.environ.get('AR_POLICY_SYNTHETIC_DB_URL') == URL, 'isolated PostgreSQL only')
class MaterialPolicyPostgresTests(unittest.TestCase):
    def test_guard_waits_for_writer_and_rechecks_committed_occupancy(self):
        engine = create_engine(URL, connect_args={'options': '-c statement_timeout=10000'})
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        fixture = PostPublishOccupancyTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        blocked_context = fixture.workflow.context_json
        context = json.loads(blocked_context)
        context['ar_execution']['completed'].append('complete_reconciliation')
        context['formal_ledgers'] = {'file_id': 'formal', 'sha256': 'c'*64}
        fixture.workflow.context_json = json.dumps(context)
        fixture.db.commit()
        with engine.begin() as connection:
            for table in Base.metadata.sorted_tables:
                rows = [dict(row) for row in fixture.db.execute(select(table)).mappings()]
                if rows:
                    connection.execute(table.insert(), rows)
            connection.execute(SchedulerLock.__table__.insert().values(name='global'))

        loaded, proceed = threading.Event(), threading.Event()
        output = []
        def reader():
            try:
                with Session(engine, expire_on_commit=False) as db:
                    stale = db.get(WorkflowSession, 'unfinished')
                    self.assertTrue(get_safety_view(db, 'owner', 'finance', 'ar-hexiao-daily-lab')
                                    ['material_admission_allowed'])
                    loaded.set()
                    if not proceed.wait(5):
                        raise AssertionError('reader barrier timeout')
                    try:
                        assert_operation_allowed(db, 'owner', 'finance', 'ar-hexiao-daily-lab',
                                                 operation='create_run')
                    except MaterialOccupancyConflict as error:
                        output.append(error.view['reason'])
                    else:
                        output.append('incorrectly-admitted')
                    self.assertIn('formal_ledgers', stale.context_json)
                    db.rollback()
            except BaseException as error:
                output.append(error)
                loaded.set()

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        self.assertTrue(loaded.wait(5))
        try:
            with Session(engine) as writer:
                acquire_claim_lock(writer)
                workflow = writer.get(WorkflowSession, 'unfinished')
                workflow.context_json = blocked_context
                writer.flush()
                proceed.set()
                observed_wait = False
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with engine.connect() as observer:
                        observed_wait = bool(observer.scalar(text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                            "AND wait_event_type='Lock' AND pid <> pg_backend_pid()")))
                    if observed_wait:
                        break
                    time.sleep(.05)
                self.assertTrue(observed_wait, 'reader never waited on the writer transaction')
                self.assertEqual(output, [])
                writer.commit()
        finally:
            proceed.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(output, ['unresolved_write'])
        # The actual PostgreSQL server-side claim cursor must tolerate the
        # guarded flush between a blocked candidate and an independent one.
        from test_ar_claim_material_policy import ClaimMaterialPolicyTests
        with Session(engine, expire_on_commit=False) as db:
            case = ClaimMaterialPolicyTests()
            case.db = db
            case.test_blocked_candidate_does_not_starve_independent_owner()



if __name__ == '__main__':
    unittest.main()
