from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .auth_service import (
    get_or_create_development_clerk_admin,
    get_session_user,
    get_user_by_clerk_id,
)
from .clerk_auth import ClerkTokenError, verify_clerk_token
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


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "").strip()
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization 请求头格式无效。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def _clerk_user(request: Request, db: Session) -> UserContext:
    token = _bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Clerk 身份令牌。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        identity = verify_clerk_token(token)
    except ClerkTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    user = get_user_by_clerk_id(db, identity.user_id)
    if (
        not user
        and settings.environment.strip().lower() == "development"
        and settings.dev_clerk_auto_provision_admin
    ):
        user = get_or_create_development_clerk_admin(
            db,
            clerk_user_id=identity.user_id,
            clerk_organization_id=identity.organization_id,
        )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前 Clerk 身份尚未绑定平台用户，请联系管理员。",
        )
    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="平台用户已被禁用。",
        )
    if user.clerk_organization_id and user.clerk_organization_id != identity.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前 Clerk 组织与平台用户绑定不一致。",
        )
    return UserContext(
        user_id=user.id,
        display_name=user.display_name,
        role=user.role,
        department_id=user.department_id,
        username=user.username,
        auth_provider="clerk",
    )


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
    """按显式认证模式从 Clerk Bearer 或服务端会话 Cookie 解析身份。

    拒绝任何 X-User-* 请求头。hybrid 模式下如果请求携带 Bearer，
    验证失败会直接拒绝，不会降级到 Cookie。首次登录仍需修改初始
    密码的本地会话用户，只能访问少数认证接口。
    """
    if settings.auth_mode not in {"session", "hybrid", "clerk"}:
        raise HTTPException(status_code=500, detail="平台认证模式配置无效。")
    authorization = request.headers.get("authorization", "").strip()
    if authorization.lower().startswith("bearer local."):
        if settings.auth_mode == "clerk":
            raise HTTPException(status_code=401, detail="本地会话不能用于 Clerk 模式。")
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
    if settings.auth_mode in {"hybrid", "clerk"} and authorization:
        return _clerk_user(request, db)
    if settings.auth_mode == "clerk":
        return _clerk_user(request, db)

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
