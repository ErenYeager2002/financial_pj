from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import MetaData, create_engine, select, text
from sqlalchemy.engine import make_url


SKIP_TABLES = {"alembic_version"}
SAFE_DATABASE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,62}$")


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _fingerprint(rows: list[dict[str, Any]]) -> str:
    normalized = [
        {key: _canonical(value) for key, value in sorted(row.items())}
        for row in rows
    ]
    normalized.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compare(target_database: str) -> dict[str, Any]:
    if not SAFE_DATABASE.fullmatch(target_database):
        raise RuntimeError("恢复验证数据库名称不合法。")
    database_url = os.environ.get("FINANCIAL_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("缺少 PostgreSQL 连接配置。")
    source_url = make_url(database_url)
    if source_url.get_backend_name() != "postgresql":
        raise RuntimeError("源数据库必须是 PostgreSQL。")
    target_url = source_url.set(database=target_database)
    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url)
    source_meta = MetaData()
    target_meta = MetaData()
    source_meta.reflect(bind=source_engine)
    target_meta.reflect(bind=target_engine)
    source_tables = sorted(set(source_meta.tables) - SKIP_TABLES)
    target_tables = sorted(set(target_meta.tables) - SKIP_TABLES)
    if source_tables != target_tables:
        raise RuntimeError("恢复库表集合与源库不一致。")

    report: dict[str, Any] = {"tables": {}, "verified": True}
    with source_engine.connect() as source, target_engine.connect() as target:
        source_revision = source.scalar(text("SELECT version_num FROM alembic_version"))
        target_revision = target.scalar(text("SELECT version_num FROM alembic_version"))
        report["revision"] = source_revision
        report["revision_verified"] = source_revision == target_revision
        for name in source_tables:
            source_rows = [
                dict(item) for item in source.execute(select(source_meta.tables[name])).mappings()
            ]
            target_rows = [
                dict(item) for item in target.execute(select(target_meta.tables[name])).mappings()
            ]
            source_hash = _fingerprint(source_rows)
            target_hash = _fingerprint(target_rows)
            verified = len(source_rows) == len(target_rows) and source_hash == target_hash
            report["tables"][name] = {
                "rows": len(source_rows),
                "source_sha256": source_hash,
                "target_sha256": target_hash,
                "verified": verified,
            }
    failed = [name for name, item in report["tables"].items() if not item["verified"]]
    report["verified"] = bool(report["revision_verified"]) and not failed
    report["table_count"] = len(report["tables"])
    report["row_count"] = sum(item["rows"] for item in report["tables"].values())
    report["failed_tables"] = failed
    source_engine.dispose()
    target_engine.dispose()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 PostgreSQL 备份恢复结果")
    parser.add_argument("--target-database", required=True)
    args = parser.parse_args()
    report = compare(args.target_database)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
