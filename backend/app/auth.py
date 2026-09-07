from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .auth_service import get_session_user
from .database import get_db
from .settings import settings


@dataclass(frozen=True)
class UserContext:
    user_id: str
    display_name: str
    role: str
    department_id: str = "finance"
    username: str = ""
    auth_provider: str = "session"

    @property
    def is_admin(self) -> bool:
        return self.role == "skill_admin"


def _session_token(request: Request) -> str:
    return request.cookies.get(settings.session_cookie_name, "")


# 首次登录必须修改初始密码时，允许访问的最小接口集合。
PASSWORD_CHANGE_ALLOWED_PATHS = {
    "/api/session",
    "/api/auth/session",
    "/api/auth/change-password",
    "/api/auth/logout",
}


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> UserContext:
    """Resolve only platform sessions; arbitrary identity headers are rejected."""
    authorization = request.headers.get("authorization", "").strip()
    if authorization.lower().startswith("bearer local."):
        token = authorization[len("Bearer local.") :].strip()
        user = get_session_user(db, token)
        if not user:
            raise HTTPException(status_code=401, detail="未登录或会话已失效。")
        if user.must_change_password and request.url.path not in PASSWORD_CHANGE_ALLOWED_PATHS:
            raise HTTPException(
                status_code=403,
                detail="PASSWORD_CHANGE_REQUIRED：首次登录需要先修改初始密码。",
            )
        return UserContext(
            user_id=user.id,
            display_name=user.display_name,
            role=user.role,
            department_id=user.department_id,
            username=user.username,
            auth_provider="session",
        )
    if authorization:
        raise HTTPException(status_code=401, detail="仅支持平台账号会话登录。")

    token = _session_token(request)
    user = get_session_user(db, token) if token else None
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或会话已失效。",
            headers={"WWW-Authenticate": "Session"},
        )
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_ALLOWED_PATHS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PASSWORD_CHANGE_REQUIRED：首次登录需要先修改初始密码。",
        )
    return UserContext(
        user_id=user.id,
        display_name=user.display_name,
        role=user.role,
        department_id=user.department_id,
        username=user.username,
        auth_provider="session",
    )


def get_sse_user(
    request: Request,
    db: Session = Depends(get_db),
) -> UserContext:
    """SSE 使用相同认证边界，不接受 URL 参数声明的用户身份。"""
    return get_current_user(request, db)


def require_admin(user: UserContext) -> None:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有 Skill 管理员可以执行此操作。",
        )
