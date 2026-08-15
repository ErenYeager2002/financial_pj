from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import UserContext
from .credential_service import decrypt_secret, encrypt_secret
from .model_providers import (
    DISCOVERY_API,
    DISCOVERY_MANUAL,
    ProviderDefinition,
    build_extra_body,
    filter_candidate_models,
    get_provider,
    secure_llm_request,
    validate_https_base_url,
)
from .models import ModelConnection, ModelProfile
from .orchestrator import LlmConfig
from .schemas import ModelConnectionRead


def _hint(api_key: str) -> str:
    prefix = api_key[:3] if len(api_key) >= 3 else ""
    return f"{prefix}••••••••{api_key[-4:]}"


def _fetch_models(
    provider: ProviderDefinition,
    api_key: str,
    base_url: str,
) -> list[str]:
    response = secure_llm_request(
        "GET",
        provider,
        base_url,
        "/models",
        api_key,
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    return [
        str(item["id"])
        for item in payload.get("data", [])
        if isinstance(item, dict) and item.get("id")
    ]


def _discover_models(
    provider: ProviderDefinition,
    api_key: str,
    base_url: str,
) -> list[str]:
    if provider.discovery_mode == DISCOVERY_MANUAL:
        return []
    try:
        return filter_candidate_models(provider, _fetch_models(provider, api_key, base_url))
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        if provider.discovery_mode == DISCOVERY_API:
            raise ValueError("无法从该供应商读取模型列表，请检查 API Key 与网络连接。") from exc
        return []


def _is_requested_model_excluded(provider: ProviderDefinition, model: str) -> bool:
    return provider.matches_exclude(model)


def _resolve_models(
    provider: ProviderDefinition,
    discovered: list[str],
    requested_model: str | None,
) -> list[str]:
    """按发现模式严格解析最终模型列表。

    - api：必须来自 /models 目录；目录为空即报错，手工模型不能绕过目录。
    - manual：必须手工填写，不读取目录；命中排除规则拒绝。
    - hybrid：手工模型必须通过排除规则并追加进发现列表，不丢弃既有发现；
      目录为空且无手工模型时报错。
    """
    requested = requested_model.strip() if requested_model else ""
    if provider.discovery_mode == DISCOVERY_MANUAL:
        if not requested:
            raise ValueError("该供应商需要手动填写模型名称或部署 ID。")
        if _is_requested_model_excluded(provider, requested):
            raise ValueError(f"模型 {requested} 不在该供应商支持的对话模型范围内。")
        return [requested]
    if provider.discovery_mode == DISCOVERY_API:
        if not discovered:
            raise ValueError("该账号没有发现可用模型，请检查 API Key 与网络连接。")
        if requested and requested not in discovered:
            raise ValueError(f"模型 {requested} 不在该账号的可用列表中。")
        return discovered
    if requested and _is_requested_model_excluded(provider, requested):
        raise ValueError(f"模型 {requested} 不在该供应商支持的对话模型范围内。")
    if not discovered:
        if requested:
            return [requested]
        raise ValueError("该账号没有发现可用模型，请填写模型名称或部署 ID。")
    if not requested or requested in discovered:
        return discovered
    if provider.allow_manual_model:
        return [requested, *discovered]
    raise ValueError(f"模型 {requested} 不在该账号的可用列表中。")


def _default_model(provider: ProviderDefinition, models: list[str]) -> str:
    for preferred in provider.preferred_models:
        if preferred in models:
            return preferred
    return models[0]


def _has_expected_tool_call(body: object) -> bool:
    """校验响应确实包含指向 tool_call_supported 的 Tool Calling 调用。"""
    try:
        choices = body["choices"]  # type: ignore[index]
        message = choices[0]["message"]
        calls = message.get("tool_calls") or []
        function = calls[0].get("function") or {}
        if function.get("name") != "tool_call_supported":
            return False
        arguments = json.loads(function.get("arguments") or "{}")
        return isinstance(arguments, dict)
    except (KeyError, IndexError, TypeError, AttributeError, json.JSONDecodeError):
        return False


def _verify_tool_calling(
    provider: ProviderDefinition,
    api_key: str,
    base_url: str,
    model: str,
) -> None:
    # MiniMax OpenAI 兼容端点不支持 tool_choice 对象形式（仅 none/auto），
    # 且 M3 思考默认开启会占用 max_tokens；改用 system 指令强制调用工具。
    is_minimax = provider.id == "minimax"
    payload: dict[str, Any] = {
        "model": model,
        "messages": (
            [
                {
                    "role": "system",
                    "content": "你必须调用提供的 tool_call_supported 工具并返回空参数对象。",
                },
                {"role": "user", "content": "ping"},
            ]
            if is_minimax
            else [{"role": "user", "content": "ping"}]
        ),
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "tool_call_supported",
                    "description": "验证模型是否支持 Tool Calling",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            }
        ],
        "max_tokens": 1024 if is_minimax else 32,
        "temperature": 0,
    }
    if not is_minimax:
        payload["tool_choice"] = {
            "type": "function",
            "function": {"name": "tool_call_supported"},
        }
    payload.update(build_extra_body(provider.id, model))
    try:
        response = secure_llm_request(
            "POST",
            provider,
            base_url,
            "/chat/completions",
            api_key,
            payload,
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as exc:
        raise ValueError(
            f"模型 {model} 未通过 Tool Calling 验证"
            f"（HTTP {exc.response.status_code}），请更换模型。"
        ) from exc
    except httpx.HTTPError as exc:
        raise ValueError(
            f"模型 {model} 无法完成 Tool Calling 验证：{type(exc).__name__}。"
        ) from exc
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"模型 {model} 返回成功，但没有完成平台要求的 Tool Calling 验证。"
        ) from exc
    if not _has_expected_tool_call(body):
        raise ValueError(
            f"模型 {model} 返回成功，但没有完成平台要求的 Tool Calling 验证。"
        )


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


