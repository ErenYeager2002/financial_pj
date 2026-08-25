from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from helpers import auth_client
from openpyxl import Workbook
from sqlalchemy import select

from app import model_service, workflow_orchestrator, workflow_service
from app.auth_models import UserSkillPermission
from app.auth_service import get_user_by_username
from app.database import SessionLocal, init_db
from app.models import (
    AuditEvent,
    FileRecord,
    ServiceCredential,
    WorkflowAction,
    WorkflowBatch,
    WorkflowSession,
)


@pytest.fixture(autouse=True)
def _allow_disabled_workflow_skill(monkeypatch):
    """工作流测试始终允许读取目标 Skill，避免发布状态影响状态机测试。"""
    _finish_all_ar_workflows()
    from app.registry import registry as _registry

    real_get = _registry.get

    def get(skill_id: str, include_unpublished: bool = False):
        return real_get(skill_id, include_unpublished=True)

    monkeypatch.setattr(_registry, "get", get)
    yield
    _finish_all_ar_workflows()


def workbook_bytes() -> bytes:
    workbook = Workbook()
    workbook.active.append(["测试列"])
    workbook.active.append(["假数据"])
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def test_workflow_fetch_error_is_business_safe_and_actionable() -> None:
    workflow = SimpleNamespace(
        context_json=json.dumps({"current_step": "fetch_zhiyun", "current_step_label": "智云取数"}),
        stage="preparing",
        reconciliation_date="2026-08-12",
        owner_name="测试员工",
        owner_id="owner-1",
        skill_id="ar-hexiao-daily",
        skill_name="应收核销日清",
    )

    detail = workflow_service._workflow_error_detail(
        workflow,
        "fetch_secure.py 执行失败（退出码 2）：HTTP 502 https://private.example/api",
    )
    public = workflow_service._workflow_public_error(workflow, detail)

    assert public["message"] == (
        "2026-08-12 取数未完成：智云暂时无法访问，本次取数未完成。请稍后点击“重试失败日期”。"
    )
    assert "fetch_secure.py" not in public["message"]
    assert "退出码" not in public["message"]
    assert "https://" not in public["message"]
    assert "测试员工" not in public["message"]


def test_batch_child_can_register_artifact_from_controlled_shared_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    current_root = tmp_path / "current"
    shared_root = tmp_path / "primary"
    source = shared_root / "batch" / "工作区" / "04_产出" / "核销日清.xlsx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"synthetic-worklist")
    added = []
    db = SimpleNamespace(add=added.append, flush=lambda: None)
    workflow = SimpleNamespace(
        id="child-workflow",
        owner_id="owner",
        department_id="finance",
        skill_id="ar-hexiao-daily",
        skill_name="应收核销日清",
        skill_version="1.6.4",
    )
    monkeypatch.setattr(workflow_service, "workflow_root", lambda *_args: current_root)
    monkeypatch.setattr(
        workflow_service,
        "_workflow_storage_root",
        lambda *_args: shared_root,
    )

    artifact = workflow_service._register_artifact(
        db,
        workflow,
        source,
        "action-1",
    )

    assert artifact["name"] == "核销日清.xlsx"
    assert (current_root / "outputs" / "action-1" / "核销日清.xlsx").read_bytes() == (
        b"synthetic-worklist"
    )
    assert len(added) == 1


def test_artifact_outside_controlled_workspace_is_rejected(
    monkeypatch,
    tmp_path: Path,
) -> None:
    current_root = tmp_path / "current"
    shared_root = tmp_path / "primary"
    source = tmp_path / "outside" / "核销日清.xlsx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"outside")
    workflow = SimpleNamespace(id="child-workflow", owner_id="owner")
    monkeypatch.setattr(workflow_service, "workflow_root", lambda *_args: current_root)
    monkeypatch.setattr(
        workflow_service,
        "_workflow_storage_root",
        lambda *_args: shared_root,
    )

    with pytest.raises(RuntimeError, match="工作流产物必须位于当前会话目录"):
        workflow_service._register_artifact(
            SimpleNamespace(),
            workflow,
            source,
            "action-1",
        )


class FakeVerificationResponse:
    """符合 Tool Calling 验证要求的成功响应结构。"""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "tool_call_supported",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    }
                }
            ]
        }


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


def _finish_all_ar_workflows() -> None:
    """Keep platform-global single-flight tests isolated from earlier cases."""
    init_db()
    with SessionLocal() as db:
        workflows = list(
            db.scalars(
                select(WorkflowSession).where(
                    WorkflowSession.skill_id == "ar-hexiao-daily",
                    WorkflowSession.state.not_in(("succeeded", "failed", "cancelled")),
                )
            ).all()
        )
        for workflow in workflows:
            workflow.state = "failed"
            workflow.stage = "failed"
        batches = list(
            db.scalars(
                select(WorkflowBatch).where(
                    WorkflowBatch.skill_id == "ar-hexiao-daily",
                    WorkflowBatch.state.not_in(("succeeded", "failed", "cancelled")),
                )
            ).all()
        )
        for batch in batches:
            batch.state = "failed"
        pending_actions = list(
            db.scalars(
                select(WorkflowAction)
                .join(WorkflowSession, WorkflowSession.id == WorkflowAction.workflow_id)
                .where(
                    WorkflowSession.skill_id == "ar-hexiao-daily",
                    WorkflowAction.state.in_(("queued", "running")),
                )
            ).all()
        )
        for action in pending_actions:
            action.state = "cancelled"
            action.finished_at = workflow_service.datetime.now(workflow_service.UTC)
            action.worker_id = ""
            action.heartbeat_at = None
            action.lease_expires_at = None
        db.commit()


def test_ar_workflow_has_business_id_and_blocks_concurrent_start() -> None:
    _finish_all_ar_workflows()
    username = f"single-flight-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "single-flight", "password": "single-flight-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        payload = {
            "skill_id": "ar-hexiao-daily",
            "reconciliation_date": "2026-08-20",
            "files": {
                "profit_loss_ledgers": [ledger_id],
                "receipt_flow_table": [flow_id],
            },
        }
        first = client.post("/api/workflows/start", json=payload)
        assert first.status_code == 200, first.text
        first_body = first.json()
        today = workflow_service.datetime.now(workflow_service.PLATFORM_TIMEZONE)
        expected_prefix = f"ar-hexiao-daily_{today.month}.{today.day}_"
        assert first_body["display_id"].startswith(expected_prefix)
        assert first_body["display_id"].rsplit("_", 1)[1].isdigit()

        blocked = client.post("/api/workflows/start", json=payload)
        assert blocked.status_code == 409, blocked.text
        assert first_body["display_id"] in blocked.json()["detail"]

        blocked_batch = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_dates": ["2026-08-19", "2026-08-20"],
                "files": payload["files"],
            },
        )
        assert blocked_batch.status_code == 409, blocked_batch.text

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, first_body["id"])
            assert workflow is not None
            workflow.state = "failed"
            workflow.stage = "failed"
            db.commit()

        allowed = client.post("/api/workflows/start", json=payload)
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["display_id"] != first_body["display_id"]
    _finish_all_ar_workflows()


def test_multi_date_batch_assigns_business_ids_to_batch_and_children() -> None:
    _finish_all_ar_workflows()


def test_multi_date_batch_accepts_contiguous_calendar_days() -> None:
    _finish_all_ar_workflows()
    username = f"weekend-batch-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "weekend-batch", "password": "weekend-batch-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        response = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_dates": [
                    "2026-08-14",
                    "2026-08-15",
                    "2026-08-16",
                    "2026-08-17",
                ],
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["reconciliation_dates"] == [
            "2026-08-14",
            "2026-08-15",
            "2026-08-16",
            "2026-08-17",
        ]
    _finish_all_ar_workflows()


def test_failed_range_report_retries_without_rerunning_daily_tasks() -> None:
    _finish_all_ar_workflows()
    username = f"finalizer-retry-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        assert (
            client.put(
                "/api/service-credentials/zhiyun",
                json={"account": "finalizer-retry", "password": "finalizer-password"},
            ).status_code
            == 200
        )
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_dates": ["2026-08-17", "2026-08-18"],
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        batch_id = started.json()["id"]

        with SessionLocal() as db:
            batch = db.get(WorkflowBatch, batch_id)
            assert batch is not None
            children = sorted(batch.workflows, key=lambda item: item.batch_sequence)
            for child in children:
                child.state = "succeeded"
                child.stage = "completed"
                for pending in child.actions:
                    pending.state = "succeeded"
            last = children[-1]
            last.context_json = json.dumps(
                {
                    "workspace": "D:/synthetic-batch-workspace",
                    "step_error": {"reason": "stale"},
                    "error_detail": {"reason": "stale"},
                }
            )
            db.add(
                WorkflowAction(
                    id=str(uuid.uuid4()),
                    workflow_id=last.id,
                    name="finalize_batch",
                    state="failed",
                    input_json=json.dumps({"workspace": "D:/synthetic-batch-workspace"}),
                )
            )
            batch.state = "failed"
            batch.error_message = "范围报告生成失败"
            db.commit()

        retried = client.post(f"/api/workflow-batches/{batch_id}/retry")
        assert retried.status_code == 200, retried.text
        body = retried.json()
        assert body["state"] == "finalizing"
        assert all(item["state"] == "succeeded" for item in body["workflows"])
        assert body["workflows"][-1]["actions"][-1]["name"] == "finalize_batch"
        assert body["workflows"][-1]["actions"][-1]["state"] == "queued"
        with SessionLocal() as db:
            batch = db.get(WorkflowBatch, batch_id)
            assert batch is not None
            last = sorted(batch.workflows, key=lambda item: item.batch_sequence)[-1]
            context = json.loads(last.context_json)
            assert "step_error" not in context
            assert "error_detail" not in context
    _finish_all_ar_workflows()
    username = f"range-batch-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "range-batch", "password": "range-batch-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        response = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_dates": ["2026-08-17", "2026-08-19"],
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert response.status_code == 422
        assert "连续日期" in response.json()["detail"]
    _finish_all_ar_workflows()
    username = f"display-batch-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "display-batch", "password": "display-batch-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        response = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_dates": ["2026-08-19", "2026-08-20"],
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        today = workflow_service.datetime.now(workflow_service.PLATFORM_TIMEZONE)
        expected_prefix = f"ar-hexiao-daily_{today.month}.{today.day}_"
        assert body["display_id"].startswith(expected_prefix)
        assert len({item["display_id"] for item in body["workflows"]}) == 2
        assert all(item["display_id"].startswith(expected_prefix) for item in body["workflows"])

        with SessionLocal() as db:
            batch = db.get(WorkflowBatch, body["id"])
            assert batch is not None
            children = sorted(batch.workflows, key=lambda item: item.batch_sequence)
            for child in children:
                child.state = "succeeded"
                child.stage = "completed"
                child.artifacts_json = json.dumps(
                    [
                        {"name": f"核销日清_{child.reconciliation_date.replace('-', '')}.xlsx"},
                        {"name": "盈亏核算表.xlsx"},
                    ],
                    ensure_ascii=False,
                )
            children[-1].artifacts_json = json.dumps(
                [
                    {"name": "核销日清_20260819_20260820.xlsx", "file_id": "integrated"},
                    {"name": "盈亏核算表.xlsx", "file_id": "ledger"},
                ],
                ensure_ascii=False,
            )
            batch.state = "succeeded"
            db.commit()

        displayed = client.get(f"/api/workflow-batches/{body['id']}")
        assert displayed.status_code == 200, displayed.text
        displayed_workflows = displayed.json()["workflows"]
        assert displayed_workflows[0]["artifacts"] == []
        assert displayed_workflows[-1]["artifacts"] == [
            {"name": "核销日清_20260819_20260820.xlsx", "file_id": "integrated"}
        ]
    _finish_all_ar_workflows()


def test_active_batch_can_be_cancelled_and_releases_single_flight() -> None:
    _finish_all_ar_workflows()
    username = f"cancel-batch-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "cancel-batch", "password": "cancel-batch-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        files = {
            "profit_loss_ledgers": [ledger_id],
            "receipt_flow_table": [flow_id],
        }
        started = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_dates": ["2026-08-19", "2026-08-20"],
                "files": files,
            },
        )
        assert started.status_code == 200, started.text
        batch_id = started.json()["id"]

        cancelled = client.post(f"/api/workflow-batches/{batch_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        body = cancelled.json()
        assert body["state"] == "cancelled"
        assert all(item["state"] == "cancelled" for item in body["workflows"])

        with SessionLocal() as db:
            batch = db.get(WorkflowBatch, batch_id)
            assert batch is not None
            assert all(
                action.state not in {"queued", "running"}
                for workflow in batch.workflows
                for action in workflow.actions
            )

        allowed = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-20",
                "files": files,
            },
        )
        assert allowed.status_code == 200, allowed.text
    _finish_all_ar_workflows()


