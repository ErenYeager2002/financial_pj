from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import UserContext
from .credential_service import decrypt_secret, encrypt_secret
from .models import ModelConnection
from .orchestrator import LlmConfig
from .schemas import ModelConnectionRead


@dataclass(frozen=True)
class ProviderCandidate:
    id: str
    name: str
    base_url: str


PROVIDERS = (
    ProviderCandidate(
        id="qwen",
        name="阿里云百炼 / 千问",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
)

QWEN_FUNCTION_MODEL = re.compile(
    r"^(?:"
    r"qwen3\.8-max-preview|"
    r"qwen3\.7-(?:max|plus)(?:-\d{4}-\d{2}-\d{2})?|"
    r"qwen3\.6-(?:max|plus|flash)(?:-\d{4}-\d{2}-\d{2})?|"
    r"qwen3\.5-(?:plus|flash)(?:-\d{4}-\d{2}-\d{2})?|"
    r"qwen-(?:max|plus|flash|turbo)(?:-\d{4}-\d{2}-\d{2})?"
    r")$",
    re.IGNORECASE,
)

MODEL_PREFERENCE = (
    "qwen3.7-plus",
    "qwen3.7-max",
    "qwen3.6-plus",
    "qwen3.6-flash",
    "qwen-plus",
)


def _hint(api_key: str) -> str:
    prefix = api_key[:3] if len(api_key) >= 3 else ""
    return f"{prefix}••••••••{api_key[-4:]}"


def _filter_models(raw_models: list[str]) -> list[str]:
    models = sorted({item for item in raw_models if QWEN_FUNCTION_MODEL.match(item)})
    preference = {name: index for index, name in enumerate(MODEL_PREFERENCE)}
    return sorted(
        models,
        key=lambda item: (
            0 if item in preference else 1,
            preference.get(item, 999),
            bool(re.search(r"-\d{4}-\d{2}-\d{2}$", item)),
            item,
        ),
    )


def _probe(api_key: str, provider: ProviderCandidate) -> list[str]:
    response = httpx.get(
        f"{provider.base_url}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    raw_models = [
        str(item["id"])
        for item in payload.get("data", [])
        if isinstance(item, dict) and item.get("id")
    ]
    models = _filter_models(raw_models)
    if not models:
        raise ValueError("该账号没有发现支持 Tool Calling 的千问文本模型。")
    return models


def _default_model(models: list[str]) -> str:
    for preferred in MODEL_PREFERENCE:
        if preferred in models:
            return preferred
    return models[0]


def serialize_connection(connection: ModelConnection) -> ModelConnectionRead:
    return ModelConnectionRead(
        id=connection.id,
        provider=connection.provider,
        provider_name=connection.provider_name,
        api_key_hint=connection.api_key_hint,
        models=json.loads(connection.models_json or "[]"),
        selected_model=connection.selected_model,
        status=connection.status,
        last_checked_at=connection.last_checked_at,
        created_at=connection.created_at,
    )


def list_connections(
    db: Session,
    user: UserContext,
) -> list[ModelConnectionRead]:
    query = select(ModelConnection).where(ModelConnection.department_id == user.department_id)
    if not user.is_admin:
        query = query.where(ModelConnection.owner_id == user.user_id)
    query = query.order_by(ModelConnection.created_at.desc())
    return [serialize_connection(item) for item in db.scalars(query).all()]


def connect_api_key(
    db: Session,
    user: UserContext,
    api_key: str,
) -> ModelConnectionRead:
    clean_key = api_key.strip()
    if not clean_key:
        raise HTTPException(status_code=422, detail="API Key 不能为空。")
    detected: tuple[ProviderCandidate, list[str]] | None = None
    for provider in PROVIDERS:
        try:
            detected = provider, _probe(clean_key, provider)
            break
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            continue
    if not detected:
        raise HTTPException(
            status_code=422,
            detail="无法识别或验证该 API Key。请确认密钥有效且服务器可以访问模型服务。",
        )

    provider, models = detected
    fingerprint = hashlib.sha256(clean_key.encode("utf-8")).hexdigest()
    existing = db.scalar(
        select(ModelConnection).where(
            ModelConnection.owner_id == user.user_id,
            ModelConnection.department_id == user.department_id,
            ModelConnection.api_key_fingerprint == fingerprint,
        )
    )
    now = datetime.now(UTC)
    if existing:
        existing.models_json = json.dumps(models, ensure_ascii=False)
        if existing.selected_model not in models:
            existing.selected_model = _default_model(models)
        existing.status = "connected"
        existing.last_checked_at = now
        existing.api_key_encrypted = encrypt_secret(clean_key)
        connection = existing
    else:
        connection = ModelConnection(
            id=str(uuid.uuid4()),
            owner_id=user.user_id,
            department_id=user.department_id,
            provider=provider.id,
            provider_name=provider.name,
            base_url=provider.base_url,
            api_key_encrypted=encrypt_secret(clean_key),
            api_key_hint=_hint(clean_key),
            api_key_fingerprint=fingerprint,
            models_json=json.dumps(models, ensure_ascii=False),
            selected_model=_default_model(models),
            status="connected",
            last_checked_at=now,
        )
        db.add(connection)
    db.commit()
    db.refresh(connection)
    return serialize_connection(connection)


def get_connection(
    db: Session,
    user: UserContext,
    connection_id: str,
) -> ModelConnection:
    connection = db.get(ModelConnection, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="模型连接不存在。")
    if connection.department_id != user.department_id:
        raise HTTPException(status_code=403, detail="无权使用其他部门的模型连接。")
    if connection.owner_id != user.user_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="无权使用其他员工的模型连接。")
    return connection


