from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


def test_probe_uses_stdin_and_returns_strict_summary(monkeypatch, tmp_path: Path) -> None:
    from app import zhiyun_task_probe

    runtime = SimpleNamespace(timeout_seconds=30)
    registered = SimpleNamespace(
        directory=tmp_path / "skills" / "ar-hexiao-daily",
        manifest=SimpleNamespace(runtime=runtime),
    )
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "results": [
                        {
                            "business_date": "2026-08-24",
                            "record_count": 2,
                            "fingerprint": "a" * 64,
                        }
                    ]
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        zhiyun_task_probe,
        "settings",
        SimpleNamespace(
            project_root=tmp_path,
            zhiyun_base_url="https://zhiyun.example.com",
        ),
    )
    monkeypatch.setattr(zhiyun_task_probe.registry, "get", lambda _skill_id: registered)
    monkeypatch.setattr(
        zhiyun_task_probe,
        "skill_subprocess_environment",
        lambda _runtime: {"SAFE": "1"},
    )
    monkeypatch.setattr(zhiyun_task_probe, "assert_url_allowed", lambda _url, _runtime: "ok")
    monkeypatch.setattr(zhiyun_task_probe.subprocess, "run", fake_run)

    results = zhiyun_task_probe.probe_zhiyun_tasks(
        "synthetic-account",
        "synthetic-password",
        ("2026-08-24",),
    )

    assert results[0].business_date == "2026-08-24"
    assert results[0].record_count == 2
    assert captured["input"] == json.dumps(
        {
            "account": "synthetic-account",
            "password": "synthetic-password",
            "business_dates": ["2026-08-24"],
        },
        ensure_ascii=False,
    )
    assert "synthetic-password" not in captured["command"]
    assert captured["env"] == {
        "SAFE": "1",
        "FINANCIAL_SKILL_DIR": str((registered.directory / "vendor" / "scripts").resolve()),
        "ZHIYUN_BASE": "https://zhiyun.example.com",
    }
