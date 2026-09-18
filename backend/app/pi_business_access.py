"""Business delegation is session scoped and distinct from model credentials."""
import fcntl
import hashlib
import json
import secrets
from fastapi import HTTPException
from .settings import settings
from .auth import UserContext
from .auth_models import User
from .pi_model_access import atomic_json, password_epoch
from .pi_runtime_service import require_session, owner_scope


def root():
    return settings.data_dir / 'pi-business-access'


def provision(db, user, session_id):
    session_id = require_session(user, session_id, check_skill=False)
    account = db.get(User, user.user_id)
    if account is None or account.status != 'active' or account.must_change_password or account.department_id != user.department_id:
        raise HTTPException(403, '账号当前不可用。')
    directory = root()
    for name in ['sessions', 'tokens', 'locks']:
        (directory / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    key = owner_scope(user) + '-' + session_id
    path = directory / 'sessions' / (key + '.json')
    with (directory / 'locks' / key).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = json.loads(path.read_text()) if path.exists() else {}
        if current.get('password_epoch') != password_epoch(account) or not current.get('token'):
            if current.get('token'):
                (directory / 'tokens' / (hashlib.sha256(current['token'].encode()).hexdigest() + '.json')).unlink(missing_ok=True)
            current = {'token':secrets.token_urlsafe(48), 'user_id':user.user_id,
                       'department_id':user.department_id, 'owner':owner_scope(user),
                       'session_id':session_id, 'password_epoch':password_epoch(account),
                       'purpose':'pi-business-read-v1'}
            atomic_json(directory / 'tokens' / (hashlib.sha256(current['token'].encode()).hexdigest() + '.json'),
                        {k:v for k,v in current.items() if k != 'token'})
            atomic_json(path, current)
    return {'token':current['token'], 'session_id':session_id}


def authenticate(db, authorization, session_id):
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not 32 <= len(token) <= 128:
        raise HTTPException(401, 'Invalid business credential')
    try:
        record = json.loads((root() / 'tokens' / (hashlib.sha256(token.encode()).hexdigest() + '.json')).read_text())
    except (OSError, ValueError):
        raise HTTPException(401, 'Invalid business credential') from None
    if record.get('purpose') != 'pi-business-read-v1' or record.get('session_id') != session_id:
        raise HTTPException(403, 'Invalid business session scope')
    account = db.get(User, record.get('user_id'))
    if (account is None or account.status != 'active' or account.must_change_password
        or account.department_id != record.get('department_id')
        or password_epoch(account) != record.get('password_epoch')):
        raise HTTPException(401, 'Business credential is no longer active')
    user = UserContext(user_id=account.id, display_name=account.display_name, role=account.role,
                       department_id=account.department_id, username=account.username)
    if owner_scope(user) != record.get('owner'):
        raise HTTPException(403, 'Invalid business owner')
    require_session(user, session_id)
    return user
