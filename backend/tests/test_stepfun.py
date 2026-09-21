from contextlib import contextmanager
import httpx
import pytest
from fastapi import HTTPException
from app.model_providers import (get_provider, list_public_providers, filter_candidate_models,
                                chat_completion_request, chat_completion_stream_request, build_extra_body)
from app.model_service import _discover_models, _resolve_models, _verify_tool_calling, _effective_base_url


def test_stepfun_catalog_and_fixed_endpoint(monkeypatch):
    provider = get_provider('stepfun')
    assert provider in list_public_providers()
    assert provider.name == '阶跃星辰 / StepFun'
    assert provider.base_url == 'https://api.stepfun.com/v1'
    candidates = ['step-3.5-flash', 'step-3.7-flash', 'step-3.5-flash-2603', 'step-5-preview']
    rejected = ['stepaudio-3-chat-preview', 'step-1x-medium', 'step-image-edit-2',
                'step-router-v1', 'step-3.7-flash-audio', 'unknown-model']
    def get(url, **kwargs):
        assert url == provider.base_url + '/models'
        assert kwargs['headers'] == {'Authorization': 'Bearer test-step-key'}
        return httpx.Response(200, json={'data': [{'id': x} for x in candidates + rejected]},
                              request=httpx.Request('GET', url))
    monkeypatch.setattr('app.model_providers.httpx.get', get)
    assert _discover_models(provider, 'test-step-key', provider.base_url) == [
        'step-3.7-flash', 'step-3.5-flash', 'step-3.5-flash-2603', 'step-5-preview']
    with pytest.raises(HTTPException):
        _effective_base_url(provider, 'https://other.example/v1')
    with pytest.raises(ValueError):
        _resolve_models(provider, candidates, 'step-router-v1')


@pytest.mark.parametrize('message,valid', [
    ({'tool_calls': [{'type': 'function', 'function': {'name': 'tool_call_supported', 'arguments': '{}'}}]}, True),
    ({'content': 'pong'}, False),
    ({'tool_calls': [{'function': {'name': 'other', 'arguments': '{}'}}]}, False),
    ({'tool_calls': [{'function': {'name': 'tool_call_supported', 'arguments': 'invalid'}}]}, False),
])
def test_stepfun_probe_requires_valid_tool_call(monkeypatch, message, valid):
    provider = get_provider('stepfun')
    def post(url, **kwargs):
        payload = kwargs['json']
        assert url == provider.base_url + '/chat/completions'
        assert payload['max_tokens'] == 4096
        assert payload['tool_choice'] == 'auto'
        assert payload['messages'][0]['role'] == 'system'
        assert 'thinking' not in payload and 'enable_thinking' not in payload
        assert 'temperature' not in payload
        assert kwargs['timeout'] == 60
        return httpx.Response(200, json={'choices': [{'message': message}]},
                              request=httpx.Request('POST', url))
    monkeypatch.setattr('app.model_providers.httpx.post', post)
    if valid:
        _verify_tool_calling(provider, 'test-step-key', provider.base_url, 'step-3.7-flash')
    else:
        with pytest.raises(ValueError):
            _verify_tool_calling(provider, 'test-step-key', provider.base_url, 'step-3.7-flash')


def test_stepfun_chat_and_stream_preserve_tools_and_reasoning(monkeypatch):
    provider = get_provider('stepfun')
    payload = {'model': 'step-3.7-flash', 'reasoning_effort': 'low',
               'messages': [{'role': 'user', 'content': 'ping'}],
               'tools': [{'type': 'function', 'function': {'name': 'ping', 'parameters': {'type': 'object'}}}]}
    seen = []
    def post(url, **kwargs):
        assert url == provider.base_url + '/chat/completions'
        assert kwargs['headers'] == {'Authorization': 'Bearer test-step-key'}
        seen.append(kwargs['json'])
        return httpx.Response(200)
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['headers'] == {'Authorization': 'Bearer test-step-key'}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        @contextmanager
        def stream(self, method, url, **kwargs):
            assert method == 'POST' and url == provider.base_url + '/chat/completions'
            seen.append(kwargs['json'])
            yield httpx.Response(200)
    monkeypatch.setattr('app.model_providers.httpx.post', post)
    monkeypatch.setattr('app.model_providers.httpx.Client', Client)
    chat_completion_request('stepfun', provider.base_url, 'test-step-key', payload)
    with chat_completion_stream_request('stepfun', provider.base_url, 'test-step-key', payload): pass
    assert seen == [payload, payload]
    assert build_extra_body('stepfun', payload['model']) == {}


def test_stepfun_text_only_probe_gets_one_explicit_retry(monkeypatch):
    provider = get_provider('stepfun')
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs['json'])
        if len(calls) == 1:
            message = {'content': 'pong'}
            finish = 'stop'
        else:
            assert len(calls) == 2
            assert kwargs['json']['messages'][-1]['role'] == 'user'
            assert 'tool_call_supported' in kwargs['json']['messages'][-1]['content']
            message = {'tool_calls': [{'function': {'name': 'tool_call_supported', 'arguments': '{}'}}]}
            finish = 'tool_calls'
        return httpx.Response(200, json={'choices': [{'finish_reason': finish, 'message': message}]},
                              request=httpx.Request('POST', url))
    monkeypatch.setattr('app.model_providers.httpx.post', post)
    _verify_tool_calling(provider, 'test-step-key', provider.base_url, 'step-3.7-flash')
    assert len(calls) == 2


@pytest.mark.parametrize('finish,expected_calls,detail', [
    ('stop', 2, '未返回'), ('length', 1, '额度'), ('content_filter', 1, '安全过滤'),
])
def test_stepfun_probe_retry_is_bounded_and_failure_specific(monkeypatch, finish, expected_calls, detail):
    provider = get_provider('stepfun')
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs['json'])
        return httpx.Response(200, json={'choices': [{'finish_reason': finish, 'message': {'content': ''}}]},
                              request=httpx.Request('POST', url))
    monkeypatch.setattr('app.model_providers.httpx.post', post)
    with pytest.raises(ValueError, match=detail):
        _verify_tool_calling(provider, 'test-step-key', provider.base_url, 'step-3.7-flash')
    assert len(calls) == expected_calls