def _effective_base_url(provider: ProviderDefinition, base_url: str | None) -> str:
    if provider.base_url:
        if base_url and base_url.strip().rstrip("/") != provider.base_url:
            raise HTTPException(
                status_code=422,
                detail="内置供应商的接入地址已固定，不可修改。",
            )
        return provider.base_url
    return validate_https_base_url(base_url)


def _store_connection(
    db: Session,
    user: UserContext,
    provider: ProviderDefinition,
    api_key: str,
    base_url: str,
    models: list[str],
    selected_model: str,
) -> ModelConnectionRead:
    fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    existing = db.scalar(
        select(ModelConnection).where(
            ModelConnection.owner_id == user.user_id,
            ModelConnection.department_id == user.department_id,
            ModelConnection.provider == provider.id,
            ModelConnection.base_url == base_url,
            ModelConnection.api_key_fingerprint == fingerprint,
        )
    )
    now = datetime.now(UTC)
    if existing:
        existing.models_json = json.dumps(models, ensure_ascii=False)
        if existing.selected_model not in models:
            existing.selected_model = selected_model
        existing.provider_name = provider.name
        existing.base_url = base_url
        existing.status = "connected"
        existing.last_checked_at = now
        existing.api_key_encrypted = encrypt_secret(api_key)
        existing.api_key_hint = _hint(api_key)
        connection = existing
    else:
        connection = ModelConnection(
            id=str(uuid.uuid4()),
            owner_id=user.user_id,
            department_id=user.department_id,
            provider=provider.id,
            provider_name=provider.name,
            base_url=base_url,
            api_key_encrypted=encrypt_secret(api_key),
            api_key_hint=_hint(api_key),
            api_key_fingerprint=fingerprint,
            models_json=json.dumps(models, ensure_ascii=False),
            selected_model=selected_model,
            status="connected",
            last_checked_at=now,
        )
        db.add(connection)
    db.commit()
    db.refresh(connection)
    return serialize_connection(connection)


def connect_api_key(
    db: Session,
    user: UserContext,
    api_key: str,
    provider_id: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> ModelConnectionRead:
    clean_key = api_key.strip()
    if not clean_key:
        raise HTTPException(status_code=422, detail="API Key 不能为空。")

    requested_id = provider_id.strip() if provider_id else ""
    if not requested_id:
        # 兼容旧客户端：只尝试千问，不向其他供应商探测。
        provider = get_provider("qwen")
        assert provider is not None
        try:
            models = _discover_models(provider, clean_key, provider.base_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not models:
            raise HTTPException(
                status_code=422,
                detail="该账号没有发现支持 Tool Calling 的千问文本模型。",
            )
        selected_model = _default_model(provider, models)
        try:
            _verify_tool_calling(provider, clean_key, provider.base_url, selected_model)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _store_connection(
            db,
            user,
            provider,
            clean_key,
            provider.base_url,
            models,
            selected_model,
        )

    provider = get_provider(requested_id)
    if not provider:
        raise HTTPException(status_code=422, detail=f"不支持的模型供应商：{requested_id}")
    if provider.admin_only and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有管理员可以接入自定义模型服务。")

    try:
        effective_base_url = _effective_base_url(provider, base_url)
        requested_model = model.strip() if model else ""
        discovered = _discover_models(provider, clean_key, effective_base_url)
        models = _resolve_models(provider, discovered, requested_model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    selected_model = (
        requested_model
        if requested_model in models
        else _default_model(provider, models)
    )
    try:
        _verify_tool_calling(provider, clean_key, effective_base_url, selected_model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _store_connection(
        db,
        user,
        provider,
        clean_key,
        effective_base_url,
        models,
        selected_model,
    )


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
    provider = get_provider(connection.provider)
    if not provider:
        raise HTTPException(status_code=422, detail="当前模型供应商不再受支持。")
    api_key = decrypt_secret(connection.api_key_encrypted)
    try:
        _verify_tool_calling(provider, api_key, connection.base_url, model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    provider = get_provider(connection.provider)
    if not provider:
        raise HTTPException(status_code=422, detail="当前模型供应商不再受支持。")
    api_key = decrypt_secret(connection.api_key_encrypted)
    try:
        if provider.base_url:
            discovered = _discover_models(provider, api_key, connection.base_url)
            models = _resolve_models(provider, discovered, None)
        else:
            # 自定义服务地址由管理员录入：刷新时按混合模式尽力发现，失败保留原列表。
            try:
                discovered = _discover_models(provider, api_key, connection.base_url)
                models = _resolve_models(provider, discovered, None)
            except ValueError:
                models = json.loads(connection.models_json or "[]")
                if not models:
                    raise
    except (httpx.HTTPError, ValueError) as exc:
        connection.status = "error"
        db.commit()
        raise HTTPException(
            status_code=422,
            detail=f"模型连接验证失败：{type(exc).__name__}",
        ) from exc
    connection.models_json = json.dumps(models, ensure_ascii=False)
    if connection.selected_model not in models:
        connection.selected_model = _default_model(provider, models)
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
    if db.scalar(select(ModelProfile).where(ModelProfile.connection_id == connection.id)):
        raise HTTPException(
            status_code=409,
            detail="该模型连接正在被 AI 助手使用，请先更换助手配置。",
        )
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
    provider = get_provider(connection.provider)
    return LlmConfig(
        provider=connection.provider,
        connection_id=connection.id,
        base_url=connection.base_url,
        api_key=decrypt_secret(connection.api_key_encrypted),
        model=model,
        protocol=provider.protocol if provider else "chat_completions",
        extra_body=build_extra_body(connection.provider, model),
    )
