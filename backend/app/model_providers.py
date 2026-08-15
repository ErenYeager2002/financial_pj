from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass, field
from re import Pattern
from typing import Any
from urllib.parse import urlparse

import httpx

from .settings import settings

PROTOCOL_CHAT_COMPLETIONS = "chat_completions"

DISCOVERY_API = "api"
DISCOVERY_MANUAL = "manual"
DISCOVERY_HYBRID = "hybrid"


@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    name: str
    protocol: str
    base_url: str
    discovery_mode: str
    include_patterns: tuple[str, ...]
    exclude_patterns: tuple[str, ...] = ()
    preferred_models: tuple[str, ...] = ()
    allow_manual_model: bool = False
    admin_only: bool = False
    _compiled_include: tuple[Pattern[str], ...] = field(init=False, repr=False)
    _compiled_exclude: tuple[Pattern[str], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_compiled_include",
            tuple(re.compile(pattern) for pattern in self.include_patterns),
        )
        object.__setattr__(
            self,
            "_compiled_exclude",
            tuple(re.compile(pattern, re.IGNORECASE) for pattern in self.exclude_patterns),
        )

    def matches_include(self, model: str) -> bool:
        if not self._compiled_include:
            return True
        return any(pattern.search(model) for pattern in self._compiled_include)

    def matches_exclude(self, model: str) -> bool:
        return any(pattern.search(model) for pattern in self._compiled_exclude)


