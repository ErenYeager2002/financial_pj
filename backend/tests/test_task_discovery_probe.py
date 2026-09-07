from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _probe_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "secure_zhiyun_probe.py"
    spec = importlib.util.spec_from_file_location("secure_zhiyun_probe", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_returns_only_date_count_and_fingerprint() -> None:
    module = _probe_module()

    class SyntheticClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        def filter_rows_by_date(
            self,
            worksheet_id: str,
            control_id: str,
            business_date: str,
        ) -> tuple[list[dict[str, str]], int]:
            self.calls.append((worksheet_id, control_id, business_date))
            return (
                [
                    {"rowid": "row-2", "customer": "不能进入结果"},
                    {"rowid": "row-1", "amount": "999"},
                ],
                2,
            )

    client = SyntheticClient()
    result = module.summarize_dates(
        client,
        ("2026-08-24",),
        worksheet_id="synthetic-sheet",
        date_control_id="synthetic-date-control",
    )

    assert result == [
        {
            "business_date": "2026-08-24",
            "record_count": 2,
            "fingerprint": result[0]["fingerprint"],
        }
    ]
    assert len(result[0]["fingerprint"]) == 64
    assert "不能进入结果" not in str(result)
    assert "999" not in str(result)
    assert client.calls == [
        ("synthetic-sheet", "synthetic-date-control", "2026-08-24")
    ]


@pytest.mark.parametrize("close_fails", [False, True])
def test_main_uses_real_client_session_cleanup_without_losing_results(monkeypatch, capsys, close_fails) -> None:
    module = _probe_module()
    path = Path(__file__).resolve().parents[2] / "skills/ar-hexiao-daily/vendor/scripts/fetch_zhiyun.py"
    spec = importlib.util.spec_from_file_location("probe_real_fetch_zhiyun", path)
    assert spec is not None and spec.loader is not None
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)
    closed = []

    class Session:
        def post(self, *args, **kwargs):
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"data": {"data": [{"rowid": "synthetic-row"}], "count": 1}},
            )

        def close(self):
            closed.append(True)
            if close_fails:
                raise RuntimeError("synthetic cleanup failure")

    import requests

    monkeypatch.setattr(requests, "Session", Session)
    monkeypatch.setattr(fetch, "_assert_platform_network_url", lambda url: None)
    monkeypatch.setitem(sys.modules, "fetch_zhiyun", fetch)
    monkeypatch.setitem(sys.modules, "secure_zhiyun_fetch", SimpleNamespace(
        _edge_login=lambda *args: ("synthetic-cookie", "synthetic-account"),
        LOGIN_FAILURE_MESSAGES={},
    ))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "account": "synthetic-user", "password": "synthetic-password",
        "business_dates": ["2026-09-03"],
    })))

    assert module.main() == 0
    output = capsys.readouterr()
    result = json.loads(output.out)["results"]
    assert [(item["business_date"], item["record_count"]) for item in result] == [("2026-09-03", 1)]
    assert len(result[0]["fingerprint"]) == 64
    assert closed == [True]
    assert "Traceback" not in output.err
    assert "synthetic-password" not in output.out + output.err
    assert "synthetic cleanup failure" not in output.err
