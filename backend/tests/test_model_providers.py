from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from helpers import auth_client

from app import model_service, orchestrator, workflow_orchestrator
from app.model_providers import (
    ProviderDefinition,
    build_extra_body,
    filter_candidate_models,
    get_provider,
    list_public_providers,
    validate_https_base_url,
)
from app.registry import registry


class FakeModelsResponse:
    def __init__(self, models: list[str]) -> None:
        self._models = models

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"data": [{"id": item} for item in self._models]}


class FakeOkResponse:
    """200 且包含符合验证要求的 choices/message/tool_calls 结构。"""

    def __init__(self, name: str = "tool_call_supported", arguments: str = "{}") -> None:
        self._name = name
        self._arguments = arguments

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": self._name,
                                    "arguments": self._arguments,
                                },
                            }
                        ],
                    }
                }
            ]
        }


class FakePlainTextResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> str:
        return "plain text"


class FakeEmptyToolCallsResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"choices": [{"message": {"role": "assistant", "content": "你好"}}]}


class FakeWrongToolNameResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return FakeOkResponse(name="other_function").json()


class FakeInvalidArgumentsResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return FakeOkResponse(arguments="not-a-json{").json()


class FakeHttpErrorResponse:
    def __init__(self, status_code: int) -> None:
        self._status = status_code

    def raise_for_status(self) -> None:
        request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
        raise httpx.HTTPStatusError(
            f"{self._status} Error",
            request=request,
            response=httpx.Response(self._status, request=request),
        )


class FakeToolResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "arguments": (
                                        '{"amount_tolerance":1,"date_tolerance_days":2}'
                                    )
                                }
                            }
                        ]
                    }
                }
            ]
        }


class FakeChatResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "这是回复内容。",
                    }
                }
            ]
        }


def offline(*_, **__):
    raise httpx.ConnectError("offline")


def cleanup_all_connections(client: TestClient) -> None:
    admin = {"X-User-Role": "skill_admin", "X-User-Id": "skill-admin"}
    for item in client.get("/api/model-connections", headers=admin).json():
        client.delete(f"/api/model-connections/{item['id']}", headers=admin)


def set_custom_allowlist(monkeypatch, hosts: str) -> None:
    monkeypatch.setenv("FINANCIAL_LLM_CUSTOM_HOST_ALLOWLIST", hosts)


def public_addrinfo(host, port, **kwargs):
    del host, port, kwargs
    return [(2, 1, 6, "", ("8.8.8.8", 443))]


# ---------- 注册表与过滤单元测试 ----------


def test_provider_registry_registers_seven_builtin_providers() -> None:
    providers = list_public_providers(include_admin_only=False)
    assert [item.id for item in providers] == [
        "qwen",
        "deepseek",
        "zhipu",
        "moonshot",
        "openai",
        "doubao",
        "minimax",
    ]
    assert all(item.protocol == "chat_completions" for item in providers)
    assert all(not item.admin_only for item in providers)
    assert get_provider("qwen").base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert get_provider("deepseek").base_url == "https://api.deepseek.com"
    assert get_provider("zhipu").base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert get_provider("moonshot").base_url == "https://api.moonshot.cn/v1"
    assert get_provider("openai").base_url == "https://api.openai.com/v1"
    assert get_provider("doubao").base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert get_provider("doubao").discovery_mode == "hybrid"
    assert get_provider("doubao").allow_manual_model is True
    assert get_provider("minimax").base_url == "https://api.minimaxi.com/v1"
    assert get_provider("minimax").discovery_mode == "api"

    custom = get_provider("custom_openai")
    assert custom is not None
    assert custom.admin_only is True
    assert custom.discovery_mode == "hybrid"
    assert custom.allow_manual_model is True
    assert get_provider("unknown") is None


def test_filter_candidate_models_qwen() -> None:
    provider = get_provider("qwen")
    models = filter_candidate_models(
        provider,
        [
            "qwen3.7-plus",
            "qwen3.7-max",
            "qwen3.6-flash-260528",
            "qwen-turbo",
            "qwen-image-2.0-pro",
            "qwen3-vl-plus",
            "text-embedding-v3",
            "qwen3.9-x-max",
        ],
    )
    assert models == ["qwen3.7-plus", "qwen3.7-max", "qwen-turbo", "qwen3.6-flash-260528"]


def test_filter_candidate_models_other_providers() -> None:
    deepseek_models = [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-chat",
        "deepseek-v5-turbo",
        "deepseek-embedding-v3",
    ]
    deepseek = filter_candidate_models(get_provider("deepseek"), deepseek_models)
    assert deepseek == [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-chat",
        "deepseek-v5-turbo",
    ]

    zhipu = filter_candidate_models(
        get_provider("zhipu"),
        ["glm-5.2", "glm-5", "glm-4.7", "glm-4v-flash", "glm-embedding-3", "cogview-4"],
    )
    assert zhipu == ["glm-5.2", "glm-5", "glm-4.7"]

    moonshot_models = [
        "kimi-k3",
        "kimi-k2.6",
        "kimi-k2.7-code",
        "moonshot-v1-8k",
        "moonshot-v1-8k-vision-preview",
        "kimi-k2-embedding",
    ]
    moonshot = filter_candidate_models(get_provider("moonshot"), moonshot_models)
    assert moonshot == ["kimi-k3", "kimi-k2.6", "moonshot-v1-8k", "kimi-k2.7-code"]

    doubao_models = [
        "doubao-seed-2-1-pro-260628",
        "doubao-pro-32k",
        "ep-20260101-abcde",
        "doubao-seedream-4-0",
        "doubao-seedance-1-0",
    ]
    doubao = filter_candidate_models(get_provider("doubao"), doubao_models)
    assert doubao == ["doubao-seed-2-1-pro-260628", "doubao-pro-32k", "ep-20260101-abcde"]

    minimax_models = [
        "MiniMax-M3",
        "MiniMax-M2.7",
        "MiniMax-M2.1-highspeed",
        "MiniMax-M2",
        "MiniMax-M2-her",
        "MiniMax-VL-01",
        "MiniMax-Text-01",
        "MiniMax-Speech-01",
        "speech-2.5-hd-turbo",
        "image-01",
        "video-01",
    ]
    minimax = filter_candidate_models(get_provider("minimax"), minimax_models)
    assert minimax == [
        "MiniMax-M3",
        "MiniMax-M2.7",
        "MiniMax-M2",
        "MiniMax-M2.1-highspeed",
        "MiniMax-Text-01",
    ]

    custom = filter_candidate_models(
        get_provider("custom_openai"),
        ["my-chat-model", "my-embedding-model"],
    )
    assert custom == ["my-chat-model"]