PROVIDERS: tuple[ProviderDefinition, ...] = (
    ProviderDefinition(
        id="qwen",
        name="阿里云百炼 / 千问",
        protocol=PROTOCOL_CHAT_COMPLETIONS,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        discovery_mode=DISCOVERY_API,
        include_patterns=(
            r"^qwen3(?:\.\d+)?-(?:max|plus|flash|turbo|deepseek)(?:-[\w.-]*)?$",
            r"^qwen-(?:max|plus|flash|turbo)(?:-\d{4}-\d{2}-\d{2})?$",
        ),
        exclude_patterns=(
            r"(?:^|[-_])(?:vl|vlm|omni|audio|video|image|vision|ocr|multimodal)(?:[-_]|$)",
            r"embedding|rerank|moderation|tts|asr|whisper|longtext",
        ),
        preferred_models=(
            "qwen3.8-max-preview",
            "qwen3.7-plus",
            "qwen3.7-max",
            "qwen3.6-plus",
            "qwen3.6-flash",
            "qwen3.5-plus",
            "qwen3.5-flash",
            "qwen-plus",
        ),
    ),
    ProviderDefinition(
        id="deepseek",
        name="DeepSeek",
        protocol=PROTOCOL_CHAT_COMPLETIONS,
        base_url="https://api.deepseek.com",
        discovery_mode=DISCOVERY_API,
        include_patterns=(
            r"^deepseek-(?:chat|reasoner)$",
            r"^deepseek-v\d+(?:-[a-z][\w.-]*)?$",
        ),
        exclude_patterns=(r"embedding|rerank|moderation|tts|asr|whisper",),
        preferred_models=("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat"),
    ),
    ProviderDefinition(
        id="zhipu",
        name="智谱 AI",
        protocol=PROTOCOL_CHAT_COMPLETIONS,
        base_url="https://open.bigmodel.cn/api/paas/v4",
        discovery_mode=DISCOVERY_API,
        include_patterns=(r"^glm-[\w.-]+$",),
        exclude_patterns=(
            r"embedding|image|video|audio|tts|asr|ocr|codegeex|moderation",
            r"cogview|cogvideo|cogagent|vlm|vision",
            r"glm-4v|glm-4\.1v|glm-4\.5v",
        ),
        preferred_models=(
            "glm-5.2",
            "glm-5",
            "glm-4.7",
            "glm-4.6",
            "glm-4.5",
            "glm-4.5-air",
            "glm-4-flash",
        ),
    ),
    ProviderDefinition(
        id="moonshot",
        name="Moonshot / Kimi",
        protocol=PROTOCOL_CHAT_COMPLETIONS,
        base_url="https://api.moonshot.cn/v1",
        discovery_mode=DISCOVERY_API,
        include_patterns=(
            r"^moonshot-v1-[a-z0-9.-]+$",
            r"^kimi-k[\d.]+(?:-[\w.-]+)?$",
            r"^kimi-latest$",
        ),
        exclude_patterns=(r"vision|embedding|image|audio|tts|asr|rerank|moderation|long",),
        preferred_models=(
            "kimi-k3",
            "kimi-k2.6",
            "kimi-k2.5",
            "moonshot-v1-32k",
            "moonshot-v1-8k",
        ),
    ),
    ProviderDefinition(
        id="openai",
        name="OpenAI",
        protocol=PROTOCOL_CHAT_COMPLETIONS,
        base_url="https://api.openai.com/v1",
        discovery_mode=DISCOVERY_API,
        include_patterns=(
            r"^gpt-(?:4o|4\.1|4\.5|5|6)[\w.-]*$",
            r"^chatgpt-4o(?:-[\w.-]+)?$",
        ),
        exclude_patterns=(
            r"embedding|image|audio|speech|tts|asr|whisper|moderation|realtime|vision",
        ),
        preferred_models=(
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4.1",
            "gpt-5.2",
            "gpt-5.1",
            "gpt-5",
        ),
    ),
    ProviderDefinition(
        id="doubao",
        name="火山方舟 / 豆包",
        protocol=PROTOCOL_CHAT_COMPLETIONS,
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        discovery_mode=DISCOVERY_HYBRID,
        include_patterns=(
            r"^doubao(?:-[a-z0-9]+)+[\w.-]*$",
            r"^ep-[a-z0-9-]+$",
        ),
        exclude_patterns=(
            r"embedding|image|video|audio|tts|asr|vision|ocr|rerank|moderation",
            r"seedream|seedance|seemore|seededit",
        ),
        preferred_models=(
            "doubao-seed-2-1-pro-260628",
            "doubao-seed-2-1-flash-260628",
            "doubao-seed-1-6-flash-250615",
            "doubao-pro-32k",
        ),
        allow_manual_model=True,
    ),
    ProviderDefinition(
        id="minimax",
        name="MiniMax / 海螺 AI",
        protocol=PROTOCOL_CHAT_COMPLETIONS,
        base_url="https://api.minimaxi.com/v1",
        discovery_mode=DISCOVERY_API,
        include_patterns=(r"^MiniMax-[A-Za-z0-9]+(?:[.-][\w.-]*)?$",),
        exclude_patterns=(
            r"vl|vision|image|video|audio|speech|tts|asr|whisper|embedding",
            r"rerank|moderation|ocr|music",
            r"(?:^|-)her$",
        ),
        preferred_models=(
            "MiniMax-M3",
            "MiniMax-M2.7",
            "MiniMax-M2.7-highspeed",
            "MiniMax-M2.5",
            "MiniMax-M2.1",
            "MiniMax-M2",
        ),
    ),
    ProviderDefinition(
        id="custom_openai",
        name="自定义 OpenAI 兼容服务",
        protocol=PROTOCOL_CHAT_COMPLETIONS,
        base_url="",
        discovery_mode=DISCOVERY_HYBRID,
        include_patterns=(),
        exclude_patterns=(r"embedding|image|audio|speech|tts|asr|whisper|moderation|realtime|vision|rerank",),
        preferred_models=(),
        allow_manual_model=True,
        admin_only=True,
    ),
)

_PROVIDERS_BY_ID: dict[str, ProviderDefinition] = {item.id: item for item in PROVIDERS}

_QWEN3_PATTERN = re.compile(r"^qwen3(?:\.\d+)?-")
_KIMI_K2_PATTERN = re.compile(r"^kimi-k2[\d.]")
_MINIMAX_M3_PATTERN = re.compile(r"^MiniMax-M3(?:[.-]|$)")


def get_provider(provider_id: str | None) -> ProviderDefinition | None:
    if not provider_id:
        return None
    return _PROVIDERS_BY_ID.get(provider_id.strip())


def list_public_providers(include_admin_only: bool = False) -> list[ProviderDefinition]:
    return [item for item in PROVIDERS if include_admin_only or not item.admin_only]


