from __future__ import annotations

from scripts.migrate_sqlite_to_postgres import _fingerprint, _rewrite_json, _rewrite_path


def test_migration_rewrites_only_paths_under_the_data_root() -> None:
    rewritten, changed = _rewrite_path(
        r"D:\BESTEASY\financial_pj\data\users\u1\output.xlsx",
        "D:/BESTEASY/financial_pj/data",
        "/var/lib/financial-platform",
    )
    assert changed == 1
    assert rewritten == "/var/lib/financial-platform/users/u1/output.xlsx"
    untouched, changed = _rewrite_path(
        r"D:\other\input.xlsx",
        "D:/BESTEASY/financial_pj/data",
        "/var/lib/financial-platform",
    )
    assert changed == 0
    assert untouched == r"D:\other\input.xlsx"


def test_migration_rewrites_paths_inside_json_without_changing_other_text() -> None:
    payload, changed = _rewrite_json(
        {
            "workspace": r"D:\BESTEASY\financial_pj\data\users\u1\workflows\w1",
            "message": "保留普通业务文本",
            "files": [r"D:\BESTEASY\financial_pj\data\uploads\a.xlsx"],
        },
        "D:/BESTEASY/financial_pj/data",
        "/var/lib/financial-platform",
    )
    assert changed == 2
    assert payload["workspace"].startswith("/var/lib/financial-platform/")
    assert payload["files"] == ["/var/lib/financial-platform/uploads/a.xlsx"]
    assert payload["message"] == "保留普通业务文本"


def test_migration_fingerprint_is_row_order_independent() -> None:
    rows = [{"id": "b", "value": 2}, {"id": "a", "value": 1}]
    assert _fingerprint(rows) == _fingerprint(list(reversed(rows)))