def test_running_batch_atomic_write_cannot_be_cancelled() -> None:
    _finish_all_ar_workflows()
    username = f"cancel-batch-write-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "cancel-batch-write", "password": "cancel-batch-write-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_dates": ["2026-08-19", "2026-08-20"],
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        body = started.json()
        batch_id = body["id"]
        active_id = body["workflows"][0]["id"]

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, active_id)
            assert workflow is not None
            action = workflow.actions[0]
            action.name = "apply_confirmed"
            action.state = "running"
            action.worker_id = "batch-write-test-worker"
            workflow.stage = "applying"
            workflow.state = "running"
            db.commit()

        denied = client.post(f"/api/workflow-batches/{batch_id}/cancel")
        assert denied.status_code == 409, denied.text
        assert "原子写入" in denied.json()["detail"]
    _finish_all_ar_workflows()


def test_running_batch_cancellation_is_idempotent_and_audited_once() -> None:
    _finish_all_ar_workflows()
    username = f"cancel-batch-repeat-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "cancel-batch-repeat", "password": "cancel-batch-repeat-pass"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_dates": ["2026-08-19", "2026-08-20"],
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        batch_id = started.json()["id"]
        active_id = started.json()["workflows"][0]["id"]

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, active_id)
            assert workflow is not None
            action = workflow.actions[0]
            action.state = "running"
            action.worker_id = "repeat-cancel-test-worker"
            workflow.state = "running"
            db.commit()

        first = client.post(f"/api/workflow-batches/{batch_id}/cancel")
        assert first.status_code == 200, first.text
        assert first.json()["state"] == "cancelling"
        second = client.post(f"/api/workflow-batches/{batch_id}/cancel")
        assert second.status_code == 200, second.text
        assert second.json()["state"] == "cancelling"

        with SessionLocal() as db:
            events = list(
                db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.resource_id == batch_id,
                        AuditEvent.action == "workflow.batch.cancel",
                    )
                ).all()
            )
            assert len(events) == 1
    _finish_all_ar_workflows()


def test_active_workflow_can_be_cancelled_and_releases_single_flight() -> None:
    _finish_all_ar_workflows()
    username = f"cancel-workflow-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "cancel-workflow", "password": "cancel-workflow-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        files = {
            "profit_loss_ledgers": [ledger_id],
            "receipt_flow_table": [flow_id],
        }
        started = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-20",
                "files": files,
            },
        )
        assert started.status_code == 200, started.text
        workflow_id = started.json()["id"]

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            action = workflow.actions[0]
            workspace = (
                workflow_service.workflow_root(workflow.owner_id, workflow.id)
                / "actions"
                / action.id
                / "工作区"
            )
            export_dir = workspace / "01_智云导出"
            export_dir.mkdir(parents=True)
            (export_dir / "取数摘要_20260820.json").write_text("{}", encoding="utf-8")
            context = json.loads(workflow.context_json)
            context.update(
                {
                    "workspace": str(workspace.resolve()),
                    "fetched_data": {
                        "available": True,
                        "review_status": "waiting",
                        "reconciliation_date": "2026-08-20",
                    },
                }
            )
            workflow.context_json = json.dumps(context)
            db.commit()

        cancelled = client.post(f"/api/workflows/{workflow_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        body = cancelled.json()
        assert body["state"] == "cancelled"
        assert body["stage"] == "cancelled"

        repeated = client.post(f"/api/workflows/{workflow_id}/cancel")
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["state"] == "cancelled"

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            assert all(action.state not in {"queued", "running"} for action in workflow.actions)
            context = json.loads(workflow.context_json)
            assert context["fetched_data"]["available"] is False
            assert context["fetched_data"]["review_status"] == "deleted"
            assert not export_dir.exists()

        allowed = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-20",
                "files": files,
            },
        )
        assert allowed.status_code == 200, allowed.text
    _finish_all_ar_workflows()


def test_running_fetch_observes_cancellation_before_advancing(monkeypatch) -> None:
    _finish_all_ar_workflows()
    username = f"cancel-running-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "cancel-running", "password": "cancel-running-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-20",
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        workflow_id = started.json()["id"]

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            action = workflow.actions[0]
            action.state = "running"
            action.worker_id = "cancel-test-worker"
            db.commit()
            action_id = action.id

        def finish_fetch_after_cancel(db, action, workflow):
            cancelled = client.post(f"/api/workflows/{workflow_id}/cancel")
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["state"] == "cancelling"
            return {
                "artifacts": [],
                "summary": {},
                "awaiting_fetched_data_confirmation": True,
            }

        monkeypatch.setattr(workflow_service, "_prepare_worklist", finish_fetch_after_cancel)
        with SessionLocal() as db:
            action = db.get(WorkflowAction, action_id)
            assert action is not None
            workflow_service.execute_workflow_action(db, action)
            db.commit()

        current = client.get(f"/api/workflows/{workflow_id}")
        assert current.status_code == 200, current.text
        assert current.json()["state"] == "cancelled"
        assert current.json()["stage"] == "cancelled"
    _finish_all_ar_workflows()


def test_worker_progress_update_preserves_concurrent_cancellation_flag() -> None:
    _finish_all_ar_workflows()
    username = f"cancel-progress-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "cancel-progress", "password": "cancel-progress-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-20",
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        workflow_id = started.json()["id"]

        with SessionLocal() as worker_db:
            stale_workflow = worker_db.get(WorkflowSession, workflow_id)
            assert stale_workflow is not None
            with SessionLocal() as cancelling_db:
                current = cancelling_db.get(WorkflowSession, workflow_id)
                assert current is not None
                context = json.loads(current.context_json)
                context["stop_after_action"] = True
                current.context_json = json.dumps(context)
                current.state = "cancelling"
                cancelling_db.commit()

            workflow_service._set_progress_step(
                worker_db,
                stale_workflow,
                "post_fetch_check",
                "正在检查取数结果",
                15,
            )

        with SessionLocal() as verify_db:
            current = verify_db.get(WorkflowSession, workflow_id)
            assert current is not None
            context = json.loads(current.context_json)
            assert context["stop_after_action"] is True
            assert context["current_step"] == "post_fetch_check"
            assert current.state == "cancelling"
    _finish_all_ar_workflows()


def test_input_copy_completion_preserves_concurrent_cancellation_flag(monkeypatch) -> None:
    _finish_all_ar_workflows()
    username = f"cancel-copy-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "cancel-copy", "password": "cancel-copy-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-20",
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        workflow_id = started.json()["id"]

        original_copy_inputs = workflow_service._copy_inputs

        def copy_then_cancel(db, action, workflow, business):
            copied = original_copy_inputs(db, action, workflow, business)
            db.commit()
            cancelled = client.post(f"/api/workflows/{workflow_id}/cancel")
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["state"] == "cancelling"
            return copied

        monkeypatch.setattr(workflow_service, "_copy_inputs", copy_then_cancel)
        monkeypatch.setattr(workflow_service, "_run_script", lambda *args, **kwargs: "")
        monkeypatch.setattr(workflow_service, "_fetched_summary_from_export", lambda *args: {})

        with SessionLocal() as worker_db:
            workflow = worker_db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            action = workflow.actions[0]
            action.state = "running"
            action.worker_id = "copy-cancel-test-worker"
            worker_db.commit()
            workflow_service._prepare_worklist(worker_db, action, workflow)

        with SessionLocal() as verify_db:
            current = verify_db.get(WorkflowSession, workflow_id)
            assert current is not None
            assert json.loads(current.context_json)["stop_after_action"] is True
            assert current.state == "cancelling"
    _finish_all_ar_workflows()


def test_running_atomic_write_cannot_be_cancelled() -> None:
    _finish_all_ar_workflows()
    username = f"cancel-write-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "cancel-write", "password": "cancel-write-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-20",
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        workflow_id = started.json()["id"]

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            action = workflow.actions[0]
            action.name = "apply_confirmed"
            action.state = "running"
            action.worker_id = "write-test-worker"
            workflow.stage = "applying"
            workflow.state = "running"
            db.commit()

        denied = client.post(f"/api/workflows/{workflow_id}/cancel")
        assert denied.status_code == 409, denied.text
        assert "原子写入" in denied.json()["detail"]

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            assert workflow.state == "running"
    _finish_all_ar_workflows()


def test_department_admin_cannot_cancel_another_users_workflow() -> None:
    _finish_all_ar_workflows()
    owner_name = f"cancel-owner-{uuid.uuid4().hex[:8]}"
    with auth_client(username=owner_name) as owner:
        credential = owner.put(
            "/api/service-credentials/zhiyun",
            json={"account": "cancel-owner", "password": "cancel-owner-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(owner, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(owner, "receipt_flow_table", "到账流转表.xlsx")
        started = owner.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-20",
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        workflow_id = started.json()["id"]

    with auth_client(
        role="skill_admin",
        username=f"cancel-admin-{uuid.uuid4().hex[:8]}",
    ) as admin:
        denied = admin.post(f"/api/workflows/{workflow_id}/cancel")
        assert denied.status_code == 403, denied.text

    with SessionLocal() as db:
        workflow = db.get(WorkflowSession, workflow_id)
        assert workflow is not None
        assert workflow.state != "cancelled"
    _finish_all_ar_workflows()


def test_owner_can_cancel_after_skill_permission_is_revoked() -> None:
    _finish_all_ar_workflows()
    username = f"cancel-revoked-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "cancel-revoked", "password": "cancel-revoked-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-20",
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        workflow_id = started.json()["id"]

        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            permission = db.scalar(
                select(UserSkillPermission).where(
                    UserSkillPermission.user_id == user.id,
                    UserSkillPermission.skill_id == "ar-hexiao-daily",
                )
            )
            assert permission is not None
            permission.can_run = False
            db.commit()

        cancelled = client.post(f"/api/workflows/{workflow_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["state"] == "cancelled"
    _finish_all_ar_workflows()


def test_owner_can_cancel_by_message_after_skill_permission_is_revoked() -> None:
    _finish_all_ar_workflows()
    username = f"cancel-message-revoked-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "cancel-message", "password": "cancel-message-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-20",
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        workflow_id = started.json()["id"]

        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            permission = db.scalar(
                select(UserSkillPermission).where(
                    UserSkillPermission.user_id == user.id,
                    UserSkillPermission.skill_id == "ar-hexiao-daily",
                )
            )
            assert permission is not None
            permission.can_run = False
            db.commit()

        cancelled = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "取消任务"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["state"] == "cancelled"
    _finish_all_ar_workflows()


def test_failed_batch_retry_is_blocked_while_another_ar_task_is_active() -> None:
    username = f"retry-single-flight-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "retry-flight", "password": "retry-flight-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        files = {
            "profit_loss_ledgers": [ledger_id],
            "receipt_flow_table": [flow_id],
        }
        started_batch = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_dates": ["2026-08-19", "2026-08-20"],
                "files": files,
            },
        )
        assert started_batch.status_code == 200, started_batch.text
        batch_body = started_batch.json()
        failed_child_id = batch_body["workflows"][0]["id"]
        with SessionLocal() as db:
            batch = db.get(WorkflowBatch, batch_body["id"])
            failed_child = db.get(WorkflowSession, failed_child_id)
            assert batch is not None and failed_child is not None
            batch.state = "failed"
            failed_child.state = "failed"
            failed_child.stage = "failed"
            for action in failed_child.actions:
                action.state = "failed"
            db.commit()

        visible = client.get(f"/api/workflow-batches/{batch_body['id']}")
        assert visible.status_code == 200, visible.text
        assert visible.json()["retryable"] is True
        assert visible.json()["can_retry"] is True
        assert visible.json()["retry_block_reason"] == ""

        with SessionLocal() as db:
            owner = get_user_by_username(db, username)
            assert owner is not None
            permission = db.scalar(
                select(UserSkillPermission).where(
                    UserSkillPermission.user_id == owner.id,
                    UserSkillPermission.skill_id == "ar-hexiao-daily",
                )
            )
            assert permission is not None
            permission.can_run = False
            db.commit()

        blocked_details = client.get(f"/api/workflow-batches/{batch_body['id']}")
        assert blocked_details.status_code == 200, blocked_details.text
        assert blocked_details.json()["retryable"] is True
        assert blocked_details.json()["can_retry"] is False
        assert "没有使用该财务工具的权限" in blocked_details.json()["retry_block_reason"]

        with SessionLocal() as db:
            owner = get_user_by_username(db, username)
            assert owner is not None
            permission = db.scalar(
                select(UserSkillPermission).where(
                    UserSkillPermission.user_id == owner.id,
                    UserSkillPermission.skill_id == "ar-hexiao-daily",
                )
            )
            assert permission is not None
            permission.can_run = True
            db.commit()

        active = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-20",
                "files": files,
            },
        )
        assert active.status_code == 200, active.text
        blocked = client.post(f"/api/workflow-batches/{batch_body['id']}/retry")
        assert blocked.status_code == 409, blocked.text
        assert active.json()["display_id"] in blocked.json()["detail"]

        with SessionLocal() as db:
            active_workflow = db.get(WorkflowSession, active.json()["id"])
            assert active_workflow is not None
            active_workflow.state = "failed"
            active_workflow.stage = "failed"
            for action in active_workflow.actions:
                action.state = "cancelled"
            db.commit()

        retried = client.post(f"/api/workflow-batches/{batch_body['id']}/retry")
        assert retried.status_code == 200, retried.text
        assert retried.json()["state"] == "running"