def test_filter_candidate_models_accepts_future_openai_models() -> None:
    openai_models = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-5.9",
        "gpt-5.9-mini",
        "text-embedding-3-large",
        "whisper-1",
        "gpt-4o-audio-preview",
    ]
    models = filter_candidate_models(get_provider("openai"), openai_models)
    assert models == ["gpt-4o", "gpt-4o-mini", "gpt-5.9", "gpt-5.9-mini"]


def test_build_extra_body_isolation() -> None:
    assert build_extra_body("qwen", "qwen3.7-plus") == {"enable_thinking": False}
    assert build_extra_body("qwen", "qwen-plus") == {}
    assert build_extra_body("moonshot", "kimi-k2.6") == {"thinking": {"type": "disabled"}}
    assert build_extra_body("moonshot", "moonshot-v1-8k") == {}
    assert build_extra_body("minimax", "MiniMax-M3") == {"thinking": {"type": "disabled"}}
    assert build_extra_body("minimax", "MiniMax-M3-priority") == {
        "thinking": {"type": "disabled"}
    }
    assert build_extra_body("minimax", "MiniMax-M2.7") == {}
    assert build_extra_body("minimax", "MiniMax-M2.1-highspeed") == {}
    for provider_id in (
        "deepseek",
        "zhipu",
        "moonshot",
        "openai",
        "doubao",
        "minimax",
        "custom_openai",
    ):
        assert build_extra_body(provider_id, "any-model") == {}
    assert build_extra_body("unknown", "any-model") == {}


def test_validate_https_base_url_rejects_non_public_targets(monkeypatch) -> None:
    set_custom_allowlist(monkeypatch, "1.1.1.1,trusted.example.com")
    for bad in (
        "",
        "http://1.1.1.1/v1",
        "https://127.0.0.1/v1",
        "https://localhost/v1",
        "https://192.168.50.10/v1",
        "https://10.0.0.5/v1",
        "https://169.254.169.254/latest",
        "https://[::1]/v1",
        "https://evil.example.com/v1",
        "https://user:pass@1.1.1.1/v1",
        "https://1.1.1.1/v1#fragment",
    ):
        with pytest.raises(ValueError):
            validate_https_base_url(bad)
    assert validate_https_base_url("https://1.1.1.1/v1") == "https://1.1.1.1/v1"


def test_validate_https_base_url_requires_allowlist(monkeypatch) -> None:
    monkeypatch.delenv("FINANCIAL_LLM_CUSTOM_HOST_ALLOWLIST", raising=False)
    with pytest.raises(ValueError, match="尚未配置允许的自定义模型服务域名"):
        validate_https_base_url("https://trusted.example.com/v1")


def test_validate_https_base_url_normalizes_port_and_path(monkeypatch) -> None:
    set_custom_allowlist(monkeypatch, "trusted.example.com")
    monkeypatch.setattr("app.model_providers.socket.getaddrinfo", public_addrinfo)
    assert (
        validate_https_base_url("https://TRUSTED.example.com:443/v1/")
        == "https://trusted.example.com/v1"
    )
    assert (
        validate_https_base_url("https://trusted.example.com:8443/v1")
        == "https://trusted.example.com:8443/v1"
    )


