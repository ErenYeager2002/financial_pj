from __future__ import annotations

import json
import uuid

from app.auth_models import User, UserSkillPermission
from app.auth_service import create_user
from app.database import SessionLocal, init_db
from app.main import app
from app.models import AuditEvent, SkillDedicatedUser
from app.registry import registry
from fastapi.testclient import TestClient
from helpers import TEST_PASSWORD, auth_client


def _skill_id() -> str:
    registry.refresh()
    return registry.list(include_disabled=True)[0].manifest.id


def _create_user(
    *,
    role: str = "finance_user",
    status: str = "active",
    department_id: str = "finance",
) -> tuple[str, str]:
    username = f"skill-dedication-{uuid.uuid4().hex[:12]}"
    init_db()
    with SessionLocal() as db:
        user = create_user(
            db,
            username=username,
            password=TEST_PASSWORD,
            role=role,
            department_id=department_id,
            display_name=f"专属员工 {username[-4:]}",
        )
        user.status = status
        db.commit()
        return user.id, username


def test_employee_cannot_read_set_or_clear_skill_dedication() -> None:
    target_id, _ = _create_user()
    with auth_client(username="skill-dedication-ordinary-user") as employee:
        assert employee.get("/api/admin/skill-dedications").status_code == 403
        assert (
            employee.put(
                f"/api/admin/skill-dedications/{_skill_id()}",
                json={"user_id": target_id},
            ).status_code
            == 403
        )
        assert (
            employee.delete(f"/api/admin/skill-dedications/{_skill_id()}").status_code
            == 403
        )


def test_admin_can_add_replace_clear_and_repeat_dedication_idempotently() -> None:
    skill_id = _skill_id()
    first_id, _ = _create_user()
    second_id, _ = _create_user()

    with auth_client(role="skill_admin", username="skill-dedication-crud-admin") as admin:
        created = admin.put(
            f"/api/admin/skill-dedications/{skill_id}",
            json={"user_id": first_id},
        )
        assert created.status_code == 200, created.text
        assert created.json()["skill_id"] == skill_id
        assert created.json()["user_id"] == first_id
        assert created.json()["user_status"] == "active"

        repeated = admin.put(
            f"/api/admin/skill-dedications/{skill_id}",
            json={"user_id": first_id},
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["user_id"] == first_id

        listed = admin.get("/api/admin/skill-dedications")
        assert listed.status_code == 200, listed.text
        assert [item["skill_id"] for item in listed.json()].count(skill_id) == 1

        replaced = admin.put(
            f"/api/admin/skill-dedications/{skill_id}",
            json={"user_id": second_id},
        )
        assert replaced.status_code == 200, replaced.text
        assert replaced.json()["user_id"] == second_id

        cleared = admin.delete(f"/api/admin/skill-dedications/{skill_id}")
        assert cleared.status_code == 204
        assert all(
            item["skill_id"] != skill_id
            for item in admin.get("/api/admin/skill-dedications").json()
        )
        assert admin.delete(f"/api/admin/skill-dedications/{skill_id}").status_code == 204

    with SessionLocal() as db:
        assert (
            db.query(SkillDedicatedUser)
            .filter_by(department_id="finance", skill_id=skill_id)
            .count()
            == 0
        )
        actions = {
            item.action
            for item in db.query(AuditEvent)
            .filter(AuditEvent.action.like("admin.skill_dedication.%"))
            .all()
        }
        assert {
            "admin.skill_dedication.read",
            "admin.skill_dedication.set",
            "admin.skill_dedication.clear",
        } <= actions


def test_dedication_rejects_unknown_skill_and_cross_department_user() -> None:
    foreign_id, _ = _create_user(department_id="other-department")
    with auth_client(role="skill_admin", username="skill-dedication-scope-admin") as admin:
        assert (
            admin.put(
                "/api/admin/skill-dedications/not-a-registered-skill",
                json={"user_id": foreign_id},
            ).status_code
            == 404
        )
        assert (
            admin.put(
                f"/api/admin/skill-dedications/{_skill_id()}",
                json={"user_id": foreign_id},
            ).status_code
            == 404
        )
        assert (
            admin.delete("/api/admin/skill-dedications/not-a-registered-skill").status_code
            == 404
        )


def test_dedication_rejects_admin_and_disabled_targets() -> None:
    admin_target_id, _ = _create_user(role="skill_admin")
    disabled_id, _ = _create_user(status="disabled")
    with auth_client(role="skill_admin", username="skill-dedication-target-admin") as admin:
        for user_id in (admin_target_id, disabled_id):
            response = admin.put(
                f"/api/admin/skill-dedications/{_skill_id()}",
                json={"user_id": user_id},
            )
            assert response.status_code == 422, response.text


def test_disabled_existing_dedication_is_kept_and_reported() -> None:
    skill_id = _skill_id()
    target_id, _ = _create_user()
    with auth_client(role="skill_admin", username="skill-dedication-disabled-admin") as admin:
        assigned = admin.put(
            f"/api/admin/skill-dedications/{skill_id}",
            json={"user_id": target_id},
        )
        assert assigned.status_code == 200

        with SessionLocal() as db:
            target = db.get(User, target_id)
            assert target is not None
            target.status = "disabled"
            db.commit()

        listed = admin.get("/api/admin/skill-dedications")
        assert listed.status_code == 200
        item = next(row for row in listed.json() if row["skill_id"] == skill_id)
        assert item["user_id"] == target_id
        assert item["user_status"] == "disabled"

        rejected = admin.put(
            f"/api/admin/skill-dedications/{skill_id}",
            json={"user_id": target_id},
        )
        assert rejected.status_code == 422

        assert admin.delete(f"/api/admin/skill-dedications/{skill_id}").status_code == 204


def test_setting_dedication_does_not_change_skill_permissions_and_audit_is_minimal() -> None:
    skill_id = _skill_id()
    target_id, _ = _create_user()
    permission_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(
            UserSkillPermission(
                id=permission_id,
                user_id=target_id,
                skill_id=skill_id,
                can_run=False,
                can_upload=True,
                can_create_draft=False,
                requires_approval=True,
            )
        )
        db.commit()

    with auth_client(role="skill_admin", username="skill-dedication-audit-admin") as admin:
        response = admin.put(
            f"/api/admin/skill-dedications/{skill_id}",
            json={"user_id": target_id},
        )
        assert response.status_code == 200, response.text

    with SessionLocal() as db:
        permission = db.get(UserSkillPermission, permission_id)
        assert permission is not None
        assert permission.can_run is False
        assert permission.can_create_draft is False
        assert permission.requires_approval is True

        events = db.query(AuditEvent).filter_by(action="admin.skill_dedication.set").all()
        assert events
        details = json.loads(events[-1].details_json)
        assert set(details) <= {"skill_id", "old_user_id", "new_user_id"}
        assert details["skill_id"] == skill_id
        assert details["new_user_id"] == target_id
        assert "display_name" not in events[-1].details_json


def test_skill_catalog_contract_does_not_expose_dedication_to_employees() -> None:
    with auth_client(username="skill-dedication-catalog-user") as employee:
        for path in ("/api/skills", "/api/catalog/skills"):
            response = employee.get(path)
            assert response.status_code == 200
            assert all(
                "dedication" not in key and "dedicated" not in key
                for item in response.json()
                for key in item
            )


def test_dedication_route_is_available_through_test_client() -> None:
    assert isinstance(app, object)
    with TestClient(app) as client:
        assert client.get("/api/admin/skill-dedications").status_code == 401