def test_failed_batch_retry_discards_partial_fetch_snapshot_and_forces_refetch() -> None:
    username = f"retry-partial-fetch-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "retry-partial", "password": "retry-partial-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_dates": ["2026-08-17", "2026-08-18"],
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        batch_id = started.json()["id"]
        workflow_id = started.json()["workflows"][0]["id"]

        with SessionLocal() as db:
            batch = db.get(WorkflowBatch, batch_id)
            workflow = db.get(WorkflowSession, workflow_id)
            assert batch is not None and workflow is not None
            workspace_path = (
                workflow_service._workflow_storage_root(db, workflow)
                / "batch"
                / batch_id
                / "工作区"
            )
            export_dir = workspace_path / "01_智云导出"
            export_dir.mkdir(parents=True, exist_ok=True)
            (export_dir / "取数摘要_20260817.json").write_text("{}", encoding="utf-8")
            workspace = str(workspace_path.resolve())
            workflow.context_json = json.dumps(
                {
                    "started_from_form": True,
                    "batch_id": batch_id,
                    "workspace": workspace,
                    "fetched_data": {
                        "available": True,
                        "review_status": "confirmed",
                    },
                }
            )
            workflow.state = "failed"
            workflow.stage = "failed"
            for action in workflow.actions:
                action.state = "failed"
            batch.state = "failed"
            db.commit()

        retried = client.post(f"/api/workflow-batches/{batch_id}/retry")
        assert retried.status_code == 200, retried.text
        duplicate = client.post(f"/api/workflow-batches/{batch_id}/retry")
        assert duplicate.status_code == 409, duplicate.text

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            context = json.loads(workflow.context_json)
            assert context["workspace"] == workspace
            assert context["fetched_data"]["available"] is False
            assert context["fetched_data"]["review_status"] == "deleted"
            assert not export_dir.exists()
            queued = max(workflow.actions, key=lambda item: item.queued_at)
            queued_input = json.loads(queued.input_json)
            assert queued_input["resume_existing_workspace"] is True
            assert sum(action.state == "queued" for action in workflow.actions) == 1


def write_workbook(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    workbook.close()


def test_batch_fetched_data_is_reviewed_once_and_can_preview_each_date() -> None:
    _finish_all_ar_workflows()
    username = f"batch-preview-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        assert (
            client.put(
                "/api/service-credentials/zhiyun",
                json={"account": "batch-preview", "password": "batch-preview-password"},
            ).status_code
            == 200
        )
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_dates": ["2026-08-17", "2026-08-18"],
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        batch_id = started.json()["id"]

        with SessionLocal() as db:
            batch = db.get(WorkflowBatch, batch_id)
            assert batch is not None
            workflow = sorted(batch.workflows, key=lambda item: item.batch_sequence)[0]
            workspace = (
                workflow_service.workflow_root(workflow.owner_id, workflow.id)
                / "batch"
                / batch_id
                / "工作区"
            )
            export_dir = workspace / "01_智云导出"
            for selected_date, amount in (("2026-08-17", 100), ("2026-08-18", 200)):
                tag = selected_date.replace("-", "")
                write_workbook(
                    export_dir / f"回款记录_{tag}.xlsx",
                    ["核销日期", "到账金额"],
                    [[selected_date, amount]],
                )
                write_workbook(export_dir / f"订单交付_{tag}.xlsx", ["订单号"], [["SO-1"]])
                write_workbook(export_dir / f"核销明细_{tag}.xlsx", ["回款ID"], [["AR-1"]])
                write_workbook(export_dir / f"订单明细_{tag}.xlsx", ["订单号"], [["SO-1"]])
            workflow.context_json = json.dumps(
                {
                    "workspace": str(workspace.resolve()),
                    "fetched_data": {
                        "available": True,
                        "dates": ["2026-08-17", "2026-08-18"],
                        "review_status": "waiting",
                        "summary_by_date": {},
                        "supplement_history": [],
                    },
                }
            )
            workflow.stage = "awaiting_fetched_data_confirmation"
            workflow.state = "waiting_confirmation"
            for action in workflow.actions:
                action.state = "succeeded"
            db.commit()

        preview = client.get(
            f"/api/workflow-batches/{batch_id}/fetched-data",
            params={"reconciliation_date": "2026-08-18", "dataset": "payments"},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["reconciliation_date"] == "2026-08-18"
        assert preview.json()["rows"] == [["2026-08-18", 200]]

        confirmed = client.post(f"/api/workflow-batches/{batch_id}/fetched-data/confirm")
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["fetched_data_review_status"] == "confirmed"
        assert confirmed.json()["workflows"][0]["stage"] == "preparing"
    _finish_all_ar_workflows()


def test_batch_fetched_data_uses_retried_date_after_primary_snapshot_cleanup() -> None:
    """A batch retry must remain reviewable when failure cleanup removed the primary snapshot."""
    _finish_all_ar_workflows()
    username = f"batch-retry-preview-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        assert (
            client.put(
                "/api/service-credentials/zhiyun",
                json={"account": "batch-retry-preview", "password": "batch-retry-password"},
            ).status_code
            == 200
        )
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_dates": ["2026-08-18", "2026-08-19"],
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        batch_id = started.json()["id"]

        with SessionLocal() as db:
            batch = db.get(WorkflowBatch, batch_id)
            assert batch is not None
            first, retried = sorted(batch.workflows, key=lambda item: item.batch_sequence)
            workspace = (
                workflow_service.workflow_root(first.owner_id, first.id)
                / "batch"
                / batch_id
                / "工作区"
            )
            export_dir = workspace / "01_智云导出"
            selected_date = "2026-08-19"
            tag = selected_date.replace("-", "")
            for prefix, header, value in (
                ("回款记录", "到账金额", 100),
                ("订单交付", "订单号", "SO-1"),
                ("核销明细", "回款ID", "AR-1"),
                ("订单明细", "订单号", "SO-1"),
            ):
                write_workbook(export_dir / f"{prefix}_{tag}.xlsx", [header], [[value]])

            dates = ["2026-08-18", "2026-08-19"]
            first.context_json = json.dumps(
                {
                    "workspace": str(workspace.resolve()),
                    "fetched_data": {
                        "available": False,
                        "dates": dates,
                        "review_status": "deleted",
                    },
                }
            )
            retried.context_json = json.dumps(
                {
                    "workspace": str(workspace.resolve()),
                    "fetched_data": {
                        "available": True,
                        "dates": dates,
                        "review_status": "waiting",
                        "summary_by_date": {selected_date: {"回款记录笔数": 1}},
                        "supplement_history": [],
                    },
                }
            )
            first.state = "succeeded"
            first.stage = "completed"
            retried.state = "waiting_confirmation"
            retried.stage = "awaiting_fetched_data_confirmation"
            for workflow in (first, retried):
                for action in workflow.actions:
                    action.state = "succeeded"
            db.commit()

        preview = client.get(
            f"/api/workflow-batches/{batch_id}/fetched-data",
            params={"reconciliation_date": selected_date, "dataset": "payments"},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["reconciliation_date"] == selected_date

        confirmed = client.post(f"/api/workflow-batches/{batch_id}/fetched-data/confirm")
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["workflows"][1]["stage"] == "preparing"

    _finish_all_ar_workflows()


def test_fetched_data_preview_is_task_scoped_paginated_and_hides_technical_columns() -> None:
    """Only the task owner can page through the post-fetch business data."""
    with auth_client(username=f"fetched-preview-{uuid.uuid4().hex[:8]}") as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "preview-user", "password": "preview-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-12",
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        workflow_id = started.json()["id"]

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            workspace = (
                workflow_service.workflow_root(workflow.owner_id, workflow.id)
                / "actions"
                / "fetched-preview"
                / "工作区"
            )
            export_dir = workspace / "01_智云导出"
            tag = "20260812"
            write_workbook(
                export_dir / f"回款记录_{tag}.xlsx",
                ["回款ID", "核销日期", "到账金额", "rowid"],
                [["AR-1", "2026-08-12", 100, 1], ["AR-2", "2026-08-12", 200, 2]],
            )
            write_workbook(export_dir / f"订单交付_{tag}.xlsx", ["订单号"], [["SO-1"]])
            write_workbook(export_dir / f"核销明细_{tag}.xlsx", ["回款ID"], [["AR-1"]])
            write_workbook(export_dir / f"订单明细_{tag}.xlsx", ["订单号"], [["SO-1"]])
            (export_dir / f"取数摘要_{tag}.json").write_text(
                json.dumps({"回款记录笔数": 2, "回款类型分布": {"到账": 2}, "files": ["internal"]}),
                encoding="utf-8",
            )
            workflow.context_json = json.dumps(
                {
                    "workspace": str(workspace.resolve()),
                    "fetched_data": {"available": True, "reconciliation_date": "2026-08-12"},
                }
            )
            db.commit()

        first_page = client.get(
            f"/api/workflows/{workflow_id}/fetched-data",
            params={"dataset": "payments", "offset": 0, "limit": 1},
        )
        assert first_page.status_code == 200, first_page.text
        body = first_page.json()
        assert body["reconciliation_date"] == "2026-08-12"
        assert body["dataset"] == "payments"
        assert body["headers"] == ["回款ID", "核销日期", "到账金额"]
        assert body["rows"] == [["AR-1", "2026-08-12", 100]]
        assert body["total"] == 2
        assert body["summary"] == {"回款记录笔数": 2, "回款类型分布": {"到账": 2}}
        assert {item["key"] for item in body["datasets"]} == {
            "payments",
            "orders",
            "writeoffs",
            "order_details",
        }

        second_page = client.get(
            f"/api/workflows/{workflow_id}/fetched-data",
            params={"dataset": "payments", "offset": 1, "limit": 1},
        )
        assert second_page.status_code == 200, second_page.text
        assert second_page.json()["rows"] == [["AR-2", "2026-08-12", 200]]

        with auth_client(username=f"other-preview-user-{uuid.uuid4().hex[:8]}") as other_user:
            hidden = other_user.get(f"/api/workflows/{workflow_id}/fetched-data")
            assert hidden.status_code == 404


def test_fetched_data_preview_groups_complete_business_data_by_ar() -> None:
    """The review API pages by AR and keeps SO, writeoff, and SOD relationships together."""
    with auth_client(username=f"fetched-ar-groups-{uuid.uuid4().hex[:8]}") as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "group-user", "password": "group-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-12",
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        workflow_id = started.json()["id"]

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            workspace = (
                workflow_service.workflow_root(workflow.owner_id, workflow.id)
                / "actions"
                / "fetched-ar-groups"
                / "工作区"
            )
            export_dir = workspace / "01_智云导出"
            tag = "20260812"
            write_workbook(
                export_dir / f"回款记录_{tag}.xlsx",
                ["回款记录ID", "核销日期", "到账金额/本币", "开票客户", "rowid"],
                [
                    ["AR-1", "2026-08-12", 300, "客户甲", 1],
                    ["AR-2", "2026-08-12", 80, "客户乙", 2],
                ],
            )
            write_workbook(
                export_dir / f"订单交付_{tag}.xlsx",
                ["回款记录ID", "SO", "交付额/原币", "订单名称", "项目交付日期"],
                [
                    ["AR-1", "SO-1", 200, "订单一", "2026-07-01"],
                    ["AR-1", "SO-2", 100, "订单二", None],
                    ["AR-2", "SO-3", 80, "订单三", "2026-07-02"],
                ],
            )
            write_workbook(
                export_dir / f"核销明细_{tag}.xlsx",
                ["核销记录NUM", "回款记录NUM", "核销日期", "本次核销金额/本币", "SO"],
                [
                    ["HX-1", "AR-1", "2026-08-12", 120, "SO-1"],
                    ["HX-2", "AR-1", "2026-08-12", 80, "SO-1"],
                    ["HX-3", "AR-1", "2026-08-12", 100, "SO-2"],
                    ["HX-4", "AR-2", "2026-08-12", 80, "SO-3"],
                ],
            )
            write_workbook(
                export_dir / f"订单明细_{tag}.xlsx",
                ["SO", "SOD", "交付额/原币", "币种", "项目状态"],
                [
                    ["SO-1", "SOD-1", 120, "CNY", "已交付"],
                    ["SO-1", "SOD-2", 80, "CNY", "已交付"],
                    ["SO-3", "SOD-3", 80, "CNY", "已交付"],
                ],
            )
            workflow.context_json = json.dumps(
                {
                    "workspace": str(workspace.resolve()),
                    "fetched_data": {"available": True, "reconciliation_date": "2026-08-12"},
                }
            )
            db.commit()

        first_page = client.get(
            f"/api/workflows/{workflow_id}/fetched-data",
            params={"dataset": "ar_groups", "offset": 0, "limit": 1},
        )
        assert first_page.status_code == 200, first_page.text
        body = first_page.json()
        assert body["dataset"] == "ar_groups"
        assert body["dataset_label"] == "按 AR 分组"
        assert body["total"] == 2
        assert body["headers"] == []
        assert body["rows"] == []
        assert len(body["ar_groups"]) == 1
        group = body["ar_groups"][0]
        assert group["ar_id"] == "AR-1"
        assert group["payments"][0]["ar_id"] == "AR-1"
        assert group["payments"][0]["reconciliation_date"] == "2026-08-12"
        assert group["payments"][0]["amount_local"] == 300
        assert group["payments"][0]["customer"] == "客户甲"
        assert [order["so_id"] for order in group["orders"]] == ["SO-1", "SO-2"]
        assert len(group["orders"][0]["writeoffs"]) == 2
        assert [item["sod_id"] for item in group["orders"][0]["order_details"]] == [
            "SOD-1",
            "SOD-2",
        ]
        assert group["orders"][1]["issues"] == ["缺少项目交付日期", "未找到 SOD"]
        assert group["issues"] == ["SO-2：缺少项目交付日期", "SO-2：未找到 SOD"]

        second_page = client.get(
            f"/api/workflows/{workflow_id}/fetched-data",
            params={"dataset": "ar_groups", "offset": 1, "limit": 1},
        )
        assert second_page.status_code == 200, second_page.text
        assert [group["ar_id"] for group in second_page.json()["ar_groups"]] == ["AR-2"]

        searched = client.get(
            f"/api/workflows/{workflow_id}/fetched-data",
            params={"dataset": "ar_groups", "query": "SOD-3"},
        )
        assert searched.status_code == 200, searched.text
        assert searched.json()["total"] == 1
        assert [group["ar_id"] for group in searched.json()["ar_groups"]] == ["AR-2"]

        amount_is_not_a_search_field = client.get(
            f"/api/workflows/{workflow_id}/fetched-data",
            params={"dataset": "ar_groups", "query": "300"},
        )
        assert amount_is_not_a_search_field.status_code == 200
        assert amount_is_not_a_search_field.json()["total"] == 0

        issues_only = client.get(
            f"/api/workflows/{workflow_id}/fetched-data",
            params={"dataset": "ar_groups", "issues_only": True},
        )
        assert issues_only.status_code == 200, issues_only.text
        assert issues_only.json()["total"] == 1
        assert [group["ar_id"] for group in issues_only.json()["ar_groups"]] == ["AR-1"]


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


def test_failed_workflow_action_discards_fetched_snapshot(monkeypatch) -> None:
    _finish_all_ar_workflows()

    def fail_after_fetch(db, action, workflow):
        workspace = (
            workflow_service.workflow_root(workflow.owner_id, workflow.id)
            / "actions"
            / action.id
            / "工作区"
        )
        export_dir = workspace / "01_智云导出"
        export_dir.mkdir(parents=True)
        (export_dir / "取数摘要_20260820.json").write_text("{}", encoding="utf-8")
        context = json.loads(workflow.context_json)
        context.update(
            {
                "workspace": str(workspace.resolve()),
                "fetched_data": {
                    "available": True,
                    "review_status": "waiting",
                    "reconciliation_date": "2026-08-20",
                },
            }
        )
        workflow.context_json = json.dumps(context)
        db.flush()
        raise RuntimeError("simulated failure after fetch")

    monkeypatch.setattr(workflow_service, "_prepare_worklist", fail_after_fetch)
    username = f"failed-fetch-cleanup-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        assert (
            client.put(
                "/api/service-credentials/zhiyun",
                json={"account": "failed-fetch", "password": "failed-fetch-password"},
            ).status_code
            == 200
        )
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-20",
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        workflow_id = started.json()["id"]

        execute_next_action(workflow_id)

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            assert workflow.state == "failed"
            context = json.loads(workflow.context_json)
            assert context["fetched_data"]["available"] is False
            assert context["fetched_data"]["review_status"] == "deleted"
            assert not (Path(context["workspace"]) / "01_智云导出").exists()
    _finish_all_ar_workflows()


