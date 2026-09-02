from __future__ import annotations

import json
from io import BytesIO

from helpers import TEST_PASSWORD, auth_client
from sqlalchemy import select

from app.audit_service import record_audit
from app.auth import UserContext
from app.auth_service import get_user_by_username
from app.database import SessionLocal
from app.models import AuditEvent


def test_login_file_and_permission_events_are_admin_queryable() -> None:
    username = "audit-employee"
    with auth_client(username=username) as employee:
        failed = employee.post(
            "/api/auth/login",
            json={"username": username, "password": "wrong-password"},
        )
        assert failed.status_code == 401

        uploaded = employee.post(
            "/api/files",
            files={
                "upload": (
                    "audit.xlsx",
                    BytesIO(b"synthetic-audit"),
                    "application/octet-stream",
                )
            },
        )
        assert uploaded.status_code == 200
        file_id = uploaded.json()["id"]
        downloaded = employee.get(f"/api/files/{file_id}/download")
        assert downloaded.status_code == 200
        assert downloaded.content == b"synthetic-audit"
        assert employee.delete(f"/api/files/{file_id}").status_code == 204

        assert employee.get("/api/admin/audit-events").status_code == 403

    with auth_client(role="skill_admin") as admin:
        users = admin.get("/api/admin/users").json()
        target = next(item for item in users if item["username"] == username)
        replaced = admin.put(
            f"/api/admin/users/{target['id']}/skill-permissions",
            json={"permissions": []},
        )
        assert replaced.status_code == 200

        events = admin.get("/api/admin/audit-events", params={"limit": 500})
        assert events.status_code == 200
        rows = events.json()
        actions = {item["action"] for item in rows}
        assert {
            "auth.login",
            "file.upload",
            "file.download",
            "file.delete",
            "permission.replace",
        } <= actions
        assert any(item["action"] == "auth.login" and item["outcome"] == "failed" for item in rows)
        assert all(
            "password" not in json.dumps(item["details"], ensure_ascii=False).lower()
            for item in rows
        )
        upload_event = next(
            item
            for item in rows
            if item["action"] == "file.upload" and item["resource_id"] == file_id
        )
        assert "audit.xlsx" not in json.dumps(upload_event, ensure_ascii=False)
        assert upload_event["details"]["sha256"]
        download_event = next(
            item
            for item in rows
            if item["action"] == "file.download" and item["resource_id"] == file_id
        )
        assert "audit.xlsx" not in json.dumps(download_event, ensure_ascii=False)
        assert download_event["details"]["sha256"] == upload_event["details"]["sha256"]


def test_audit_cursor_stays_stable_when_reads_create_new_audit_events() -> None:
    username = "audit-cursor-admin"
    with auth_client(role="skill_admin", username=username) as admin:
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            actor = UserContext(
                user_id=user.id,
                display_name=user.display_name,
                role=user.role,
                department_id=user.department_id,
                username=user.username,
            )
            record_audit(db, actor=actor, action="cursor.first")
            record_audit(db, actor=actor, action="cursor.second")
            db.commit()

        first = admin.get("/api/admin/audit-events", params={"limit": 2})
        assert first.status_code == 200, first.text
        first_rows = first.json()
        assert len(first_rows) == 2

        cursor = first_rows[-1]["id"]
        second = admin.get(
            "/api/admin/audit-events",
            params={"limit": 2, "before_id": cursor},
        )
        assert second.status_code == 200, second.text
        second_rows = second.json()
        assert all(item["id"] < cursor for item in second_rows)
        assert {item["id"] for item in first_rows}.isdisjoint(item["id"] for item in second_rows)


def test_audit_details_redact_sensitive_keys() -> None:
    username = "audit-redaction-user"
    with auth_client(username=username):
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            actor = UserContext(
                user_id=user.id,
                display_name=user.display_name,
                role=user.role,
                department_id=user.department_id,
                username=user.username,
            )
            event = record_audit(
                db,
                actor=actor,
                action="test.redaction",
                details={
                    "password": TEST_PASSWORD,
                    "api_key": "secret-key",
                    "nested": {"file_content": "financial-content", "safe": "ok"},
                },
            )
            db.commit()
            payload = json.loads(event.details_json)
            assert payload["password"] == "[REDACTED]"
            assert payload["api_key"] == "[REDACTED]"
            assert payload["nested"]["file_content"] == "[REDACTED]"
            assert payload["nested"]["safe"] == "ok"


def test_admin_user_and_audit_reads_are_audited() -> None:
    username = "audited-admin-reader"
    with auth_client(role="skill_admin", username=username) as admin:
        assert admin.get("/api/admin/users").status_code == 200
        assert admin.get("/api/admin/audit-events", params={"limit": 20}).status_code == 200

    with SessionLocal() as db:
        user = get_user_by_username(db, username)
        assert user is not None
        actions = set(
            db.scalars(select(AuditEvent.action).where(AuditEvent.actor_id == user.id)).all()
        )
        assert {"admin.users.read", "admin.audit.read"} <= actions
