from __future__ import annotations

import json
import uuid
from io import BytesIO
from pathlib import Path

import httpx
from app import draft_service
from app.auth_service import get_user_by_username
from app.credential_service import encrypt_secret
from app.database import SessionLocal
from app.models import (
    FileRecord,
    ModelConnection,
    ModelProfile,
    ModelTraceRecord,
    RunRecord,
    TaskDraftRecord,
)
from app.schemas_assistant import AssistantRecommendation
from helpers import auth_client


def _upload(client, name: str) -> str:
    response = client.post(
        "/api/files",
        files={"upload": (name, BytesIO(b"synthetic-xlsx"), "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _configure_profile(username: str) -> str:
    connection_id = str(uuid.uuid4())
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
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                api_key_encrypted=encrypt_secret("sk-synthetic-assistant"),
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
    return connection_id


def _bank_recommendation() -> AssistantRecommendation:
    return AssistantRecommendation(
        skill_id="reconcile-bank",
        confidence=0.96,
        candidates=["reconcile-bank"],
        parameters={"amount_tolerance": 1, "date_tolerance_days": 2},
        file_roles={"bank_file": "F1", "ledger_file": "F2"},
        confirmation_text="使用两份合成文件执行银行流水对账。",
    )


def test_prepare_draft_does_not_create_run_until_confirmed(monkeypatch) -> None:
    username = "assistant-draft-owner"
    with auth_client(username=username) as client:
        _configure_profile(username)
        bank_id = _upload(client, "合成银行流水.xlsx")
        ledger_id = _upload(client, "合成财务总账.xlsx")
        monkeypatch.setattr(
            draft_service,
            "_call_recommender",
            lambda _payload, _config: _bank_recommendation(),
        )
        with SessionLocal() as db:
            runs_before = db.query(RunRecord).count()

        prepared = client.post(
            "/api/assistant/prepare",
            json={
                "message": "请对这两份合成文件进行银行流水对账",
                "file_ids": [bank_id, ledger_id],
            },
        )
        assert prepared.status_code == 200, prepared.text
        draft = prepared.json()
        assert draft["state"] == "ready"
        assert draft["skill_id"] == "reconcile-bank"
        assert draft["files"] == {"bank_file": bank_id, "ledger_file": ledger_id}
        assert draft["file_hashes"] == {
            bank_id: draft["file_hashes"][bank_id],
            ledger_id: draft["file_hashes"][ledger_id],
        }
        with SessionLocal() as db:
            assert db.query(RunRecord).count() == runs_before
            trace = db.query(ModelTraceRecord).filter_by(task_draft_id=draft["id"]).one()
            assert trace.purpose == "assistant_recommendation"
            assert trace.status == "succeeded"
            assert trace.duration_ms >= 0
            serialized_trace = " ".join(
                [trace.purpose, trace.provider, trace.model, trace.failure_code]
            )
            assert "请对这两份" not in serialized_trace
            assert "合成银行流水" not in serialized_trace

        confirmed = client.post(f"/api/task-drafts/{draft['id']}/confirm")
        assert confirmed.status_code == 200, confirmed.text
        run = confirmed.json()
        assert run["state"] == "queued"
        assert run["confirmed_by"]
        duplicate = client.post(f"/api/task-drafts/{draft['id']}/confirm")
        assert duplicate.status_code == 200
        assert duplicate.json()["id"] == run["id"]

        stored = client.get(f"/api/task-drafts/{draft['id']}")
        assert stored.json()["state"] == "consumed"
        assert stored.json()["run_id"] == run["id"]


def test_prepare_draft_records_real_model_usage(monkeypatch) -> None:
    username = f"assistant-trace-success-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        _configure_profile(username)
        recommendation = AssistantRecommendation(
            skill_id="reconcile-bank",
            confidence=0.8,
            candidates=["reconcile-bank"],
            parameters={"amount_tolerance": 1, "date_tolerance_days": 2},
            file_roles={},
            confirmation_text="合成模型结果。",
        )
        monkeypatch.setattr(
            draft_service,
            "chat_completion_request",
            lambda *_args, **_kwargs: httpx.Response(
                200,
                request=httpx.Request("POST", "https://model.synthetic/v1/chat/completions"),
                json={
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "prepare_task_draft",
                                            "arguments": recommendation.model_dump_json(),
                                        }
                                    }
                                ]
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 17, "completion_tokens": 9},
                },
            ),
        )

        prepared = client.post(
            "/api/assistant/prepare",
            json={"message": "合成模型调用", "file_ids": []},
        )
        assert prepared.status_code == 200, prepared.text
        with SessionLocal() as db:
            trace = (
                db.query(ModelTraceRecord)
                .filter_by(task_draft_id=prepared.json()["id"])
                .one()
            )
            assert trace.status == "succeeded"
            assert trace.input_tokens == 17
            assert trace.output_tokens == 9
            assert trace.failure_code == ""