def filter_candidate_models(provider: ProviderDefinition, raw_models: list[str]) -> list[str]:
    models = sorted(
        {
            item
            for item in raw_models
            if provider.matches_include(item) and not provider.matches_exclude(item)
        }
    )
    preference = {name: index for index, name in enumerate(provider.preferred_models)}
    return sorted(
        models,
        key=lambda item: (
            0 if item in preference else 1,
            preference.get(item, 999),
            bool(re.search(r"-\d{4}-\d{2}-\d{2}$", item)),
            item,
        ),
    )


def build_extra_body(provider_id: str, model: str) -> dict[str, Any]:
    if provider_id == "qwen" and _QWEN3_PATTERN.match(model):
        return {"enable_thinking": False}
    if provider_id == "moonshot" and _KIMI_K2_PATTERN.match(model):
        return {"thinking": {"type": "disabled"}}
    if provider_id == "minimax" and _MINIMAX_M3_PATTERN.match(model):
        return {"thinking": {"type": "disabled"}}
    return {}


def custom_host_allowlist() -> tuple[str, ...]:
    """管理员配置的自定义模型服务白名单（精确主机名，不含协议与路径）。"""
    return settings.custom_llm_host_allowlist


def validate_https_base_url(base_url: str | None) -> str:
    """校验自定义 OpenAI 兼容服务地址：必须 HTTPS、主机名与白名单精确匹配、
    不允许 userinfo/片段，且解析出的所有 IP 必须为公网地址
    （is_global 且非组播，防 DNS rebinding 与非公网共享地址）。"""
    raw = (base_url or "").strip().rstrip("/")
    if not raw:
        raise ValueError("自定义服务需要填写 HTTPS 接入地址。")
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise ValueError("自定义服务接入地址必须使用 HTTPS。")
    if parsed.username or parsed.password:
        raise ValueError("自定义服务接入地址不允许包含用户名或密码。")
    if parsed.fragment:
        raise ValueError("自定义服务接入地址不允许包含片段(#)。")
    host = parsed.hostname
    if not host:
        raise ValueError("自定义服务接入地址无效。")
    allowed = custom_host_allowlist()
    if not allowed:
        raise ValueError("尚未配置允许的自定义模型服务域名。")
    if host.lower() not in allowed:
        raise ValueError("自定义服务域名不在管理员配置的允许列表中。")
    try:
        addresses = [
            ipaddress.ip_address(address[4][0])
            for address in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        ]
    except (socket.gaierror, OSError) as exc:
        raise ValueError("自定义服务接入地址无法解析。") from exc
    if not addresses:
        raise ValueError("自定义服务接入地址无法解析。")
    for address in addresses:
        if not address.is_global or address.is_multicast:
            raise ValueError(
                "自定义服务接入地址不允许指向内网、回环或非公网地址。"
            )
    port = f":{parsed.port}" if parsed.port and parsed.port != 443 else ""
    suffix = f"?{parsed.query}" if parsed.query else ""
    return f"https://{host.lower()}{port}{parsed.path}{suffix}"


def secure_llm_request(
    method: str,
    provider: ProviderDefinition | None,
    base_url: str,
    path: str,
    api_key: str,
    json_body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    """统一模型 HTTP 入口。

    自定义服务（provider.base_url 为空）每次请求前重新执行白名单与公网地址
    校验，且不跟随重定向；内置厂商保持原请求行为。
    """
    is_custom = provider is not None and not provider.base_url
    if is_custom:
        base_url = validate_https_base_url(base_url)
    kwargs: dict[str, Any] = {
        "headers": {"Authorization": f"Bearer {api_key}"},
        "timeout": timeout,
    }
    if json_body is not None:
        kwargs["json"] = json_body
    if is_custom:
        kwargs["follow_redirects"] = False
    request = httpx.get if method.upper() == "GET" else httpx.post
    return request(f"{base_url}{path}", **kwargs)


def chat_completion_request(
    provider_id: str,
    base_url: str,
    api_key: str,
    json_body: dict[str, Any],
    timeout: float = 30.0,
) -> httpx.Response:
    """运行态统一入口：自定义 OpenAI 兼容服务每次真实调用都经过安全校验。"""
    provider = get_provider(provider_id)
    return secure_llm_request(
        "POST",
        provider,
        base_url,
        "/chat/completions",
        api_key,
        json_body,
        timeout,
    )
