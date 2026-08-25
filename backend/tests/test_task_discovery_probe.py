from __future__ import annotations

import importlib.util
from pathlib import Path


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