def test_validate_https_base_url_blocks_dns_rebinding(monkeypatch) -> None:
    set_custom_allowlist(monkeypatch, "public-looking.example.com")

    def fake_getaddrinfo(host, port, **kwargs):
        del host, port, kwargs
        return [(2, 1, 6, "", ("10.0.0.99", 443))]

    monkeypatch.setattr("app.model_providers.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError):
        validate_https_base_url("https://public-looking.example.com/v1")


def test_validate_https_base_url_rejects_any_non_global_ip(monkeypatch) -> None:
    set_custom_allowlist(monkeypatch, "mixed.example.com")

    def fake_getaddrinfo(host, port, **kwargs):
        del host, port, kwargs
        return [
            (2, 1, 6, "", ("8.8.8.8", 443)),
            (2, 1, 6, "", ("10.0.0.1", 443)),
        ]

    monkeypatch.setattr("app.model_providers.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError):
        validate_https_base_url("https://mixed.example.com/v1")


def test_validate_https_base_url_rejects_shared_and_special_addresses(
    monkeypatch,
) -> None:
    set_custom_allowlist(monkeypatch, "trusted.example.com")
    for ip in (
        "100.64.0.1",
        "100.127.255.254",
        "198.18.0.1",
        "192.0.0.8",
        "2001:db8::1",
        "224.0.0.1",
        "ff02::1",
    ):
        monkeypatch.setattr(
            "app.model_providers.socket.getaddrinfo",
            lambda host, port, ip=ip, **kwargs: [(2, 1, 6, "", (ip, 443))],
        )
        with pytest.raises(ValueError):
            validate_https_base_url("https://trusted.example.com/v1")


def test_validate_https_base_url_accepts_global_addresses(monkeypatch) -> None:
    set_custom_allowlist(monkeypatch, "trusted.example.com")
    for ip in ("1.1.1.1", "8.8.8.8", "2606:4700:4700::1111"):
        monkeypatch.setattr(
            "app.model_providers.socket.getaddrinfo",
            lambda host, port, ip=ip, **kwargs: [(2, 1, 6, "", (ip, 443))],
        )
        assert (
            validate_https_base_url("https://trusted.example.com/v1")
            == "https://trusted.example.com/v1"
        )


def test_validate_https_base_url_rejects_mixed_resolution(monkeypatch) -> None:
    set_custom_allowlist(monkeypatch, "trusted.example.com")
    monkeypatch.setattr(
        "app.model_providers.socket.getaddrinfo",
        lambda host, port, **kwargs: [
            (2, 1, 6, "", ("1.1.1.1", 443)),
            (2, 1, 6, "", ("100.64.0.1", 443)),
        ],
    )
    with pytest.raises(ValueError):
        validate_https_base_url("https://trusted.example.com/v1")


def test_manual_discovery_requires_model_and_skips_directory(monkeypatch) -> None:
    provider = ProviderDefinition(
        id="manual-test",
        name="Manual",
        protocol="chat_completions",
        base_url="https://manual.example.com/v1",
        discovery_mode="manual",
        include_patterns=(),
        preferred_models=(),
        allow_manual_model=True,
    )
    called: list[str] = []

    def fake_get(url, **kwargs):
        del kwargs
        called.append(url)
        return FakeModelsResponse([])

    monkeypatch.setattr(model_service.httpx, "get", fake_get)
    assert model_service._discover_models(provider, "sk-test", provider.base_url) == []
    with pytest.raises(ValueError):
        model_service._resolve_models(provider, [], None)
    assert model_service._resolve_models(provider, [], "my-manual-model") == ["my-manual-model"]
    assert called == []


def test_api_mode_rejects_unknown_requested_model() -> None:
    provider = get_provider("qwen")
    assert model_service._resolve_models(provider, ["qwen3.7-plus"], "qwen3.7-plus") == [
        "qwen3.7-plus"
    ]
    with pytest.raises(ValueError):
        model_service._resolve_models(provider, ["qwen3.7-plus"], "qwen-unknown-model")
    with pytest.raises(ValueError):
        model_service._resolve_models(provider, [], None)


def test_api_mode_empty_discovery_rejects_manual_bypass() -> None:
    provider = get_provider("qwen")
    with pytest.raises(ValueError):
        model_service._resolve_models(provider, [], "arbitrary-model")


def test_hybrid_mode_keeps_discovery_and_appends_manual_model() -> None:
    provider = get_provider("doubao")
    models = model_service._resolve_models(
        provider,
        ["doubao-seed-2-1-pro-260628"],
        "ep-20260101-abcde",
    )
    assert models == ["ep-20260101-abcde", "doubao-seed-2-1-pro-260628"]
    assert model_service._resolve_models(
        provider, ["doubao-seed-2-1-pro-260628"], None
    ) == ["doubao-seed-2-1-pro-260628"]
    assert model_service._resolve_models(
        provider, ["doubao-seed-2-1-pro-260628"], "doubao-seed-2-1-pro-260628"
    ) == ["doubao-seed-2-1-pro-260628"]


def test_hybrid_mode_rejects_excluded_manual_model() -> None:
    provider = get_provider("doubao")
    with pytest.raises(ValueError):
        model_service._resolve_models(
            provider,
            ["doubao-seed-2-1-pro-260628"],
            "doubao-seedream-4-0",
        )
    with pytest.raises(ValueError):
        model_service._resolve_models(provider, [], "doubao-seedream-4-0")


def test_manual_mode_requires_model_and_rejects_excluded() -> None:
    provider = ProviderDefinition(
        id="manual-test",
        name="Manual",
        protocol="chat_completions",
        base_url="https://manual.example.com/v1",
        discovery_mode="manual",
        include_patterns=(),
        exclude_patterns=(r"embedding",),
        preferred_models=(),
        allow_manual_model=True,
    )
    with pytest.raises(ValueError):
        model_service._resolve_models(provider, [], None)
    assert model_service._resolve_models(provider, [], "my-chat-model") == ["my-chat-model"]
    with pytest.raises(ValueError):
        model_service._resolve_models(provider, [], "my-embedding-model")


# ---------- API 集成测试 ----------


def test_model_providers_endpoint_hides_admin_only_from_normal_users() -> None:
    with auth_client() as finance_client:
        public = finance_client.get("/api/model-providers")
        assert public.status_code == 200
        assert [item["id"] for item in public.json()] == [
            "qwen",
            "deepseek",
            "zhipu",
            "moonshot",
            "openai",
            "doubao",
            "minimax",
        ]
        assert all(not item["admin_only"] for item in public.json())
        assert all(
            item["discovery_mode"] in {"api", "manual", "hybrid"} for item in public.json()
        )

    with auth_client(role="skill_admin") as admin_client:
        admin = admin_client.get("/api/model-providers")
        assert admin.status_code == 200
        assert admin.json()[-1]["id"] == "custom_openai"
        assert admin.json()[-1]["admin_only"] is True


def test_connect_manual_selection_hits_only_selected_provider(monkeypatch) -> None:
    hits: list[str] = []
    post_kwargs: list[dict[str, object]] = []

    def fake_get(url, **kwargs):
        del kwargs
        hits.append(url)
        return FakeModelsResponse(["deepseek-v4-flash"])

    def fake_post(url, **kwargs):
        hits.append(url)
        post_kwargs.append(kwargs)
        return FakeOkResponse()

    monkeypatch.setattr(model_service.httpx, "get", fake_get)
    monkeypatch.setattr(model_service.httpx, "post", fake_post)

    with auth_client(role="skill_admin") as client:
        connected = client.post(
            "/api/model-connections",
            json={"api_key": "sk-deepseek-test-0001", "provider_id": "deepseek"},
        )
        assert connected.status_code == 200, connected.text
        body = connected.json()
        assert body["provider"] == "deepseek"
        assert body["selected_model"] == "deepseek-v4-flash"
        assert body["provider_name"] == "DeepSeek"
    assert any("api.deepseek.com" in url for url in hits)
    assert all("dashscope" not in url for url in hits)
    assert all("follow_redirects" not in kwargs for kwargs in post_kwargs)
    with auth_client(role="skill_admin") as client:
        cleanup_all_connections(client)


def test_legacy_connect_without_provider_only_probes_qwen(monkeypatch) -> None:
    hits: list[str] = []
    monkeypatch.setattr(
        model_service.httpx,
        "get",
        lambda url, **kwargs: hits.append(url) or offline(url, **kwargs),
    )
    with auth_client(role="skill_admin") as client:
        failed = client.post("/api/model-connections", json={"api_key": "sk-legacy-only-qwen"})
        assert failed.status_code == 422
    assert len(hits) == 1
    assert "dashscope" in hits[0]
    assert "deepseek" not in hits[0]


def test_connect_unknown_provider_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        model_service.httpx,
        "get",
        lambda *_, **__: pytest.fail("不应向未知供应商发起请求"),
    )
    with auth_client(role="skill_admin") as client:
        failed = client.post(
            "/api/model-connections",
            json={"api_key": "sk-unknown-provider", "provider_id": "nonsense"},
        )
        assert failed.status_code == 422
        assert "不支持" in failed.text


def test_failed_selected_provider_does_not_probe_others(monkeypatch) -> None:
    hits: list[str] = []

    def fake_get(url, **kwargs):
        del kwargs
        hits.append(url)
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(model_service.httpx, "get", fake_get)
    with auth_client(role="skill_admin") as client:
        failed = client.post(
            "/api/model-connections",
            json={"api_key": "sk-openai-bad-key", "provider_id": "openai"},
        )
        assert failed.status_code == 422
    assert len(hits) == 1
    assert "api.openai.com" in hits[0]


def test_doubao_hybrid_discovers_or_falls_back_to_manual_model(monkeypatch) -> None:
    def fake_get(url, **kwargs):
        del kwargs
        if "models" in url:
            return FakeModelsResponse(["doubao-seed-2-1-pro-260628", "doubao-seedream-4-0"])
        return FakeOkResponse()

    monkeypatch.setattr(model_service.httpx, "get", fake_get)
    monkeypatch.setattr(model_service.httpx, "post", lambda *_, **__: FakeOkResponse())

    with auth_client(role="skill_admin") as client:
        discovered = client.post(
            "/api/model-connections",
            json={"api_key": "sk-doubao-test-0001", "provider_id": "doubao"},
        )
        assert discovered.status_code == 200, discovered.text
        assert discovered.json()["models"] == ["doubao-seed-2-1-pro-260628"]

        monkeypatch.setattr(model_service.httpx, "get", offline)
        manual = client.post(
            "/api/model-connections",
            json={
                "api_key": "sk-doubao-ep-test-01",
                "provider_id": "doubao",
                "model": "ep-20260101-abcde",
            },
        )
        assert manual.status_code == 200, manual.text
        assert manual.json()["selected_model"] == "ep-20260101-abcde"
        cleanup_all_connections(client)


def test_tool_calling_verification_only_on_final_selected_model(monkeypatch) -> None:
    posts: list[dict[str, object]] = []

    def fake_get(url, **kwargs):
        del kwargs
        return FakeModelsResponse(["deepseek-v4-flash", "deepseek-v4-pro"])

    def fake_post(url, **kwargs):
        del url
        posts.append(kwargs["json"])
        if kwargs["json"].get("thinking") != {"type": "disabled"}:
            return FakeHttpErrorResponse(400)
        return FakeOkResponse()

    monkeypatch.setattr(model_service.httpx, "get", fake_get)
    monkeypatch.setattr(model_service.httpx, "post", fake_post)

    with auth_client(role="skill_admin") as client:
        connected = client.post(
            "/api/model-connections",
            json={"api_key": "sk-verify-single-key", "provider_id": "deepseek"},
        )
        assert connected.status_code == 200, connected.text
    assert len(posts) == 1
    payload = posts[0]
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["tools"][0]["type"] == "function"
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "tool_call_supported"},
    }
    assert payload["max_tokens"] == 32
    assert payload["thinking"] == {"type": "disabled"}
    assert "enable_thinking" not in payload
    with auth_client(role="skill_admin") as client:
        cleanup_all_connections(client)


