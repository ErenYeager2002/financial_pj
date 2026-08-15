from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from helpers import TEST_PASSWORD, auth_client

from app.auth_service import (
    create_session,
    create_user,
    get_user_by_username,
    revoke_all_user_sessions,
)
from app.database import SessionLocal
from app.main import app


def test_unauthenticated_requests_are_rejected() -> None:
    with TestClient(app) as client:
        for path in (
            "/api/skills",
            "/api/runs",
            "/api/workflows",
            "/api/session",
        ):
            assert client.get(path).status_code == 401, path
        assert client.get("/api/health").status_code == 200

def test_forged_identity_headers_do_not_change_session() -> None:
    with auth_client() as client:
        forged = {
            "X-User-Id": "attacker-user",
            "X-User-Name": "attacker",
            "X-User-Role": "skill_admin",
            "X-Department-Id": "other-dept",
        }
        session = client.get("/api/session", headers=forged)
        assert session.status_code == 200
        body = session.json()
        assert body["username"] == "tester-finance_user"
        assert body["role"] == "finance_user"
        assert body["department_id"] == "finance"

        forged_admin = client.post("/api/admin/registry/reload", headers=forged)
        assert forged_admin.status_code == 403


def test_employee_cannot_access_admin_endpoints() -> None:
    with auth_client() as client:
        assert client.post("/api/admin/registry/reload").status_code == 403
        assert client.get("/api/model-providers").status_code == 200
        admin_models = client.get("/api/model-providers")
        assert all(not item["admin_only"] for item in admin_models.json())


def test_login_wrong_password_and_lockout() -> None:
    with auth_client(username="lockout-victim") as client:
        for _ in range(5):
            response = client.post(
                "/api/auth/login",
                json={"username": "lockout-victim", "password": "wrong-password"},
            )
            assert response.status_code == 401
        # 达到失败阈值后账号被锁定，即使密码正确也拒绝登录。
        locked = client.post(
            "/api/auth/login",
            json={"username": "lockout-victim", "password": TEST_PASSWORD},
        )
        assert locked.status_code == 401


def test_logout_revokes_session() -> None:
    with auth_client() as client:
        assert client.get("/api/session").status_code == 200
        assert client.post("/api/auth/logout").status_code == 204
        assert client.get("/api/session").status_code == 401


def test_disabled_user_session_is_invalidated() -> None:
    with auth_client(username="to-disable-user") as client:
        assert client.get("/api/session").status_code == 200
        with SessionLocal() as db:
            user = get_user_by_username(db, "to-disable-user")
            assert user is not None
            user.status = "disabled"
            db.commit()
        # 既有会话立即失效，不能继续访问。
        assert client.get("/api/session").status_code == 401


def test_revoked_sessions_are_rejected() -> None:
    with auth_client(username="revoke-session-user") as client:
        assert client.get("/api/session").status_code == 200
        with SessionLocal() as db:
            user = get_user_by_username(db, "revoke-session-user")
            assert user is not None
            count = revoke_all_user_sessions(db, user.id)
            assert count >= 1
        assert client.get("/api/session").status_code == 401


def test_sse_ignores_url_identity_claims() -> None:
    with auth_client() as client:
        # SSE 身份只来自会话 Cookie；URL 参数不能声明用户身份。
        # 对不存在的运行 ID 应返回 404（说明通过了身份校验），而不是以 URL 身份执行。
        response = client.get(
            "/api/runs/does-not-exist/events",
            params={"user_id": "someone-else", "role": "skill_admin"},
        )
        assert response.status_code == 404


def test_password_is_never_stored_plaintext() -> None:
    with SessionLocal() as db:
        user = get_user_by_username(db, "tester-finance_user")
        assert user is not None
        assert user.password_hash.startswith("$argon2")
        assert TEST_PASSWORD not in user.password_hash
        assert create_session(db, user)


