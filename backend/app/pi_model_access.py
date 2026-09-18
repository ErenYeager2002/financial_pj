"""Owner-scoped model access; shared provider secrets never enter Pi containers."""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
import secrets
from pathlib import Path
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy.orm import Session
from .auth import UserContext
from .auth_models import User
from .settings import settings
from .pi_runtime_service import owner_scope
from .assistant_profile_service import assistant_status, _profile
from .model_service import list_connections, resolve_runtime_config, get_connection
from .agent_model_gateway import resolve_agent_model_config


def root() -> Path:
    return settings.data_dir / 'pi-model-access'


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + '.' + uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def password_epoch(user: User) -> str:
    return user.password_changed_at.isoformat() if user.password_changed_at else ''


def provision(db: Session, user: UserContext) -> dict | None:
    status = assistant_status(db, user)
    available = [c for c in list_connections(db, user) if c.status == 'connected']
    if not status.configured and not available:
        return None
    account = db.get(User, user.user_id)
    if account is None or account.status != 'active' or account.department_id != user.department_id:
        raise HTTPException(403, '账号当前不可用。')
    directory = root()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ('owners', 'tokens', 'locks'):
        (directory / name).mkdir(exist_ok=True, mode=0o700)
    owner = owner_scope(user)
    owner_file = directory / 'owners' / (owner + '.json')
    with (directory / 'locks' / owner).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = json.loads(owner_file.read_text()) if owner_file.exists() else {}
        if current.get('password_epoch') != password_epoch(account) or not current.get('token'):
            if current.get('token'):
                old_hash = hashlib.sha256(current['token'].encode()).hexdigest()
                (directory / 'tokens' / (old_hash + '.json')).unlink(missing_ok=True)
            current = {'token': secrets.token_urlsafe(48), 'user_id': user.user_id,
                       'department_id': user.department_id, 'owner': owner,
                       'password_epoch': password_epoch(account)}
            digest = hashlib.sha256(current['token'].encode()).hexdigest()
            atomic_json(directory / 'tokens' / (digest + '.json'),
                        {k: v for k, v in current.items() if k != 'token'})
            atomic_json(owner_file, current)
    models = []
    if status.configured:
        profile = _profile(db, user.department_id)
        from .models import ModelConnection
        default_connection = db.get(ModelConnection, profile.connection_id)
        models.append({'id': 'platform-default', 'name': status.model + ' (platform default)',
                       'source_model': status.model, 'source_provider': default_connection.provider})
    for connection in available:
        for model in connection.models:
            models.append({'id': connection.id + ':' + model, 'name': model,
                           'source_model': model, 'source_provider': connection.provider})
    return {'token': current['token'], 'models': models,
            'default_model': models[0]['id']}


def authenticate(db: Session, authorization: str) -> UserContext:
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not 32 <= len(token) <= 128:
        raise HTTPException(401, 'Invalid Pi model credential')
    digest = hashlib.sha256(token.encode()).hexdigest()
    path = root() / 'tokens' / (digest + '.json')
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        raise HTTPException(401, 'Invalid Pi model credential') from None
    account = db.get(User, record.get('user_id'))
    if (account is None or account.status != 'active' or account.must_change_password
            or account.department_id != record.get('department_id')
            or password_epoch(account) != record.get('password_epoch')):
        raise HTTPException(401, 'Pi model credential is no longer active')
    user = UserContext(user_id=account.id, display_name=account.display_name,
                       role=account.role, department_id=account.department_id,
                       username=account.username)
    if owner_scope(user) != record.get('owner'):
        raise HTTPException(401, 'Invalid Pi model scope')
    return user


def resolve_model(db: Session, user: UserContext, alias: str):
    if alias == 'platform-default':
        return resolve_agent_model_config(db, user, None, '')
    connection, separator, model = alias.partition(':')
    try:
        connection = str(UUID(connection))
    except (TypeError, ValueError):
        raise HTTPException(422, 'Invalid platform model') from None
    if not separator or not model:
        raise HTTPException(422, 'Invalid platform model')
    record = get_connection(db, user, connection)
    if record.status != 'connected':
        raise HTTPException(409, 'Model connection is unavailable')
    return resolve_runtime_config(db, user, connection, model)