def test_tool_calling_verification_minimax_m3_uses_system_instruction(
    monkeypatch,
) -> None:
    posts: list[dict[str, object]] = []

    def fake_get(url, **kwargs):
        del kwargs
        return FakeModelsResponse(["MiniMax-M3", "MiniMax-M2.7"])

    def fake_post(url, **kwargs):
        del url
        posts.append(kwargs["json"])
        return FakeOkResponse()

    monkeypatch.setattr(model_service.httpx, "get", fake_get)
    monkeypatch.setattr(model_service.httpx, "post", fake_post)

    with auth_client(role="skill_admin") as client:
        connected = client.post(
            "/api/model-connections",
            json={"api_key": "sk-minimax-m3-test", "provider_id": "minimax"},
        )
        assert connected.status_code == 200, connected.text
        assert connected.json()["selected_model"] == "MiniMax-M3"
    assert len(posts) == 1
    payload = posts[0]
    assert payload["model"] == "MiniMax-M3"
    assert "tool_choice" not in payload
    assert payload["messages"][0]["role"] == "system"
    assert "必须调用提供的 tool_call_supported 工具" in payload["messages"][0]["content"]
    assert payload["max_tokens"] == 1024
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["tools"][0]["function"]["name"] == "tool_call_supported"
    with auth_client(role="skill_admin") as client:
        cleanup_all_connections(client)


