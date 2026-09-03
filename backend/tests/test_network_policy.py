from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import adapters
from app.network_policy import (
    NetworkPolicyError,
    assert_https_url_allowed,
    assert_url_allowed,
    execution_network_environment,
    normalize_allowed_host,
    normalize_network_target,
    normalize_proxy_url,
    skill_subprocess_environment,
)


def _runtime(
    *,
    enabled: bool,
    allowlist: list[str] | None = None,
    targets: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        network_access=enabled,
        network_allowlist=allowlist or [],
        network_targets=targets or [],
    )


def test_exact_domain_allowlist_builds_child_process_environment() -> None:
    env = execution_network_environment(
        _runtime(enabled=True, allowlist=["api.finance.example.com"])
    )
    assert env == {
        "FINANCIAL_NETWORK_POLICY_REQUIRED": "1",
        "FINANCIAL_NETWORK_ACCESS": "1",
        "FINANCIAL_NETWORK_POLICY_MODE": "strict",
        "FINANCIAL_NETWORK_TARGETS": "https://api.finance.example.com:443",
        "FINANCIAL_NETWORK_ALLOWLIST": "api.finance.example.com",
    }
    assert (
        assert_url_allowed(
            "https://api.finance.example.com/v1/jobs",
            _runtime(enabled=True, allowlist=["api.finance.example.com"]),
        )
        == "api.finance.example.com"
    )


@pytest.mark.parametrize(
    "value",
    [
        "*.example.com",
        "https://api.example.com",
        "api.example.com:443",
        "192.168.10.167",
        "localhost",
    ],
)
def test_allowlist_rejects_broad_or_non_domain_targets(value: str) -> None:
    with pytest.raises(NetworkPolicyError):
        normalize_allowed_host(value)


def test_network_access_requires_allowlist_and_exact_host() -> None:
    with pytest.raises(NetworkPolicyError, match="必须配置"):
        execution_network_environment(_runtime(enabled=True, allowlist=[]))
    with pytest.raises(NetworkPolicyError, match="不在"):
        assert_url_allowed(
            "https://other.example.com/api",
            _runtime(enabled=True, allowlist=["api.example.com"]),
        )
    with pytest.raises(NetworkPolicyError, match="账号或密码"):
        assert_url_allowed(
            "https://user:secret@api.example.com/api",
            _runtime(enabled=True, allowlist=["api.example.com"]),
        )


def test_http_adapter_rejects_target_before_network_call(monkeypatch) -> None:
    called = False

    def unexpected_post(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("不应发出网络请求")

    monkeypatch.setattr(adapters, "build_execution_request", lambda _ctx: ({}, None))
    monkeypatch.setattr(adapters.httpx, "post", unexpected_post)
    ctx = SimpleNamespace(
        manifest=SimpleNamespace(
            handler=SimpleNamespace(endpoint="https://blocked.example.com/api"),
            runtime=_runtime(enabled=True, allowlist=["allowed.example.com"]),
        ),
        emit=lambda *_args, **_kwargs: None,
    )
    with pytest.raises(NetworkPolicyError):
        adapters.HttpAdapter().execute(ctx)
    assert called is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://egress-proxy:8080", "http://egress-proxy:8080"),
        ("http://PROXY.INTERNAL", "http://proxy.internal:80"),
    ],
)
def test_proxy_url_normalization(value: str, expected: str) -> None:
    assert normalize_proxy_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://egress-proxy:8080",
        "http://user:secret@egress-proxy:8080",
        "http://egress-proxy:70000",
        "http://egress-proxy:8080/path",
    ],
)
def test_proxy_url_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(NetworkPolicyError):
        normalize_proxy_url(value)


def test_production_network_skill_requires_controlled_proxy(monkeypatch) -> None:
    runtime = _runtime(enabled=True, allowlist=["api.finance.example.com"])
    monkeypatch.setenv("FINANCIAL_ENV", "production")
    monkeypatch.delenv("FINANCIAL_NETWORK_PROXY_URL", raising=False)
    with pytest.raises(NetworkPolicyError, match="受控出站代理"):
        execution_network_environment(runtime)

    monkeypatch.setenv("FINANCIAL_NETWORK_PROXY_URL", "http://egress-proxy:8080")
    env = execution_network_environment(runtime)
    assert env["HTTPS_PROXY"] == "http://egress-proxy:8080"
    assert env["https_proxy"] == "http://egress-proxy:8080"


