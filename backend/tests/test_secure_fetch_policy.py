from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_wrapper() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "skills"
        / "ar-hexiao-daily"
        / "vendor"
        / "scripts"
        / "fetch_secure.py"
    )
    spec = importlib.util.spec_from_file_location("platform_fetch_secure", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_secure_fetch_wrapper_enforces_exact_scheme_ip_and_port(monkeypatch) -> None:
    wrapper = _load_wrapper()
    monkeypatch.setenv("FINANCIAL_NETWORK_POLICY_REQUIRED", "1")
    monkeypatch.setenv("FINANCIAL_NETWORK_ACCESS", "1")
    monkeypatch.setenv("FINANCIAL_NETWORK_TARGETS", "http://192.168.10.167:18880")
    assert wrapper._allowed_url("http://192.168.10.167:18880/login") is True
    assert wrapper._allowed_url("http://192.168.10.167:18880/api/query") is True
    assert wrapper._allowed_url("http://192.168.10.168:18880/login") is False
    assert wrapper._allowed_url("http://192.168.10.167:80/login") is False
    assert wrapper._allowed_url("https://192.168.10.167:18880/login") is False


def test_secure_fetch_wrapper_denies_network_when_runtime_access_is_off(monkeypatch) -> None:
    wrapper = _load_wrapper()
    monkeypatch.setenv("FINANCIAL_NETWORK_POLICY_REQUIRED", "1")
    monkeypatch.setenv("FINANCIAL_NETWORK_ACCESS", "0")
    monkeypatch.setenv("FINANCIAL_NETWORK_TARGETS", "http://192.168.10.167:18880")
    assert wrapper._allowed_url("http://192.168.10.167:18880/login") is False