def test_tool_calling_verification_minimax_m2_keeps_object_omitted(monkeypatch) -> None:
    posts: list[dict[str, object]] = []

    def fake_get(url, **kwargs):
        del kwargs
        return FakeModelsResponse(["MiniMax-M2.7"])

    def fake_post(url, **kwargs):
        del url
        posts.append(kwargs["json"])
        return FakeOkResponse()

    monkeypatch.setattr(model_service.httpx, "get", fake_get)
    monkeypatch.setattr(model_service.httpx, "post", fake_post)

    with auth_client(role="skill_admin") as client:
        connected = client.post(
            "/api/model-connections",
            json={"api_key": "sk-minimax-m2-test", "provider_id": "minimax"},
        )
        assert connected.status_code == 200, connected.text
        assert connected.json()["selected_model"] == "MiniMax-M2.7"
    assert len(posts) == 1
    payload = posts[0]
    assert payload["model"] == "MiniMax-M2.7"
    assert "tool_choice" not in payload
    assert payload["max_tokens"] == 1024
    assert "thinking" not in payload
    with auth_client(role="skill_admin") as client:
        cleanup_all_connections(client)


def test_legacy_qwen_connect_verifies_tool_calling(monkeypatch) -> None:
    posts: list[dict[str, object]] = []

    def fake_get(url, **kwargs):
        del kwargs
        return FakeModelsResponse(["qwen3.7-plus", "qwen3.6-plus"])

    def fake_post(url, **kwargs):
        del url
        posts.append(kwargs["json"])
        return FakeOkResponse()

    monkeypatch.setattr(model_service.httpx, "get", fake_get)
    monkeypatch.setattr(model_service.httpx, "post", fake_post)

    with auth_client(role="skill_admin") as client:
        connected = client.post("/api/model-connections", json={"api_key": "sk-legacy-qwen"})
        assert connected.status_code == 200, connected.text
        assert connected.json()["provider"] == "qwen"
    assert len(posts) == 1
    payload = posts[0]
    assert payload["model"] == "qwen3.7-plus"
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "tool_call_supported"},
    }
    with auth_client(role="skill_admin") as client:
        cleanup_all_connections(client)


def test_legacy_qwen_connect_requires_real_tool_call(monkeypatch) -> None:
    monkeypatch.setattr(
        model_service.httpx,
        "get",
        lambda *_, **__: FakeModelsResponse(["qwen3.7-plus"]),
    )
    monkeypatch.setattr(model_service.httpx, "post", lambda *_, **__: FakeEmptyToolCallsResponse())
    with auth_client(role="skill_admin") as client:
        failed = client.post("/api/model-connections", json={"api_key": "sk-legacy-bad"})
        assert failed.status_code == 422
        assert "Tool Calling 验证" in failed.text
        assert "sk-legacy-bad" not in failed.text


@pytest.mark.parametrize(
    "bad_response",
    [
        FakePlainTextResponse(),
        FakeEmptyToolCallsResponse(),
        FakeWrongToolNameResponse(),
        FakeInvalidArgumentsResponse(),
    ],
)
def test_tool_calling_verification_rejects_empty_or_malformed_success(
    monkeypatch,
    bad_response,
) -> None:
    monkeypatch.setattr(
        model_service.httpx,
        "get",
        lambda *_, **__: FakeModelsResponse(["deepseek-v4-flash"]),
    )
    monkeypatch.setattr(model_service.httpx, "post", lambda *_, **__: bad_response)
    with auth_client(role="skill_admin") as client:
        failed = client.post(
            "/api/model-connections",
            json={"api_key": "sk-verify-malformed", "provider_id": "deepseek"},
        )
        assert failed.status_code == 422, type(bad_response).__name__
        assert "返回成功，但没有完成平台要求的 Tool Calling 验证" in failed.text
        assert "sk-verify-malformed" not in failed.text


def test_tool_calling_verification_rejects_http_401(monkeypatch) -> None:
    monkeypatch.setattr(
        model_service.httpx,
        "get",
        lambda *_, **__: FakeModelsResponse(["deepseek-v4-flash"]),
    )
    monkeypatch.setattr(
        model_service.httpx,
        "post",
        lambda *_, **__: FakeHttpErrorResponse(401),
    )
    with auth_client(role="skill_admin") as client:
        failed = client.post(
            "/api/model-connections",
            json={"api_key": "sk-verify-401", "provider_id": "deepseek"},
        )
        assert failed.status_code == 422
        assert "Tool Calling 验证" in failed.text
        assert "401" in failed.text
        assert "sk-verify-401" not in failed.text


def test_tool_calling_verification_rejects_network_timeout(monkeypatch) -> None:
    monkeypatch.setattr(
        model_service.httpx,
        "get",
        lambda *_, **__: FakeModelsResponse(["deepseek-v4-flash"]),
    )
    monkeypatch.setattr(model_service.httpx, "post", offline)
    with auth_client(role="skill_admin") as client:
        failed = client.post(
            "/api/model-connections",
            json={"api_key": "sk-verify-timeout", "provider_id": "deepseek"},
        )
        assert failed.status_code == 422
        assert "无法完成 Tool Calling 验证" in failed.text
        assert "sk-verify-timeout" not in failed.text


