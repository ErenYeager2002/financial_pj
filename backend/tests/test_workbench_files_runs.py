from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

from helpers import auth_client

from app.audit_service import query_audit_events
from app.auth_service import get_user_by_username
from app.database import SessionLocal
from app.models import RunRecord


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
        assert body["pending_runs"][0]["id"] == run_id
        assert body["pending_runs"][0]["can_retry"] is True
        assert all("handler" not in item["skill"] for item in body["common_skills"])

        page = client.get("/api/runs", params={"page": 1, "page_size": 1})
        assert page.status_code == 200, page.text
        page_body = page.json()
        assert page_body["total"] == 1
        assert page_body["pages"] == 1
        assert [item["id"] for item in page_body["items"]] == [run_id]


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
