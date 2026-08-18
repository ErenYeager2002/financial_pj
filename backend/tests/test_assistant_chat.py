from __future__ import annotations

import uuid

from helpers import auth_client


def test_assistant_conversation_is_persisted_and_owner_scoped() -> None:
    username = f"assistant-history-{uuid.uuid4().hex[:8]}"
    session_id = f"chat-{uuid.uuid4().hex}"
    with auth_client(username=username) as client:
        first = client.post(
            f"/api/assistant/conversations/{session_id}/messages",
            json={"role": "user", "content": "请记住这条测试消息。"},
        )
        assert first.status_code == 201, first.text
        second = client.post(
            f"/api/assistant/conversations/{session_id}/messages",
            json={"role": "assistant", "content": "已记录。"},
        )
        assert second.status_code == 201, second.text

        conversation = client.get(f"/api/assistant/conversations/{session_id}")
        assert conversation.status_code == 200, conversation.text
        assert [item["content"] for item in conversation.json()["messages"]] == [
            "请记住这条测试消息。",
            "已记录。",
        ]

        latest = client.get("/api/assistant/conversations/latest")
        assert latest.status_code == 200, latest.text
        assert latest.json()["session_id"] == session_id

    with auth_client(username=f"assistant-history-other-{uuid.uuid4().hex[:8]}") as other:
        denied = other.get(f"/api/assistant/conversations/{session_id}")
        assert denied.status_code == 404
        assert other.get("/api/assistant/conversations/latest").json() is None
