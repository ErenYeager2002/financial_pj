from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from helpers import auth_client
from openpyxl import Workbook

from app import run_service
from app.approval_service import request_workflow_approval
from app.auth import UserContext
from app.database import SessionLocal
from app.models import ApprovalRecord, WorkflowAction, WorkflowSession
from app.registry import SkillManifest, registry
from app.resource_policy import workflow_root
from app.schemas import RunCreate
from app.storage import sha256_file
from app.workflow_service import _snapshot_skill, claim_next_workflow_action


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    workbook.active.append(["测试列"])
    workbook.active.append(["合成数据"])
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _upload(client: TestClient, name: str) -> dict[str, object]:
    response = client.post(
        "/api/files",
        data={"role": "finance_workbooks"},
        files={
            "upload": (
                name,
                _workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _ready_workflow(client: TestClient) -> tuple[str, Path]:
    session = client.get("/api/session").json()
    skill = registry.get("ar-hexiao-daily", include_unpublished=True)
    assert skill is not None
    workflow_id = str(uuid.uuid4())
    _snapshot_skill(skill, session["user_id"], workflow_id)
    first = _upload(client, "盈亏表.xlsx")
    second = _upload(client, "到账流转表.xlsx")
    business = workflow_root(session["user_id"], workflow_id) / "actions" / "prepare" / "工作区"
    checked = business / "04_产出" / "写入计划_校验后.json"
    ledger = business / "02_我的表副本" / "盈亏表.xlsx"
    preview = business / "04_产出" / "核销日清_测试.xlsx"
    checked.parent.mkdir(parents=True)
    ledger.parent.mkdir(parents=True)
    checked.write_text('{"rows": 1}', encoding="utf-8")
    ledger.write_bytes(_workbook_bytes())
    preview.write_bytes(_workbook_bytes())
    files = {
        "finance_workbooks": [
            {
                "file_id": item["id"],
                "name": item["name"],
                "size_bytes": item["size_bytes"],
                "sha256": item["sha256"],
            }
            for item in (first, second)
        ]
    }
    context = {
        "workspace": str(business.resolve()),
        "checked_plan": str(checked.resolve()),
        "ledger": str(ledger.resolve()),
        "summary": {"今天要填": 1, "异常": 0},
        "artifacts": [
            {
                "file_id": f"preview-{workflow_id}",
                "name": preview.name,
                "size_bytes": preview.stat().st_size,
                "sha256": sha256_file(preview),
            }
        ],
    }
    with SessionLocal() as db:
        db.add(
            WorkflowSession(
                id=workflow_id,
                owner_id=session["user_id"],
                owner_name=session["display_name"],
                department_id=session["department_id"],
                skill_id=skill.manifest.id,
                skill_name=skill.manifest.name,
                skill_version=skill.manifest.version,
                skill_hash=skill.skill_hash,
                skill_commit=skill.commit_sha,
                concurrency_limit=skill.manifest.runtime.concurrency_limit,
                model_connection_id="approval-test",
                model_provider="test",
                model_name="test",
                state="waiting_confirmation",
                stage="awaiting_apply_confirmation",
                reconciliation_date="2026-07-24",
                context_json=json.dumps(context, ensure_ascii=False),
                files_json=json.dumps(files, ensure_ascii=False),
                artifacts_json="[]",
            )
        )
        db.commit()
    return workflow_id, checked


def _request(workflow_id: str, actor: UserContext) -> ApprovalRecord:
    with SessionLocal() as db:
        workflow = db.get(WorkflowSession, workflow_id)
        assert workflow is not None
        created = request_workflow_approval(db, workflow, actor)
        db.commit()
        record = db.get(ApprovalRecord, created.id)
        assert record is not None
        db.expunge(record)
        return record


def test_employee_cannot_read_or_decide_approvals() -> None:
    with auth_client() as employee:
        assert employee.get("/api/admin/approvals").status_code == 403
        assert (
            employee.post(
                f"/api/admin/approvals/{uuid.uuid4()}/decision",
                json={"decision": "approve", "reason": "不应允许员工审批。"},
            ).status_code
            == 403
        )


def test_standard_write_run_is_rejected_before_queueing(monkeypatch) -> None:
    manifest = SkillManifest.model_validate(
        {
            "schema_version": 1,
            "id": "synthetic-write",
            "name": "合成写入任务",
            "version": "1.0.0",
            "status": "published",
            "description": "只用于验证标准写入任务默认拒绝。",
            "handler": {"adapter": "python", "entrypoint": "entry.py"},
            "risk": {"level": "write", "requires_approval": True},
        }
    )
    monkeypatch.setattr(
        run_service.registry,
        "get",
        lambda _skill_id: SimpleNamespace(manifest=manifest),
    )
    actor = UserContext(
        user_id="write-test-admin",
        display_name="写入测试管理员",
        role="skill_admin",
        department_id="finance",
    )
    with SessionLocal() as db, pytest.raises(HTTPException) as caught:
        run_service.create_run(
            db,
            RunCreate(skill_id=manifest.id, message="执行合成写入任务"),
            actor,
        )
    assert caught.value.status_code == 409
    assert "不能直接创建" in caught.value.detail


def test_requester_cannot_approve_own_write() -> None:
    with auth_client(role="skill_admin") as admin:
        session = admin.get("/api/session").json()
        workflow_id, _ = _ready_workflow(admin)
        approval = _request(
            workflow_id,
            UserContext(
                user_id=session["user_id"],
                display_name=session["display_name"],
                role="skill_admin",
                department_id=session["department_id"],
            ),
        )
        denied = admin.post(
            f"/api/admin/approvals/{approval.id}/decision",
            json={"decision": "approve", "reason": "尝试自批，应被拒绝。"},
        )
        assert denied.status_code == 409
        assert "不能审批自己" in denied.json()["detail"]


def test_changed_snapshot_revokes_pending_approval() -> None:
    with auth_client(username="approval-owner") as owner:
        session = owner.get("/api/session").json()
        workflow_id, checked = _ready_workflow(owner)
        approval = _request(
            workflow_id,
            UserContext(
                user_id=session["user_id"],
                display_name=session["display_name"],
                role="finance_user",
                department_id=session["department_id"],
            ),
        )
        checked.write_text('{"rows": 2}', encoding="utf-8")

    with auth_client(role="skill_admin") as admin:
        denied = admin.post(
            f"/api/admin/approvals/{approval.id}/decision",
            json={"decision": "approve", "reason": "文件已经变化，不能批准。"},
        )
        assert denied.status_code == 409
        assert "快照已经变化" in denied.json()["detail"]
    with SessionLocal() as db:
        stored = db.get(ApprovalRecord, approval.id)
        assert stored is not None and stored.status == "revoked"


def test_missing_snapshot_revokes_pending_approval_and_resets_workflow() -> None:
    with auth_client(username="approval-missing-owner") as owner:
        session = owner.get("/api/session").json()
        workflow_id, checked = _ready_workflow(owner)
        approval = _request(
            workflow_id,
            UserContext(
                user_id=session["user_id"],
                display_name=session["display_name"],
                role="finance_user",
                department_id=session["department_id"],
            ),
        )
        checked.unlink()

    with auth_client(role="skill_admin") as admin:
        denied = admin.post(
            f"/api/admin/approvals/{approval.id}/decision",
            json={"decision": "approve", "reason": "缺少快照时不得批准。"},
        )
        assert denied.status_code == 409
        assert "原审批已失效" in denied.json()["detail"]
    with SessionLocal() as db:
        stored = db.get(ApprovalRecord, approval.id)
        workflow = db.get(WorkflowSession, workflow_id)
        assert stored is not None and stored.status == "revoked"
        assert workflow is not None and workflow.stage == "awaiting_apply_confirmation"


def test_expired_approval_cannot_be_decided() -> None:
    with auth_client(username="approval-expiry-owner") as owner:
        session = owner.get("/api/session").json()
        workflow_id, _ = _ready_workflow(owner)
        approval = _request(
            workflow_id,
            UserContext(
                user_id=session["user_id"],
                display_name=session["display_name"],
                role="finance_user",
                department_id=session["department_id"],
            ),
        )
    with SessionLocal() as db:
        stored = db.get(ApprovalRecord, approval.id)
        assert stored is not None
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    with auth_client(role="skill_admin") as admin:
        denied = admin.post(
            f"/api/admin/approvals/{approval.id}/decision",
            json={"decision": "approve", "reason": "过期审批不能执行。"},
        )
        assert denied.status_code == 409
        assert "已经过期" in denied.json()["detail"]
    with SessionLocal() as db:
        workflow = db.get(WorkflowSession, workflow_id)
        assert workflow is not None and workflow.stage == "awaiting_apply_confirmation"


def test_worker_rejects_write_action_without_approval() -> None:
    with auth_client(username="approval-gate-owner") as owner:
        workflow_id, _ = _ready_workflow(owner)
    action_id = str(uuid.uuid4())
    with SessionLocal() as db:
        workflow = db.get(WorkflowSession, workflow_id)
        assert workflow is not None
        db.add(
            WorkflowAction(
                id=action_id,
                workflow_id=workflow.id,
                name="apply_confirmed",
                state="queued",
                input_json=json.dumps(
                    {
                        "reconciliation_date": workflow.reconciliation_date,
                        "files": json.loads(workflow.files_json),
                        "context": json.loads(workflow.context_json),
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
        assert claim_next_workflow_action(db, ("workflow",), "approval-gate-test") is None
        action = db.get(WorkflowAction, action_id)
        workflow = db.get(WorkflowSession, workflow_id)
        assert action is not None and action.state == "failed"
        assert "有效的双人审批" in action.error_message
        assert workflow is not None and workflow.stage == "awaiting_apply_confirmation"
