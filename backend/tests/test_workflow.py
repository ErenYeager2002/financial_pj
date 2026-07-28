from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select

from app import model_service, workflow_orchestrator, workflow_service
from app.database import SessionLocal
from app.main import app
from app.models import WorkflowAction


def workbook_bytes() -> bytes:
    workbook = Workbook()
    workbook.active.append(["测试列"])
    workbook.active.append(["假数据"])
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def upload(client: TestClient, role: str, name: str) -> str:
    response = client.post(
        "/api/files",
        data={"role": role},
        files={
            "upload": (
                name,
                workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def execute_next_action(workflow_id: str) -> None:
    with SessionLocal() as db:
        action = db.scalar(
            select(WorkflowAction)
            .where(
                WorkflowAction.workflow_id == workflow_id,
                WorkflowAction.state == "queued",
            )
            .order_by(WorkflowAction.queued_at.asc())
        )
        assert action is not None
        action.state = "running"
        db.commit()
        workflow_service.execute_workflow_action(db, action)
        db.commit()


def test_qwen_workflow_supports_natural_multi_turn(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeChatResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "到账日期是银行收款日，核销日期是销售关联订单的日期。",
                        }
                    }
                ]
            }

    def fake_post(*_, **kwargs):
        captured.update(kwargs["json"])
        return FakeChatResponse()

    monkeypatch.setattr(workflow_orchestrator.httpx, "post", fake_post)
    decision = workflow_orchestrator.decide_workflow_turn(
        SimpleNamespace(
            provider="qwen",
            model="qwen3.7-plus",
            base_url="https://dashscope.example/v1",
            api_key="test-key",
        ),
        "awaiting_date",
        "核销日期和到账日期有什么区别？",
        "",
        [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，需要一起处理什么财务工作？"},
            {"role": "user", "content": "核销日期和到账日期有什么区别？"},
        ],
    )

    assert decision.action == "reply"
    assert "银行收款日" in decision.arguments["content"]
    assert captured["tool_choice"] == "auto"
    assert captured["enable_thinking"] is False
    messages = captured["messages"]
    assert isinstance(messages, list)
    assert messages[-3:] == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，需要一起处理什么财务工作？"},
        {"role": "user", "content": "核销日期和到账日期有什么区别？"},
    ]


def test_questions_containing_action_words_do_not_execute() -> None:
    assert workflow_orchestrator._fallback_decision(
        "awaiting_files",
        "为什么还不能开始？",
    ).action == "show_status"
    assert workflow_orchestrator._fallback_decision(
        "awaiting_apply_confirmation",
        "确认写入是什么意思？",
    ).action == "show_status"
    assert workflow_orchestrator._fallback_decision(
        "awaiting_date",
        "2026-07-24 是星期几？",
    ).action == "show_status"
    assert workflow_orchestrator._fallback_decision(
        "preparing",
        "停止按钮有什么作用？",
    ).action == "show_status"


def test_conversational_workflow_hard_gates(monkeypatch) -> None:
    class FakeModelsResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": [{"id": "qwen3.7-plus"}]}

    monkeypatch.setattr(
        model_service.httpx,
        "get",
        lambda *_, **__: FakeModelsResponse(),
    )

    def unavailable_model(*_, **__):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(workflow_orchestrator.httpx, "post", unavailable_model)
    monkeypatch.setattr(
        workflow_service,
        "_prepare_worklist",
        lambda db, action, workflow: {
            "workspace": "isolated-test-workspace",
            "checked_plan": "checked-plan.json",
            "ledger": "ledger.xlsx",
            "summary": {"今天要填": 3, "异常": 0},
            "artifacts": [],
        },
    )
    monkeypatch.setattr(
        workflow_service,
        "_apply_confirmed",
        lambda db, action, workflow: {
            "workspace": "isolated-test-workspace",
            "artifacts": [],
        },
    )

    with TestClient(app) as client:
        connection = client.post(
            "/api/model-connections",
            json={"api_key": "sk-workflow-test-secret"},
        )
        assert connection.status_code == 200, connection.text

        created = client.post(
            "/api/workflows",
            json={
                "skill_id": "ar-hexiao-daily",
                "model_connection_id": connection.json()["id"],
                "model": "qwen3.7-plus",
            },
        )
        assert created.status_code == 200, created.text
        workflow_id = created.json()["id"]
        assert created.json()["stage"] == "awaiting_date"

        status_before_date = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "上传好了"},
        )
        assert status_before_date.status_code == 200
        assert status_before_date.json()["stage"] == "awaiting_date"
        assert status_before_date.json()["messages"][-1]["content"] == "请先告诉我核销日期。"

        dated = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "2026年7月24日"},
        )
        assert dated.status_code == 200
        assert dated.json()["stage"] == "awaiting_date_confirmation"
        assert dated.json()["reconciliation_date"] == "2026-07-24"

        confirmed = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "确认"},
        )
        assert confirmed.json()["stage"] == "awaiting_files"

        premature = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "确认写入"},
        )
        assert premature.json()["stage"] == "awaiting_files"
        assert premature.json()["actions"] == []

        zhiyun_id = upload(client, "zhiyun_exports", "智云导出.xlsx")
        ledger_id = upload(client, "finance_workbooks", "盈亏表.xlsx")
        flow_id = upload(client, "finance_workbooks", "到账流转表.xlsx")

        too_few = client.put(
            f"/api/workflows/{workflow_id}/files",
            json={"files": {"finance_workbooks": [ledger_id]}},
        )
        assert too_few.status_code == 422

        attached = client.put(
            f"/api/workflows/{workflow_id}/files",
            json={
                "files": {
                    "zhiyun_exports": [zhiyun_id],
                    "finance_workbooks": [ledger_id, flow_id],
                }
            },
        )
        assert attached.status_code == 200, attached.text

        preparing = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "上传好了"},
        )
        assert preparing.json()["stage"] == "preparing"
        assert preparing.json()["actions"][0]["name"] == "prepare_worklist"

        execute_next_action(workflow_id)
        review = client.get(f"/api/workflows/{workflow_id}").json()
        assert review["stage"] == "awaiting_apply_confirmation"
        assert review["state"] == "waiting_confirmation"

        original_decider = workflow_service.decide_workflow_turn
        monkeypatch.setattr(
            workflow_service,
            "decide_workflow_turn",
            lambda *_, **__: workflow_orchestrator.WorkflowDecision(
                "confirm_apply",
                {},
                "malformed-model",
            ),
        )
        guarded = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "现在进度怎么样"},
        )
        assert guarded.json()["stage"] == "awaiting_apply_confirmation"
        assert len(guarded.json()["actions"]) == 1
        monkeypatch.setattr(
            workflow_service,
            "decide_workflow_turn",
            original_decider,
        )

        applying = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "我已检查核销日清，确认写入"},
        )
        assert applying.json()["stage"] == "applying"
        assert len(applying.json()["actions"]) == 2

        execute_next_action(workflow_id)
        completed = client.get(f"/api/workflows/{workflow_id}").json()
        assert completed["stage"] == "completed"
        assert completed["state"] == "succeeded"

        monkeypatch.setattr(
            workflow_service,
            "decide_workflow_turn",
            lambda *_, **__: workflow_orchestrator.WorkflowDecision(
                "reply",
                {"content": "任务已经完成，我还可以继续解释结果或回答问题。"},
                "llm",
            ),
        )
        continued = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "任务完成后还能继续聊吗？"},
        )
        assert continued.status_code == 200
        assert continued.json()["stage"] == "completed"
        assert "继续解释结果" in continued.json()["messages"][-1]["content"]