def test_fetched_data_review_must_be_confirmed_before_analysis(monkeypatch) -> None:
    calls = 0

    def fake_prepare(_db, action, workflow) -> dict[str, object]:
        nonlocal calls
        calls += 1
        business = (
            workflow_service.workflow_root(workflow.owner_id, workflow.id)
            / "actions"
            / "review-gate"
            / "工作区"
        )
        business.mkdir(parents=True, exist_ok=True)
        if calls == 1:
            return {
                "workspace": str(business.resolve()),
                "fetched_data": {
                    "available": True,
                    "reconciliation_date": workflow.reconciliation_date,
                    "review_status": "waiting",
                },
                "awaiting_fetched_data_confirmation": True,
                "artifacts": [],
            }
        return {
            "workspace": str(business.resolve()),
            "checked_plan": str((business / "写入计划.json").resolve()),
            "summary": {"今天要填": 0, "异常": 0},
            "artifacts": [],
        }

    monkeypatch.setattr(workflow_service, "_prepare_worklist", fake_prepare)

    with auth_client(username=f"fetched-review-{uuid.uuid4().hex[:8]}") as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "review-user", "password": "review-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-12",
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        workflow_id = started.json()["id"]

        execute_next_action(workflow_id)
        waiting = client.get(f"/api/workflows/{workflow_id}")
        assert waiting.status_code == 200, waiting.text
        assert waiting.json()["stage"] == "awaiting_fetched_data_confirmation"
        assert waiting.json()["state"] == "waiting_confirmation"
        assert waiting.json()["current_step"] == "review_fetched_data"
        assert calls == 1

        confirmed = client.post(f"/api/workflows/{workflow_id}/fetched-data/confirm")
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["stage"] == "preparing"
        assert [item["name"] for item in confirmed.json()["actions"]] == [
            "prepare_worklist",
            "prepare_worklist",
        ]

        execute_next_action(workflow_id)
        ready = client.get(f"/api/workflows/{workflow_id}")
        assert ready.status_code == 200, ready.text
        assert ready.json()["stage"] == "applying"
        assert [item["name"] for item in ready.json()["actions"]] == [
            "prepare_worklist",
            "prepare_worklist",
            "apply_confirmed",
        ]
        assert calls == 2


def test_worker_can_request_audited_so_ar_supplement_and_returns_to_review(monkeypatch) -> None:
    def fake_prepare(_db, _action, workflow) -> dict[str, object]:
        business = (
            workflow_service.workflow_root(workflow.owner_id, workflow.id)
            / "actions"
            / "supplement-gate"
            / "工作区"
        )
        business.mkdir(parents=True, exist_ok=True)
        return {
            "workspace": str(business.resolve()),
            "fetched_data": {
                "available": True,
                "reconciliation_date": workflow.reconciliation_date,
                "review_status": "waiting",
                "summary": {"回款记录笔数": 2},
                "supplement_history": [],
            },
            "awaiting_fetched_data_confirmation": True,
            "artifacts": [],
        }

    def fake_supplement(_db, action, _workflow) -> dict[str, object]:
        payload = json.loads(action.input_json)["supplement"]
        assert payload == {
            "ar_ids": ["AR26070140"],
            "so_ids": ["SO26020320"],
        }
        return {
            "summary": {"回款记录笔数": 3},
            "supplement_result": {
                "ar_ids": ["AR26070140"],
                "so_ids": ["SO26020320"],
                "found_ar_ids": ["AR26070140"],
                "found_so_ids": ["SO26020320"],
                "unresolved_ar_ids": [],
                "unresolved_so_ids": [],
            },
        }

    monkeypatch.setattr(workflow_service, "_prepare_worklist", fake_prepare)
    monkeypatch.setattr(
        workflow_service,
        "_supplement_fetched_data",
        fake_supplement,
        raising=False,
    )

    with auth_client(username=f"fetched-supplement-{uuid.uuid4().hex[:8]}") as client:
        assert (
            client.put(
                "/api/service-credentials/zhiyun",
                json={"account": "supplement-user", "password": "supplement-password"},
            ).status_code
            == 200
        )
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        started = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-12",
                "files": {
                    "profit_loss_ledgers": [ledger_id],
                    "receipt_flow_table": [flow_id],
                },
            },
        )
        assert started.status_code == 200, started.text
        workflow_id = started.json()["id"]
        execute_next_action(workflow_id)

        invalid = client.post(
            f"/api/workflows/{workflow_id}/fetched-data/supplement",
            json={"ar_ids": ["26070140"], "so_ids": []},
        )
        assert invalid.status_code == 422

        requested = client.post(
            f"/api/workflows/{workflow_id}/fetched-data/supplement",
            json={
                "ar_ids": ["AR26070140"],
                "so_ids": ["so26020320", "SO26020320"],
            },
        )
        assert requested.status_code == 200, requested.text
        assert requested.json()["stage"] == "supplementing_fetched_data"
        assert requested.json()["state"] == "running"

        execute_next_action(workflow_id)
        waiting = client.get(f"/api/workflows/{workflow_id}")
        assert waiting.status_code == 200, waiting.text
        assert waiting.json()["stage"] == "awaiting_fetched_data_confirmation"
        assert waiting.json()["state"] == "waiting_confirmation"
        assert waiting.json()["fetched_data_summary"]["回款记录笔数"] == 3

        with SessionLocal() as db:
            event = db.scalar(
                select(AuditEvent)
                .where(
                    AuditEvent.resource_id == workflow_id,
                    AuditEvent.action == "workflow.fetched_data.supplement",
                )
                .order_by(AuditEvent.id.desc())
            )
            assert event is not None
            details = json.loads(event.details_json)
            assert details["ar_count"] == 1
            assert details["so_count"] == 1
            assert "AR26070140" not in event.details_json
            assert "SO26020320" not in event.details_json


def fake_prepare_worklist(_db, action, workflow) -> dict[str, object]:
    business = (
        workflow_service.workflow_root(workflow.owner_id, workflow.id)
        / "actions"
        / action.id
        / "工作区"
    )
    checked = business / "04_产出" / "写入计划_校验后.json"
    ledger = business / "02_我的表副本" / "盈亏表.xlsx"
    preview = business / "04_产出" / "核销日清_测试.xlsx"
    export_dir = business / "01_智云导出"
    checked.parent.mkdir(parents=True, exist_ok=True)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)
    checked.write_text('{"rows": 1}', encoding="utf-8")
    ledger.write_bytes(workbook_bytes())
    preview.write_bytes(workbook_bytes())
    (export_dir / "取数摘要_20260724.json").write_text("{}", encoding="utf-8")
    return {
        "workspace": str(business.resolve()),
        "checked_plan": str(checked.resolve()),
        "ledger": str(ledger.resolve()),
        "summary": {"今天要填": 1, "异常": 0},
        "artifacts": [
            {
                "file_id": f"preview-{action.id}",
                "name": preview.name,
                "sha256": workflow_service.sha256_file(preview),
                "size_bytes": preview.stat().st_size,
            }
        ],
    }


