from __future__ import annotations

import asyncio

import pytest
from scripts.egress_proxy import (
    ProxyPolicy,
    ProxyRequestError,
    _relay_http_response,
    parse_connect_request,
    prepare_http_request,
)

from app.network_policy import NetworkPolicyError, normalize_network_target


class _MemoryWriter:
    def __init__(self) -> None:
        self.data = bytearray()
        self.eof = False

    def write(self, chunk: bytes) -> None:
        self.data.extend(chunk)

    async def drain(self) -> None:
        return None

    def write_eof(self) -> None:
        self.eof = True


def _policy() -> ProxyPolicy:
    return ProxyPolicy(
        targets=frozenset(
            {normalize_network_target("https://zhiyun.finance.example.com:443")}
        ),
    )


def test_proxy_accepts_only_exact_approved_https_connect() -> None:
    assert parse_connect_request(
        b"CONNECT zhiyun.finance.example.com:443 HTTP/1.1\r\nHost: ignored.example\r\n\r\n",
        _policy(),
    ) == ("zhiyun.finance.example.com", 443)


@pytest.mark.parametrize(
    "header",
    [
        b"CONNECT other.finance.example.com:443 HTTP/1.1\r\n\r\n",
        b"CONNECT sub.zhiyun.finance.example.com:443 HTTP/1.1\r\n\r\n",
        b"CONNECT zhiyun.finance.example.com:8443 HTTP/1.1\r\n\r\n",
        b"CONNECT 192.168.10.167:443 HTTP/1.1\r\n\r\n",
    ],
)
def test_proxy_rejects_unapproved_connect_targets(header: bytes) -> None:
    with pytest.raises(ProxyRequestError) as exc_info:
        parse_connect_request(header, _policy())
    assert exc_info.value.status == 403


def test_proxy_rejects_plain_http_and_malformed_requests() -> None:
    with pytest.raises(ProxyRequestError) as exc_info:
        parse_connect_request(
            b"GET https://zhiyun.finance.example.com/ HTTP/1.1\r\n\r\n",
            _policy(),
        )
    assert exc_info.value.status == 405

    with pytest.raises(ProxyRequestError) as exc_info:
        parse_connect_request(b"CONNECT missing-port HTTP/1.1\r\n\r\n", _policy())
    assert exc_info.value.status == 400


def test_proxy_policy_reads_exact_hosts_and_deny_all(monkeypatch) -> None:
    monkeypatch.delenv("FINANCIAL_EGRESS_PROXY_TARGETS", raising=False)
    monkeypatch.delenv("FINANCIAL_EGRESS_PROXY_ALLOWLIST", raising=False)
    assert ProxyPolicy.from_environment() == ProxyPolicy(targets=frozenset())

    monkeypatch.setenv(
        "FINANCIAL_EGRESS_PROXY_ALLOWLIST",
        "zhiyun.finance.example.com,api.finance.example.com",
    )
    assert ProxyPolicy.from_environment().targets == frozenset(
        {
            normalize_network_target("https://zhiyun.finance.example.com:443"),
            normalize_network_target("https://api.finance.example.com:443"),
        }
    )


@pytest.mark.parametrize(
    "allowlist",
    [
        "*.finance.example.com",
        "192.168.10.167",
        "zhiyun.finance.example.com,zhiyun.finance.example.com",
    ],
)
def test_proxy_policy_rejects_broad_ip_or_duplicate_hosts(monkeypatch, allowlist: str) -> None:
    monkeypatch.delenv("FINANCIAL_EGRESS_PROXY_TARGETS", raising=False)
    monkeypatch.setenv("FINANCIAL_EGRESS_PROXY_ALLOWLIST", allowlist)
    with pytest.raises(NetworkPolicyError):
        ProxyPolicy.from_environment()


def test_internal_http_proxy_rewrites_only_exact_target(monkeypatch) -> None:
    monkeypatch.setenv("FINANCIAL_NETWORK_POLICY_MODE", "internal")
    policy = ProxyPolicy(
        targets=frozenset({normalize_network_target("http://192.168.10.167:18880")}),
    )
    host, port, forwarded = prepare_http_request(
        b"GET http://192.168.10.167:18880/login?a=1 HTTP/1.1\r\n"
        b"Host: attacker.example\r\nProxy-Authorization: secret\r\n\r\n",
        policy,
    )
    assert (host, port) == ("192.168.10.167", 18880)
    assert forwarded.startswith(
        b"GET /login?a=1 HTTP/1.1\r\nHost: 192.168.10.167:18880\r\n"
    )
    assert b"attacker.example" not in forwarded
    assert b"secret" not in forwarded
    with pytest.raises(ProxyRequestError) as exc_info:
        prepare_http_request(
            b"GET http://192.168.10.168:18880/ HTTP/1.1\r\n\r\n",
            policy,
        )
    assert exc_info.value.status == 403


def test_internal_http_proxy_rejects_unneeded_write_methods(monkeypatch) -> None:
    monkeypatch.setenv("FINANCIAL_NETWORK_POLICY_MODE", "internal")
    policy = ProxyPolicy(
        targets=frozenset({normalize_network_target("http://192.168.10.167:18880")}),
    )
    with pytest.raises(ProxyRequestError) as exc_info:
        prepare_http_request(
            b"PUT http://192.168.10.167:18880/api HTTP/1.1\r\n\r\n",
            policy,
        )
    assert exc_info.value.status == 405


def test_http_proxy_keeps_downloading_after_client_half_closes() -> None:
    async def exercise() -> bytes:
        client_reader = asyncio.StreamReader()
        remote_reader = asyncio.StreamReader()
        client_reader.feed_eof()
        client_writer = _MemoryWriter()
        remote_writer = _MemoryWriter()

        relay = asyncio.create_task(
            _relay_http_response(
                client_reader,
                client_writer,  # type: ignore[arg-type]
                remote_reader,
                remote_writer,  # type: ignore[arg-type]
            )
        )
        await asyncio.sleep(0)
        remote_reader.feed_data(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
        remote_reader.feed_eof()
        await relay
        return bytes(client_writer.data)

    assert asyncio.run(exercise()).endswith(b"\r\n\r\nOK")
