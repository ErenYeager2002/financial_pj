from contextlib import contextmanager
import httpx
import pytest
from fastapi import HTTPException
from app.model_providers import (get_provider, list_public_providers, filter_candidate_models,
                                chat_completion_request, chat_completion_stream_request, build_extra_body)
from app.model_service import _discover_models, _resolve_models, _verify_tool_calling, _effective_base_url


def test_agnes_catalog_and_fixed_endpoint(monkeypatch):
    provider = get_provider('agnes')
    assert provider in list_public_providers()
    assert provider.name == 'Agnes AI'
    assert provider.base_url == 'https://apihub.agnes-ai.com/v1'
    candidates = ['agnes-2.5-flash', 'agnes-3.0-flash', 'agnes-2.5-pro']
    rejected = ['agnes-image-2.5-flash', 'agnes-video-2.5-flash', 'agnes-2.0-flash', 'agnes-2.5-pro-alpha', 'agnes-2.5-pro-beta', 'unknown-model']
    def get(url, **kwargs):
        assert url == provider.base_url + '/models'
        assert kwargs['headers'] == {'Authorization': 'Bearer test-agnes-key'}
        return httpx.Response(200, json={'data': [{'id': x} for x in candidates + rejected]},
                              request=httpx.Request('GET', url))
    monkeypatch.setattr('app.model_providers.httpx.get', get)
    assert _discover_models(provider, 'test-agnes-key', provider.base_url) == [
        'agnes-3.0-flash', 'agnes-2.5-flash', 'agnes-2.5-pro']
    with pytest.raises(HTTPException):
        _effective_base_url(provider, 'https://other.example/v1')
    with pytest.raises(ValueError):
        _resolve_models(provider, candidates, 'agnes-image-2.5-flash')


@pytest.mark.parametrize('message,valid', [
    ({'tool_calls': [{'type': 'function', 'function': {'name': 'tool_call_supported', 'arguments': '{}'}}]}, True),
    ({'content': 'pong'}, False),
    ({'tool_calls': [{'function': {'name': 'other', 'arguments': '{}'}}]}, False),
    ({'tool_calls': [{'function': {'name': 'tool_call_supported', 'arguments': 'invalid'}}]}, False),
])
def test_agnes_probe_requires_valid_tool_call(monkeypatch, message, valid):
    provider = get_provider('agnes')
    def post(url, **kwargs):
        payload = kwargs['json']
        assert url == provider.base_url + '/chat/completions'
        assert payload['max_tokens'] == 4096
        assert payload['tool_choice'] == {'type': 'function', 'function': {'name': 'tool_call_supported'}}
        assert payload['messages'][0]['role'] == 'system'
        assert 'thinking' not in payload and 'enable_thinking' not in payload
        assert payload['temperature'] == 0
        assert kwargs['timeout'] == 60
        return httpx.Response(200, json={'choices': [{'message': message}]},
                              request=httpx.Request('POST', url))
    monkeypatch.setattr('app.model_providers.httpx.post', post)
    if valid:
        _verify_tool_calling(provider, 'test-agnes-key', provider.base_url, 'agnes-3.0-flash')
    else:
        with pytest.raises(ValueError):
            _verify_tool_calling(provider, 'test-agnes-key', provider.base_url, 'agnes-3.0-flash')


def test_agnes_chat_and_stream_preserve_tools_and_reasoning(monkeypatch):
    provider = get_provider('agnes')
    payload = {'model': 'agnes-3.0-flash', 'chat_template_kwargs': {'enable_thinking': True},
               'messages': [{'role': 'user', 'content': 'ping'}],
               'tools': [{'type': 'function', 'function': {'name': 'ping', 'parameters': {'type': 'object'}}}]}
    seen = []
    def post(url, **kwargs):
        assert url == provider.base_url + '/chat/completions'
        assert kwargs['headers'] == {'Authorization': 'Bearer test-agnes-key'}
        seen.append(kwargs['json'])
        return httpx.Response(200)
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['headers'] == {'Authorization': 'Bearer test-agnes-key'}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        @contextmanager
        def stream(self, method, url, **kwargs):
            assert method == 'POST' and url == provider.base_url + '/chat/completions'
            seen.append(kwargs['json'])
            yield httpx.Response(200)
    monkeypatch.setattr('app.model_providers.httpx.post', post)
    monkeypatch.setattr('app.model_providers.httpx.Client', Client)
    chat_completion_request('agnes', provider.base_url, 'test-agnes-key', payload)
    with chat_completion_stream_request('agnes', provider.base_url, 'test-agnes-key', payload): pass
    assert seen == [payload, payload]
    assert build_extra_body('agnes', payload['model']) == {}

