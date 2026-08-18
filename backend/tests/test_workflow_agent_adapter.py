from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import workflow_execution_policy
from app.auth import UserContext
from app.database import SessionLocal
from app.models import WorkflowSession
from app.workflow_orchestrator import (
    CONTROLLED_WORKFLOW_ACTIONS,
    validate_workflow_agent_request,
    workflow_agent_tools,
)
from app.workflow_service import apply_workflow_agent_action


def _actor() -> UserContext:
    return UserContext(
        user_id="workflow-agent-user",
        username="workflow-agent-user",
        display_name="Workflow Agent User",
        department_id="finance",
        role="finance_user",
    )


def test_workflow_agent_tools_only_expose_the_controlled_action_set() -> None:
    expected = {
        "set_reconciliation_date",
        "get_workflow_stage",
        "prepare_daily_reconciliation",
        "request_regeneration",
        "request_user_confirmation",
    }
    assert set(CONTROLLED_WORKFLOW_ACTIONS) == expected

    for stage in (
        "awaiting_date",
        "awaiting_date_confirmation",
        "awaiting_files",
        "preparing",
        "awaiting_apply_confirmation",
        "applying",
        "completed",
        "failed",
        "cancelled",
    ):
        names = {item["function"]["name"] for item in workflow_agent_tools(stage)}
        assert names <= expected
        assert "confirm_apply" not in names
        assert "apply_confirmed" not in names


def test_workflow_agent_request_is_stage_and_argument_checked() -> None:
    decision = validate_workflow_agent_request(
        "awaiting_date",
        "set_reconciliation_date",
        {"date": "2026-08-16"},
    )
    assert decision.action == "set_date"
    assert decision.arguments == {"date": "2026-08-16"}
    assert decision.source == "pi"

    with pytest.raises(HTTPException, match="当前阶段"):
        validate_workflow_agent_request(
            "completed",
            "prepare_daily_reconciliation",
            {},
        )
    with pytest.raises(HTTPException, match="日期"):
        validate_workflow_agent_request(
            "awaiting_date",
            "set_reconciliation_date",
            {"date": "2099-01-01"},
        )
    with pytest.raises(HTTPException, match="不支持"):
        validate_workflow_agent_request("awaiting_date", "run_shell", {})


def test_apply_workflow_agent_action_only_updates_state_and_requests_confirmation() -> None:
    class FakeDb:
        def __init__(self) -> None:
            self.added: list[object] = []

        def add(self, value: object) -> None:
            self.added.append(value)

        def flush(self) -> None:
            return None

        def commit(self) -> None:
            return None

        def refresh(self, _value: object) -> None:
            return None

    workflow = SimpleNamespace(
        id="synthetic-workflow",
        owner_id="workflow-agent-user",
        department_id="finance",
        skill_id="synthetic-readonly-workflow",
        stage="awaiting_date",
        state="active",
        reconciliation_date="",
        progress_message="等待确认核销日期",
        progress=0,
        error_message="",
        updated_at=datetime.now(),
    )
    db = FakeDb()

    result = apply_workflow_agent_action(
        db,
        workflow,
        "set_reconciliation_date",
        {"date": "2026-08-16"},
        _actor(),
    )

    assert workflow.stage == "awaiting_date_confirmation"
    assert workflow.reconciliation_date == "2026-08-16"
    assert result.action == "set_reconciliation_date"
    assert result.await_confirmation is True
    assert result.confirmation_kind == "date"
    assert not any("shell" in repr(item).lower() for item in db.added)


def test_ar_hexiao_agent_execution_actions_follow_the_deployment_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow_execution_policy,
        "settings",
        replace(workflow_execution_policy.settings, ar_hexiao_execution_enabled=False),
    )
    class FakeDb:
        def commit(self) -> None:
            raise AssertionError("the blocked action must not commit")

    for stage, action in (
        ("awaiting_files", "prepare_daily_reconciliation"),
        ("awaiting_apply_confirmation", "request_regeneration"),
    ):
        workflow = SimpleNamespace(
            id="ar-synthetic-workflow",
            owner_id="workflow-agent-user",
            department_id="finance",
            skill_id="ar-hexiao-daily",
            stage=stage,
            state="active",
            reconciliation_date="2026-08-16",
            progress_message="合成测试工作流",
            progress=0,
            error_message="",
            updated_at=datetime.now(),
        )

        with pytest.raises(HTTPException, match="真实工作流执行"):
            apply_workflow_agent_action(FakeDb(), workflow, action, {}, _actor())


def test_ar_hexiao_legacy_execution_gate_blocks_workflow_entrypoints(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow_execution_policy,
        "settings",
        replace(workflow_execution_policy.settings, ar_hexiao_execution_enabled=False),
    )

    with pytest.raises(HTTPException, match="真实工作流执行"):
        workflow_execution_policy.assert_workflow_execution_enabled(
            SimpleNamespace(skill_id="ar-hexiao-daily")
        )


def test_workflow_agent_action_endpoint_keeps_worker_execution_behind_the_api() -> None:
    from helpers import auth_client

    workflow_id = str(uuid4())
    with auth_client(
        role="skill_admin",
        username=f"workflow-agent-endpoint-{uuid4().hex[:8]}",
    ) as client:
        owner_id = client.get("/api/session").json()["user_id"]
        with SessionLocal() as db:
            db.add(
                WorkflowSession(
                    id=workflow_id,
                    owner_id=owner_id,
                    owner_name="测试管理员",
                    department_id="finance",
                    skill_id="synthetic-readonly-workflow",
                    skill_name="合成只读工作流",
                    skill_version="0.1.0",
                    skill_hash="a" * 64,
                    model_connection_id="synthetic-connection",
                    model_provider="synthetic",
                    model_name="synthetic-model",
                    stage="awaiting_date",
                    state="active",
                    progress_message="等待确认核销日期",
                )
            )
            db.commit()

        changed = client.post(
            f"/api/workflows/{workflow_id}/agent/actions",
            json={
                "action": "set_reconciliation_date",
                "arguments": {"date": "2026-08-16"},
            },
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["workflow"]["stage"] == "awaiting_date_confirmation"
        assert changed.json()["await_confirmation"] is True
        assert changed.json()["confirmation_kind"] == "date"

        context = client.get(f"/api/workflows/{workflow_id}/agent/context")
        assert context.status_code == 200, context.text
        assert context.json()["connection_id"] == "synthetic-connection"
        assert context.json()["model"] == "synthetic-model"
        assert "model_connection_id" not in context.json()["workflow"]

        denied = client.post(
            f"/api/workflows/{workflow_id}/agent/actions",
            json={
                "action": "prepare_daily_reconciliation",
                "arguments": {},
            },
        )
        assert denied.status_code == 409