def test_tool_calling_verification_failure_is_clear(monkeypatch) -> None:
    class FailingResponse:
        def raise_for_status(self) -> None:
            request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
            raise httpx.HTTPStatusError(
                "400 Bad Request",
                request=request,
                response=httpx.Response(400, request=request),
            )

    monkeypatch.setattr(
        model_service.httpx,
        "get",
        lambda *_, **__: FakeModelsResponse(["deepseek-v4-flash"]),
    )
    monkeypatch.setattr(model_service.httpx, "post", lambda *_, **__: FailingResponse())

    with auth_client(role="skill_admin") as client:
        failed = client.post(
            "/api/model-connections",
            json={"api_key": "sk-verify-fail-key", "provider_id": "deepseek"},
        )
        assert failed.status_code == 422
        assert "Tool Calling" in failed.text
        assert "sk-verify-fail-key" not in failed.text


def test_same_key_different_providers_are_isolated(monkeypatch) -> None:
    def fake_get(url, **kwargs):
        del kwargs
        if "deepseek" in url:
            return FakeModelsResponse(["deepseek-v4-flash"])
        return FakeModelsResponse(["qwen3.7-plus"])

    monkeypatch.setattr(model_service.httpx, "get", fake_get)
    monkeypatch.setattr(model_service.httpx, "post", lambda *_, **__: FakeOkResponse())

    with auth_client(role="skill_admin") as client:
        deepseek = client.post(
            "/api/model-connections",
            json={"api_key": "sk-shared-key-0001", "provider_id": "deepseek"},
        )
        qwen = client.post(
            "/api/model-connections",
            json={"api_key": "sk-shared-key-0001", "provider_id": "qwen"},
        )
        assert deepseek.status_code == 200, deepseek.text
        assert qwen.status_code == 200, qwen.text
        assert deepseek.json()["id"] != qwen.json()["id"]
        assert deepseek.json()["provider"] == "deepseek"
        assert qwen.json()["provider"] == "qwen"
        assert len(client.get("/api/model-connections").json()) == 2

        reconnected = client.post(
            "/api/model-connections",
            json={"api_key": "sk-shared-key-0001", "provider_id": "deepseek"},
        )
        assert reconnected.status_code == 200
        assert reconnected.json()["id"] == deepseek.json()["id"]
        assert len(client.get("/api/model-connections").json()) == 2
        cleanup_all_connections(client)


def test_legacy_qwen_connection_still_refreshes(monkeypatch) -> None:
    monkeypatch.setattr(
        model_service.httpx,
        "get",
        lambda *_, **__: FakeModelsResponse(["qwen3.7-plus", "qwen3.6-plus"]),
    )
    monkeypatch.setattr(model_service.httpx, "post", lambda *_, **__: FakeOkResponse())

    with auth_client(role="skill_admin") as client:
        connected = client.post("/api/model-connections", json={"api_key": "sk-legacy-refresh"})
        assert connected.status_code == 200, connected.text
        connection_id = connected.json()["id"]

        refreshed = client.post(f"/api/model-connections/{connection_id}/refresh")
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["selected_model"] == "qwen3.7-plus"
        assert refreshed.json()["status"] == "connected"
        cleanup_all_connections(client)


def test_select_model_reverifies_tool_calling_before_switching(monkeypatch) -> None:
    posts: list[dict[str, object]] = []

    def fake_get(url, **kwargs):
        del kwargs
        return FakeModelsResponse(["deepseek-v4-flash", "deepseek-v4-pro"])

    def fake_post(url, **kwargs):
        del url
        posts.append(kwargs["json"])
        return FakeOkResponse()

    monkeypatch.setattr(model_service.httpx, "get", fake_get)
    monkeypatch.setattr(model_service.httpx, "post", fake_post)

    with auth_client(role="skill_admin") as client:
        connected = client.post(
            "/api/model-connections",
            json={"api_key": "sk-select-reverify", "provider_id": "deepseek"},
        )
        assert connected.status_code == 200, connected.text
        connection_id = connected.json()["id"]

        posts.clear()
        switched = client.patch(
            f"/api/model-connections/{connection_id}",
            json={"selected_model": "deepseek-v4-pro"},
        )
        assert switched.status_code == 200, switched.text
        assert switched.json()["selected_model"] == "deepseek-v4-pro"
        assert len(posts) == 1
        assert posts[0]["model"] == "deepseek-v4-pro"
        assert posts[0]["tool_choice"] == {
            "type": "function",
            "function": {"name": "tool_call_supported"},
        }
        cleanup_all_connections(client)


def test_select_model_failure_keeps_connection_state(monkeypatch) -> None:
    def fake_get(url, **kwargs):
        del kwargs
        return FakeModelsResponse(["deepseek-v4-flash", "deepseek-v4-pro"])

    monkeypatch.setattr(model_service.httpx, "get", fake_get)
    monkeypatch.setattr(model_service.httpx, "post", lambda *_, **__: FakeOkResponse())

    with auth_client(role="skill_admin") as client:
        connected = client.post(
            "/api/model-connections",
            json={"api_key": "sk-select-fail", "provider_id": "deepseek"},
        )
        assert connected.status_code == 200, connected.text
        connection_id = connected.json()["id"]

        monkeypatch.setattr(
            model_service.httpx,
            "post",
            lambda *_, **__: FakeEmptyToolCallsResponse(),
        )
        failed = client.patch(
            f"/api/model-connections/{connection_id}",
            json={"selected_model": "deepseek-v4-pro"},
        )
        assert failed.status_code == 422
        assert "返回成功，但没有完成平台要求的 Tool Calling 验证" in failed.text
        assert "sk-select-fail" not in failed.text

        current = next(
            item
            for item in client.get("/api/model-connections").json()
            if item["id"] == connection_id
        )
        assert current["selected_model"] == "deepseek-v4-flash"
        assert current["status"] == "connected"
        assert current["models"] == ["deepseek-v4-flash", "deepseek-v4-pro"]
        cleanup_all_connections(client)


