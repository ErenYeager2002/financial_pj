from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    MetaData,
    create_engine,
    func,
    select,
    text,
)

SKIP_TABLES = {"alembic_version"}


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bytes):
        return value.hex()
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


def _rewrite_path(value: str, source_root: str, target_root: str) -> tuple[str, int]:
    normalized = value.replace("\\", "/")
    source = source_root.replace("\\", "/").rstrip("/")
    if normalized.lower() == source.lower():
        return target_root.rstrip("/"), 1
    prefix = source + "/"
    if normalized.lower().startswith(prefix.lower()):
        return target_root.rstrip("/") + normalized[len(source) :], 1
    return value, 0


def _rewrite_json(value: Any, source_root: str, target_root: str) -> tuple[Any, int]:
    if isinstance(value, str):
        return _rewrite_path(value, source_root, target_root)
    if isinstance(value, list):
        output = []
        count = 0
        for item in value:
            rewritten, changed = _rewrite_json(item, source_root, target_root)
            output.append(rewritten)
            count += changed
        return output, count
    if isinstance(value, dict):
        output = {}
        count = 0
        for key, item in value.items():
            rewritten, changed = _rewrite_json(item, source_root, target_root)
            output[key] = rewritten
            count += changed
        return output, count
    return value, 0


def _convert_row(
    row: dict[str, Any],
    table,
    source_root: str,
    target_root: str,
) -> tuple[dict[str, Any], int]:
    output: dict[str, Any] = {}
    rewrites = 0
    for column in table.columns:
        if column.name not in row:
            continue
        value = row[column.name]
        if isinstance(value, str) and column.name.endswith("_json"):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                parsed, changed = _rewrite_json(parsed, source_root, target_root)
                if changed:
                    value = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
                    rewrites += changed
        elif isinstance(value, str):
            value, changed = _rewrite_path(value, source_root, target_root)
            rewrites += changed
        if value is not None and isinstance(column.type, DateTime) and isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif value is not None and isinstance(column.type, Boolean):
            value = bool(value)
        elif value is not None and isinstance(column.type, Integer) and not isinstance(value, int):
            value = int(value)
        output[column.name] = value
    return output, rewrites


def _reset_sequences(connection, metadata: MetaData) -> None:
    for table in metadata.sorted_tables:
        integer_keys = [
            column
            for column in table.primary_key.columns
            if isinstance(column.type, Integer) and column.autoincrement is not False
        ]
        for column in integer_keys:
            sequence = connection.scalar(
                text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                {"table_name": table.name, "column_name": column.name},
            )
            if not sequence:
                continue
            maximum = connection.scalar(select(func.max(column)))
            connection.execute(
                text("SELECT setval(CAST(:sequence AS regclass), :value, :called)"),
                {
                    "sequence": sequence,
                    "value": int(maximum or 1),
                    "called": maximum is not None,
                },
            )


def migrate(*, apply: bool, report_path: Path | None) -> dict[str, Any]:
    source_url = os.environ.get("FINANCIAL_MIGRATION_SOURCE_URL", "")
    target_url = os.environ.get("FINANCIAL_MIGRATION_TARGET_URL", "")
    source_root = os.environ.get("FINANCIAL_MIGRATION_SOURCE_DATA_DIR", "")
    target_root = os.environ.get("FINANCIAL_MIGRATION_TARGET_DATA_DIR", "")
    if not source_url.startswith("sqlite"):
        raise RuntimeError("迁移源必须是 SQLite。")
    if not target_url.startswith(("postgresql", "postgres")):
        raise RuntimeError("迁移目标必须是 PostgreSQL。")
    if not source_root or not target_root:
        raise RuntimeError("必须配置源和目标数据目录。")

    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url)
    source_metadata = MetaData()
    target_metadata = MetaData()
    source_metadata.reflect(bind=source_engine)
    target_metadata.reflect(bind=target_engine)
    tables = [
        table
        for table in target_metadata.sorted_tables
        if table.name not in SKIP_TABLES and table.name in source_metadata.tables
    ]
    report: dict[str, Any] = {
        "source_dialect": source_engine.dialect.name,
        "target_dialect": target_engine.dialect.name,
        "applied": apply,
        "tables": {},
        "path_rewrites": 0,
    }
    expected: dict[str, list[dict[str, Any]]] = {}
    with source_engine.connect() as source:
        for target_table in tables:
            source_table = source_metadata.tables[target_table.name]
            raw_rows = [dict(item) for item in source.execute(select(source_table)).mappings()]
            converted: list[dict[str, Any]] = []
            for row in raw_rows:
                item, rewrites = _convert_row(row, target_table, source_root, target_root)
                converted.append(item)
                report["path_rewrites"] += rewrites
            expected[target_table.name] = converted
            report["tables"][target_table.name] = {
                "rows": len(converted),
                "source_sha256": _fingerprint(converted),
            }

    if apply:
        with target_engine.begin() as target:
            occupied = {
                table.name: int(target.scalar(select(func.count()).select_from(table)) or 0)
                for table in tables
            }
            occupied = {name: count for name, count in occupied.items() if count}
            if occupied:
                raise RuntimeError(f"PostgreSQL 目标不是空库，拒绝覆盖：{sorted(occupied)}")
            for table in tables:
                rows = expected[table.name]
                for offset in range(0, len(rows), 500):
                    target.execute(table.insert(), rows[offset : offset + 500])
            _reset_sequences(target, target_metadata)

        with target_engine.connect() as target:
            for table in tables:
                actual = [dict(item) for item in target.execute(select(table)).mappings()]
                source_hash = report["tables"][table.name]["source_sha256"]
                target_hash = _fingerprint(actual)
                report["tables"][table.name]["target_sha256"] = target_hash
                report["tables"][table.name]["verified"] = (
                    len(actual) == len(expected[table.name]) and target_hash == source_hash
                )
        failed = [
            name
            for name, item in report["tables"].items()
            if not item.get("verified", False)
        ]
        if failed:
            raise RuntimeError(f"PostgreSQL 写后复核失败：{failed}")

    report["verified"] = bool(apply) and all(
        item.get("verified", False) for item in report["tables"].values()
    )
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    source_engine.dispose()
    target_engine.dispose()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="把财务平台 SQLite 数据迁移到空 PostgreSQL")
    parser.add_argument("--apply", action="store_true", help="执行写入；默认只读取并生成计划")
    parser.add_argument("--report", type=Path, help="脱敏迁移报告路径")
    args = parser.parse_args()
    report = migrate(apply=args.apply, report_path=args.report)
    print(
        json.dumps(
            {
                "applied": report["applied"],
                "verified": report["verified"],
                "tables": len(report["tables"]),
                "rows": sum(item["rows"] for item in report["tables"].values()),
                "path_rewrites": report["path_rewrites"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
