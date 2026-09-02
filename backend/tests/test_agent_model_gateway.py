from __future__ import annotations

import uuid
from contextlib import contextmanager

import httpx
from helpers import auth_client

from app.agent_model_gateway import (
    AgentModelStreamStats,
    build_agent_model_payload,
    iter_agent_model_stream,
    resolve_agent_model_config,
)
from app.auth import UserContext
from app.auth_service import get_user_by_username
from app.authorization import replace_user_permissions
from app.credential_service import encrypt_secret
from app.database import SessionLocal
from app.models import ModelConnection, ModelProfile, ModelTraceRecord
from app.orchestrator import LlmConfig
from app.registry import registry
from app.routers import assistant as assistant_router


def _config() -> LlmConfig:
    return LlmConfig(
        provider="qwen",
        connection_id="connection-1",
        base_url="https://model.synthetic.example/v1",
        api_key="sk-never-logged",
        model="qwen3.7-plus",
    )


def test_background_workflow_marker_never_queries_model_connections(monkeypatch) -> None:
    expected = _config()
    calls: list[str] = []

    monkeypatch.setattr(
        "app.agent_model_gateway.resolve_runtime_config",
        lambda *_args: calls.append("runtime") or None,
    )
    monkeypatch.setattr(
        "app.agent_model_gateway.resolve_assistant_config",
        lambda *_args: expected,
    )
    user = UserContext(
        user_id="user-1",
        display_name="测试用户",
        role="finance_user",
        department_id="finance",
    )

    resolved = resolve_agent_model_config(
        object(),  # type: ignore[arg-type]
        user,
        "platform-background-worker",
        "后台 Skill Worker",
    )

    assert resolved is expected
    assert calls == []


def test_agent_gateway_binds_department_model_and_drops_connection_fields() -> None:
    payload = build_agent_model_payload(
        _config(),
        {
            "model": "attacker-selected-model",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [],
            "stream": True,
            "temperature": 0,
            "api_key": "must-not-forward",
            "base_url": "https://attacker.example/v1",
            "store": True,
            "providerOptions": {"persist": True},
        },
    )

    assert payload["model"] == "qwen3.7-plus"
    assert payload["enable_thinking"] is False
    assert "api_key" not in payload
    assert "base_url" not in payload
    assert "store" not in payload
    assert "providerOptions" not in payload


def test_agent_gateway_usage_parser_handles_split_sse_chunks_without_logging_text() -> None:
    stats = AgentModelStreamStats()
    stats.observe(b'data: {"choices": [{"delta": {"content": "secret"}}]}\n\n')
    stats.observe(b'data: {"usage": {"prompt_tokens": 7, "completion_tokens": 11}}\n')
    stats.observe(b'\ndata: [DONE]\n\n')
    stats.succeed()

    assert stats.status == "succeeded"
    assert stats.input_tokens == 7
    assert stats.output_tokens == 11
    assert "secret" not in repr(stats)


def test_agent_model_stream_marks_client_disconnect_as_failed() -> None:
    class FakeResponse:
        def iter_bytes(self):
            yield b"first"
            yield b"second"

    stats = AgentModelStreamStats()
    stream = iter_agent_model_stream(FakeResponse(), stats)
    assert next(stream) == b"first"
    stream.close()

    assert stats.status == "failed"
    assert stats.failure_code == "stream_cancelled"


def test_agent_skill_directory_uses_draft_permission_not_run_permission() -> None:
    username = f"agent-skill-directory-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username, grant_skills=False) as client:
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            replace_user_permissions(
                db,
                user,
                [
                    {
                        "skill_id": "reconcile-bank",
                        "can_run": True,
                        "can_upload": True,
                        "can_create_draft": False,
                        "requires_approval": False,
                    }
                ],
            )
            db.commit()

        response = client.get("/api/assistant/skills")

        assert response.status_code == 200, response.text
        assert "reconcile-bank" not in {item["id"] for item in response.json()}
        assert registry.get("ar-hexiao-daily") is not None


