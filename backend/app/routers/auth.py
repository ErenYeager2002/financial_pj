from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ..audit_service import record_audit
from ..auth import UserContext, get_current_user
from ..auth_models import User
from ..auth_service import (
    change_password,
    create_session,
    delete_initial_password_file,
    login,
    revoke_all_user_sessions_except,
    revoke_session,
)
from ..database import get_db
from ..schemas_auth import ChangePasswordRequest, LoginRequest, SessionRead
from ..settings import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )


def _session_read(
    user: UserContext,
    must_change_password: bool = False,
    avatar_updated_at: datetime | None = None,
) -> SessionRead:
    return SessionRead(
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        department_id=user.department_id,
        must_change_password=must_change_password,
        auth_provider=user.auth_provider,
        avatar_updated_at=avatar_updated_at,
    )


@router.post("/login", response_model=SessionRead)
def auth_login(
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> SessionRead:
    user = login(db, body.username, body.password)
    if not user:
        record_audit(db, action="auth.login", outcome="failed")
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误，或账号已被锁定/禁用。",
        )
    token = create_session(db, user, client_hint=body.username)
    actor = UserContext(
        user_id=user.id,
        display_name=user.display_name,
        role=user.role,
        department_id=user.department_id,
        username=user.username,
    )
    record_audit(db, actor=actor, action="auth.login", resource_type="session")
    db.commit()
    _set_session_cookie(response, token)
    return _session_read(
        actor,
        must_change_password=user.must_change_password,
        avatar_updated_at=user.avatar_updated_at,
    )


@router.post("/change-password", response_model=SessionRead)
def auth_change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionRead:
    stored = db.get(User, user.user_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="用户不存在。")
    delete_bootstrap_secret = bool(
        stored.must_change_password and stored.username == settings.bootstrap_admin_username
    )
    if not change_password(db, stored, body.current_password, body.new_password):
        raise HTTPException(status_code=400, detail="当前密码不正确。")
    # 只有自动生成的一次性管理员凭据完成首次改密后，才删除对应密码文件。
    if delete_bootstrap_secret:
        delete_initial_password_file()
    # 撤销该用户的其他会话；当前会话保留，便于前端刷新状态。
    token = request.cookies.get(settings.session_cookie_name, "")
    revoke_all_user_sessions_except(db, user.user_id, token)
    record_audit(
        db,
        actor=user,
        action="auth.password_change",
        resource_type="user",
        resource_id=user.user_id,
    )
    db.commit()
    return _session_read(user, avatar_updated_at=stored.avatar_updated_at)


@router.post("/logout", status_code=204)
def auth_logout(
    request: Request,
    response: Response,
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    token = request.cookies.get(settings.session_cookie_name, "")
    if token:
        revoke_session(db, token)
    record_audit(db, actor=user, action="auth.logout", resource_type="session")
    db.commit()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
    )


@router.get("/session", response_model=SessionRead)
def auth_session(
    user: UserContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionRead:
    stored = db.get(User, user.user_id)
    return _session_read(
        user,
        must_change_password=bool(stored and stored.must_change_password),
        avatar_updated_at=stored.avatar_updated_at if stored else None,
    )
