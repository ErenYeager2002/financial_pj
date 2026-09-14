import json
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.auth import UserContext
from app.models import AssistantMessage, ModelTraceRecord
from app.orchestrator import LlmConfig
from app import assistant_title_service as titles
from app.assistant_chat_service import list_conversations


class TitleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        AssistantMessage.__table__.create(self.engine)
        ModelTraceRecord.__table__.create(self.engine)
        self.user = UserContext(user_id="owner", display_name="Test", role="finance_user", department_id="finance")
        with Session(self.engine) as db:
            for id, role, content, owner in [
                ("1", "user", "FIRST_USER_MESSAGE", "owner"),
                ("2", "assistant", "LATEST_ASSISTANT_REPLY", "owner"),
                ("3", "user", "OTHER_OWNER_SECRET", "other"),
            ]:
                db.add(AssistantMessage(id=id, session_id="test", owner_id=owner, department_id="finance", role=role, content=content, data_json='{"preserved":true}'))
            db.commit()
        self.session = patch.object(titles, "SessionLocal", lambda: Session(self.engine))
        self.session.start()
        self.config = patch.object(titles, "resolve_assistant_config", return_value=LlmConfig(provider="custom", connection_id="c", base_url="https://example.test", api_key="test", model="test"))
        self.config.start()
        self.extra = patch.object(titles, "config_extra_body", return_value={})
        self.extra.start()

    def tearDown(self):
        self.extra.stop(); self.config.stop(); self.session.stop(); self.engine.dispose()

    @patch.object(titles, "chat_completion_request")
    def test_first_message_cached_and_owner_scoped(self, request):
        request.return_value.json.return_value = {"choices":[{"message":{"content":"核销速度优化"}}]}
        titles.generate_titles(self.user, ["test"])
        titles.generate_titles(self.user, ["test"])
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[3]["messages"][1]["content"], "FIRST_USER_MESSAGE")
        with Session(self.engine) as db:
            metadata=json.loads(db.get(AssistantMessage,"1").data_json)
            self.assertTrue(metadata["preserved"])
            self.assertEqual(metadata[titles.TITLE_KEY],"核销速度优化")
            self.assertNotIn(titles.TITLE_KEY,json.loads(db.get(AssistantMessage,"3").data_json))
            self.assertEqual(list_conversations(db,self.user)[0].preview,"核销速度优化")

    @patch.object(titles, "chat_completion_request", side_effect=RuntimeError("provider unavailable"))
    def test_failure_does_not_fail_chat_or_retry_immediately(self, request):
        titles.generate_titles(self.user,["test"])
        titles.generate_titles(self.user,["test"])
        self.assertEqual(request.call_count,1)
        with Session(self.engine) as db:
            self.assertEqual(list_conversations(db,self.user)[0].preview,"新对话")
            self.assertEqual(db.get(AssistantMessage,"1").content,"FIRST_USER_MESSAGE")

    @patch.object(titles, "chat_completion_request")
    def test_long_generation_is_rewritten_not_cut(self, request):
        request.return_value.json.side_effect = [
            {"choices":[{"message":{"content":"应收核销慢因分析及优化"}}]},
            {"choices":[{"message":{"content":"应收核销提速"}}]},
        ]
        titles.generate_titles(self.user,["test"])
        self.assertEqual(request.call_count,2)
        with Session(self.engine) as db:
            self.assertEqual(list_conversations(db,self.user)[0].preview,"应收核销提速")

    def test_title_is_single_line_and_at_most_ten_characters(self):
        title=titles.normalize_title('“这是一个超过十个字的对话标题。”')
        self.assertLessEqual(len(title),10)
        self.assertNotIn('“',title)
        self.assertEqual(titles.normalize_title("<think>ignore</think>核销\n优化"),"核销优化")

if __name__ == "__main__": unittest.main()