def approve_pending_workflow(workflow_id: str) -> dict[str, object]:
    with auth_client(role="skill_admin") as admin:
        listed = admin.get("/api/admin/approvals?status=pending")
        assert listed.status_code == 200, listed.text
        approval = next(item for item in listed.json() if item.get("workflow_id") == workflow_id)
        decided = admin.post(
            f"/api/admin/approvals/{approval['id']}/decision",
            json={"decision": "approve", "reason": "变更预览和执行快照复核通过。"},
        )
        assert decided.status_code == 200, decided.text
        assert decided.json()["status"] == "approved"
        return decided.json()


def test_apply_confirmed_verifies_before_write_and_refreshes_final_baseline(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workflow_id = str(uuid.uuid4())
    owner_id = "workflow-unit-user"
    workflow_root = tmp_path / owner_id / workflow_id
    workspace = workflow_root / "actions" / "prepare" / "工作区"
    checked = workspace / "04_产出" / "写入计划_校验后.json"
    worklist = workspace / "04_产出" / "核销日清_测试.xlsx"
    ledger = workspace / "02_我的表副本" / "盈亏核算表.xlsx"
    flow = workspace / "02_我的表副本" / "到账流转表.xlsx"
    checked.parent.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    checked.write_text(
        json.dumps(
            {
                "ledger_checks": {"2026": {"path": str(ledger)}},
                "flow_path": str(flow),
                "external_note": "unchanged",
            }
        ),
        encoding="utf-8",
    )
    worklist.write_bytes(workbook_bytes())
    ledger.write_bytes(workbook_bytes())
    flow.write_bytes(workbook_bytes())
    (workflow_root / "skill" / "vendor" / "scripts").mkdir(parents=True)

    calls: list[tuple[str, list[str]]] = []
    staged_plan: dict[str, object] = {}

    def fake_run_script(
        script_dir: Path,
        script_name: str,
        arguments: list[str],
        **_kwargs,
    ) -> str:
        calls.append((script_name, arguments))
        if script_name == "apply_all.py":
            staged_plan.update(
                json.loads(Path(arguments[arguments.index("--checked") + 1]).read_text("utf-8"))
            )
        return ""

    monkeypatch.setattr(
        workflow_service,
        "workflow_root",
        lambda selected_owner, selected_workflow: (
            tmp_path / selected_owner / selected_workflow
        ).resolve(),
    )
    monkeypatch.setattr(workflow_service, "_run_script", fake_run_script)
    monkeypatch.setattr(
        workflow_service,
        "_register_artifact",
        lambda _db, _workflow, path, _action_id: {"name": path.name},
    )
    action = SimpleNamespace(
        id="apply-action",
        input_json=json.dumps(
            {
                "context": {
                    "workspace": str(workspace),
                    "checked_plan": str(checked),
                    "ledger": str(ledger),
                    "flow_file": str(flow),
                }
            }
        ),
    )
    workflow = SimpleNamespace(id=workflow_id, owner_id=owner_id)

    result = workflow_service._apply_confirmed(
        SimpleNamespace(),
        action,
        workflow,
    )

    assert result["workspace"] == str(workspace.resolve())
    assert {item["name"] for item in result["artifacts"]} == {
        "盈亏核算表.xlsx",
        "到账流转表.xlsx",
    }
    assert [(name, args[0]) for name, args in calls] == [
        ("verify_sources.py", "verify"),
        ("verify_sources.py", "snapshot"),
        ("verify_sources.py", "verify"),
        ("apply_all.py", "--checked"),
        ("verify_sources.py", "snapshot"),
        ("verify_sources.py", "verify"),
    ]
    apply_args = next(args for name, args in calls if name == "apply_all.py")
    staging = workspace / "03_写入暂存区" / action.id
    assert apply_args[apply_args.index("--checked") + 1] == str(
        staging / "04_产出" / "写入计划_校验后.json"
    )
    assert apply_args[apply_args.index("--ledger") + 1] == str(
        staging / "02_我的表副本" / "盈亏核算表.xlsx"
    )
    assert apply_args[apply_args.index("--workspace") + 1] == str(staging)
    assert staged_plan["ledger_checks"] == {
        "2026": {"path": str(staging / "02_我的表副本" / "盈亏核算表.xlsx")}
    }
    assert staged_plan["flow_path"] == str(staging / "02_我的表副本" / "到账流转表.xlsx")
    assert staged_plan["external_note"] == "unchanged"


def test_apply_confirmed_discards_staging_when_write_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """写入脚本失败时，日清阶段工作副本必须保持完全不变。"""
    workflow_id = str(uuid.uuid4())
    owner_id = "workflow-staging-user"
    workflow_root = tmp_path / owner_id / workflow_id
    workspace = workflow_root / "actions" / "prepare" / "工作区"
    checked = workspace / "04_产出" / "写入计划_校验后.json"
    worklist = workspace / "04_产出" / "核销日清_测试.xlsx"
    ledger = workspace / "02_我的表副本" / "盈亏核算表.xlsx"
    flow = workspace / "02_我的表副本" / "到账流转表.xlsx"
    checked.parent.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    checked.write_text("{}", encoding="utf-8")
    worklist.write_bytes(workbook_bytes())
    original_ledger = workbook_bytes()
    ledger.write_bytes(original_ledger)
    flow.write_bytes(workbook_bytes())
    (workflow_root / "skill" / "vendor" / "scripts").mkdir(parents=True)

    def fake_run_script(_script_dir, script_name, arguments, **_kwargs):
        if script_name == "apply_all.py":
            staged_ledger = Path(arguments[arguments.index("--ledger") + 1])
            staged_ledger.write_bytes(b"mutated-in-staging")
            raise RuntimeError("simulated write failure")
        return ""

    monkeypatch.setattr(
        workflow_service,
        "workflow_root",
        lambda selected_owner, selected_workflow: (
            tmp_path / selected_owner / selected_workflow
        ).resolve(),
    )
    monkeypatch.setattr(workflow_service, "_run_script", fake_run_script)
    action = SimpleNamespace(
        id="apply-action",
        input_json=json.dumps(
            {
                "context": {
                    "workspace": str(workspace),
                    "checked_plan": str(checked),
                    "ledger": str(ledger),
                    "flow_file": str(flow),
                }
            }
        ),
    )
    workflow = SimpleNamespace(id=workflow_id, owner_id=owner_id)

    with pytest.raises(
        workflow_service.StagedWriteError,
        match="写入未发布，已丢弃暂存副本",
    ):
        workflow_service._apply_confirmed(SimpleNamespace(), action, workflow)

    assert ledger.read_bytes() == original_ledger
    staging_root = workspace / "03_写入暂存区"
    assert not staging_root.exists() or not any(staging_root.iterdir())


def test_annual_ledgers_have_no_count_limit_and_are_passed_explicitly(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workflow_id = str(uuid.uuid4())
    owner_id = "workflow-multi-year-user"
    workflow_root = tmp_path / owner_id / workflow_id
    workspace = workflow_root / "actions" / "prepare" / "工作区"
    checked = workspace / "04_产出" / "写入计划_校验后.json"
    worklist = workspace / "04_产出" / "核销日清_测试.xlsx"
    ledger_dir = workspace / "02_我的表副本"
    checked.parent.mkdir(parents=True)
    ledger_dir.mkdir(parents=True)
    checked.write_text("{}", encoding="utf-8")
    worklist.write_bytes(workbook_bytes())
    ledgers = {year: ledger_dir / f"{year}年盈亏核算表.xlsx" for year in (2024, 2025, 2026)}
    for ledger in ledgers.values():
        ledger.write_bytes(workbook_bytes())
    flow = ledger_dir / "到账流转表.xlsx"
    flow.write_bytes(workbook_bytes())
    (workflow_root / "skill" / "vendor" / "scripts").mkdir(parents=True)

    calls: list[tuple[str, list[str]]] = []

    def fake_run_script(_script_dir, script_name, arguments, **_kwargs):
        calls.append((script_name, arguments))
        return ""

    monkeypatch.setattr(
        workflow_service,
        "workflow_root",
        lambda selected_owner, selected_workflow: (
            tmp_path / selected_owner / selected_workflow
        ).resolve(),
    )
    monkeypatch.setattr(workflow_service, "_run_script", fake_run_script)
    monkeypatch.setattr(
        workflow_service,
        "_register_artifact",
        lambda _db, _workflow, path, _action_id: {"name": path.name},
    )
    context = {
        "workspace": str(workspace),
        "checked_plan": str(checked),
        "ledger_years": {str(year): str(path) for year, path in ledgers.items()},
        "flow_file": str(flow),
    }
    action = SimpleNamespace(id="apply-action", input_json=json.dumps({"context": context}))
    workflow = SimpleNamespace(id=workflow_id, owner_id=owner_id)

    workflow_service._apply_confirmed(SimpleNamespace(), action, workflow)

    apply_args = next(args for name, args in calls if name == "apply_all.py")
    specs = [
        apply_args[index + 1] for index, value in enumerate(apply_args) if value == "--ledger-year"
    ]
    staging = workspace / "03_写入暂存区" / action.id / "02_我的表副本"
    assert specs == [f"{year}={staging / ledgers[year].name}" for year in (2024, 2025, 2026)]
    assert "--ledger" not in apply_args


def test_duplicate_annual_ledger_year_is_rejected(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "02_我的表副本"
    ledger_dir.mkdir()
    for name in ("2026年盈亏核算表.xlsx", "2026年盈亏核算表_第二份.xlsx"):
        (ledger_dir / name).write_bytes(workbook_bytes())

    with pytest.raises(RuntimeError, match="每个年度只能上传一份"):
        workflow_service._discover_annual_ledger_paths(tmp_path)


def test_workflow_reuses_and_updates_the_two_material_roles(monkeypatch) -> None:
    class FakeModelsResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": [{"id": "qwen3.7-plus"}]}

    monkeypatch.setattr(model_service.httpx, "get", lambda *_, **__: FakeModelsResponse())
    monkeypatch.setattr(
        model_service.httpx,
        "post",
        lambda *_, **__: FakeVerificationResponse(),
    )
    username = f"material-reuse-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username) as client:
        connection = client.post(
            "/api/model-connections",
            json={"api_key": "sk-material-reuse-test"},
        )
        assert connection.status_code == 200, connection.text
        first = client.post(
            "/api/workflows",
            json={
                "skill_id": "ar-hexiao-daily",
                "model_connection_id": connection.json()["id"],
                "model": "qwen3.7-plus",
            },
        )
        assert first.status_code == 200, first.text
        first_id = first.json()["id"]
        assert first.json()["display_id"].startswith("ar-hexiao-daily_")
        ledger_2025 = upload(client, "profit_loss_ledgers", "2025年盈亏核算表.xlsx")
        flow = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        bound = client.put(
            f"/api/workflows/{first_id}/files",
            json={
                "files": {
                    "profit_loss_ledgers": [ledger_2025],
                    "receipt_flow_table": [flow],
                }
            },
        )
        assert bound.status_code == 200, bound.text

        reusable = client.get(
            "/api/workflows/reusable-files",
            params={"skill_id": "ar-hexiao-daily"},
        )
        assert reusable.status_code == 200, reusable.text
        assert reusable.json()["ready"] is True
        saved_ledger = reusable.json()["files"]["profit_loss_ledgers"][0]
        assert saved_ledger["file_id"] == ledger_2025
        assert saved_ledger["name"] == "2025年盈亏核算表.xlsx"
        assert saved_ledger["year"] == 2025
        assert saved_ledger["material_version"] == 1
        assert reusable.json()["files"]["receipt_flow_table"][0]["file_id"] == flow
        assert reusable.json()["files"]["receipt_flow_table"][0]["name"] == "到账流转表.xlsx"

        with SessionLocal() as db:
            first_workflow = db.get(WorkflowSession, first_id)
            assert first_workflow is not None
            first_workflow.state = "failed"
            first_workflow.stage = "failed"
            db.commit()

        second = client.post(
            "/api/workflows",
            json={
                "skill_id": "ar-hexiao-daily",
                "model_connection_id": connection.json()["id"],
                "model": "qwen3.7-plus",
            },
        )
        assert second.status_code == 200, second.text
        assert second.json()["files"]["profit_loss_ledgers"][0]["file_id"] == ledger_2025
        assert second.json()["files"]["receipt_flow_table"][0]["file_id"] == flow

        ledger_2026 = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        added = client.put(
            f"/api/workflows/{second.json()['id']}/files",
            json={"files": {"profit_loss_ledgers": [ledger_2026]}},
        )
        assert added.status_code == 200, added.text
        assert {item["file_id"] for item in added.json()["files"]["profit_loss_ledgers"]} == {
            ledger_2025,
            ledger_2026,
        }
        newer_ledger_2025 = upload(
            client,
            "profit_loss_ledgers",
            "2025年盈亏核算表_新版.xlsx",
        )
        duplicated_year = client.put(
            f"/api/workflows/{second.json()['id']}/files",
            json={"files": {"profit_loss_ledgers": [newer_ledger_2025]}},
        )
        assert duplicated_year.status_code == 200, duplicated_year.text
        reusable_after_replacement = client.get(
            "/api/workflows/reusable-files",
            params={"skill_id": "ar-hexiao-daily"},
        )
        assert reusable_after_replacement.status_code == 200, reusable_after_replacement.text
        assert {
            item["file_id"]
            for item in reusable_after_replacement.json()["files"]["profit_loss_ledgers"]
        } == {newer_ledger_2025, ledger_2026}
        replacement = upload(client, "receipt_flow_table", "到账流转表_新版.xlsx")
        replaced = client.put(
            f"/api/workflows/{second.json()['id']}/files",
            json={"files": {"receipt_flow_table": [replacement]}},
        )
        assert replaced.status_code == 200, replaced.text
        assert [item["file_id"] for item in replaced.json()["files"]["receipt_flow_table"]] == [
            replacement
        ]

        reduced = client.put(
            f"/api/workflows/{second.json()['id']}/files",
            json={
                "files": {"profit_loss_ledgers": [ledger_2025]},
                "replace_roles": ["profit_loss_ledgers"],
            },
        )
        assert reduced.status_code == 200, reduced.text
        assert [item["file_id"] for item in reduced.json()["files"]["profit_loss_ledgers"]] == [
            ledger_2025
        ]

        cleared = client.put(
            f"/api/workflows/{second.json()['id']}/files",
            json={"files": {}, "replace_roles": ["receipt_flow_table"]},
        )
        assert cleared.status_code == 200, cleared.text
        assert "receipt_flow_table" not in cleared.json()["files"]
        # Superseded material sets remain immutable and restorable, so files
        # referenced by their history cannot be deleted independently.
        assert client.delete(f"/api/files/{ledger_2026}").status_code == 409
        assert client.delete(f"/api/files/{replacement}").status_code == 409

        history = client.get(
            "/api/workflows/material-sets",
            params={"skill_id": "ar-hexiao-daily"},
        )
        assert history.status_code == 200, history.text
        versions = history.json()
        assert versions[0]["state"] == "current"
        assert all(item["sha256"] for version in versions for item in version["files"])
        historical = versions[-1]
        restored = client.post(
            f"/api/workflows/material-sets/{historical['id']}/restore",
            params={"skill_id": "ar-hexiao-daily"},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["state"] == "current"
        assert restored.json()["version"] == versions[0]["version"] + 1


def test_reusable_files_include_unbound_uploads_and_partial_materials() -> None:
    with auth_client(username=f"material-upload-{uuid.uuid4().hex[:8]}") as client:

        def upload_for_skill(role: str, name: str) -> str:
            response = client.post(
                "/api/files",
                data={"role": role, "skill_id": "ar-hexiao-daily"},
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

        ledger_id = upload_for_skill(
            "profit_loss_ledgers",
            "2026年盈亏核算表_待启动.xlsx",
        )
        partial = client.get(
            "/api/workflows/reusable-files",
            params={"skill_id": "ar-hexiao-daily"},
        )
        assert partial.status_code == 200, partial.text
        assert partial.json()["ready"] is False
        assert partial.json()["missing_roles"] == ["receipt_flow_table"]
        assert partial.json()["files"]["profit_loss_ledgers"][0]["file_id"] == ledger_id

        flow_id = upload_for_skill("receipt_flow_table", "到账流转表_待启动.xlsx")
        ready = client.get(
            "/api/workflows/reusable-files",
            params={"skill_id": "ar-hexiao-daily"},
        )
        assert ready.status_code == 200, ready.text
        assert ready.json()["ready"] is True
        assert ready.json()["missing_roles"] == []
        assert ready.json()["material_version"] is None
        assert ready.json()["files"]["receipt_flow_table"][0]["file_id"] == flow_id


def test_background_start_accepts_one_or_many_past_dates_without_model_connection() -> None:
    with auth_client(username=f"background-start-{uuid.uuid4().hex[:8]}") as client:
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "background-test-user", "password": "background-test-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "profit_loss_ledgers", "2026年盈亏核算表.xlsx")
        flow_id = upload(client, "receipt_flow_table", "到账流转表.xlsx")
        files = {
            "profit_loss_ledgers": [ledger_id],
            "receipt_flow_table": [flow_id],
        }

        single = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-12",
                "files": files,
            },
        )
        assert single.status_code == 200, single.text
        assert single.json()["model_provider"] == "platform"
        assert single.json()["model_name"] == "后台 Skill Worker"
        assert single.json()["stage"] == "preparing"
        context = client.get(f"/api/workflows/{single.json()['id']}/agent/context")
        assert context.status_code == 200, context.text
        assert context.json()["connection_id"] is None
        assert context.json()["model"] == ""
        _finish_all_ar_workflows()

        replacement_ledger_id = upload(
            client,
            "profit_loss_ledgers",
            "2025年盈亏核算表.xlsx",
        )
        replaced = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": "2026-08-13",
                "files": {
                    "profit_loss_ledgers": [replacement_ledger_id],
                    "receipt_flow_table": [flow_id],
                },
                "replace_roles": ["profit_loss_ledgers", "receipt_flow_table"],
            },
        )
        assert replaced.status_code == 200, replaced.text
        assert [item["file_id"] for item in replaced.json()["files"]["profit_loss_ledgers"]] == [
            replacement_ledger_id
        ]

        future = (date.today() + timedelta(days=1)).isoformat()
        rejected = client.post(
            "/api/workflows/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_date": future,
                "files": files,
            },
        )
        assert rejected.status_code == 422
        assert "不能晚于今天" in rejected.text
        _finish_all_ar_workflows()

        batch = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "reconciliation_dates": ["2026-08-11", "2026-08-12"],
                "files": files,
            },
        )
        assert batch.status_code == 200, batch.text
        assert batch.json()["reconciliation_dates"] == ["2026-08-11", "2026-08-12"]
        assert batch.json()["model_provider"] == "platform"


