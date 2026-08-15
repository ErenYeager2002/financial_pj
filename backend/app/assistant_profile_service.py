from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import UserContext
from .contracts import AdminAssistantProfile, AssistantStatus
from .credential_service import decrypt_secret
from .model_providers import build_extra_body, get_provider
from .models import ModelConnection, ModelProfile
from .orchestrator import LlmConfig

PROFILE_PURPOSE = "finance-assistant"


def _profile(db: Session, department_id: str) -> ModelProfile | None:
    return db.scalar(
        select(ModelProfile).where(
            ModelProfile.department_id == department_id,
            ModelProfile.purpose == PROFILE_PURPOSE,
        )
    )


def assistant_status(db: Session, user: UserContext) -> AssistantStatus:
    profile = _profile(db, user.department_id)
    connection = db.get(ModelConnection, profile.connection_id) if profile else None
    return AssistantStatus(
        configured=bool(profile and connection and connection.status == "connected")
    )


def admin_profile(db: Session, user: UserContext) -> AdminAssistantProfile:
    profile = _profile(db, user.department_id)
    connection = db.get(ModelConnection, profile.connection_id) if profile else None
    if not profile or not connection:
        return AdminAssistantProfile(configured=False)
    return AdminAssistantProfile(
        configured=connection.status == "connected",
        connection_id=connection.id,
        provider_name=connection.provider_name,
        api_key_hint=connection.api_key_hint,
        model=profile.model,
        updated_at=profile.updated_at,
    )


def configure_assistant_profile(
    db: Session,
    user: UserContext,
    connection_id: str,
    model: str,
) -> AdminAssistantProfile:
    connection = db.get(ModelConnection, connection_id)
    if not connection or connection.department_id != user.department_id:
        raise HTTPException(status_code=404, detail="模型连接不存在。")
    if connection.status != "connected":
        raise HTTPException(status_code=409, detail="模型连接当前不可用。")
    models = json.loads(connection.models_json or "[]")
    if model not in models:
        raise HTTPException(status_code=422, detail="模型不在当前连接的可用列表中。")
    profile = _profile(db, user.department_id)
    now = datetime.now(UTC)
    if profile:
        profile.connection_id = connection.id
        profile.model = model
        profile.configured_by = user.user_id
        profile.updated_at = now
    else:
        profile = ModelProfile(
            id=str(uuid.uuid4()),
            department_id=user.department_id,
            purpose=PROFILE_PURPOSE,
            connection_id=connection.id,
            model=model,
            configured_by=user.user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(profile)
    db.flush()
    return admin_profile(db, user)


def remove_assistant_profile(db: Session, user: UserContext) -> None:
    profile = _profile(db, user.department_id)
    if profile:
        db.delete(profile)
        db.flush()


def resolve_assistant_config(db: Session, user: UserContext) -> LlmConfig:
    profile = _profile(db, user.department_id)
    if not profile:
        raise HTTPException(status_code=409, detail="AI 助手尚未配置，请联系管理员。")
    connection = db.get(ModelConnection, profile.connection_id)
    if not connection or connection.department_id != user.department_id:
        raise HTTPException(status_code=409, detail="AI 助手的模型连接已经不可用。")
    models = json.loads(connection.models_json or "[]")
    if connection.status != "connected" or profile.model not in models:
        raise HTTPException(status_code=409, detail="AI 助手的模型当前不可用。")
    provider = get_provider(connection.provider)
    return LlmConfig(
        provider=connection.provider,
        connection_id=connection.id,
        base_url=connection.base_url,
        api_key=decrypt_secret(connection.api_key_encrypted),
        model=profile.model,
        protocol=provider.protocol if provider else "chat_completions",
        extra_body=build_extra_body(connection.provider, profile.model),
    )