def test_agent_model_endpoint_streams_and_records_only_safe_metrics(monkeypatch) -> None:
    username = f"agent-gateway-{uuid.uuid4().hex[:8]}"
    department_id = f"agent-department-{uuid.uuid4().hex[:8]}"
    connection_id = str(uuid.uuid4())
    with auth_client(username=username, department_id=department_id) as client:
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            db.add(
                ModelConnection(
                    id=connection_id,
                    owner_id=user.id,
                    department_id=user.department_id,
                    provider="qwen",
                    provider_name="合成模型",
                    base_url="https://model.synthetic.example/v1",
                    api_key_encrypted=encrypt_secret("sk-secret-not-logged"),
                    api_key_hint="sk-••••test",
                    api_key_fingerprint=uuid.uuid4().hex,
                    models_json='["synthetic-model"]',
                    selected_model="synthetic-model",
                    status="connected",
                )
            )
            profile = (
                db.query(ModelProfile)
                .filter_by(department_id=user.department_id, purpose="finance-assistant")
                .one_or_none()
            )
            if profile:
                profile.connection_id = connection_id
                profile.model = "synthetic-model"
                profile.configured_by = user.id
            else:
                db.add(
                    ModelProfile(
                        id=str(uuid.uuid4()),
                        department_id=user.department_id,
                        purpose="finance-assistant",
                        connection_id=connection_id,
                        model="synthetic-model",
                        configured_by=user.id,
                    )
                )
            db.commit()

        @contextmanager
        def fake_stream(_config, payload):
            assert payload["model"] == "synthetic-model"
            assert "api_key" not in payload
            assert "base_url" not in payload
            response = httpx.Response(
                200,
                request=httpx.Request("POST", "https://model.synthetic.example/v1/chat/completions"),
                headers={"content-type": "text/event-stream"},
                content=(
                    b'data: {"choices":[{"delta":{"content":"secret response"}}]}\n\n'
                    b'data: {"usage":{"prompt_tokens":3,"completion_tokens":5}}\n\n'
                    b"data: [DONE]\n\n"
                ),
            )
            yield response

        monkeypatch.setattr(assistant_router, "open_agent_model_stream", fake_stream)
        response = client.post(
            "/api/assistant/model/chat/completions",
            json={
                "model": "synthetic-model",
                "connection_id": connection_id,
                "messages": [{"role": "user", "content": "secret prompt"}],
                "stream": True,
            },
        )

        assert response.status_code == 200, response.text
        assert "secret response" in response.text

        invalid_model = client.post(
            "/api/assistant/model",
            json={
                "model": "attacker-selected-model",
                "connection_id": connection_id,
                "messages": [{"role": "user", "content": "secret prompt"}],
                "stream": True,
            },
        )
        assert invalid_model.status_code == 422

        rejected_storage_control = client.post(
            "/api/assistant/model",
            json={
                "model": "synthetic-model",
                "connection_id": connection_id,
                "messages": [{"role": "user", "content": "secret prompt"}],
                "stream": True,
                "store": True,
            },
        )
        assert rejected_storage_control.status_code == 422

        draft_response = client.post(
            "/api/assistant/prepare-from-recommendation",
            json={
                "message": "合成 Agent 草稿",
                "file_ids": [],
                "recommendation": {
                    "skill_id": "reconcile-bank",
                    "confidence": 0.8,
                    "candidates": ["reconcile-bank"],
                    "parameters": {"amount_tolerance": 1, "date_tolerance_days": 2},
                    "file_roles": {},
                    "clarification": "请补充两份对账文件。",
                },
            },
        )
        assert draft_response.status_code == 200, draft_response.text
        assert draft_response.json()["source"] == "assistant"
        with SessionLocal() as db:
            trace = (
                db.query(ModelTraceRecord)
                .filter_by(owner_id=user.id, purpose="agent_turn")
                .one()
            )
            assert trace.model == "synthetic-model"
            assert trace.input_tokens == 3
            assert trace.output_tokens == 5
            assert "secret prompt" not in trace.failure_code
            assert (
                db.query(ModelTraceRecord)
                .filter_by(owner_id=user.id, purpose="agent_tool")
                .count()
                == 1
            )
