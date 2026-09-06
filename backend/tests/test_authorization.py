from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import TEST_PASSWORD, auth_client

from app.auth_models import UserSkillPermission
from app.auth_service import create_user, get_user_by_username
from app.authorization import replace_user_permissions
from app.database import SessionLocal
from app.main import app
from app.models import AuditEvent, RunRecord
from app.skill_execution_experiences import SUPPORTING_SKILL_IDS


def _published_standard_skill(client: TestClient) -> dict[str, object]:
    skills = client.get("/api/skills").json()
    return next(
        item
        for item in skills
        if item.get("status", "published") == "published"
        and (
            item.get("execution_mode") != "guided_workflow"
            if "handler" not in item
            else item["handler"]["adapter"] != "workflow"
        )
    )


def test_employee_skill_dto_excludes_runtime_internals() -> None:
    forbidden = {
        "schema_version",
        "category",
        "output_schema",
        "handler",
        "runtime",
        "permissions",
        "skill_hash",
        "commit_sha",
        "source",
        "upstream",
        "blocked_reason",
        "safety_constraints",
    }
    with auth_client(username="employee-skill-dto") as employee:
        response = employee.get("/api/skills")
        assert response.status_code == 200
        skills = response.json()
        assert skills
        skills_by_id = {skill["id"]: skill for skill in skills}
        for skill in skills:
            assert forbidden.isdisjoint(skill)
            assert skill["version"]
            assert skill["status"] == "published"
            assert skill["categories"]
            assert skill["estimated_minutes"] >= 1
            assert skill["action_label"]
            assert isinstance(skill["risk"]["requires_confirmation"], bool)
        assert skills_by_id["ar-hexiao-daily"]["risk"]["requires_confirmation"] is True


def test_admin_skill_dto_keeps_runtime_internals() -> None:
    with auth_client(role="skill_admin") as admin:
        skill = _published_standard_skill(admin)
        assert skill["version"]
        assert skill["handler"]["adapter"]
        assert skill["runtime"]["timeout_seconds"]
        assert skill["skill_hash"]


def test_catalog_skill_dto_is_employee_safe_for_admin() -> None:
    forbidden = {
        "handler",
        "runtime",
        "permissions",
        "output_schema",
        "skill_hash",
        "commit_sha",
        "source",
        "safety_constraints",
    }
    with auth_client(role="skill_admin") as admin:
        response = admin.get("/api/catalog/skills")
        assert response.status_code == 200
        skills = response.json()
        assert skills
        assert all(forbidden.isdisjoint(skill) for skill in skills)
        detail = admin.get(f"/api/catalog/skills/{skills[0]['id']}")
        assert detail.status_code == 200
        assert forbidden.isdisjoint(detail.json())


def test_catalog_skill_summaries_are_lightweight_and_employee_safe() -> None:
    forbidden = {
        "file_inputs",
        "input_schema",
        "progress_stages",
        "result_presentation",
        "handler",
        "runtime",
        "permissions",
        "output_schema",
        "skill_hash",
        "commit_sha",
        "source",
        "safety_constraints",
    }
    with auth_client(role="skill_admin") as admin:
        response = admin.get("/api/catalog/skill-summaries")
        assert response.status_code == 200
        summaries = response.json()
        assert summaries
        assert all(forbidden.isdisjoint(summary) for summary in summaries)


def test_catalog_exposes_supporting_entries_without_making_them_runnable() -> None:
    with auth_client(username="supporting-catalog-user", grant_skills=False) as client:
        response = client.get("/api/catalog/skills")
        assert response.status_code == 200
        support = {item["id"]: item for item in response.json()}
        assert set(support) == set(SUPPORTING_SKILL_IDS)
        assert all(item["status"] == "disabled" for item in support.values())

        summary_response = client.get("/api/catalog/skill-summaries")
        assert summary_response.status_code == 200
        assert {item["id"] for item in summary_response.json()} == set(SUPPORTING_SKILL_IDS)

        for skill_id in SUPPORTING_SKILL_IDS:
            detail = client.get(f"/api/catalog/skills/{skill_id}")
            assert detail.status_code == 200
            denied = client.post(
                "/api/runs",
                json={
                    "skill_id": skill_id,
                    "message": "support surface only",
                    "parameters": {},
                    "files": {},
                },
            )
            assert denied.status_code == 404