def test_change_password_lifecycle() -> None:
    with SessionLocal() as db:
        user = create_user(
            db,
            username="first-time-user",
            password="initial-pass-123",
            role="finance_user",
            must_change_password=True,
        )
        db.commit()
        user_id = user.id

    with TestClient(app) as client:
        logged = client.post(
            "/api/auth/login",
            json={"username": "first-time-user", "password": "initial-pass-123"},
        )
        assert logged.status_code == 200, logged.text
        assert logged.json()["must_change_password"] is True

        # 必须改密码前，只能访问少数认证接口。
        assert client.get("/api/session").status_code == 200
        assert client.get("/api/skills").status_code == 403
        assert "PASSWORD_CHANGE_REQUIRED" in client.get("/api/skills").text

        changed = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "initial-pass-123",
                "new_password": "new-secret-456",
            },
        )
        assert changed.status_code == 200, changed.text
        assert client.get("/api/skills").status_code == 200

    # 初始密码失效，新密码可用。
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "first-time-user", "password": "initial-pass-123"},
            ).status_code
            == 401
        )
        renewed = client.post(
            "/api/auth/login",
            json={"username": "first-time-user", "password": "new-secret-456"},
        )
        assert renewed.status_code == 200
        assert renewed.json()["must_change_password"] is False

    from app.auth_models import User as UserModel

    with SessionLocal() as db:
        stored = db.get(UserModel, user_id)
        assert stored is not None
        assert stored.must_change_password is False
        assert stored.password_hash.startswith("$argon2")


def test_change_password_rejects_wrong_current() -> None:
    with SessionLocal() as db:
        create_user(
            db,
            username="wrong-current-user",
            password="old-pass-123",
            role="finance_user",
        )
        db.commit()

    with TestClient(app) as client:
        logged = client.post(
            "/api/auth/login",
            json={"username": "wrong-current-user", "password": "old-pass-123"},
        )
        assert logged.status_code == 200
        rejected = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "not-the-password",
                "new_password": "whatever-789",
            },
        )
        assert rejected.status_code == 400


def test_employee_password_change_keeps_bootstrap_secret() -> None:
    from app.settings import settings

    token_file = settings.data_dir / "initial_admin_password.txt"
    token_file.write_text("bootstrap-secret", encoding="utf-8")
    with SessionLocal() as db:
        create_user(
            db,
            username="employee-password-change",
            password="old-pass-123",
            role="finance_user",
            must_change_password=True,
        )
        db.commit()

    with TestClient(app) as client:
        logged = client.post(
            "/api/auth/login",
            json={"username": "employee-password-change", "password": "old-pass-123"},
        )
        assert logged.status_code == 200
        changed = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "old-pass-123",
                "new_password": "new-pass-456",
            },
        )
        assert changed.status_code == 200

    assert token_file.read_text(encoding="utf-8") == "bootstrap-secret"
    token_file.unlink()


def test_csrf_origin_guard_blocks_cross_origin() -> None:
    with auth_client() as client:
        blocked = client.post(
            "/api/auth/logout",
            headers={"Origin": "https://evil.example.com"},
        )
        assert blocked.status_code == 403
        same_origin = client.post(
            "/api/auth/logout",
            headers={"Origin": "http://testserver"},
        )
        assert same_origin.status_code == 204


def test_docs_and_openapi_require_auth() -> None:
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 401
        assert client.get("/redoc").status_code == 401
        assert client.get("/openapi.json").status_code == 401
    with auth_client() as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_production_requires_secure_cookie(tmp_path: Path) -> None:
    code = (
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "try:\n"
        "    with TestClient(app) as client:\n"
        "        pass\n"
        "except RuntimeError as exc:\n"
        "    if 'SECURE' in str(exc) or 'secure' in str(exc):\n"
        "        print('PROD_GUARD_OK')\n"
        "        raise SystemExit(0)\n"
        "    raise\n"
        "raise SystemExit(1)\n"
    )
    env = os.environ.copy()
    env["FINANCIAL_ENV"] = "production"
    env["FINANCIAL_SESSION_COOKIE_SECURE"] = "false"
    env["FINANCIAL_DATA_DIR"] = str(tmp_path / "data")
    env["FINANCIAL_DATABASE_URL"] = f"sqlite:///{(tmp_path / 'prod.db').as_posix()}"
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "PROD_GUARD_OK" in result.stdout
