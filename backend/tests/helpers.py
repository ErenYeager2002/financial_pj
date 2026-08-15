from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.auth_service import create_user, get_user_by_username
from app.authorization import replace_user_permissions
from app.database import SessionLocal, init_db
from app.main import app
from app.registry import registry

TEST_PASSWORD = "test-password-123"


@contextmanager
def auth_client(
    *,
    role: str = "finance_user",
    username: str | None = None,
    grant_skills: bool = True,
    department_id: str = "finance",
) -> Generator[TestClient, None, None]:
    """返回已登录指定角色的 TestClient。

    测试默认使用 finance_user；管理员测试传 role="skill_admin"。
    所有身份都来自服务端会话 Cookie，伪造 X-User-* 请求头无效。
    """
    init_db()
    username = username or f"tester-{role}"
    with SessionLocal() as db:
        existing = get_user_by_username(db, username)
        if not existing:
            existing = create_user(
                db,
                username=username,
                password=TEST_PASSWORD,
                role=role,
                display_name=f"测试{role}",
                department_id=department_id,
            )
            db.commit()
        if role != "skill_admin" and grant_skills:
            registry.refresh()
            replace_user_permissions(
                db,
                existing,
                [
                    {
                        "skill_id": item.manifest.id,
                        "can_run": True,
                        "can_upload": True,
                        "can_create_draft": True,
                        "requires_approval": False,
                    }
                    for item in registry.list(include_disabled=True)
                ],
            )
    client = TestClient(app)
    with client:
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": TEST_PASSWORD},
        )
        assert response.status_code == 200, response.text
        yield client
