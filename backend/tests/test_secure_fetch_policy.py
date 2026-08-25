from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType
from urllib.error import HTTPError, URLError

import pytest


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


def test_secure_fetch_reports_unreachable_internal_service_before_browser_login(
    monkeypatch,
) -> None:
    wrapper = _load_wrapper()
    monkeypatch.setattr(wrapper.time, "sleep", lambda _seconds: None)

    def unavailable(*_args, **_kwargs):
        raise URLError(TimeoutError("timed out"))

    monkeypatch.setattr(wrapper, "urlopen", unavailable)

    with pytest.raises(wrapper.NetworkReachabilityError, match="智云内网服务不可达"):
        wrapper._assert_login_endpoint_reachable("http://192.168.10.167:18880")


def test_secure_fetch_reachability_retries_transient_502(monkeypatch) -> None:
    wrapper = _load_wrapper()
    calls = 0
    sleeps = []

    class Reachable:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _size):
            return b"x"

    def transient_then_reachable(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError("<REDACTED_URL>", 502, "synthetic", None, None)
        return Reachable()

    monkeypatch.setattr(wrapper, "urlopen", transient_then_reachable)
    monkeypatch.setattr(wrapper.time, "sleep", sleeps.append)

    wrapper._assert_login_endpoint_reachable("http://192.168.10.167:18880")

    assert calls == 2
    assert sleeps == [1.0]


def test_secure_fetch_login_page_retries_transient_502() -> None:
    wrapper = _load_wrapper()

    class Response:
        def __init__(self, status: int):
            self.status = status

    class Page:
        def __init__(self):
            self.statuses = iter((502, 200))
            self.waits: list[int] = []

        def goto(self, *_args, **_kwargs):
            return Response(next(self.statuses))

        def wait_for_timeout(self, milliseconds: int) -> None:
            self.waits.append(milliseconds)

    page = Page()
    wrapper._goto_login_page(page, "http://192.168.10.167:18880")

    assert page.waits == [1_000]


def test_secure_fetch_forwards_supplement_identifiers_without_exposing_credentials(
    monkeypatch,
    tmp_path: Path,
) -> None:
    wrapper = _load_wrapper()
    captured: list[str] = []
    fake = ModuleType("fetch_zhiyun")
    fake.LoginError = RuntimeError
    fake.login_with_password = lambda *_args, **_kwargs: ("", "")
    fake.main = lambda arguments: captured.extend(arguments) or 0
    monkeypatch.setitem(sys.modules, "fetch_zhiyun", fake)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "account": "finance-user",
                    "password": "secret-password",
                    "reconciliation_date": "2026-08-14",
                    "workspace": str(tmp_path),
                    "supplement_ar_ids": ["ar26070140"],
                    "supplement_so_ids": ["so26020320"],
                }
            )
        ),
    )

    assert wrapper.main() == 0
    assert captured[-4:] == [
        "--supplement-ar",
        "AR26070140",
        "--supplement-so",
        "SO26020320",
    ]
    assert "secret-password" in captured


def test_secure_fetch_forwards_one_multi_date_range_call(monkeypatch, tmp_path: Path) -> None:
    wrapper = _load_wrapper()
    captured: list[list[str]] = []
    fake = ModuleType("fetch_zhiyun")
    fake.LoginError = RuntimeError
    fake.login_with_password = lambda *_args, **_kwargs: ("", "")
    fake.main = lambda arguments: captured.append(arguments) or 0
    monkeypatch.setitem(sys.modules, "fetch_zhiyun", fake)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "account": "finance-user",
                    "password": "secret-password",
                    "date_from": "2026-08-17",
                    "date_to": "2026-08-19",
                    "workspace": str(tmp_path),
                }
            )
        ),
    )

    assert wrapper.main() == 0
    assert len(captured) == 1
    assert captured[0][:4] == [
        "--date-from",
        "2026-08-17",
        "--date-to",
        "2026-08-19",
    ]
    assert "--all-days" in captured[0]
    assert "--date" not in captured[0]
