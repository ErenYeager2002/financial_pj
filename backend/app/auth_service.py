from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth_models import User, UserSession
from .settings import settings

_hasher = PasswordHasher()

# 会话“最后使用时间”只按该间隔刷新一次，避免前端轮询时持续写 SQLite。
SESSION_LAST_USED_THROTTLE_SECONDS = 300


def _now_naive() -> datetime:
    """SQLite 读取 DateTime(timezone=True) 会丢失时区信息，统一用 naive UTC 比较。"""
    return datetime.now(UTC).replace(tzinfo=None)


def _naive_utc(value: datetime) -> datetime:
    """Normalize SQLite naive UTC and PostgreSQL timezone-aware values."""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, TypeError):
        return False


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_user(
    db: Session,
    *,
    username: str,
    password: str,
    display_name: str = "",
    role: str = "finance_user",
    department_id: str = "finance",
    user_id: str | None = None,
    must_change_password: bool = False,
    clerk_user_id: str | None = None,
    clerk_organization_id: str | None = None,
) -> User:
    user = User(
        id=user_id or str(uuid.uuid4()),
        username=username.strip(),
        clerk_user_id=clerk_user_id.strip() if clerk_user_id else None,
        clerk_organization_id=(clerk_organization_id.strip() if clerk_organization_id else None),
        display_name=display_name.strip() or username.strip(),
        password_hash=hash_password(password),
        role=role,
        department_id=department_id,
        status="active",
        must_change_password=must_change_password,
        password_changed_at=None if must_change_password else _now_naive(),
    )
    db.add(user)
    db.flush()
    return user


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username.strip()))


def get_user_by_clerk_id(db: Session, clerk_user_id: str) -> User | None:
    if not clerk_user_id:
        return None
    return db.scalar(select(User).where(User.clerk_user_id == clerk_user_id))


def get_or_create_development_clerk_admin(
    db: Session,
    *,
    clerk_user_id: str,
    clerk_organization_id: str = "",
) -> User:
    """为隔离的本地开发数据库幂等建立 Clerk 管理员映射。"""
    existing = get_user_by_clerk_id(db, clerk_user_id)
    if existing is not None:
        return existing

    identity_hash = hashlib.sha256(clerk_user_id.encode("utf-8")).hexdigest()[:16]
    try:
        user = create_user(
            db,
            username=f"dev-clerk-{identity_hash}",
            password=secrets.token_urlsafe(32),
            display_name="开发管理员",
            role="skill_admin",
            department_id="finance",
            clerk_user_id=clerk_user_id,
            clerk_organization_id=clerk_organization_id or None,
        )
        db.commit()
        return user
    except IntegrityError:
        # Next.js 首次渲染可能并发请求多个接口；另一请求可能已经完成建档。
        db.rollback()
        existing = get_user_by_clerk_id(db, clerk_user_id)
        if existing is None:
            raise
        return existing


def _user_locked(user: User) -> bool:
    return bool(user.locked_until and _naive_utc(user.locked_until) > _now_naive())


def login(db: Session, username: str, password: str) -> User | None:
    user = get_user_by_username(db, username)
    if not user:
        return None
    if user.status == "disabled":
        return None
    if _user_locked(user):
        return None
    if not verify_password(user.password_hash, password):
        # 原子递增失败计数，避免并发登录丢失计数。
        db.execute(
            update(User).where(User.id == user.id).values(failed_attempts=User.failed_attempts + 1)
        )
        updated = db.scalar(select(User).where(User.id == user.id))
        if updated is not None and updated.failed_attempts >= settings.login_failure_limit:
            db.execute(
                update(User)
                .where(User.id == user.id)
                .values(
                    failed_attempts=0,
                    locked_until=_now_naive() + timedelta(seconds=settings.login_lockout_seconds),
                )
            )
        db.commit()
        return None
    user.failed_attempts = 0
    user.locked_until = None
    db.commit()
    return user


def create_session(db: Session, user: User, client_hint: str = "") -> str:
    token = secrets.token_urlsafe(32)
    session = UserSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=token_sha256(token),
        expires_at=_now_naive() + timedelta(seconds=settings.session_max_age_seconds),
        client_hint=client_hint[:255],
    )
    db.add(session)
    db.flush()
    return token


def get_session_user(db: Session, token: str) -> User | None:
    if not token:
        return None
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_sha256(token)))
    if not session:
        return None
    now = _now_naive()
    if session.revoked_at is not None:
        return None
    if _naive_utc(session.expires_at) < now:
        return None
    user = db.get(User, session.user_id)
    if not user or user.status != "active":
        return None
    # 限频刷新 last_used_at：只有超过阈值才写库，避免轮询持续写 SQLite。
    if (
        session.last_used_at is None
        or (now - _naive_utc(session.last_used_at)).total_seconds()
        >= SESSION_LAST_USED_THROTTLE_SECONDS
    ):
        session.last_used_at = now
        db.commit()
    return user


def revoke_session(db: Session, token: str) -> None:
    if not token:
        return
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_sha256(token)))
    if session and session.revoked_at is None:
        session.revoked_at = _now_naive()
        db.commit()


def revoke_all_user_sessions(db: Session, user_id: str, *, commit: bool = True) -> int:
    return _revoke_sessions(db, user_id, keep_token=None, commit=commit)


def revoke_all_user_sessions_except(db: Session, user_id: str, keep_token: str) -> int:
    return _revoke_sessions(db, user_id, keep_token=keep_token, commit=True)


def _revoke_sessions(
    db: Session,
    user_id: str,
    keep_token: str | None,
    *,
    commit: bool,
) -> int:
    query = select(UserSession).where(
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
    )
    if keep_token:
        query = query.where(UserSession.token_hash != token_sha256(keep_token))
    sessions = db.scalars(query).all()
    now = _now_naive()
    for session in sessions:
        session.revoked_at = now
    if commit:
        db.commit()
    return len(sessions)


def change_password(db: Session, user: User, current_password: str, new_password: str) -> bool:
    """校验当前密码并更新；成功后撤销该用户除当前会话外的所有会话。"""
    if not verify_password(user.password_hash, current_password):
        return False
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.password_changed_at = _now_naive()
    db.commit()
    return True


def _write_bootstrap_password(token_file: Path, password: str) -> None:
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(
        f"首次初始化管理员密码（请登录后立即修改，修改成功后此文件会被删除）：{password}\n",
        encoding="utf-8",
    )
    try:
        token_file.chmod(0o600)
    except OSError:
        pass


def delete_initial_password_file() -> bool:
    token_file = settings.data_dir / "initial_admin_password.txt"
    try:
        token_file.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def bootstrap_admin(db: Session) -> str:
    """确保至少存在一个管理员账号；已存在时幂等。

    管理员使用独立 UUID，不继承 demo-user 的历史数据；历史演示数据的所有者
    归属由 P0-07 专项迁移处理。自动生成的初始密码标记为“必须首次修改”。
    """
    existing = db.scalar(select(User).where(User.username == settings.bootstrap_admin_username))
    if existing:
        return existing.username
    if settings.bootstrap_admin_password:
        password = settings.bootstrap_admin_password
        must_change = False
    else:
        password = secrets.token_urlsafe(12)
        _write_bootstrap_password(settings.data_dir / "initial_admin_password.txt", password)
        must_change = True
    create_user(
        db,
        username=settings.bootstrap_admin_username,
        password=password,
        display_name="Skill 管理员",
        role="skill_admin",
        department_id="finance",
        must_change_password=must_change,
    )
    db.commit()
    return settings.bootstrap_admin_username
