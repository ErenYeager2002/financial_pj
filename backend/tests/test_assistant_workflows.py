import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.auth import UserContext
from app.models import AssistantMessage
from app import assistant_workflow_service as bridge
from app.assistant_chat_service import append_message, get_conversation

class AssistantWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        AssistantMessage.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.user = UserContext(user_id="owner", display_name="Test", role="finance_user", department_id="finance")
        append_message(self.db, self.user, "test", "user", "再跑一次", {"preserved": True})
        self.db.commit()
        self.summary = {"ready": True, "files": [], "missing_roles": []}
        self.materials = patch.object(bridge, "inspect_materials", return_value=(self.summary, "version-one"))
        self.inspect = self.materials.start()
        self.preflight = patch.object(bridge, "check_execution_state", return_value=[]).start()
        self.runner = patch("app.workflow_service.start_workflow_batch", return_value=SimpleNamespace(
            id="BAT-test", display_id="核销任务1", state="running", reconciliation_dates_json='["2026-08-20"]')).start()
        def execute(db, request, user, *, before_start, on_created):
            before_start()
            batch = self.runner.return_value
            on_created(batch)
            db.commit()
            return batch
        self.runner.side_effect = execute
        self.body = bridge.AssistantWorkflowPrepare(session_id="test", message="再跑一次", skill_id="ar-hexiao-daily-lab",
            reconciliation_dates=["2026-08-20"], rerun_successful_dates=True, authorization_quote="再跑一次")

    def tearDown(self):
        patch.stopall()
        self.db.close()
        self.engine.dispose()

    def prepare(self):
        return bridge.prepare(self.db, self.user, self.body)

    def start(self, plan):
        return bridge.start(self.db, self.user, bridge.AssistantWorkflowStart(
            session_id="test", message="再跑一次", plan_id=plan["plan_id"]))

    def test_reuses_materials_and_submits_once(self):
        plan = self.prepare()
        self.runner.assert_not_called()
        first = self.start(plan)
        self.assertEqual(self.start(plan), first)
        self.assertEqual(self.runner.call_count, 1)
        request = self.runner.call_args.args[1]
        self.assertEqual(request.skill_id, "ar-hexiao-daily-lab")
        self.assertEqual(request.files, {})
        self.assertIsNone(request.fetched_bundle_id)
        self.assertTrue(request.rerun_successful_dates)
        self.assertEqual(first["url"], "/dashboard/workflows/batches/BAT-test")
        self.assertNotIn(bridge.STATE_KEY, get_conversation(self.db, self.user, "test").messages[0].data)

    def test_material_change_blocks_before_batch_creation(self):
        plan = self.prepare()
        self.inspect.return_value = (self.summary, "new-version")
        with self.assertRaises(HTTPException): self.start(plan)
        self.assertIsNone(bridge.request_status(self.db, self.user, "test")["task"])
        with self.assertRaises(HTTPException): self.start(plan)

    def test_failed_start_is_not_retried(self):
        plan = self.prepare()
        self.runner.side_effect = RuntimeError("response lost")
        with self.assertRaises(RuntimeError): self.start(plan)
        with self.assertRaises(HTTPException): self.start(plan)
        with self.assertRaises(HTTPException): self.prepare()
        self.assertEqual(self.runner.call_count, 1)

    def test_other_owner_and_stale_turn_are_rejected(self):
        other = UserContext(user_id="other", display_name="Other", role="finance_user", department_id="finance")
        with self.assertRaises(HTTPException): bridge.prepare(self.db, other, self.body)
        self.body.message = "旧消息"
        with self.assertRaises(HTTPException): self.prepare()
        self.runner.assert_not_called()

    def test_missing_materials_do_not_create_plan(self):
        self.inspect.return_value = ({"ready": False, "missing_roles": ["receipt_flow_table"]}, "empty")
        self.assertIsNone(self.prepare()["plan_id"])
        self.runner.assert_not_called()

    def test_permission_error_propagates_without_execution(self):
        self.inspect.side_effect = HTTPException(403, "Skill permission denied")
        with self.assertRaises(HTTPException) as error: self.prepare()
        self.assertEqual(error.exception.status_code, 403)
        self.runner.assert_not_called()

    def test_consultation_cannot_start_and_quote_cannot_be_invented(self):
        self.body.authorization_quote = "用户没说过"
        with self.assertRaises(HTTPException): self.prepare()
        self.body.authorization_quote = ""
        self.body.rerun_successful_dates = False
        with self.assertRaises(HTTPException): self.start(self.prepare())
        self.runner.assert_not_called()

    def test_dates_are_sorted_and_invalid_dates_blocked(self):
        self.body.reconciliation_dates = ["2026-08-21", "2026-08-20", "2026-08-20"]
        self.assertEqual(self.prepare()["reconciliation_dates"], ["2026-08-20", "2026-08-21"])
        for dates in (["2099-01-01"], ["2026-02-30"], ["2026-07-01", "2026-08-20"]):
            self.body.reconciliation_dates = dates
            with self.assertRaises(HTTPException): self.prepare()
        self.runner.assert_not_called()

    def test_denial_consultation_and_quoted_execution_do_not_start(self):
        for text in ["不要执行9.8", "为什么执行9.8", '他说“执行9.8”', "假如执行9.8会怎样", "你能执行核销吗", "启动核销需要什么条件"]:
            append_message(self.db, self.user, "test", "user", text)
            self.db.commit()
            self.body.message = text
            self.body.authorization_quote = text
            self.body.rerun_successful_dates = False
            with self.assertRaises(HTTPException): self.prepare()
        self.runner.assert_not_called()

    def test_rerun_requires_explicit_rerun_context(self):
        append_message(self.db, self.user, "fresh", "user", "帮我做核销")
        self.db.commit()
        self.body.session_id = "fresh"
        self.body.message = self.body.authorization_quote = "帮我做核销"
        with self.assertRaises(HTTPException): self.prepare()
        self.runner.assert_not_called()

    def test_lost_response_returns_atomically_recorded_task(self):
        execute = self.runner.side_effect
        def lost(*args, **kwargs):
            execute(*args, **kwargs)
            raise RuntimeError("response lost after commit")
        self.runner.side_effect = lost
        self.assertEqual(self.start(self.prepare())["id"], "BAT-test")
        append_message(self.db, self.user, "test", "user", "刚才启动成功了吗")
        self.db.commit()
        self.assertEqual(bridge.request_status(self.db, self.user, "test")["task"]["id"], "BAT-test")
        self.assertEqual(self.runner.call_count, 1)

    def test_continuation_is_bound_to_prepared_date_and_skill(self):
        self.prepare()
        append_message(self.db, self.user, "test", "user", "可以继续")
        self.db.commit()
        self.body.message = self.body.authorization_quote = "可以继续"
        self.assertTrue(self.prepare()["rerun_successful_dates"])
        self.body.reconciliation_dates = ["2026-08-21"]
        with self.assertRaises(HTTPException): self.prepare()
        self.body.reconciliation_dates = ["2026-08-20"]
        self.body.skill_id = "ar-hexiao-daily"
        with self.assertRaises(HTTPException): self.prepare()
        self.runner.assert_not_called()

    def test_authorization_survives_missing_materials(self):
        self.inspect.return_value = ({"ready": False, "missing_roles": ["receipt_flow_table"]}, "empty")
        self.assertIsNone(self.prepare()["plan_id"])
        append_message(self.db, self.user, "test", "user", "都准备好了，帮我执行")
        self.db.commit()
        self.body.message = self.body.authorization_quote = "都准备好了，帮我执行"
        self.inspect.return_value = (self.summary, "version-one")
        self.assertTrue(self.prepare()["ready"])
        self.runner.assert_not_called()

    def test_client_cannot_inject_internal_plan(self):
        result = append_message(self.db, self.user, "other", "user", "test", {
            bridge.STATE_KEY: {"state": "prepared"}, "keep": "yes"})
        self.assertEqual(result.data, {"keep": "yes"})
        self.assertNotIn(bridge.STATE_KEY, json.loads(self.db.get(AssistantMessage, result.id).data_json))

class ExecutionStateTests(unittest.TestCase):
    def test_failed_staged_write_stops_new_batch(self):
        from unittest.mock import MagicMock
        db = MagicMock()
        db.scalars.return_value.all.return_value = [SimpleNamespace(
            state="failed", reconciliation_date="2026-08-20", context_json='{"ar_failure":{"write_status":"unknown"}}',
            display_id="failed-task", id="failed", actions=[])]
        user = UserContext(user_id="owner", display_name="Test", role="finance_user", department_id="finance")
        with patch("app.workflow_service._assert_single_flight_available"), patch("app.workflow_material_service.current_material_set", return_value=None):
            with self.assertRaises(HTTPException) as error:
                bridge.check_execution_state(db, user, "ar-hexiao-daily-lab", ["2026-08-20"])
            self.assertIn("原任务", error.exception.detail)

if __name__ == "__main__": unittest.main()
