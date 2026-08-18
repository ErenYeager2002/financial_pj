from __future__ import annotations

import json
import re
import uuid

from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .auth import UserContext
from .contracts import AssistantConversationRead, AssistantMessageRead
from .models import AssistantMessage, utcnow

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_HISTORY_MESSAGES = 200
MAX_DATA_BYTES = 64 * 1024


def _checked_session_id(session_id: str) -> str:
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="AI 会话标识格式无效。")
    return session_id


def _serialize(message: AssistantMessage) -> AssistantMessageRead:
    try:
        data = json.loads(message.data_json or "{}")
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return AssistantMessageRead(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        data=data,
        created_at=message.created_at,
    )


def get_conversation(
    db: Session,
    user: UserContext,
    session_id: str,
    *,
    missing_is_empty: bool = False,
) -> AssistantConversationRead:
    checked_id = _checked_session_id(session_id)
    messages = db.scalars(
        select(AssistantMessage)
        .where(
            AssistantMessage.session_id == checked_id,
            AssistantMessage.owner_id == user.user_id,
            AssistantMessage.department_id == user.department_id,
        )
        .order_by(desc(AssistantMessage.created_at), desc(AssistantMessage.id))
        .limit(MAX_HISTORY_MESSAGES)
    ).all()
    messages.reverse()
    if not messages and not missing_is_empty:
        raise HTTPException(status_code=404, detail="AI 会话记录不存在。")
    return AssistantConversationRead(
        session_id=checked_id,
        messages=[_serialize(item) for item in messages],
        updated_at=messages[-1].created_at if messages else None,
    )


def get_latest_conversation(
    db: Session,
    user: UserContext,
) -> AssistantConversationRead | None:
    session_id = db.scalar(
        select(AssistantMessage.session_id)
        .where(
            AssistantMessage.owner_id == user.user_id,
            AssistantMessage.department_id == user.department_id,
        )
        .group_by(AssistantMessage.session_id)
        .order_by(desc(func.max(AssistantMessage.created_at)))
        .limit(1)
    )
    if not session_id:
        return None
    return get_conversation(db, user, session_id, missing_is_empty=True)


def append_message(
    db: Session,
    user: UserContext,
    session_id: str,
    role: str,
    content: str,
    data: dict[str, object] | None = None,
) -> AssistantMessageRead:
    checked_id = _checked_session_id(session_id)
    clean_content = content.strip()
    if not clean_content or len(clean_content) > 20000:
        raise HTTPException(status_code=422, detail="AI 消息内容长度无效。")
    if role not in {"user", "assistant", "system"}:
        raise HTTPException(status_code=422, detail="AI 消息角色无效。")
    payload = data if isinstance(data, dict) else {}
    data_json = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
    if len(data_json.encode("utf-8")) > MAX_DATA_BYTES:
        raise HTTPException(status_code=422, detail="AI 消息附加数据过大。")
    message = AssistantMessage(
        id=str(uuid.uuid4()),
        session_id=checked_id,
        owner_id=user.user_id,
        department_id=user.department_id,
        role=role,
        content=clean_content,
        data_json=data_json,
        created_at=utcnow(),
    )
    db.add(message)
    db.flush()
    return _serialize(message)