def test_prepare_draft_retries_unknown_skill_and_constrains_catalog_ids(monkeypatch) -> None:
    username = f"assistant-retry-unknown-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        _configure_profile(username)
        invalid = AssistantRecommendation(
            skill_id="bank_reconciliation_readonly",
            confidence=0.92,
            candidates=[],
            parameters={},
            file_roles={},
        )
        valid = AssistantRecommendation(
            skill_id="reconcile-bank",
            confidence=0.8,
            candidates=["reconcile-bank"],
            parameters={"amount_tolerance": 1, "date_tolerance_days": 2},
            file_roles={},
        )
        responses = iter([invalid, valid])
        payloads: list[dict] = []

        def fake_request(_provider, _base_url, _api_key, payload):
            payloads.append(payload)
            recommendation = next(responses)
            return httpx.Response(
                200,
                request=httpx.Request("POST", "https://model.synthetic/v1/chat/completions"),
                json={
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "prepare_task_draft",
                                            "arguments": recommendation.model_dump_json(),
                                        }
                                    }
                                ]
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                },
            )

        monkeypatch.setattr(draft_service, "chat_completion_request", fake_request)
        prepared = client.post(
            "/api/assistant/prepare",
            json={"message": "请推荐银行流水与总账对账任务", "file_ids": []},
        )

        assert prepared.status_code == 200, prepared.text
        assert prepared.json()["skill_id"] == "reconcile-bank"
        assert len(payloads) == 2
        parameters = payloads[0]["tools"][0]["function"]["parameters"]
        allowed = parameters["properties"]["skill_id"]["enum"]
        assert "reconcile-bank" in allowed
        assert "bank_reconciliation_readonly" not in allowed


def test_prepare_draft_retries_missing_tool_call(monkeypatch) -> None:
    username = f"assistant-retry-tool-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        _configure_profile(username)
        valid = AssistantRecommendation(
            skill_id="reconcile-bank",
            confidence=0.8,
            candidates=["reconcile-bank"],
            parameters={"amount_tolerance": 1, "date_tolerance_days": 2},
            file_roles={},
        )
        responses = iter(
            [
                {"choices": [{"message": {"tool_calls": []}}]},
                {
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "prepare_task_draft",
                                            "arguments": valid.model_dump_json(),
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                },
            ]
        )
        calls = 0

        def fake_request(_provider, _base_url, _api_key, _payload):
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                request=httpx.Request("POST", "https://model.synthetic/v1/chat/completions"),
                json=next(responses),
            )

        monkeypatch.setattr(draft_service, "chat_completion_request", fake_request)
        prepared = client.post(
            "/api/assistant/prepare",
            json={"message": "请推荐银行流水与总账对账任务", "file_ids": []},
        )

        assert prepared.status_code == 200, prepared.text
        assert prepared.json()["skill_id"] == "reconcile-bank"
        assert calls == 2


