import unittest
from datetime import UTC, datetime, timedelta
from sqlalchemy import create_engine, update, select
from sqlalchemy.orm import Session
from app.models import RunRecord, FileRecord
from app.run_fencing import bind_run_fence, RunLeaseLost, assert_run_fence
class FenceTests(unittest.TestCase):
 def setUp(self):
  self.engine=create_engine("sqlite://")
  RunRecord.__table__.create(self.engine);FileRecord.__table__.create(self.engine)
  self.db=Session(self.engine)
  self.run=RunRecord(id="run",owner_id="owner",skill_id="test",skill_name="test",skill_version="1",skill_hash="hash",manifest_path="",manifest_snapshot="{}",adapter="python",worker_pool="python",worker_id="worker",attempt_count=1,state="running",lease_expires_at=datetime.now(UTC)+timedelta(seconds=60))
  self.db.add(self.run);self.db.commit();bind_run_fence(self.db,self.run)
 def tearDown(self):self.db.close();self.engine.dispose()
 def steal(self,**values):
  with self.engine.begin() as c:c.execute(update(RunRecord).where(RunRecord.id=="run").values(**values))
 def test_old_attempt_cannot_publish_terminal(self):
  self.steal(attempt_count=2);self.run.state="succeeded"
  with self.assertRaises(RunLeaseLost):self.db.commit()
  self.db.rollback()
  with self.engine.connect() as c:self.assertEqual(c.scalar(select(RunRecord.state)),"running")
 def test_old_attempt_cannot_publish_file(self):
  self.steal(worker_id="new")
  self.db.add(FileRecord(id="file",owner_id="owner",kind="output",original_name="x",stored_path="/tmp/x",size_bytes=1,sha256="h",run_id="run"))
  with self.assertRaises(RunLeaseLost):self.db.flush()
 def test_expired_owner_cannot_revive(self):
  self.steal(lease_expires_at=datetime.now(UTC)-timedelta(seconds=1))
  with self.assertRaises(RunLeaseLost):assert_run_fence(self.db)
 def test_current_attempt_can_commit(self):
  self.run.state="succeeded";self.db.commit();self.assertEqual(self.run.state,"succeeded")
if __name__=="__main__":unittest.main()