def select_model(
    db: Session,
    user: UserContext,
    connection_id: str,
    model: str,
) -> ModelConnectionRead:
    connection = get_connection(db, user, connection_id)
    models = json.loads(connection.models_json or "[]")
    if model not in models:
        raise HTTPException(status_code=422, detail="该模型不在当前 API Key 的可用列表中。")
    connection.selected_model = model
    connection.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(connection)
    return serialize_connection(connection)


def refresh_connection(
    db: Session,
    user: UserContext,
    connection_id: str,
) -> ModelConnectionRead:
    connection = get_connection(db, user, connection_id)
    provider = next((item for item in PROVIDERS if item.id == connection.provider), None)
    if not provider:
        raise HTTPException(status_code=422, detail="当前模型供应商不再受支持。")
    try:
        models = _probe(decrypt_secret(connection.api_key_encrypted), provider)
    except (httpx.HTTPError, ValueError) as exc:
        connection.status = "error"
        db.commit()
        raise HTTPException(
            status_code=422,
            detail=f"模型连接验证失败：{type(exc).__name__}",
        ) from exc
    connection.models_json = json.dumps(models, ensure_ascii=False)
    if connection.selected_model not in models:
        connection.selected_model = _default_model(models)
    connection.status = "connected"
    connection.last_checked_at = datetime.now(UTC)
    db.commit()
    db.refresh(connection)
    return serialize_connection(connection)


def remove_connection(
    db: Session,
    user: UserContext,
    connection_id: str,
) -> None:
    connection = get_connection(db, user, connection_id)
    db.delete(connection)
    db.commit()


def resolve_runtime_config(
    db: Session,
    user: UserContext,
    connection_id: str | None,
    requested_model: str | None,
) -> LlmConfig | None:
    if not connection_id:
        return None
    connection = get_connection(db, user, connection_id)
    models = json.loads(connection.models_json or "[]")
    model = requested_model or connection.selected_model
    if model not in models:
        raise HTTPException(status_code=422, detail="所选模型当前不可用，请刷新模型列表。")
    return LlmConfig(
        provider=connection.provider,
        connection_id=connection.id,
        base_url=connection.base_url,
        api_key=decrypt_secret(connection.api_key_encrypted),
        model=model,
    )