def test_select_model_rejects_model_not_in_list(monkeypatch) -> None:
    monkeypatch.setattr(
        model_service.httpx,
        "get",
        lambda *_, **__: FakeModelsResponse(["deepseek-v4-flash"]),
    )
    monkeypatch.setattr(model_service.httpx, "post", lambda *_, **__: FakeOkResponse())
    with auth_client(role="skill_admin") as client:
        connected = client.post(
            "/api/model-connections",
            json={"api_key": "sk-select-ghost", "provider_id": "deepseek"},
        )
        assert connected.status_code == 200, connected.text
        connection_id = connected.json()["id"]

        monkeypatch.setattr(
            model_service.httpx,
            "post",
            lambda *_, **__: pytest.fail("不应向模型发起验证请求"),
        )
        failed = client.patch(
            f"/api/model-connections/{connection_id}",
            json={"selected_model": "ghost-model"},
        )
        assert failed.status_code == 422
        cleanup_all_connections(client)


def test_custom_openai_admin_only_and_ssrf(monkeypatch) -> None:
    set_custom_allowlist(monkeypatch, "trusted.example.com")
    posts: list[dict[str, object]] = []

    def fake_get(url, **kwargs):
        del kwargs
        return FakeModelsResponse(["my-custom-chat"])

    def fake_post(url, **kwargs):
        posts.append({"url": url, **kwargs})
        return FakeOkResponse()

    monkeypatch.setattr(model_service.httpx, "get", fake_get)
    monkeypatch.setattr(model_service.httpx, "post", fake_post)
    monkeypatch.setattr("app.model_providers.socket.getaddrinfo", public_addrinfo)

    with auth_client() as finance_client:
        denied = finance_client.post(
            "/api/model-connections",
            json={
                "api_key": "sk-custom-user-key",
                "provider_id": "custom_openai",
                "base_url": "https://trusted.example.com/v1",
                "model": "my-model",
            },
        )
        assert denied.status_code == 403
        assert posts == []

    with auth_client(role="skill_admin") as client:
        for bad_url in (
            "http://trusted.example.com/v1",
            "https://127.0.0.1/v1",
            "https://192.168.50.10/v1",
            "https://169.254.169.254/latest",
            "https://[::1]/v1",
            "https://evil.example.com/v1",
            "https://user:pass@trusted.example.com/v1",
            "https://trusted.example.com/v1#fragment",
        ):
            failed = client.post(
                "/api/model-connections",
                json={
                    "api_key": "sk-custom-admin-key",
                    "provider_id": "custom_openai",
                    "base_url": bad_url,
                    "model": "my-model",
                },
            )
            assert failed.status_code == 422, bad_url
            assert "sk-custom-admin-key" not in failed.text
        assert posts == []

        connected = client.post(
            "/api/model-connections",
            json={
                "api_key": "sk-custom-admin-key",
                "provider_id": "custom_openai",
                "base_url": "https://trusted.example.com/v1",
                "model": "my-model",
            },
        )
        assert connected.status_code == 200, connected.text
        assert connected.json()["provider"] == "custom_openai"
        assert connected.json()["selected_model"] == "my-model"
    assert all(kwargs["follow_redirects"] is False for kwargs in posts)
    assert all("trusted.example.com" in kwargs["url"] for kwargs in posts)
    with auth_client(role="skill_admin") as client:
        cleanup_all_connections(client)


def test_custom_connect_without_allowlist_blocks_network(monkeypatch) -> None:
    monkeypatch.delenv("FINANCIAL_LLM_CUSTOM_HOST_ALLOWLIST", raising=False)
    hits: list[str] = []

    def fake_get(url, **kwargs):
        del kwargs
        hits.append(url)
        return FakeModelsResponse(["my-custom-chat"])

    monkeypatch.setattr(model_service.httpx, "get", fake_get)
    monkeypatch.setattr(model_service.httpx, "post", lambda *_, **__: hits.append("POST"))
    with auth_client(role="skill_admin") as client:
        failed = client.post(
            "/api/model-connections",
            json={
                "api_key": "sk-custom-no-allowlist",
                "provider_id": "custom_openai",
                "base_url": "https://trusted.example.com/v1",
                "model": "my-model",
            },
            headers={"X-User-Role": "skill_admin"},
        )
        assert failed.status_code == 422
        assert "尚未配置允许的自定义模型服务域名" in failed.text
        assert "sk-custom-no-allowlist" not in failed.text
    assert hits == []


def test_custom_host_not_in_allowlist_blocks_network(monkeypatch) -> None:
    set_custom_allowlist(monkeypatch, "trusted.example.com")
    hits: list[str] = []

    def fake_get(url, **kwargs):
        del kwargs
        hits.append(url)
        return FakeModelsResponse(["my-custom-chat"])

    monkeypatch.setattr(model_service.httpx, "get", fake_get)
    monkeypatch.setattr(model_service.httpx, "post", lambda *_, **__: hits.append("POST"))
    with auth_client(role="skill_admin") as client:
        failed = client.post(
            "/api/model-connections",
            json={
                "api_key": "sk-custom-unknown-host",
                "provider_id": "custom_openai",
                "base_url": "https://not-allowlisted.example.com/v1",
                "model": "my-model",
            },
            headers={"X-User-Role": "skill_admin"},
        )
        assert failed.status_code == 422
        assert "不在管理员配置的允许列表" in failed.text
        assert "sk-custom-unknown-host" not in failed.text
    assert hits == []


