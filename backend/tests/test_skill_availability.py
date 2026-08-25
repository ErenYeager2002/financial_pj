from __future__ import annotations

import uuid

from helpers import auth_client

from app.database import SessionLocal
from app.models import RunRecord


def _set_availability(admin, skill_id: str, target_state: str):
    return admin.post(
        f"/api/admin/skills/{skill_id}/availability",
        json={"target_state": target_state, "reason": "发布测试"},
    )


def test_employee_cannot_change_skill_availability() -> None:
    with auth_client() as employee:
        response = _set_availability(employee, "compliance-spot-check", "draining")
    assert response.status_code == 403


def test_admin_can_list_availability_for_all_platform_skills() -> None:
    with auth_client(role="skill_admin") as admin:
        response = admin.get("/api/admin/skills/availability")
    assert response.status_code == 200, response.text
    items = response.json()
    assert items
    assert {item["skill_id"] for item in items} >= {
        "ar-hexiao-daily",
        "compliance-spot-check",
    }
    assert all("active_work_count" in item for item in items)


def test_employee_cannot_list_skill_availability() -> None:
    with auth_client() as employee:
        response = employee.get("/api/admin/skills/availability")
    assert response.status_code == 403


def test_draining_blocks_new_run_and_enabled_restores_entry() -> None:
    skill_id = "compliance-spot-check"
    with auth_client(role="skill_admin") as admin:
        draining = _set_availability(admin, skill_id, "draining")
        assert draining.status_code == 200, draining.text
        assert draining.json()["state"] == "draining"
    try:
        with auth_client() as employee:
            blocked = employee.post(
                "/api/runs",
                json={
                    "skill_id": skill_id,
                    "message": "开始检查",
                    "parameters": {},
                    "files": {},
                },
            )
        assert blocked.status_code == 409
        assert "暂停接收新任务" in blocked.json()["detail"]
    finally:
        with auth_client(role="skill_admin") as admin:
            enabled = _set_availability(admin, skill_id, "enabled")
            assert enabled.status_code == 200, enabled.text
            assert enabled.json()["state"] == "enabled"


def test_draining_cannot_become_disabled_while_active_work_exists() -> None:
    skill_id = "split-by-sales"
    run_id = str(uuid.uuid4())
    with auth_client(role="skill_admin") as admin:
        with SessionLocal() as db:
            db.add(
                RunRecord(
                    id=run_id,
                    owner_id="admin",
                    owner_name="管理员",
                    department_id="finance",
                    skill_id=skill_id,
                    skill_name="销售拆分",
                    skill_version="1.0.0",
                    skill_hash="a" * 64,
                    manifest_path="tool.yaml",
                    manifest_snapshot="{}",
                    adapter="python",
                    worker_pool="python",
                    state="queued",
                )
            )
            db.commit()
        draining = _set_availability(admin, skill_id, "draining")
        assert draining.status_code == 200, draining.text
        assert draining.json()["active_work_count"] == 1
        disabled = _set_availability(admin, skill_id, "disabled")
        assert disabled.status_code == 409
        assert "活动任务" in disabled.json()["detail"]
        with SessionLocal() as db:
            record = db.get(RunRecord, run_id)
            assert record is not None
            record.state = "succeeded"
            db.commit()
        disabled = _set_availability(admin, skill_id, "disabled")
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["state"] == "disabled"
        assert disabled.json()["active_work_count"] == 0
        enabled = _set_availability(admin, skill_id, "enabled")
        assert enabled.status_code == 200


def test_invalid_availability_transition_is_rejected() -> None:
    skill_id = "labor-invoice-check"
    with auth_client(role="skill_admin") as admin:
        direct = _set_availability(admin, skill_id, "disabled")
    assert direct.status_code == 409
    assert "draining" in direct.json()["detail"]


def test_draining_blocks_workflow_batch_and_draft_creation() -> None:
    workflow_skill = "ar-hexiao-daily"
    draft_skill = "compliance-spot-check"
    with auth_client(role="skill_admin") as admin:
        assert _set_availability(admin, workflow_skill, "draining").status_code == 200
        assert _set_availability(admin, draft_skill, "draining").status_code == 200
    try:
        with auth_client() as employee:
            workflow = employee.post(
                "/api/workflows",
                json={"skill_id": workflow_skill, "model_connection_id": "missing-model"},
            )
            direct = employee.post(
                "/api/workflows/start",
                json={
                    "skill_id": workflow_skill,
                    "reconciliation_date": "2026-08-20",
                },
            )
            batch = employee.post(
                "/api/workflow-batches/start",
                json={
                    "skill_id": workflow_skill,
                    "reconciliation_dates": ["2026-08-20"],
                },
            )
            draft = employee.post(
                "/api/assistant/prepare-from-recommendation",
                json={
                    "message": "开始检查",
                    "file_ids": [],
                    "recommendation": {
                        "skill_id": draft_skill,
                        "confidence": 0.9,
                        "candidates": [],
                        "parameters": {},
                        "file_roles": {},
                    },
                },
            )
        for response in (workflow, direct, batch, draft):
            assert response.status_code == 409, response.text
            assert "暂停接收新任务" in response.json()["detail"]
    finally:
        with auth_client(role="skill_admin") as admin:
            assert _set_availability(admin, workflow_skill, "enabled").status_code == 200
            assert _set_availability(admin, draft_skill, "enabled").status_code == 200