def test_unbound_upload_can_be_deleted() -> None:
    with auth_client() as owner:
        file_id = upload(owner, "finance_workbooks", "待删除.xlsx")
        with SessionLocal() as db:
            record = db.get(FileRecord, file_id)
            assert record is not None
            stored_path = Path(record.stored_path)
            assert stored_path.is_file()

        with auth_client(username="other-upload-user") as other:
            denied = other.delete(f"/api/files/{file_id}")
            assert denied.status_code == 404
        assert stored_path.is_file()

        deleted = owner.delete(f"/api/files/{file_id}")
        assert deleted.status_code == 204
        assert not stored_path.exists()
        with SessionLocal() as db:
            assert db.get(FileRecord, file_id) is None


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
    assert (
        workflow_orchestrator._fallback_decision(
            "awaiting_files",
            "为什么还不能开始？",
        ).action
        == "show_status"
    )
    assert (
        workflow_orchestrator._fallback_decision(
            "awaiting_apply_confirmation",
            "确认写入是什么意思？",
        ).action
        == "show_status"
    )
    assert (
        workflow_orchestrator._fallback_decision(
            "awaiting_date",
            "2026-07-24 是星期几？",
        ).action
        == "show_status"
    )
    assert (
        workflow_orchestrator._fallback_decision(
            "preparing",
            "停止按钮有什么作用？",
        ).action
        == "show_status"
    )


def test_prepare_worklist_stops_after_zhiyun_fetch_for_manual_review(monkeypatch) -> None:
    workflow_id = str(uuid.uuid4())
    action_id = str(uuid.uuid4())
    calls: list[tuple[str, list[str], str | None]] = []

    def fake_copy_inputs(_db, _action, _workflow, business):
        ledgers = business / "02_我的表副本"
        ledgers.mkdir(parents=True, exist_ok=True)
        (business / "04_产出").mkdir(parents=True, exist_ok=True)
        (ledgers / "测试盈亏表.xlsx").write_bytes(b"test")
        (ledgers / "测试到账流转表.xlsx").write_bytes(b"test")

    def fake_run_script(
        script_dir,
        script_name,
        arguments,
        timeout=900,
        stdin_data=None,
        sensitive_values=(),
        extra_env=None,
    ):
        del script_dir, timeout, sensitive_values, extra_env
        calls.append((script_name, arguments, stdin_data))
        return ""

    monkeypatch.setattr(workflow_service, "_copy_inputs", fake_copy_inputs)
    monkeypatch.setattr(workflow_service, "_run_script", fake_run_script)
    monkeypatch.setattr(
        workflow_service,
        "_register_artifact",
        lambda *_: {"name": "核销日清_20260724.xlsx", "file_id": "output-test"},
    )
    monkeypatch.setattr(
        workflow_service,
        "resolve_service_credential",
        lambda *_: ("test-account", "test-password"),
    )

    skill_scripts = (
        workflow_service.workflow_root("demo-user", workflow_id) / "skill" / "vendor" / "scripts"
    )
    skill_scripts.mkdir(parents=True)
    (skill_scripts / "classify_hexiao.py").write_text("", encoding="utf-8")
    (skill_scripts.parents[1] / "tool.yaml").write_text(
        """schema_version: 1
id: ar-hexiao-daily
name: 应收核销日清
version: 1.0.0
status: disabled
description: 合成测试
handler:
  adapter: workflow
runtime:
  network_access: true
  network_allowlist: [zhiyun.synthetic.example]
risk:
  level: write
  requires_approval: true
""",
        encoding="utf-8",
    )
    workflow = SimpleNamespace(
        id=workflow_id,
        owner_id="demo-user",
        department_id="finance",
        reconciliation_date="2026-07-24",
        progress=0,
        progress_message="",
        context_json="{}",
    )
    action = SimpleNamespace(id=action_id, input_json="{}")
    db = SimpleNamespace(
        commit=lambda: None,
        execute=lambda *_: None,
        refresh=lambda *_: None,
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
    )

    result = workflow_service._prepare_worklist(db, action, workflow)

    assert calls[0][0] == "fetch_secure.py"
    assert calls[0][1] == []
    payload = json.loads(calls[0][2] or "{}")
    assert payload["reconciliation_date"] == "2026-07-24"
    assert payload["account"] == "test-account"
    assert [item[0] for item in calls] == ["fetch_secure.py"]
    assert result["awaiting_fetched_data_confirmation"] is True
    assert result["fetched_data"]["review_status"] == "waiting"
    assert result["artifacts"] == []


