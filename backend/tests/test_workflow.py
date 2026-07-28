from __future__ import annotations

from io import BytesIO

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
