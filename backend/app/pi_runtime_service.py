"""Authenticated platform access to persistent official Pi environments."""
from __future__ import annotations

import hashlib
import fcntl
import json
import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException

from .auth import UserContext
from .settings import settings


def owner_scope(user: UserContext) -> str:
    return hashlib.sha256((user.user_id + "\0" + user.department_id).encode()).hexdigest()


def catalog(user: UserContext):
    return settings.data_dir / 'pi-runtime' / 'catalog' / owner_scope(user)


def sessions(user: UserContext) -> list[dict]:
    directory = catalog(user)
    if not directory.exists():
        return []
    items = []
    for path in directory.glob('*.json'):
        if path.is_symlink():
            continue
        value = json.loads(path.read_text())
        if value.get('owner') == owner_scope(user):
            items.append({k: v for k, v in value.items() if k != 'owner'})
    return sorted(items, key=lambda x: x['created_at'], reverse=True)


def create_session(user: UserContext, title: str, skill: dict | None = None, channel: str = 'assistant') -> dict:
    directory = catalog(user)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    record = {'id': str(uuid4()), 'title': title.strip() or 'Pi 会话',
              'created_at': datetime.now(timezone.utc).isoformat(), 'owner': owner_scope(user), 'channel': channel}
    if skill:
        record.update(skill_id=skill['id'], skill_commit=skill['commit'])
    path = directory / (record['id'] + '.json')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(record, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    return {k: v for k, v in record.items() if k != 'owner'}


def require_session(user: UserContext, session_id: str, *, check_skill: bool = True) -> str:
    try:
        session_id = str(UUID(session_id))
    except (ValueError, TypeError):
        raise HTTPException(404, 'Pi 会话不存在。') from None
    path = catalog(user) / (session_id + '.json')
    if not path.is_file() or path.is_symlink():
        raise HTTPException(404, 'Pi 会话不存在。')
    record = json.loads(path.read_text())
    if record.get('owner') != owner_scope(user) or record.get('id') != session_id:
        raise HTTPException(404, 'Pi 会话不存在。')
    if check_skill:
        names = [record['skill_id']] if record.get('skill_id') else record.get('mounted_skill_ids', [])
        if names:
            from .database import SessionLocal
            from .authorization import refresh_active_user, allowed_skill_ids
            with SessionLocal() as db:
                current = refresh_active_user(db, user)
                if not current.is_admin and not {'native--' + name for name in names}.issubset(allowed_skill_ids(db, current)):
                    raise HTTPException(403, 'Skill 权限已变化，请停止环境后重新启动。')
    return session_id


def store_mounted_skills(user, session_id, names):
    record_path = catalog(user) / (session_id + '.json')
    record = json.loads(record_path.read_text())
    record['mounted_skill_ids'] = sorted(set(names))
    temporary = record_path.with_name(record_path.name + '.' + uuid4().hex + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(record, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, record_path)


def operate(user: UserContext, session_id: str, operation: str, payload: dict, *, model_config: dict | None = None, skill_bindings: list[dict] | None = None, business_config: dict | None = None) -> dict:
    session_id = require_session(user, session_id, check_skill=False)
    # Serialize lifecycle, authorization and its conservative mount record across
    # API processes. A lost start reply must never leave unrecorded capabilities.
    with (catalog(user) / (session_id + '.lock')).open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return _operate_locked(user, session_id, operation, payload, model_config=model_config, skill_bindings=skill_bindings, business_config=business_config)


def _operate_locked(user: UserContext, session_id: str, operation: str, payload: dict, *, model_config: dict | None = None, skill_bindings: list[dict] | None = None, business_config: dict | None = None) -> dict:
    cancelling_job = operation == 'jobs' and payload.get('operation') == 'cancel'
    session_id = require_session(user, session_id, check_skill=operation not in {'start', 'stop'} and not cancelling_job)
    body = {'owner': owner_scope(user), 'session_id': session_id,
            'operation': operation, 'payload': payload}
    if operation == 'start' and skill_bindings is not None:
        body['skill_bindings'] = skill_bindings
    if operation == 'start' and business_config is not None:
        body['business_config'] = business_config
    if operation == 'start' and model_config is not None:
        body['model_config'] = model_config
    if operation == 'start' and skill_bindings is not None:
        from .database import SessionLocal
        from .authorization import refresh_active_user, allowed_skill_ids
        with SessionLocal() as db:
            current = refresh_active_user(db, user)
            if not current.is_admin and not {'native--' + item['id'] for item in skill_bindings}.issubset(allowed_skill_ids(db, current)):
                raise HTTPException(403, 'Skill 权限已变化，请重新启动。')
        record = json.loads((catalog(user) / (session_id + '.json')).read_text())
        store_mounted_skills(user, session_id, [*record.get('mounted_skill_ids', []), *[item['id'] for item in skill_bindings]])
    encoded = json.dumps(body, ensure_ascii=False).encode()
    if len(encoded) > 9 * 1024 * 1024:
        raise HTTPException(413, 'Pi 请求过大。')
    transport = httpx.HTTPTransport(uds=str(settings.data_dir / 'pi-runtime' / 'manager.sock'))
    try:
        with httpx.Client(transport=transport, timeout=90) as client:
            response = client.post('http://pi-runtime/operate', content=encoded,
                                   headers={'Content-Type': 'application/json'})
    except httpx.HTTPError:
        raise HTTPException(503, 'Pi 运行环境暂时无法连接。') from None
    if response.status_code != 200:
        messages = {404: 'Pi 文件或会话不存在。', 507: 'Pi 存储空间不足。', 409: 'Pi 会话状态冲突，请查询运行状态后重试。',
                    422: 'Pi 操作参数无效，文件可能已变化，请刷新后重试。', 413: 'Pi 请求过大。'}
        raise HTTPException(response.status_code if response.status_code in messages else 503,
                            messages.get(response.status_code, 'Pi 运行环境操作失败。'))
    result = response.json()
    if operation == 'start' and skill_bindings is not None:
        store_mounted_skills(user, session_id, [item['id'] for item in skill_bindings])
    return result
