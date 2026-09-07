from __future__ import annotations

from contextlib import contextmanager

import httpx
import pytest

from app.model_providers import (
    build_extra_body,
    chat_completion_request,
    chat_completion_stream_request,
    filter_candidate_models,
    get_provider,
)
from app.model_service import _resolve_models, _verify_tool_calling


def test_go_catalog_excludes_other_protocols_and_unlisted_models() -> None:
    provider = get_provider("opencode_go")
    assert provider is not None
    models = filter_candidate_models(
        provider,
        [
            "glm-5.3-flash", "kimi-k3", "deepseek-v4-flash", "mimo-v2.5",
            "minimax-m3", "qwen3.8-max", "gpt-5.6-luna", "grok-4.6", "kimi-k2.7-code",
            "muse-spark-1.3-contributor", "deepseek-v4-flash-vision-exp",
            "unknown-new-model", "opencode-go/kimi-k3",
        ],
    )
    assert models == ["deepseek-v4-flash", "glm-5.3-flash", "kimi-k3", "mimo-v2.5"]
    with pytest.raises(ValueError, match="可用列表"):
        _resolve_models(provider, models, "minimax-m3")
    with pytest.raises(ValueError, match="没有发现"):
        _resolve_models(provider, [], "kimi-k3")


def test_go_sync_and_stream_share_opaque_session_headers(monkeypatch) -> None:
    calls: list[dict[str, str]] = []
    base_url = "https://opencode.ai/zen/go/v1"
    payload = {"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": "ping"}]}

    def post(url, **kwargs):
        assert url == base_url + "/chat/completions"
        calls.append(kwargs["headers"])
        return httpx.Response(200)

    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs["headers"])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        @contextmanager
        def stream(self, method, url, **kwargs):
            assert method == "POST"
            assert url == base_url + "/chat/completions"
            yield httpx.Response(200)

    monkeypatch.setattr("app.model_providers.httpx.post", post)
    monkeypatch.setattr("app.model_providers.httpx.Client", Client)
    for session in ("assistant:user-a:chat-1", "assistant:user-b:chat-1"):
        chat_completion_request("opencode_go", base_url, "test-go-key", payload, session_id=session)
    with chat_completion_stream_request(
        "opencode_go", base_url, "test-go-key", payload, session_id="assistant:user-a:chat-1"
    ):
        pass
    assert calls[0]["x-opencode-session"] == calls[2]["x-opencode-session"]
    assert calls[0]["x-opencode-session"] != calls[1]["x-opencode-session"]
    assert all(len(item["x-opencode-session"]) == 64 for item in calls)
    assert calls[0]["User-Agent"] == "Financial-Skill-Platform/0.1"
    assert calls[0]["Authorization"] == "Bearer test-go-key"
    chat_completion_request("deepseek", base_url, "test-other-key", payload)
    assert calls[-1] == {"Authorization": "Bearer test-other-key"}


def test_go_validation_requires_real_tool_call(monkeypatch) -> None:
    provider = get_provider("opencode_go")
    assert provider is not None
    captured: list[dict] = []

    def post(url, **kwargs):
        captured.append(kwargs)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "pong"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.model_providers.httpx.post", post)
    with pytest.raises(ValueError, match="没有完成"):
        _verify_tool_calling(provider, "test-go-key", provider.base_url, "deepseek-v4-flash")
    assert captured[0]["json"]["max_tokens"] == 4096
    assert captured[0]["json"]["thinking"] == {"type": "disabled"}
    assert captured[0]["json"]["tool_choice"] == "auto"
    assert "temperature" not in captured[0]["json"]
    assert "x-opencode-session" in captured[0]["headers"]


def test_go_kimi_only_disables_thinking_for_supported_version() -> None:
    assert build_extra_body("opencode_go", "kimi-k2.6") == {"thinking": {"type": "disabled"}}
    assert build_extra_body("opencode_go", "kimi-k2.7-code") == {}