def test_skill_child_environment_does_not_inherit_platform_secrets(monkeypatch) -> None:
    monkeypatch.setenv("FINANCIAL_DATABASE_URL", "postgresql://user:secret@database/app")
    monkeypatch.setenv("POSTGRES_PASSWORD", "database-secret")
    monkeypatch.setenv("CLERK_SECRET_KEY", "clerk-secret")
    monkeypatch.setenv("FINANCIAL_LLM_API_KEY", "model-secret")
    env = skill_subprocess_environment(_runtime(enabled=False, allowlist=[]))
    assert "FINANCIAL_DATABASE_URL" not in env
    assert "POSTGRES_PASSWORD" not in env
    assert "CLERK_SECRET_KEY" not in env
    assert "FINANCIAL_LLM_API_KEY" not in env
    assert env["FINANCIAL_NETWORK_ACCESS"] == "0"


def test_skill_child_environment_preserves_windows_browser_locations(monkeypatch) -> None:
    monkeypatch.setenv("PROGRAMFILES", r"C:\Program Files")
    monkeypatch.setenv("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    monkeypatch.setenv("PROGRAMW6432", r"C:\Program Files")

    env = skill_subprocess_environment(_runtime(enabled=False, allowlist=[]))

    assert env["PROGRAMFILES"] == r"C:\Program Files"
    assert env["PROGRAMFILES(X86)"] == r"C:\Program Files (x86)"
    assert env["PROGRAMW6432"] == r"C:\Program Files"


def test_https_business_url_requires_exact_host_and_port_443() -> None:
    runtime = _runtime(enabled=True, allowlist=["zhiyun.finance.example.com"])
    assert (
        assert_https_url_allowed("https://zhiyun.finance.example.com", runtime)
        == "zhiyun.finance.example.com"
    )
    with pytest.raises(NetworkPolicyError, match="HTTPS"):
        assert_https_url_allowed("http://zhiyun.finance.example.com", runtime)
    with pytest.raises(NetworkPolicyError, match="443"):
        assert_https_url_allowed("https://zhiyun.finance.example.com:8443", runtime)


def test_internal_mode_allows_only_exact_private_ipv4_and_explicit_port(monkeypatch) -> None:
    monkeypatch.setenv("FINANCIAL_NETWORK_POLICY_MODE", "internal")
    runtime = _runtime(enabled=True, targets=["http://192.168.10.167:18880"])
    assert (
        assert_url_allowed("http://192.168.10.167:18880/login", runtime)
        == "192.168.10.167"
    )
    env = execution_network_environment(runtime)
    assert env["FINANCIAL_NETWORK_TARGETS"] == "http://192.168.10.167:18880"
    with pytest.raises(NetworkPolicyError, match="不在"):
        assert_url_allowed("http://192.168.10.168:18880/login", runtime)
    with pytest.raises(NetworkPolicyError, match="不在"):
        assert_url_allowed("http://192.168.10.167:80/login", runtime)
    with pytest.raises(NetworkPolicyError):
        assert_url_allowed("https://192.168.10.167:443/login", runtime)


@pytest.mark.parametrize(
    "target",
    [
        "http://127.0.0.1:18880",
        "http://169.254.1.1:18880",
        "http://8.8.8.8:18880",
        "http://192.168.10.167",
        "http://zhiyun.example.com:18880",
    ],
)
def test_internal_mode_rejects_non_rfc1918_or_implicit_targets(monkeypatch, target: str) -> None:
    monkeypatch.setenv("FINANCIAL_NETWORK_POLICY_MODE", "internal")
    with pytest.raises(NetworkPolicyError):
        normalize_network_target(target)


def test_strict_mode_does_not_accept_internal_http_target(monkeypatch) -> None:
    monkeypatch.setenv("FINANCIAL_NETWORK_POLICY_MODE", "strict")
    with pytest.raises(NetworkPolicyError, match="strict"):
        normalize_network_target("http://192.168.10.167:18880")