def test_prepare_draft_persists_failed_pre_draft_trace(monkeypatch) -> None:
    username = f"assistant-trace-failure-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        _configure_profile(username)
        monkeypatch.setattr(
            draft_service,
            "chat_completion_request",
            lambda *_args, **_kwargs: httpx.Response(
                200,
                request=httpx.Request("POST", "https://model.synthetic/v1/chat/completions"),
                json={
                    "choices": [{"message": {"tool_calls": []}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                },
            ),
        )

        rejected = client.post(
            "/api/assistant/prepare",
            json={"message": "合成失败模型调用", "file_ids": []},
        )
        assert rejected.status_code == 502
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            trace = (
                db.query(ModelTraceRecord)
                .filter_by(owner_id=user.id, purpose="assistant_recommendation")
                .one()
            )
            assert trace.status == "failed"
            assert trace.run_id is None
            assert trace.task_draft_id is None
            assert trace.input_tokens == 5
            assert trace.output_tokens == 2
            assert trace.failure_code == "ValueError"


def test_delete_draft_preserves_trace_without_parent(monkeypatch) -> None:
    username = f"assistant-delete-trace-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        _configure_profile(username)
        monkeypatch.setattr(
            draft_service,
            "_call_recommender",
            lambda _payload, _config: _bank_recommendation(),
        )
        bank_id = _upload(client, "待删除草稿银行流水.xlsx")
        ledger_id = _upload(client, "待删除草稿财务总账.xlsx")
        prepared = client.post(
            "/api/assistant/prepare",
            json={"message": "生成后删除草稿", "file_ids": [bank_id, ledger_id]},
        )
        assert prepared.status_code == 200, prepared.text
        draft_id = prepared.json()["id"]

        deleted = client.delete(f"/api/task-drafts/{draft_id}")
        assert deleted.status_code == 204, deleted.text
        with SessionLocal() as db:
            assert db.get(TaskDraftRecord, draft_id) is None
            user = get_user_by_username(db, username)
            assert user is not None
            trace = (
                db.query(ModelTraceRecord)
                .filter_by(owner_id=user.id)
                .one()
            )
            assert trace.task_draft_id is None
            assert trace.status == "succeeded"


def test_low_confidence_draft_stays_blocked_after_patch(monkeypatch) -> None:
    username = f"assistant-low-confidence-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        _configure_profile(username)
        bank_id = _upload(client, "低置信度银行流水.xlsx")
        ledger_id = _upload(client, "低置信度财务总账.xlsx")
        monkeypatch.setattr(
            draft_service,
            "_call_recommender",
            lambda _payload, _config: AssistantRecommendation(
                skill_id="reconcile-bank",
                confidence=0.599,
                candidates=["reconcile-bank"],
                parameters={"amount_tolerance": 1, "date_tolerance_days": 2},
                file_roles={"bank_file": "F1", "ledger_file": "F2"},
                clarification="请确认是否需要执行银行流水对账。",
            ),
        )

        prepared = client.post(
            "/api/assistant/prepare",
            json={"message": "对账", "file_ids": [bank_id, ledger_id]},
        )
        assert prepared.status_code == 200, prepared.text
        draft = prepared.json()
        assert draft["confidence"] == 0.59
        assert draft["state"] == "draft"

        patched = client.patch(
            f"/api/task-drafts/{draft['id']}",
            json={"parameters": draft["parameters"], "files": draft["files"]},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["state"] == "draft"

        denied = client.post(f"/api/task-drafts/{draft['id']}/confirm")
        assert denied.status_code == 409
        assert "尚未满足确认条件" in denied.json()["detail"]


def test_confirm_rejects_changed_file_and_cross_user_access(monkeypatch) -> None:
    username = "assistant-draft-hash-owner"
    with auth_client(username=username) as owner:
        _configure_profile(username)
        bank_id = _upload(owner, "合成银行流水.xlsx")
        ledger_id = _upload(owner, "合成财务总账.xlsx")
        monkeypatch.setattr(
            draft_service,
            "_call_recommender",
            lambda _payload, _config: _bank_recommendation(),
        )
        draft = owner.post(
            "/api/assistant/prepare",
            json={"message": "对账", "file_ids": [bank_id, ledger_id]},
        ).json()

        with auth_client(username="assistant-draft-other") as other:
            assert other.get(f"/api/task-drafts/{draft['id']}").status_code == 404
            assert other.patch(
                f"/api/task-drafts/{draft['id']}", json={"parameters": {}}
            ).status_code == 404
            assert other.post(f"/api/task-drafts/{draft['id']}/confirm").status_code == 404

        with SessionLocal() as db:
            record = db.get(TaskDraftRecord, draft["id"])
            assert record is not None
            file_id = next(iter(json.loads(record.file_hashes_json)))
            uploaded = db.get(FileRecord, file_id)
            assert uploaded is not None
            Path(uploaded.stored_path).write_bytes(b"changed-after-draft")

        denied = owner.post(f"/api/task-drafts/{draft['id']}/confirm")
        assert denied.status_code == 409
        assert "内容已经变化" in denied.json()["detail"]


def test_assistant_profile_details_are_admin_only() -> None:
    admin_name = "assistant-profile-admin"
    with auth_client(role="skill_admin", username=admin_name) as admin:
        connection_id = _configure_profile(admin_name)
        current = admin.get("/api/admin/assistant-profile")
        assert current.status_code == 200
        assert current.json()["connection_id"] == connection_id
        assert current.json()["model"] == "synthetic-model"
        assert admin.get("/api/assistant/status").json() == {"configured": True}

        with auth_client(username="assistant-profile-employee") as employee:
            assert employee.get("/api/assistant/status").json() == {"configured": True}
            assert employee.get("/api/admin/assistant-profile").status_code == 403


def test_assistant_requires_profile_and_rejects_unauthorized_recommendation(monkeypatch) -> None:
    no_profile_name = f"assistant-no-profile-{uuid.uuid4().hex[:8]}"
    with auth_client(username=no_profile_name) as client:
        with SessionLocal() as db:
            user = get_user_by_username(db, no_profile_name)
            assert user is not None
            profile = (
                db.query(ModelProfile)
                .filter_by(
                    department_id=user.department_id,
                    purpose="finance-assistant",
                )
                .one_or_none()
            )
            if profile:
                db.delete(profile)
                db.commit()
        missing = client.post("/api/assistant/prepare", json={"message": "帮我对账"})
        assert missing.status_code == 409
        assert "尚未配置" in missing.json()["detail"]

    username = "assistant-invalid-recommendation"
    with auth_client(username=username) as client:
        _configure_profile(username)
        monkeypatch.setattr(
            draft_service,
            "_call_recommender",
            lambda _payload, _config: AssistantRecommendation(
                skill_id="ar-hexiao-daily",
                confidence=0.99,
                parameters={},
                file_roles={},
            ),
        )
        rejected = client.post("/api/assistant/prepare", json={"message": "执行核销"})
        assert rejected.status_code == 502
        assert "未授权或不可用" in rejected.json()["detail"]
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            assert db.query(TaskDraftRecord).filter_by(owner_id=user.id).count() == 0
