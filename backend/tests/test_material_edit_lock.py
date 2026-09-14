import os
from datetime import datetime
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import openpyxl
from app.models import Base, WorkflowSession, WorkflowBatch, WorkflowAction, FileRecord
from app.auth import UserContext
from app.workflow_material_lock import material_edit_state, assert_material_editable
from app.workflow_material_service import MaterialVersionConflict, restore_material_set
from app.ar_material_history import receipt_facts, verify_updated_annual_materials


class MaterialLockTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = UserContext(user_id="user", display_name="test", role="finance_user", department_id="dept")
        self.fields = dict(owner_id="user", department_id="dept", skill_id="ar-hexiao-daily-lab", skill_name="test", skill_version="1", model_connection_id="m", model_provider="test", model_name="test")

    def tearDown(self):
        self.db.close(); self.engine.dispose()

    def test_running_task_locks_until_finished(self):
        w = WorkflowSession(id="w", skill_hash="hash", state="running", stage="fetching", **self.fields)
        self.db.add(w); self.db.commit()
        self.assertTrue(material_edit_state(self.db, self.user, w.skill_id)["locked"])
        with self.assertRaises(MaterialVersionConflict):
            assert_material_editable(self.db, self.user, w.skill_id)
        w.state = "succeeded"; self.db.commit()
        self.assertFalse(material_edit_state(self.db, self.user, w.skill_id)["locked"])

    def test_failed_batch_does_not_lock_paused_children(self):
        b = WorkflowBatch(id="batch", state="failed", **self.fields)
        self.db.add(b); self.db.add(WorkflowSession(id="child", batch_id="batch", skill_hash="hash", state="queued", stage="queued", **self.fields)); self.db.commit()
        self.assertFalse(material_edit_state(self.db, self.user, b.skill_id)["locked"])
        b.state = "running"; self.db.commit()
        self.assertTrue(material_edit_state(self.db, self.user, b.skill_id)["locked"])

    def test_other_owner_is_independent(self):
        self.db.add(WorkflowSession(id="w", skill_hash="hash", state="running", stage="fetching", **{**self.fields, "owner_id": "other"})); self.db.commit()
        self.assertFalse(material_edit_state(self.db, self.user, self.fields["skill_id"])["locked"])

    def test_failed_task_with_active_investigation_stays_locked(self):
        self.db.add(WorkflowSession(id="w", skill_hash="hash", state="failed", stage="failed", **self.fields)); self.db.flush()
        self.db.add(WorkflowAction(id="a", workflow_id="w", name="investigate", state="running")); self.db.commit()
        self.assertTrue(material_edit_state(self.db, self.user, self.fields["skill_id"])["locked"])

    def test_restore_is_rejected_before_changing_materials(self):
        self.db.add(WorkflowSession(id="w", skill_hash="hash", state="running", stage="fetching", **self.fields)); self.db.commit()
        with self.assertRaises(MaterialVersionConflict):
            restore_material_set(self.db, self.user, self.fields["skill_id"], "old")
        self.db.rollback()

    def test_initial_material_entry_remains_available(self):
        self.db.add(WorkflowSession(id="w", skill_hash="hash", state="awaiting_input", stage="awaiting_files", **self.fields)); self.db.commit()
        self.assertFalse(material_edit_state(self.db, self.user, self.fields["skill_id"])["locked"])

    def test_flow_replacement_and_reupload_allow_inheritance(self):
        prior = NS(files=[NS(role="profit_loss_ledgers", year=2026, file_id="old", sha256="same"), NS(role="receipt_flow_table", year=0, sha256="old-flow")])
        selected = NS(files=[NS(role="profit_loss_ledgers", year=2026, file_id="reupload", sha256="same"), NS(role="receipt_flow_table", year=0, sha256="new-flow")])
        self.assertEqual(verify_updated_annual_materials(self.db, prior, selected), [])

    @unittest.skipUnless(os.environ.get("LOCAL_SYNTHETIC_TEST_DIR"), "temporary workbooks are local only")
    def test_updated_annual_table_can_add_rows_but_preserves_receipts(self):
        import hashlib
        with tempfile.TemporaryDirectory(dir=os.environ["LOCAL_SYNTHETIC_TEST_DIR"]) as folder:
            files = []
            for name, amount, extra in [("old", 60, False), ("new", 60, True), ("bad", 20, True)]:
                wb = openpyxl.Workbook(); sh = wb.active; sh.title = "明细"
                sh.append(["新智云单号", "实收金额", "回款明细", "收款时间", "收款方式"])
                sh.append(["SO_TEST", "SOD_TEST", amount, "2026/9/4" if name == "old" else datetime(2026, 9, 4), "汇"])
                if extra: sh.append(["SO_NEW", "SOD_NEW", None, None, None])
                path = Path(folder) / (name + ".xlsx"); wb.save(path); wb.close()
                files.append(NS(role="profit_loss_ledgers", year=2026, file_id=name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), path=path))
            records = {f.file_id: NS(stored_path=str(f.path), owner_id="user", department_id="dept", skill_id="ar-hexiao-daily-lab") for f in files}
            db = NS(get=lambda model, key: records.get(key))
            ancestor = NS(files=[files[0]])
            selected = NS(files=[files[1]], owner_id="user", department_id="dept", skill_id="ar-hexiao-daily-lab")
            self.assertEqual(verify_updated_annual_materials(db, ancestor, selected), [2026])
            selected.files = [files[2]]
            with self.assertRaisesRegex(ValueError, "1条回款记录不一致"):
                verify_updated_annual_materials(db, ancestor, selected)

if __name__ == "__main__":
    unittest.main()
