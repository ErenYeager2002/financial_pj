from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import pi_runtime_service as service
from app.pi_delivery_receipts import new_receipt, receipt_path, write_receipt


@pytest.fixture
def bound_session(monkeypatch, tmp_path):
    directory = tmp_path / 'private-catalog'
    directory.mkdir()
    user = SimpleNamespace(user_id='owner', department_id='team')
    monkeypatch.setattr(service, 'catalog', lambda _: directory)
    monkeypatch.setattr(service, 'require_session', lambda _user, session_id, **_kw: session_id)
    return user, str(uuid4()), directory


def payload(request_id: str, message: str = 'first request') -> dict:
    return {'client_request_id': request_id,
            'command': {'id': 'pi-response-id', 'type': 'prompt', 'message': message}}


def test_ack_and_duplicate_never_write_twice(monkeypatch, bound_session):
    user, session_id, directory = bound_session
    request_id = str(uuid4())
    calls = []
    monkeypatch.setattr(service, '_request_runtime', lambda body: calls.append(body) or {'accepted': True})
    first = service.operate(user, session_id, 'send', payload(request_id))
    second = service.operate(user, session_id, 'send', payload(request_id))
    assert len(calls) == 1
    assert first['delivery_state'] == second['delivery_state'] == 'pi_accepted'
    assert 'client_request_id' not in calls[0]['payload']
    assert service.delivery_receipt(user, session_id, request_id)['delivery_state'] == 'pi_accepted'
    assert 'first request' not in receipt_path(directory, session_id, request_id).read_text()
    with pytest.raises(HTTPException) as conflict:
        service.operate(user, session_id, 'send', payload(request_id, 'different'))
    assert conflict.value.status_code == 409
    assert len(calls) == 1


def test_lost_ack_is_unknown_and_never_redispatched(monkeypatch, bound_session):
    user, session_id, directory = bound_session
    request_id = str(uuid4())
    calls = []

    def lost_response(body):
        path = receipt_path(directory, session_id, request_id)
        assert json.loads(path.read_text())['state'] == 'dispatching'
        calls.append(body)
        raise HTTPException(503, 'lost response')

    monkeypatch.setattr(service, '_request_runtime', lost_response)
    with pytest.raises(HTTPException):
        service.operate(user, session_id, 'send', payload(request_id))
    assert service.delivery_receipt(user, session_id, request_id)['delivery_state'] == 'unknown'
    duplicate = service.operate(user, session_id, 'send', payload(request_id))
    assert duplicate['delivery_state'] == 'unknown'
    assert len(calls) == 1


def test_prepared_crash_evidence_is_not_replayed(monkeypatch, bound_session):
    user, session_id, directory = bound_session
    request_id = str(uuid4())
    command = payload(request_id)['command']
    from app.pi_delivery_receipts import request_identity
    _, digest, kind = request_identity({'client_request_id': request_id, 'command': command})
    write_receipt(receipt_path(directory, session_id, request_id),
                  new_receipt(request_id, digest, kind))
    monkeypatch.setattr(service, '_request_runtime', lambda _: pytest.fail('replayed prepared request'))
    assert service.operate(user, session_id, 'send', payload(request_id))['delivery_state'] == 'prepared'


def test_invalid_identity_rejected_before_send(monkeypatch, bound_session):
    user, session_id, _ = bound_session
    monkeypatch.setattr(service, '_request_runtime', lambda _: pytest.fail('sent invalid request'))
    with pytest.raises(HTTPException) as invalid:
        service.operate(user, session_id, 'send', payload('not-a-uuid'))
    assert invalid.value.status_code == 422
