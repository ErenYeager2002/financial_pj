from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

from helpers import auth_client

from app.audit_service import query_audit_events
from app.auth_service import get_user_by_username
from app.database import SessionLocal
from app.models import (
    FileRecord,
    RunEvent,
    RunRecord,
    WorkflowMaterialSet,
    WorkflowMaterialSetFile,
)


def _upload(client, name: str) -> str:
    response = client.post(
        "/api/files",
        files={"upload": (name, BytesIO(b"synthetic-xlsx"), "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_failed_run(client, username: str) -> tuple[str, str, str]:
    bank_file = _upload(client, "合成银行流水.xlsx")
    ledger_file = _upload(client, "合成财务总账.xlsx")
    created = client.post(
        "/api/runs",
        json={
            "skill_id": "reconcile-bank",
            "message": "第五阶段合成测试",
            "parameters": {"amount_tolerance": 1, "date_tolerance_days": 2},
            "files": {"bank_file": bank_file, "ledger_file": ledger_file},
        },
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["id"]
    with SessionLocal() as db:
        user = get_user_by_username(db, username)
        assert user is not None
        run = db.get(RunRecord, run_id)
        assert run is not None
        run.state = "failed"
        run.progress = 60
        run.progress_message = "读取文件失败"
        run.error_message = "合成测试错误：字段格式不符合要求。"
        run.finished_at = datetime.now(UTC)
        db.commit()
    return run_id, bank_file, ledger_file


def test_workbench_and_run_pagination_are_owner_scoped() -> None:
    username = "stage5-workbench-owner"
    with auth_client(username=username) as client:
        run_id, _, _ = _create_failed_run(client, username)
        workbench = client.get("/api/workbench")
        assert workbench.status_code == 200, workbench.text
        body = workbench.json()
        assert body["counts"]["failed"] == 1
        assert body["counts"]["files"] == 2
        assert body["task_reminders"] == {
            "pending_dates": 0,
            "active_skills": 0,
            "failed_checks": 0,
        }
        assert body["pending_runs"][0]["id"] == run_id
        assert body["pending_runs"][0]["can_retry"] is True
        assert all("handler" not in item["skill"] for item in body["common_skills"])

        page = client.get("/api/runs", params={"page": 1, "page_size": 1})
        assert page.status_code == 200, page.text
        page_body = page.json()
        assert page_body["total"] == 1
        assert page_body["pages"] == 1
        assert [item["id"] for item in page_body["items"]] == [run_id]


def test_run_event_history_is_owner_scoped_and_pageable() -> None:
    username = "event-history-owner"
    with auth_client(username=username) as client:
        run_id, _, _ = _create_failed_run(client, username)
        with SessionLocal() as db:
            db.add_all(
                [
                    RunEvent(
                        run_id=run_id,
                        event_type="progress",
                        state="running",
                        progress=10,
                        message="第一条",
                    ),
                    RunEvent(
                        run_id=run_id,
                        event_type="progress",
                        state="running",
                        progress=20,
                        message="第二条",
                    ),
                ]
            )
            db.commit()

        first = client.get(f"/api/runs/{run_id}/event-history", params={"offset": 0, "limit": 1})
        second = client.get(f"/api/runs/{run_id}/event-history", params={"offset": 1, "limit": 1})

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()[0]["message"] == "第二条"
        assert second.json()[0]["message"] == "第一条"


def test_file_detail_retention_and_reference_deletion_rule() -> None:
    username = "stage5-file-owner"
    with auth_client(username=username) as client:
        unused_id = _upload(client, "待删除文件.xlsx")
        detail = client.get(f"/api/files/{unused_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["expires_at"] is not None
        assert detail.json()["can_delete"] is True
        assert client.delete(f"/api/files/{unused_id}").status_code == 204

        run_id, bank_file, _ = _create_failed_run(client, username)
        referenced = client.get(f"/api/files/{bank_file}")
        assert referenced.status_code == 200, referenced.text
        referenced_body = referenced.json()
        assert referenced_body["can_delete"] is False
        assert referenced_body["referenced_run_ids"] == [run_id]
        denied = client.delete(f"/api/files/{bank_file}")
        assert denied.status_code == 409
        assert "审计和重试证据" in denied.json()["detail"]


def test_file_center_latest_view_hides_older_duplicate_outputs() -> None:
    username = "stage5-file-latest-owner"
    with auth_client(username=username) as client:
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            older = FileRecord(
                id="11000000-0000-4000-8000-000000000001",
                owner_id=user.id,
                department_id=user.department_id,
                kind="output",
                original_name="核销日清_20260820.xlsx",
                stored_path="D:/synthetic/older.xlsx",
                content_type="application/octet-stream",
                size_bytes=10,
                sha256="1" * 64,
                skill_id="ar-hexiao-daily",
                skill_name="应收核销日清",
                skill_version="1.0.0",
                workflow_id="21000000-0000-4000-8000-000000000001",
                created_at=datetime(2026, 8, 20, 1, 0, tzinfo=UTC),
            )
            latest = FileRecord(
                id="11000000-0000-4000-8000-000000000002",
                owner_id=user.id,
                department_id=user.department_id,
                kind="output",
                original_name="核销日清_20260820.xlsx",
                stored_path="D:/synthetic/latest.xlsx",
                content_type="application/octet-stream",
                size_bytes=20,
                sha256="2" * 64,
                skill_id="ar-hexiao-daily",
                skill_name="应收核销日清",
                skill_version="1.0.1",
                workflow_id="21000000-0000-4000-8000-000000000002",
                created_at=datetime(2026, 8, 20, 2, 0, tzinfo=UTC),
            )
            distinct = FileRecord(
                id="11000000-0000-4000-8000-000000000003",
                owner_id=user.id,
                department_id=user.department_id,
                kind="output",
                original_name="核销日清_20260819.xlsx",
                stored_path="D:/synthetic/distinct.xlsx",
                content_type="application/octet-stream",
                size_bytes=30,
                sha256="3" * 64,
                skill_id="ar-hexiao-daily",
                skill_name="应收核销日清",
                skill_version="1.0.1",
                workflow_id="21000000-0000-4000-8000-000000000003",
                created_at=datetime(2026, 8, 20, 3, 0, tzinfo=UTC),
            )
            old_input = FileRecord(
                id="11000000-0000-4000-8000-000000000004",
                owner_id=user.id,
                department_id=user.department_id,
                kind="input",
                original_name="2026年盈亏核算表_旧.xlsx",
                stored_path="D:/synthetic/old-input.xlsx",
                content_type="application/octet-stream",
                size_bytes=40,
                sha256="4" * 64,
                skill_id="ar-hexiao-daily",
                skill_name="应收核销日清",
                skill_version="1.0.0",
                created_at=datetime(2026, 8, 20, 1, 0, tzinfo=UTC),
            )
            current_input = FileRecord(
                id="11000000-0000-4000-8000-000000000005",
                owner_id=user.id,
                department_id=user.department_id,
                kind="input",
                original_name="2026年盈亏核算表_当前.xlsx",
                stored_path="D:/synthetic/current-input.xlsx",
                content_type="application/octet-stream",
                size_bytes=50,
                sha256="5" * 64,
                skill_id="ar-hexiao-daily",
                skill_name="应收核销日清",
                skill_version="1.0.1",
                created_at=datetime(2026, 8, 20, 2, 0, tzinfo=UTC),
            )
            material_set = WorkflowMaterialSet(
                id="31000000-0000-4000-8000-000000000001",
                owner_id=user.id,
                department_id=user.department_id,
                skill_id="ar-hexiao-daily",
                version=1,
                state="current",
                created_at=datetime(2026, 8, 20, 2, 0, tzinfo=UTC),
                published_at=datetime(2026, 8, 20, 2, 0, tzinfo=UTC),
            )
            material_file = WorkflowMaterialSetFile(
                id="41000000-0000-4000-8000-000000000001",
                material_set_id=material_set.id,
                role="profit_loss_ledgers",
                year=2026,
                file_id=current_input.id,
                sha256=current_input.sha256,
            )
            db.add_all(
                [older, latest, distinct, old_input, current_input, material_set, material_file]
            )
            db.commit()

        response = client.get("/api/files", params={"latest_only": "true", "page_size": 100})
        assert response.status_code == 200, response.text
        body = response.json()
        matching = [item for item in body["items"] if item["name"].startswith("核销日清_")]
        assert [item["id"] for item in matching] == [distinct.id, latest.id]
        assert older.id not in {item["id"] for item in body["items"]}
        assert current_input.id in {item["id"] for item in body["items"]}
        assert old_input.id not in {item["id"] for item in body["items"]}


def test_failed_read_only_run_retry_is_bounded_and_audited() -> None:
    username = "stage5-retry-owner"
    with auth_client(username=username) as client:
        source_id, _, _ = _create_failed_run(client, username)
        first = client.post(f"/api/runs/{source_id}/retry")
        assert first.status_code == 200, first.text
        first_body = first.json()
        assert first_body["id"] != source_id
        assert first_body["state"] == "waiting_confirmation"
        assert first_body["parameters"] == {
            "amount_tolerance": 1,
            "date_tolerance_days": 2,
        }

        duplicate = client.post(f"/api/runs/{source_id}/retry")
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["id"] == first_body["id"]

        denied = client.post(f"/api/runs/{first_body['id']}/retry")
        assert denied.status_code == 409
        assert "失败或超时" in denied.json()["detail"]

        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            events = query_audit_events(
                db,
                user,
                action="run.retry",
                actor_id=user.id,
                limit=20,
            )
            assert any(item.resource_id == first_body["id"] for item in events)