def test_batch_prepare_fetches_date_range_once_into_shared_workspace(monkeypatch) -> None:
    workflow_id = str(uuid.uuid4())
    action_id = str(uuid.uuid4())
    batch_id = f"BAT-20260820-{uuid.uuid4().hex[:8].upper()}"
    calls: list[tuple[str, list[str], str | None]] = []

    def fake_copy_inputs(_db, _action, _workflow, business):
        ledgers = business / "02_我的表副本"
        ledgers.mkdir(parents=True, exist_ok=True)
        (business / "04_产出").mkdir(parents=True, exist_ok=True)
        (ledgers / "2026年测试盈亏表.xlsx").write_bytes(b"test")
        (ledgers / "测试到账流转表.xlsx").write_bytes(b"test")

    def fake_run_script(
        _script_dir,
        script_name,
        arguments,
        timeout=900,
        stdin_data=None,
        sensitive_values=(),
        extra_env=None,
    ):
        del timeout, sensitive_values, extra_env
        calls.append((script_name, arguments, stdin_data))
        return ""

    monkeypatch.setattr(workflow_service, "_copy_inputs", fake_copy_inputs)
    monkeypatch.setattr(workflow_service, "_run_script", fake_run_script)
    monkeypatch.setattr(
        workflow_service,
        "resolve_service_credential",
        lambda *_: ("test-account", "test-password"),
    )

    skill_scripts = (
        workflow_service.workflow_root("demo-user", workflow_id) / "skill" / "vendor" / "scripts"
    )
    skill_scripts.mkdir(parents=True)
    (skill_scripts / "classify_hexiao.py").write_text("", encoding="utf-8")
    (skill_scripts.parents[1] / "tool.yaml").write_text(
        """schema_version: 1
id: ar-hexiao-daily
name: 应收核销日清
version: 1.0.0
status: disabled
description: 合成测试
handler:
  adapter: workflow
runtime:
  network_access: true
  network_allowlist: [zhiyun.synthetic.example]
risk:
  level: write
  requires_approval: true
""",
        encoding="utf-8",
    )
    workflow = SimpleNamespace(
        id=workflow_id,
        owner_id="demo-user",
        department_id="finance",
        reconciliation_date="2026-08-17",
        batch_id=batch_id,
        batch_sequence=1,
        progress=0,
        progress_message="",
        context_json="{}",
    )
    batch = SimpleNamespace(
        id=batch_id,
        reconciliation_dates_json=json.dumps(["2026-08-17", "2026-08-18", "2026-08-19"]),
        workflows=[workflow],
    )
    action = SimpleNamespace(id=action_id, input_json="{}")
    db = SimpleNamespace(
        commit=lambda: None,
        execute=lambda *_: None,
        refresh=lambda *_: None,
        get=lambda model, identifier: (
            batch if model is WorkflowBatch and identifier == batch_id else None
        ),
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
    )

    result = workflow_service._prepare_worklist(db, action, workflow)

    assert [item[0] for item in calls] == ["fetch_secure.py"]
    payload = json.loads(calls[0][2] or "{}")
    assert payload["date_from"] == "2026-08-17"
    assert payload["date_to"] == "2026-08-19"
    assert "reconciliation_date" not in payload
    assert result["fetched_data"]["dates"] == [
        "2026-08-17",
        "2026-08-18",
        "2026-08-19",
    ]


def test_legacy_secure_fetch_retries_transient_script_failure(monkeypatch) -> None:
    calls = []
    sleeps = []

    def transient_then_success(*_args, **_kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError(
                "fetch_secure.py 执行失败（退出码 2）：502 Server Error: Bad Gateway"
            )
        return "ok"

    monkeypatch.setattr(workflow_service, "_run_script", transient_then_success)
    monkeypatch.setattr(workflow_service.time, "sleep", sleeps.append)

    result = workflow_service._run_secure_fetch_with_retry(
        Path("D:/synthetic-skill/scripts"),
        stdin_data="{}",
        sensitive_values=("redacted",),
        extra_env={},
        legacy_outer_retry=True,
    )

    assert result == "ok"
    assert len(calls) == 2
    assert sleeps == [1.0]


def test_secure_fetch_timeout_scales_with_date_range_and_respects_runtime_limit() -> None:
    assert workflow_service._secure_fetch_timeout_seconds(1, 1800) == 600
    assert workflow_service._secure_fetch_timeout_seconds(10, 1800) == 1200
    assert workflow_service._secure_fetch_timeout_seconds(31, 1800) == 1740
    assert workflow_service._secure_fetch_timeout_seconds(31, 900) == 840


def test_secure_fetch_forwards_calculated_timeout(monkeypatch) -> None:
    captured = {}

    def capture(*_args, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(workflow_service, "_run_script", capture)
    workflow_service._run_secure_fetch_with_retry(
        Path("D:/synthetic-skill/scripts"),
        stdin_data="{}",
        sensitive_values=(),
        extra_env={},
        legacy_outer_retry=False,
        timeout_seconds=1200,
    )

    assert captured["timeout"] == 1200


def test_batch_staging_promotion_rolls_back_partial_publish(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    staging = workspace / workflow_service.WRITE_STAGING_DIR / "action-1"
    first_target = workspace / "02_我的表副本" / "盈亏.xlsx"
    second_target = workspace / "03_台账" / "跑批台账.json"
    first_source = staging / first_target.relative_to(workspace)
    second_source = staging / second_target.relative_to(workspace)
    for path, content in (
        (first_target, b"old-ledger"),
        (second_target, b"old-state"),
        (first_source, b"new-ledger"),
        (second_source, b"new-state"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    original_replace = workflow_service.os.replace
    failed = False

    def fail_second_publish(source, target):
        nonlocal failed
        if Path(target) == second_target and not failed:
            failed = True
            raise OSError("simulated second-file interruption")
        return original_replace(source, target)

    monkeypatch.setattr(workflow_service.os, "replace", fail_second_publish)
    with pytest.raises(OSError, match="second-file interruption"):
        workflow_service._promote_batch_staging(workspace, staging)

    assert first_target.read_bytes() == b"old-ledger"
    assert second_target.read_bytes() == b"old-state"
    assert not (workspace / workflow_service.BATCH_PUBLISH_TRANSACTION_DIR).exists()


def test_batch_staging_promotion_publishes_verified_files(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    staging = workspace / workflow_service.WRITE_STAGING_DIR / "action-2"
    target = workspace / "04_产出" / "核销日清.xlsx"
    source = staging / target.relative_to(workspace)
    target.parent.mkdir(parents=True, exist_ok=True)
    source.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"old")
    source.write_bytes(b"new")

    workflow_service._promote_batch_staging(workspace, staging)

    assert target.read_bytes() == b"new"
    assert not (workspace / workflow_service.BATCH_PUBLISH_TRANSACTION_DIR).exists()


def test_secure_fetch_outer_retry_is_bounded_to_legacy_snapshots(monkeypatch) -> None:
    calls = []

    def always_transient(*_args, **_kwargs):
        calls.append(True)
        raise RuntimeError("fetch_secure.py 执行失败：HTTP 503")

    monkeypatch.setattr(workflow_service, "_run_script", always_transient)

    with pytest.raises(RuntimeError, match="HTTP 503"):
        workflow_service._run_secure_fetch_with_retry(
            Path("D:/synthetic-skill/scripts"),
            stdin_data="{}",
            sensitive_values=("redacted",),
            extra_env={},
            legacy_outer_retry=False,
        )

    assert len(calls) == 1


def test_batch_prepare_rebuilds_workspace_left_by_failed_input_copy(monkeypatch) -> None:
    workflow_id = str(uuid.uuid4())
    action_id = str(uuid.uuid4())
    batch_id = f"BAT-20260820-{uuid.uuid4().hex[:8].upper()}"
    root = workflow_service.workflow_root("demo-user", workflow_id)
    skill_scripts = root / "skill" / "vendor" / "scripts"
    skill_scripts.mkdir(parents=True)
    (skill_scripts / "classify_hexiao.py").write_text("", encoding="utf-8")
    (skill_scripts.parents[1] / "tool.yaml").write_text(
        """schema_version: 1
id: ar-hexiao-daily
name: 应收核销日清
version: 1.0.0
status: disabled
description: 合成测试
handler:
  adapter: workflow
runtime:
  network_access: true
  network_allowlist: [zhiyun.synthetic.example]
risk:
  level: write
  requires_approval: true
""",
        encoding="utf-8",
    )
    business = root / "batch" / batch_id / "工作区"
    business.mkdir(parents=True)
    stale = business / "partial-copy.tmp"
    stale.write_text("incomplete", encoding="utf-8")
    context = {
        "workspace": str(business.resolve()),
        "workspace_state": "copying_inputs",
        "fetched_data": {"available": False, "review_status": "fetching"},
    }
    copy_calls = []

    def fake_copy_inputs(_db, _action, _workflow, target):
        copy_calls.append(target)
        ledgers = target / "02_我的表副本"
        ledgers.mkdir(parents=True)
        (target / "04_产出").mkdir(parents=True)
        (ledgers / "2026年测试盈亏表.xlsx").write_bytes(b"test")
        (ledgers / "测试到账流转表.xlsx").write_bytes(b"test")
        return {}

    monkeypatch.setattr(workflow_service, "_copy_inputs", fake_copy_inputs)
    monkeypatch.setattr(workflow_service, "_run_script", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        workflow_service,
        "resolve_service_credential",
        lambda *_: ("test-account", "test-password"),
    )
    workflow = SimpleNamespace(
        id=workflow_id,
        owner_id="demo-user",
        department_id="finance",
        reconciliation_date="2026-08-17",
        batch_id=batch_id,
        batch_sequence=1,
        progress=0,
        progress_message="",
        context_json=json.dumps(context),
    )
    batch = SimpleNamespace(
        id=batch_id,
        reconciliation_dates_json=json.dumps(["2026-08-17", "2026-08-18"]),
        workflows=[workflow],
    )
    action = SimpleNamespace(
        id=action_id,
        input_json=json.dumps({"context": context, "resume_existing_workspace": True}),
    )
    db = SimpleNamespace(
        commit=lambda: None,
        execute=lambda *_: None,
        refresh=lambda *_: None,
        get=lambda model, identifier: (
            batch if model is WorkflowBatch and identifier == batch_id else None
        ),
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
    )

    result = workflow_service._prepare_worklist(db, action, workflow)

    assert result["awaiting_fetched_data_confirmation"] is True
    assert copy_calls == [business.resolve()]
    assert not stale.exists()
    assert json.loads(workflow.context_json)["workspace_state"] == "inputs_ready"


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

    def unavailable_model(url, **kwargs):
        payload = kwargs.get("json") or {}
        tools = payload.get("tools") or []
        if tools and tools[0].get("function", {}).get("name") == "tool_call_supported":
            return FakeVerificationResponse()
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(workflow_orchestrator.httpx, "post", unavailable_model)
    monkeypatch.setattr(
        workflow_service,
        "_prepare_worklist",
        fake_prepare_worklist,
    )
    monkeypatch.setattr(
        workflow_service,
        "_apply_confirmed",
        lambda db, action, workflow: {
            "workspace": json.loads(workflow.context_json)["workspace"],
            "artifacts": [],
        },
    )

    with auth_client() as client:
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
        assert created.json()["display_id"].startswith("ar-hexiao-daily_")
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

        ledger_id = upload(client, "finance_workbooks", "盈亏表.xlsx")
        flow_id = upload(client, "finance_workbooks", "到账流转表.xlsx")

        too_few = client.put(
            f"/api/workflows/{workflow_id}/files",
            json={"files": {"finance_workbooks": [ledger_id]}},
        )
        assert too_few.status_code == 200
        insufficient = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "上传好了"},
        )
        assert insufficient.json()["stage"] == "awaiting_files"
        assert insufficient.json()["actions"] == []
        assert "还缺" in insufficient.json()["messages"][-1]["content"]

        attached = client.put(
            f"/api/workflows/{workflow_id}/files",
            json={
                "files": {
                    "finance_workbooks": [ledger_id, flow_id],
                }
            },
        )
        assert attached.status_code == 200, attached.text
        still_bound = client.delete(f"/api/files/{ledger_id}")
        assert still_bound.status_code == 409
        assert "业务材料版本" in still_bound.text

        missing_credential = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "上传好了"},
        )
        assert missing_credential.json()["stage"] == "awaiting_files"
        assert missing_credential.json()["actions"] == []
        assert "还缺智云账号" in missing_credential.json()["messages"][-1]["content"]

        test_account = "test-zhiyun-user"
        test_password = "not-a-real-password"
        saved = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": test_account, "password": test_password},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["configured"] is True
        assert test_account not in saved.text
        assert test_password not in saved.text
        status = client.get("/api/service-credentials/zhiyun")
        assert status.status_code == 200
        assert status.json()["configured"] is True
        assert test_account not in status.text
        assert test_password not in status.text
        owner_id = client.get("/api/session").json()["user_id"]
        with SessionLocal() as db:
            stored = db.scalar(
                select(ServiceCredential).where(
                    ServiceCredential.service == "zhiyun",
                    ServiceCredential.owner_id == owner_id,
                )
            )
            assert stored is not None
            assert test_account not in stored.account_encrypted
            assert test_password not in stored.password_encrypted

        preparing = client.post(
            f"/api/workflows/{workflow_id}/messages",
            json={"content": "上传好了"},
        )
        assert preparing.json()["stage"] == "preparing"
        assert preparing.json()["actions"][0]["name"] == "prepare_worklist"
        with SessionLocal() as db:
            queued = db.scalar(
                select(WorkflowAction).where(
                    WorkflowAction.workflow_id == workflow_id,
                    WorkflowAction.state == "queued",
                )
            )
            assert queued is not None
            assert test_account not in queued.input_json
            assert test_password not in queued.input_json

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
        assert applying.status_code == 200, applying.text
        assert applying.json()["stage"] == "applying"
        assert applying.json()["state"] == "running"
        assert len(applying.json()["actions"]) == 2

        execute_next_action(workflow_id)
        completed = client.get(f"/api/workflows/{workflow_id}").json()
        assert completed["stage"] == "completed"
        assert completed["state"] == "succeeded"
        assert "到账流转表" in completed["messages"][-1]["content"]
        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            context = json.loads(workflow.context_json)
            workspace = Path(context["workspace"])
            assert not (workspace / "01_智云导出").exists()

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


def test_workflow_reset_clears_current_state_and_preserves_audit(monkeypatch) -> None:
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
    monkeypatch.setattr(
        model_service.httpx,
        "post",
        lambda *_, **__: FakeVerificationResponse(),
    )

    with auth_client() as client:
        connection = client.post(
            "/api/model-connections",
            json={"api_key": "sk-workflow-reset-test"},
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

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            workflow.state = "failed"
            workflow.stage = "failed"
            workflow.reconciliation_date = "2026-07-24"
            workflow.context_json = '{"workspace": "old"}'
            workflow.files_json = '{"finance_workbooks": [{"file_id": "old"}]}'
            workflow.artifacts_json = '[{"file_id": "output-old"}]'
            workflow.progress = 77
            workflow.progress_message = "旧任务失败"
            workflow.error_message = "旧错误"
            db.add(
                WorkflowAction(
                    id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    name="prepare_worklist",
                    state="failed",
                    error_message="旧动作失败",
                )
            )
            db.commit()

        competing = client.post(
            "/api/workflows",
            json={
                "skill_id": "ar-hexiao-daily",
                "model_connection_id": connection.json()["id"],
                "model": "qwen3.7-plus",
            },
        )
        assert competing.status_code == 200, competing.text
        blocked_by_competing = client.post(f"/api/workflows/{workflow_id}/reset")
        assert blocked_by_competing.status_code == 409, blocked_by_competing.text
        assert competing.json()["display_id"] in blocked_by_competing.json()["detail"]
        with SessionLocal() as db:
            competing_workflow = db.get(WorkflowSession, competing.json()["id"])
            assert competing_workflow is not None
            competing_workflow.state = "failed"
            competing_workflow.stage = "failed"
            db.commit()

        files_blocked = client.put(
            f"/api/workflows/{workflow_id}/files",
            json={"files": {}, "replace_roles": ["receipt_flow_table"]},
        )
        assert files_blocked.status_code == 409
        assert "当前阶段不能更换输入文件" in files_blocked.text

        reset = client.post(f"/api/workflows/{workflow_id}/reset")
        assert reset.status_code == 200, reset.text
        body = reset.json()
        assert body["id"] == workflow_id
        assert body["state"] == "active"
        assert body["stage"] == "awaiting_date"
        assert body["reconciliation_date"] == ""
        assert body["files"] == {}
        assert body["artifacts"] == []
        assert body["progress"] == 0
        assert body["error_message"] == ""
        assert len(body["actions"]) == 1
        assert body["actions"][0]["state"] == "failed"
        assert body["messages"][-1]["data"]["kind"] == "workflow_reset"
        assert "已经完成的写入不会撤销" in body["messages"][-1]["content"]

        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            db.add(
                WorkflowAction(
                    id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    name="prepare_worklist",
                    state="queued",
                )
            )
            workflow.stage = "preparing"
            workflow.state = "running"
            db.commit()

        blocked = client.post(f"/api/workflows/{workflow_id}/reset")
        assert blocked.status_code == 409
        assert "正在执行" in blocked.text

        # 这个测试故意留下运行中的动作来验证 reset 的保护条件；
        # 断言完成后清理它，避免后续审批测试把它误认为待领取动作。
        with SessionLocal() as db:
            workflow = db.get(WorkflowSession, workflow_id)
            assert workflow is not None
            for action in db.scalars(
                select(WorkflowAction).where(
                    WorkflowAction.workflow_id == workflow_id,
                    WorkflowAction.state == "queued",
                )
            ).all():
                action.state = "cancelled"
            workflow.state = "failed"
            workflow.stage = "failed"
            db.commit()


def test_multi_date_batch_runs_children_in_order_and_chains_files(monkeypatch) -> None:
    class FakeModelsResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": [{"id": "qwen3.7-plus"}]}

    monkeypatch.setattr(model_service.httpx, "get", lambda *_, **__: FakeModelsResponse())
    monkeypatch.setattr(
        model_service.httpx,
        "post",
        lambda *_, **__: FakeVerificationResponse(),
    )
    monkeypatch.setattr(
        workflow_service,
        "_prepare_worklist",
        fake_prepare_worklist,
    )

    def fake_apply(_db, _action, workflow):
        return {
            "workspace": f"isolated-{workflow.id}",
            "artifacts": [],
            "next_files": json.loads(workflow.files_json),
        }

    monkeypatch.setattr(workflow_service, "_apply_confirmed", fake_apply)
    monkeypatch.setattr(workflow_service, "_finalize_batch_reports", lambda *_: None)

    with auth_client() as client:
        connection = client.post(
            "/api/model-connections",
            json={"api_key": "sk-workflow-batch-test"},
        )
        assert connection.status_code == 200, connection.text
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "batch-test-user", "password": "batch-test-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "finance_workbooks", "盈亏表.xlsx")
        flow_id = upload(client, "finance_workbooks", "到账流转表.xlsx")

        started = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "model_connection_id": connection.json()["id"],
                "model": "qwen3.7-plus",
                "reconciliation_dates": ["2026-07-21", "2026-07-20"],
                "files": {"finance_workbooks": [ledger_id, flow_id]},
            },
        )
        assert started.status_code == 200, started.text
        batch = started.json()
        assert batch["id"].startswith("BAT-")
        assert batch["reconciliation_dates"] == ["2026-07-20", "2026-07-21"]
        assert [item["batch_sequence"] for item in batch["workflows"]] == [1, 2]
        first, second = batch["workflows"]
        assert first["stage"] == "preparing"
        assert second["stage"] == "queued"
        assert len(first["actions"]) == 1
        assert second["actions"] == []

        execute_next_action(first["id"])
        after_prepare = client.get(f"/api/workflows/{first['id']}").json()
        assert after_prepare["stage"] == "applying"
        assert [item["name"] for item in after_prepare["actions"]] == [
            "prepare_worklist",
            "apply_confirmed",
        ]
        assert client.get(f"/api/workflows/{second['id']}").json()["stage"] == "queued"

        execute_next_action(first["id"])
        first_complete = client.get(f"/api/workflows/{first['id']}").json()
        second_started = client.get(f"/api/workflows/{second['id']}").json()
        assert first_complete["state"] == "succeeded"
        assert second_started["stage"] == "preparing"
        assert ledger_id in {
            item["file_id"] for item in second_started["files"]["profit_loss_ledgers"]
        }

        execute_next_action(second["id"])
        second_prepare = client.get(f"/api/workflows/{second['id']}").json()
        assert second_prepare["stage"] == "applying"
        execute_next_action(second["id"])
        finalizing = client.get(f"/api/workflow-batches/{batch['id']}").json()
        assert finalizing["state"] == "finalizing"
        with SessionLocal() as db:
            stuck = db.get(WorkflowSession, second["id"])
            assert stuck is not None
            stuck.state = "succeeded"
            stuck.stage = "completed"
            db.commit()

        with SessionLocal() as db:
            claimed = workflow_service.claim_next_workflow_action(
                db,
                ("workflow",),
                "range-report-regression-worker",
            )
            assert claimed is not None
            assert claimed.name == "finalize_batch"
            workflow_service.execute_workflow_action(db, claimed)
            db.commit()
        completed = client.get(f"/api/workflow-batches/{batch['id']}").json()
        assert completed["state"] == "succeeded"
        assert completed["progress"] == 100
        assert all(item["state"] == "succeeded" for item in completed["workflows"])
        with SessionLocal() as db:
            stored = db.get(WorkflowBatch, batch["id"])
            assert stored is not None
            assert stored.state == "succeeded"