def test_employee_has_no_skills_without_explicit_permission() -> None:
    with auth_client(username="default-deny-user", grant_skills=False) as client:
        admin_skill: dict[str, object]
        with auth_client(role="skill_admin") as admin:
            admin_skill = _published_standard_skill(admin)
        skill_id = str(admin_skill["id"])

        assert client.get("/api/skills").json() == []
        assert client.get(f"/api/skills/{skill_id}").status_code == 404
        denied = client.post(
            "/api/runs",
            json={
                "skill_id": skill_id,
                "message": "test",
                "parameters": {},
                "files": {},
            },
        )
        assert denied.status_code == 403


def test_admin_can_create_user_and_grant_one_skill() -> None:
    with auth_client(role="skill_admin") as admin:
        skill = _published_standard_skill(admin)
        skill_id = str(skill["id"])
        created = admin.post(
            "/api/admin/users",
            json={
                "username": "permission-employee",
                "display_name": "权限测试员工",
                "initial_password": "initial-pass-123",
                "role": "finance_user",
                "department_id": "finance",
            },
        )
        assert created.status_code == 201, created.text
        user = created.json()
        assert user["must_change_password"] is True
        assert user["permissions"] == []

        granted = admin.put(
            f"/api/admin/users/{user['id']}/skill-permissions",
            json={
                "permissions": [
                    {
                        "skill_id": skill_id,
                        "can_run": True,
                        "can_upload": True,
                        "can_create_draft": True,
                        "requires_approval": False,
                    }
                ]
            },
        )
        assert granted.status_code == 200, granted.text
        assert [item["skill_id"] for item in granted.json()] == [skill_id]

    with TestClient(app) as employee:
        logged = employee.post(
            "/api/auth/login",
            json={"username": "permission-employee", "password": "initial-pass-123"},
        )
        assert logged.status_code == 200
        changed = employee.post(
            "/api/auth/change-password",
            json={
                "current_password": "initial-pass-123",
                "new_password": "employee-pass-456",
            },
        )
        assert changed.status_code == 200
        visible = employee.get("/api/skills")
        assert visible.status_code == 200
        assert [item["id"] for item in visible.json()] == [skill_id]


def test_permission_revocation_immediately_hides_skill() -> None:
    username = "permission-revoked-user"
    with auth_client(username=username) as employee:
        skill = _published_standard_skill(employee)
        skill_id = str(skill["id"])
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            replace_user_permissions(db, user, [])
        assert employee.get("/api/skills").json() == []
        denied = employee.post(
            f"/api/skills/{skill_id}/interpret",
            json={"message": "test", "parameters": {}},
        )
        assert denied.status_code == 403


def test_permission_revocation_blocks_waiting_run_confirmation() -> None:
    username = "revoked-before-confirm-user"
    with auth_client(username=username) as employee:
        skill = _published_standard_skill(employee)
        skill_id = str(skill["id"])
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            run = RunRecord(
                id="permission-confirm-run",
                owner_id=user.id,
                owner_name=user.display_name,
                department_id=user.department_id,
                skill_id=skill_id,
                skill_name=str(skill["name"]),
                skill_version="test-version",
                skill_hash="test-hash",
                manifest_path="test/tool.yaml",
                manifest_snapshot="{}",
                adapter="python",
                worker_pool="python",
                state="waiting_confirmation",
                confirmation_required=True,
            )
            db.add(run)
            db.commit()
            replace_user_permissions(db, user, [])
        denied = employee.post("/api/runs/permission-confirm-run/confirm")
        assert denied.status_code == 403


def test_can_upload_is_enforced_when_binding_files() -> None:
    username = "no-upload-permission-user"
    with auth_client(username=username) as client:
        skill = _published_standard_skill(client)
        skill_id = str(skill["id"])
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            replace_user_permissions(
                db,
                user,
                [
                    {
                        "skill_id": skill_id,
                        "can_run": True,
                        "can_upload": False,
                        "can_create_draft": True,
                        "requires_approval": False,
                    }
                ],
            )
        response = client.post(
            "/api/runs",
            json={
                "skill_id": skill_id,
                "message": "test",
                "parameters": {},
                "files": {"input": "not-owned-file"},
            },
        )
        assert response.status_code == 403


def test_employee_cannot_manage_users_or_permissions() -> None:
    with auth_client(username="not-user-admin") as employee:
        assert employee.get("/api/admin/users").status_code == 403
        assert (
            employee.put(
                "/api/admin/users/someone/skill-permissions",
                json={"permissions": []},
            ).status_code
            == 403
        )