def test_custom_dns_private_ip_rejected_at_request_time(monkeypatch) -> None:
    set_custom_allowlist(monkeypatch, "trusted.example.com")

    def fake_getaddrinfo(host, port, **kwargs):
        del host, port, kwargs
        return [(2, 1, 6, "", ("10.0.0.99", 443))]

    monkeypatch.setattr("app.model_providers.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(model_service.httpx, "get", lambda *_, **__: FakeModelsResponse(["m"]))
    monkeypatch.setattr(model_service.httpx, "post", lambda *_, **__: FakeOkResponse())
    with auth_client(role="skill_admin") as client:
        failed = client.post(
            "/api/model-connections",
            json={
                "api_key": "sk-custom-private-dns",
                "provider_id": "custom_openai",
                "base_url": "https://trusted.example.com/v1",
                "model": "my-model",
            },
            headers={"X-User-Role": "skill_admin"},
        )
        assert failed.status_code == 422
        assert "不允许指向内网、回环或非公网地址" in failed.text
        assert "sk-custom-private-dns" not in failed.text


def test_custom_error_response_does_not_leak_api_key(monkeypatch) -> None:
    set_custom_allowlist(monkeypatch, "trusted.example.com")
    monkeypatch.setattr("app.model_providers.socket.getaddrinfo", public_addrinfo)
    monkeypatch.setattr(
        model_service.httpx,
        "get",
        lambda *_, **__: FakeModelsResponse(["my-custom-chat"]),
    )
    monkeypatch.setattr(
        model_service.httpx,
        "post",
        lambda *_, **__: FakeHttpErrorResponse(400),
    )
    with auth_client(role="skill_admin") as client:
        failed = client.post(
            "/api/model-connections",
            json={
                "api_key": "sk-secret-leak-check",
                "provider_id": "custom_openai",
                "base_url": "https://trusted.example.com/v1",
                "model": "my-model",
            },
            headers={"X-User-Role": "skill_admin"},
        )
        assert failed.status_code == 422
        assert "sk-secret-leak-check" not in failed.text
        assert "400" in failed.text


def test_custom_runtime_request_uses_secure_entry(monkeypatch) -> None:
    set_custom_allowlist(monkeypatch, "trusted.example.com")
    monkeypatch.setattr("app.model_providers.socket.getaddrinfo", public_addrinfo)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        orchestrator.httpx,
        "post",
        lambda url, **kwargs: captured.update({"url": url, **kwargs}) or FakeToolResponse(),
    )
    registry.refresh()
    skill = registry.get("reconcile-bank")
    assert skill is not None
    orchestrator.interpret_parameters(
        skill,
        "金额差异 1 元以内，日期相差 2 天可以匹配",
        {},
        SimpleNamespace(
            provider="custom_openai",
            model="my-model",
            base_url="https://trusted.example.com/v1",
            api_key="test-key",
        ),
    )
    assert captured["follow_redirects"] is False
    assert captured["url"] == "https://trusted.example.com/v1/chat/completions"


def test_builtin_provider_rejects_custom_base_url(monkeypatch) -> None:
    with auth_client(role="skill_admin") as client:
        failed = client.post(
            "/api/model-connections",
            json={
                "api_key": "sk-evil-base-url",
                "provider_id": "qwen",
                "base_url": "https://evil.example.com/v1",
            },
        )
        assert failed.status_code == 422
        assert "不可修改" in failed.text


# ---------- 运行时参数隔离测试 ----------


def test_other_providers_do_not_receive_qwen_specific_params(monkeypatch) -> None:
    registry.refresh()
    skill = registry.get("reconcile-bank")
    assert skill is not None
    captured: dict[str, object] = {}
    redirect_flags: list[bool] = []

    def fake_post(url, **kwargs):
        del url
        captured.update(kwargs["json"])
        redirect_flags.append("follow_redirects" in kwargs)
        return FakeToolResponse()

    monkeypatch.setattr(orchestrator.httpx, "post", fake_post)
    monkeypatch.setattr(
        orchestrator,
        "settings",
        SimpleNamespace(llm_base_url="", llm_api_key="", llm_model="", llm_provider=""),
    )

    orchestrator.interpret_parameters(
        skill,
        "金额差异 1 元以内，日期相差 2 天可以匹配",
        {},
        SimpleNamespace(
            provider="deepseek",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            api_key="test-key",
        ),
    )
    assert captured["model"] == "deepseek-v4-flash"
    assert "enable_thinking" not in captured
    assert "thinking" not in captured
    assert redirect_flags == [False]


def test_workflow_decision_does_not_inject_qwen_params_for_deepseek(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        workflow_orchestrator.httpx,
        "post",
        lambda *_, **kwargs: captured.update(kwargs["json"]) or FakeChatResponse(),
    )

    decision = workflow_orchestrator.decide_workflow_turn(
        SimpleNamespace(
            provider="deepseek",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            api_key="test-key",
        ),
        "awaiting_date",
        "核销日期和到账日期有什么区别？",
        "",
        [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好"},
            {"role": "user", "content": "核销日期和到账日期有什么区别？"},
        ],
    )
    assert decision.action == "reply"
    assert captured["model"] == "deepseek-v4-flash"
    assert "enable_thinking" not in captured


def test_extra_body_cannot_override_protected_fields(monkeypatch) -> None:
    registry.refresh()
    skill = registry.get("reconcile-bank")
    assert skill is not None
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        orchestrator.httpx,
        "post",
        lambda *_, **kwargs: captured.update(kwargs["json"]) or FakeToolResponse(),
    )
    monkeypatch.setattr(
        orchestrator,
        "settings",
        SimpleNamespace(llm_base_url="", llm_api_key="", llm_model="", llm_provider=""),
    )

    orchestrator.interpret_parameters(
        skill,
        "金额差异 1 元以内，日期相差 2 天可以匹配",
        {},
        SimpleNamespace(
            provider="qwen",
            model="qwen3.7-plus",
            base_url="https://dashscope.example/v1",
            api_key="test-key",
            extra_body={
                "model": "evil-model",
                "messages": [],
                "tools": [],
                "tool_choice": "none",
                "enable_thinking": False,
                "custom_flag": True,
            },
        ),
    )
    assert captured["model"] == "qwen3.7-plus"
    assert captured["enable_thinking"] is False
    assert captured["custom_flag"] is True
    assert isinstance(captured["tools"], list) and len(captured["tools"]) == 1
    assert captured["tool_choice"] != "none"
