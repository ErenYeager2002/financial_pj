"""Durable evidence for Pi prompt delivery across HTTP response loss.

The caller holds the per-session lock. Receipts contain a digest, never the
prompt or attachment paths, and are not a claim that a Pi turn succeeded.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException


PROMPT_TYPES = frozenset({'prompt', 'steer', 'follow_up'})


def request_identity(payload: dict) -> tuple[str, str, str] | None:
    command = payload.get('command')
    if not isinstance(command, dict) or command.get('type') not in PROMPT_TYPES:
        return None
    raw_id = payload.get('client_request_id')
    if raw_id is None:
        # Compatibility for older installed clients. The response is still not
        # evidence of turn completion, and this path must not auto-retry.
        return None
    try:
        request_id = str(UUID(raw_id))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(422, '无效的消息请求编号。') from None
    if raw_id != request_id or not isinstance(command.get('message'), str) or not command['message'].strip():
        raise HTTPException(422, '无效的消息请求。')
    encoded = json.dumps(command, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return request_id, hashlib.sha256(encoded).hexdigest(), command['type']


def receipt_path(catalog: Path, session_id: str, request_id: str) -> Path:
    try:
        request_id = str(UUID(request_id))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(404, '消息回执不存在。') from None
    base = catalog / 'delivery-receipts'
    directory = base / session_id
    if base.is_symlink() or directory.is_symlink():
        raise HTTPException(409, '消息回执目录异常。')
    return directory / (request_id + '.json')


def read_receipt(path: Path) -> dict | None:
    if path.is_symlink():
        raise HTTPException(409, '消息回执文件异常。')
    try:
        with path.open('r', encoding='utf-8') as stream:
            value = json.load(stream)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise HTTPException(409, '消息回执无法核实。') from None
    if not isinstance(value, dict) or value.get('state') not in {'prepared', 'dispatching', 'pi_accepted', 'unknown'}:
        raise HTTPException(409, '消息回执无法核实。')
    return value


def write_receipt(path: Path, value: dict) -> None:
    base = path.parent.parent
    if base.is_symlink() or path.parent.is_symlink():
        raise HTTPException(409, '消息回执路径异常。')
    base.mkdir(mode=0o700, exist_ok=True)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    if base.is_symlink() or path.parent.is_symlink() or path.is_symlink():
        raise HTTPException(409, '消息回执路径异常。')
    # Persist newly created directory entries before the dispatching marker.
    for parent in (base.parent, base):
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def public_receipt(value: dict) -> dict:
    return {'client_request_id': value['client_request_id'],
            'delivery_state': value['state'],
            'updated_at': value['updated_at']}


def new_receipt(request_id: str, digest: str, command_type: str) -> dict:
    return {'client_request_id': request_id, 'command_digest': digest,
            'command_type': command_type, 'state': 'prepared',
            'updated_at': datetime.now(timezone.utc).isoformat()}


def change_state(value: dict, state: str) -> dict:
    return {**value, 'state': state, 'updated_at': datetime.now(timezone.utc).isoformat()}
