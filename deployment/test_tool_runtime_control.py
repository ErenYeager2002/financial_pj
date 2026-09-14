"""Run inside an isolated image with an empty SQLite DB; never use production DB."""
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

class RuntimeControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("FINANCIAL_DATABASE_URL") != "sqlite:////tmp/scoped-tool-test.db":
            raise RuntimeError("isolated test database required")
        from app.database import Base, engine, SessionLocal
        from app.models import User
        from app.auth_service import create_session
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            user=User(id="scoped-test-admin",username="scoped-test-admin",display_name="Test",role="skill_admin",status="active",must_change_password=False,password_hash="unused")
            db.add(user); db.flush()
            cls.token=create_session(db,user); db.commit()

    def test_pause_idempotence_generation_and_target_lock(self):
        import tool_runtime_control as control
        from app.database import SessionLocal
        from app.skill_availability_service import get_availability
        requests=[
            {"operation":"pause","generation":0},
            {"operation":"pause","generation":0},
            {"operation":"disable","generation":1},
            {"operation":"guard","generation":2},
            {"operation":"release_guard","generation":2},
            {"operation":"resume","generation":2},
        ]
        for r in requests: r.update(token=self.token,skill_id="env-doctor",deployment_id="isolated-test-release")
        output=io.StringIO()
        original=control.acquire_claim_lock
        claims=[]
        def claim(db): claims.append(True); return original(db)
        with patch.object(control.sys,"stdin",io.StringIO("\n".join(map(json.dumps,requests))+"\n")),patch.object(control,"acquire_claim_lock",claim),redirect_stdout(output):
            control.main()
        responses=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(responses),6)
        self.assertTrue(all(r["ok"] for r in responses),responses)
        self.assertEqual(responses[0]["result"]["generation"],responses[1]["result"]["generation"])
        self.assertEqual(len(claims),4) # guard and release_guard never take global claim lock
        with SessionLocal() as db:
            self.assertEqual(get_availability(db,"env-doctor").state,"enabled")
            other=next(s.manifest.id for s in control.registry.list(include_disabled=True) if s.manifest.id!="env-doctor")
            self.assertEqual(get_availability(db,other).state,"enabled")

    def test_queued_action_blocks_disable_even_if_workflow_is_terminal(self):
        import tool_runtime_control as control
        from app.database import SessionLocal
        from app.models import WorkflowSession, WorkflowAction
        from app.skill_availability_service import get_availability
        with SessionLocal() as db:
            workflow=WorkflowSession(id="test-workflow",owner_id="scoped-test-admin",skill_id="env-doctor",skill_name="test",skill_version="1.0.0",skill_hash="0"*64,model_connection_id="test",model_provider="test",model_name="test",state="succeeded")
            db.add(workflow);db.flush()
            db.add(WorkflowAction(id="test-action",workflow_id=workflow.id,name="test",state="queued"));db.commit()
            generation=get_availability(db,"env-doctor").generation
        requests=[{"operation":"pause","generation":generation},{"operation":"disable","generation":generation+1},{"operation":"resume","generation":generation+1}]
        for r in requests: r.update(token=self.token,skill_id="env-doctor",deployment_id="queued-action-release")
        output=io.StringIO()
        with patch.object(control.sys,"stdin",io.StringIO("\n".join(map(json.dumps,requests))+"\n")),redirect_stdout(output): control.main()
        results=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(results[0]["ok"])
        self.assertFalse(results[1]["ok"])
        self.assertTrue(results[2]["ok"])

    def test_unauthenticated_control_is_rejected(self):
        import tool_runtime_control as control
        output=io.StringIO()
        with patch.object(control.sys,"stdin",io.StringIO(json.dumps({"operation":"pause","token":"invalid","skill_id":"ar-hexiao-daily"})+"\n")),redirect_stdout(output):
            control.main()
        self.assertFalse(json.loads(output.getvalue())["ok"])

if __name__=="__main__": unittest.main()