def test_disabling_user_revokes_existing_session() -> None:
    username = "disable-through-admin"
    with SessionLocal() as db:
        if not get_user_by_username(db, username):
            create_user(db, username=username, password=TEST_PASSWORD)
            db.commit()
        user = get_user_by_username(db, username)
        assert user is not None
        user_id = user.id

    employee = TestClient(app)
    with employee:
        assert (
            employee.post(
                "/api/auth/login",
                json={"username": username, "password": TEST_PASSWORD},
            ).status_code
            == 200
        )
        with auth_client(role="skill_admin") as admin:
            disabled = admin.patch(
                f"/api/admin/users/{user_id}",
                json={"status": "disabled"},
            )
            assert disabled.status_code == 200
        assert employee.get("/api/session").status_code == 401


def test_admin_password_reset_revokes_sessions_and_records_no_password() -> None:
    username = "admin-reset-password-user"
    old_password = "old-password-123"
    one_time_password = "one-time-password-456"
    employee = TestClient(app)
    with employee:
        with SessionLocal() as db:
            user = create_user(db, username=username, password=old_password)
            db.commit()
            user_id = user.id
        assert employee.post(
            "/api/auth/login",
            json={"username": username, "password": old_password},
        ).status_code == 200
        with auth_client(role="skill_admin") as admin:
            reset = admin.post(
                f"/api/admin/users/{user_id}/reset-password",
                json={"initial_password": one_time_password},
            )
            assert reset.status_code == 200, reset.text
            assert reset.json()["must_change_password"] is True
        assert employee.get("/api/session").status_code == 401

    with TestClient(app) as renewed:
        assert renewed.post(
            "/api/auth/login",
            json={"username": username, "password": old_password},
        ).status_code == 401
        logged = renewed.post(
            "/api/auth/login",
            json={"username": username, "password": one_time_password},
        )
        assert logged.status_code == 200
        assert logged.json()["must_change_password"] is True

    with SessionLocal() as db:
        audit = db.query(AuditEvent).filter_by(
            action="user.password_reset", resource_id=user_id
        ).order_by(AuditEvent.created_at.desc()).first()
        assert audit is not None
        assert audit.actor_id
        assert audit.details_json == "{}"
        assert one_time_password not in audit.details_json


def test_permission_rows_are_unique_per_user_and_skill() -> None:
    with auth_client(role="skill_admin") as admin:
        skill_id = str(_published_standard_skill(admin)["id"])
        users = admin.get("/api/admin/users").json()
        target = next(item for item in users if item["role"] == "finance_user")
        duplicated = admin.put(
            f"/api/admin/users/{target['id']}/skill-permissions",
            json={
                "permissions": [
                    {"skill_id": skill_id},
                    {"skill_id": skill_id},
                ]
            },
        )
        assert duplicated.status_code == 422
        with SessionLocal() as db:
            rows = db.query(UserSkillPermission).filter_by(user_id=target["id"], skill_id=skill_id)
            assert rows.count() <= 1


def test_department_admin_cannot_manage_other_department_users() -> None:
    with auth_client(
        role="skill_admin",
        username="department-a-admin",
        department_id="department-a",
    ) as department_admin:
        with SessionLocal() as db:
            other = get_user_by_username(db, "department-b-user")
            if not other:
                other = create_user(
                    db,
                    username="department-b-user",
                    password=TEST_PASSWORD,
                    department_id="department-b",
                )
                db.commit()
            other_id = other.id

        listed = department_admin.get("/api/admin/users")
        assert listed.status_code == 200
        assert all(item["department_id"] == "department-a" for item in listed.json())
        assert other_id not in {item["id"] for item in listed.json()}
        assert (
            department_admin.patch(
                f"/api/admin/users/{other_id}",
                json={"status": "disabled"},
            ).status_code
            == 404
        )
        assert (
            department_admin.put(
                f"/api/admin/users/{other_id}/skill-permissions",
                json={"permissions": []},
            ).status_code
            == 404
        )
        denied_create = department_admin.post(
            "/api/admin/users",
            json={
                "username": "cross-department-created",
                "display_name": "跨部门用户",
                "initial_password": TEST_PASSWORD,
                "role": "finance_user",
                "department_id": "department-b",
            },
        )
        assert denied_create.status_code == 403