def test_multi_date_batch_skips_confirmed_empty_date_and_starts_next(monkeypatch) -> None:
    class FakeModelsResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": [{"id": "qwen3.7-plus"}]}

    monkeypatch.setattr(model_service.httpx, "get", lambda *_, **__: FakeModelsResponse())
    monkeypatch.setattr(
        model_service.httpx,
        "post",
        lambda *_, **__: FakeVerificationResponse(),
    )

    calls: list[tuple[int, str]] = []

    def fake_prepare(_db, action, workflow) -> dict[str, object]:
        calls.append((workflow.batch_sequence, workflow.reconciliation_date))
        if len(calls) == 1:
            business = (
                workflow_service.workflow_root(workflow.owner_id, workflow.id)
                / "actions"
                / action.id
                / "工作区"
            )
            business.mkdir(parents=True, exist_ok=True)
            return {
                "workspace": str(business.resolve()),
                "fetched_data": {
                    "available": True,
                    "reconciliation_date": workflow.reconciliation_date,
                    "dates": ["2026-07-20", "2026-07-21"],
                    "review_status": "waiting",
                    "summary_by_date": {
                        "2026-07-20": {
                            "回款记录笔数": 0,
                            "下单行数": 0,
                            "核销明细行数": 0,
                            "订单明细SOD行数": 0,
                        },
                        "2026-07-21": {
                            "回款记录笔数": 1,
                            "下单行数": 1,
                            "核销明细行数": 1,
                            "订单明细SOD行数": 1,
                        },
                    },
                    "supplement_history": [],
                },
                "awaiting_fetched_data_confirmation": True,
                "artifacts": [],
            }
        if workflow.batch_sequence == 1:
            raise AssertionError("确认空日后不应再次生成该日核销日清")
        return fake_prepare_worklist(_db, action, workflow)

    monkeypatch.setattr(workflow_service, "_prepare_worklist", fake_prepare)

    with auth_client() as client:
        connection = client.post(
            "/api/model-connections",
            json={"api_key": "sk-empty-date-batch-test"},
        )
        assert connection.status_code == 200, connection.text
        credential = client.put(
            "/api/service-credentials/zhiyun",
            json={"account": "empty-date-batch", "password": "empty-date-password"},
        )
        assert credential.status_code == 200, credential.text
        ledger_id = upload(client, "finance_workbooks", "盈亏表.xlsx")
        flow_id = upload(client, "finance_workbooks", "到账流转表.xlsx")

        started = client.post(
            "/api/workflow-batches/start",
            json={
                "skill_id": "ar-hexiao-daily",
                "model_connection_id": connection.json()["id"],
                "model": "qwen3.7-plus",
                "reconciliation_dates": ["2026-07-20", "2026-07-21"],
                "files": {"finance_workbooks": [ledger_id, flow_id]},
            },
        )
        assert started.status_code == 200, started.text
        batch_id = started.json()["id"]
        first, second = started.json()["workflows"]

        execute_next_action(first["id"])
        waiting = client.get(f"/api/workflow-batches/{batch_id}")
        assert waiting.status_code == 200, waiting.text
        assert waiting.json()["fetched_data_review_status"] == "waiting"

        confirmed = client.post(f"/api/workflow-batches/{batch_id}/fetched-data/confirm")
        assert confirmed.status_code == 200, confirmed.text
        body = confirmed.json()
        first_after_confirm = body["workflows"][0]
        second_after_confirm = body["workflows"][1]
        assert first_after_confirm["state"] == "succeeded"
        assert first_after_confirm["stage"] == "completed"
        assert first_after_confirm["current_step_label"] == "当天无核销记录，已确认并跳过"
        assert second_after_confirm["stage"] == "preparing"
        assert body["state"] == "running"

        execute_next_action(second["id"])
        second_ready = client.get(f"/api/workflows/{second['id']}")
        assert second_ready.status_code == 200, second_ready.text
        assert second_ready.json()["stage"] == "applying"
        assert calls == [(1, "2026-07-20"), (2, "2026-07-21")]

    _finish_all_ar_workflows()
