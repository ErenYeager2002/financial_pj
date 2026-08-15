from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from helpers import auth_client

from app import auth as auth_module
from app import clerk_auth as clerk_auth_module
from app.auth_service import create_user
from app.clerk_auth import ClerkIdentity, ClerkTokenError, verify_clerk_token
from app.database import SessionLocal, init_db
from app.main import app


def _auth_mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setattr(
        auth_module,
        "settings",
        replace(auth_module.settings, auth_mode=mode),
    )


def _mapped_user(
    *,
    username: str,
    clerk_user_id: str,
    clerk_organization_id: str | None = None,
    status: str = "active",
) -> None:
    init_db()
    with SessionLocal() as db:
        user = create_user(
            db,
            username=username,
            password="unused-clerk-password",
            display_name="Clerk 测试用户",
            clerk_user_id=clerk_user_id,
            clerk_organization_id=clerk_organization_id,
        )
        user.status = status
        db.commit()


def test_hybrid_mode_accepts_mapped_clerk_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    _mapped_user(
        username="clerk-mapped-user",
        clerk_user_id="user_clerk_mapped",
        clerk_organization_id="org_finance",
    )
    _auth_mode(monkeypatch, "hybrid")
    monkeypatch.setattr(
        auth_module,
        "verify_clerk_token",
        lambda _token: ClerkIdentity(user_id="user_clerk_mapped", organization_id="org_finance"),
    )

    with TestClient(app) as client:
        response = client.get("/api/session", headers={"Authorization": "Bearer valid-clerk-token"})

    assert response.status_code == 200, response.text
    assert response.json()["username"] == "clerk-mapped-user"
    assert response.json()["auth_provider"] == "clerk"


def test_hybrid_mode_rejects_unmapped_clerk_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_mode(monkeypatch, "hybrid")
    monkeypatch.setattr(
        auth_module,
        "verify_clerk_token",
        lambda _token: ClerkIdentity(user_id="user_not_mapped"),
    )

    with TestClient(app) as client:
        response = client.get("/api/session", headers={"Authorization": "Bearer valid-clerk-token"})

    assert response.status_code == 403
    assert "尚未绑定" in response.text


def test_invalid_bearer_never_falls_back_to_valid_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with auth_client(username="cookie-fallback-user") as client:
        _auth_mode(monkeypatch, "hybrid")

        def reject(_token: str) -> ClerkIdentity:
            raise ClerkTokenError("测试无效 Token")

        monkeypatch.setattr(auth_module, "verify_clerk_token", reject)
        response = client.get("/api/session", headers={"Authorization": "Bearer invalid-token"})

    assert response.status_code == 401
    assert "测试无效 Token" in response.text


def test_clerk_mode_rejects_cookie_only_session(monkeypatch: pytest.MonkeyPatch) -> None:
    with auth_client(username="legacy-cookie-user") as client:
        _auth_mode(monkeypatch, "clerk")
        response = client.get("/api/session")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_clerk_mapping_enforces_bound_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mapped_user(
        username="clerk-org-user",
        clerk_user_id="user_clerk_org",
        clerk_organization_id="org_expected",
    )
    _auth_mode(monkeypatch, "hybrid")
    monkeypatch.setattr(
        auth_module,
        "verify_clerk_token",
        lambda _token: ClerkIdentity(user_id="user_clerk_org", organization_id="org_other"),
    )

    with TestClient(app) as client:
        response = client.get("/api/session", headers={"Authorization": "Bearer valid-clerk-token"})

    assert response.status_code == 403
    assert "组织" in response.text


def test_disabled_clerk_mapped_user_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _mapped_user(
        username="clerk-disabled-user",
        clerk_user_id="user_clerk_disabled",
        status="disabled",
    )
    _auth_mode(monkeypatch, "hybrid")
    monkeypatch.setattr(
        auth_module,
        "verify_clerk_token",
        lambda _token: ClerkIdentity(user_id="user_clerk_disabled"),
    )

    with TestClient(app) as client:
        response = client.get("/api/session", headers={"Authorization": "Bearer valid-clerk-token"})

    assert response.status_code == 403
    assert "禁用" in response.text


def test_admin_can_bind_clerk_identity() -> None:
    with auth_client(role="skill_admin", username="clerk-binding-admin") as client:
        created = client.post(
            "/api/admin/users",
            json={
                "username": "employee-to-bind",
                "display_name": "待绑定员工",
                "initial_password": "initial-password-123",
                "role": "finance_user",
                "department_id": "finance",
            },
        )
        assert created.status_code == 201, created.text
        user_id = created.json()["id"]

        bound = client.patch(
            f"/api/admin/users/{user_id}",
            json={
                "clerk_user_id": "user_bound_by_admin",
                "clerk_organization_id": "org_finance",
            },
        )

    assert bound.status_code == 200, bound.text
    assert bound.json()["clerk_user_id"] == "user_bound_by_admin"
    assert bound.json()["clerk_organization_id"] == "org_finance"


def test_real_clerk_jwt_signature_and_authorized_party(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    issuer = "https://example.clerk.accounts.dev"
    monkeypatch.setattr(
        clerk_auth_module,
        "settings",
        replace(
            clerk_auth_module.settings,
            clerk_issuer=issuer,
            clerk_jwt_key=public_key,
            clerk_authorized_parties=("http://localhost:3000",),
        ),
    )
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "user_signed",
            "iss": issuer,
            "iat": now,
            "nbf": now - timedelta(seconds=1),
            "exp": now + timedelta(minutes=5),
            "azp": "http://localhost:3000",
            "org_id": "org_finance",
        },
        private_key,
        algorithm="RS256",
    )

    identity = verify_clerk_token(token)
    assert identity.user_id == "user_signed"
    assert identity.organization_id == "org_finance"
    assert identity.authorized_party == "http://localhost:3000"

    wrong_party = jwt.encode(
        {
            "sub": "user_signed",
            "iss": issuer,
            "iat": now,
            "nbf": now - timedelta(seconds=1),
            "exp": now + timedelta(minutes=5),
            "azp": "https://evil.example.com",
        },
        private_key,
        algorithm="RS256",
    )
    with pytest.raises(ClerkTokenError, match="来源"):
        verify_clerk_token(wrong_party)
