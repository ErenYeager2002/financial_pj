from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Move:
    kind: str
    resource_id: str
    old_owner: str
    new_owner: str
    source: Path
    target: Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_owner_maps(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        old, separator, new = value.partition("=")
        old, new = old.strip(), new.strip()
        if not separator or not old or not new:
            raise ValueError(f"所有者映射格式错误：{value}，应为 old=new")
        if old in result and result[old] != new:
            raise ValueError(f"同一遗留所有者存在多个目标：{old}")
        result[old] = new
    return result


def table_exists(db: sqlite3.Connection, table: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def rows(db: sqlite3.Connection, sql: str) -> list[sqlite3.Row]:
    return list(db.execute(sql).fetchall())


def assert_idle(db: sqlite3.Connection) -> None:
    checks = {
        "runs": (
            "SELECT COUNT(*) FROM runs WHERE state IN "
            "('created','parsing','waiting_confirmation','queued','running','cancelling')"
        ),
        "workflow_sessions": (
            "SELECT COUNT(*) FROM workflow_sessions WHERE stage IN ('preparing','applying')"
        ),
        "workflow_actions": (
            "SELECT COUNT(*) FROM workflow_actions WHERE state IN ('queued','running')"
        ),
    }
    busy = {
        table: int(db.execute(sql).fetchone()[0])
        for table, sql in checks.items()
        if table_exists(db, table) and int(db.execute(sql).fetchone()[0]) > 0
    }
    if busy:
        raise RuntimeError(f"存在运行中或排队中的任务，拒绝迁移：{busy}")


def collect_owners(db: sqlite3.Connection) -> set[str]:
    owners: set[str] = set()
    for table in (
        "files",
        "runs",
        "workflow_sessions",
        "workflow_batches",
        "model_connections",
        "service_credentials",
    ):
        if table_exists(db, table):
            query = f'SELECT DISTINCT owner_id FROM "{table}"'
            owners.update(str(row[0]) for row in db.execute(query))
    return owners


def choose_source(candidates: list[Path], target: Path) -> Path | None:
    existing = [item.resolve() for item in candidates if item.exists()]
    target = target.resolve()
    distinct = list(dict.fromkeys(existing))
    if target in distinct:
        distinct.remove(target)
    if len(distinct) > 1:
        raise RuntimeError(f"同一资源存在多个旧目录：{distinct}")
    if target.exists() and distinct:
        raise RuntimeError(f"目标目录已存在，拒绝覆盖：{target}")
    return distinct[0] if distinct else None


def build_moves(
    db: sqlite3.Connection,
    data_dir: Path,
    owner_map: dict[str, str],
) -> list[Move]:
    moves: list[Move] = []
    specs = (
        ("upload", "files", "id", "uploads", "kind = 'input'"),
        ("run", "runs", "id", "runs", "1 = 1"),
        ("workflow", "workflow_sessions", "id", "workflows", "1 = 1"),
    )
    for kind, table, id_column, folder, where in specs:
        if not table_exists(db, table):
            continue
        query = f'SELECT "{id_column}" AS resource_id, owner_id FROM "{table}" WHERE {where}'
        for row in rows(db, query):
            resource_id, old_owner = str(row["resource_id"]), str(row["owner_id"])
            new_owner = owner_map.get(old_owner, old_owner)
            root = (data_dir / folder).resolve()
            target = (root / new_owner / resource_id).resolve()
            if not target.is_relative_to(root):
                raise RuntimeError(f"目标目录越界：{target}")
            source = choose_source(
                [root / old_owner / resource_id, root / resource_id],
                target,
            )
            if source:
                moves.append(
                    Move(kind, resource_id, old_owner, new_owner, source, target)
                )
    return moves


def file_manifest(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in root.rglob("*")
        if path.is_file()
    }


def verify_backup_manifest(data_dir: Path, manifest_path: Path) -> None:
    if not manifest_path.is_file():
        raise RuntimeError(f"备份 manifest 不存在：{manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if Path(str(manifest.get("source_data_dir", ""))).resolve() != data_dir:
        raise RuntimeError("备份 manifest 的来源数据目录与迁移目标不一致。")
    hashes = manifest.get("files")
    if not isinstance(hashes, dict) or "financial.db" not in hashes:
        raise RuntimeError("备份 manifest 不含数据库备份。")
    backup_root = manifest_path.parent
    backup_db = backup_root / "financial.db"
    if not backup_db.is_file() or sha256_file(backup_db) != hashes["financial.db"]:
        raise RuntimeError("备份数据库不存在或哈希校验失败。")
    for folder in ("uploads", "runs", "workflows"):
        source_root = data_dir / folder
        if not source_root.is_dir():
            continue
        for path in source_root.rglob("*"):
            if not path.is_file():
                continue
            key = path.relative_to(data_dir).as_posix()
            if hashes.get(key) != sha256_file(path):
                raise RuntimeError(f"待迁移文件未被当前备份完整覆盖：{key}")


def rewrite_file_paths(db: sqlite3.Connection, moves: list[Move]) -> int:
    if not table_exists(db, "files"):
        return 0
    count = 0
    for row in rows(db, "SELECT id, stored_path FROM files"):
        current = Path(str(row["stored_path"])).resolve()
        for move in moves:
            if current.is_relative_to(move.source):
                updated = move.target / current.relative_to(move.source)
                db.execute(
                    "UPDATE files SET stored_path = ? WHERE id = ?",
                    (str(updated.resolve()), str(row["id"])),
                )
                count += 1
                break
    return count


def update_owners(
    db: sqlite3.Connection,
    owner_map: dict[str, str],
    display_names: dict[str, str],
) -> dict[str, int]:
    changed: dict[str, int] = {}
    for old_owner, new_owner in owner_map.items():
        for table in (
            "files",
            "runs",
            "workflow_sessions",
            "workflow_batches",
            "model_connections",
            "service_credentials",
        ):
            if not table_exists(db, table):
                continue
            cursor = db.execute(
                f'UPDATE "{table}" SET owner_id = ? WHERE owner_id = ?',
                (new_owner, old_owner),
            )
            changed[table] = changed.get(table, 0) + cursor.rowcount
        for table in ("runs", "workflow_sessions", "workflow_batches"):
            if table_exists(db, table):
                db.execute(
                    f'UPDATE "{table}" SET owner_name = ? WHERE owner_id = ?',
                    (display_names[new_owner], new_owner),
                )
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="财务平台用户级存储目录离线迁移")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--owner-map", action="append", default=[], metavar="OLD=NEW")
    parser.add_argument("--apply", action="store_true", help="实际执行；默认只生成预检报告")
    parser.add_argument(
        "--backup-manifest",
        type=Path,
        default=None,
        help="--apply 必填；由 backup_database.py 生成的 manifest.json",
    )
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    database = (args.database or data_dir / "financial.db").resolve()
    if not database.is_file():
        raise RuntimeError(f"数据库不存在：{database}")
    owner_map = parse_owner_maps(args.owner_map)
    if args.apply:
        if args.backup_manifest is None:
            raise RuntimeError("实际迁移必须提供 --backup-manifest。")
        verify_backup_manifest(data_dir, args.backup_manifest.resolve())
    report_dir = data_dir / "migrations"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "applied" if args.apply else "dry-run"
    report_path = report_dir / f"user_storage_{stamp}_{mode}.json"

    db = sqlite3.connect(str(database))
    db.row_factory = sqlite3.Row
    completed_moves: list[Move] = []
    try:
        assert_idle(db)
        users = {
            str(row["id"]): str(row["display_name"])
            for row in rows(db, "SELECT id, display_name FROM users")
        }
        owners = collect_owners(db)
        missing = sorted(owner for owner in owners if owner not in users and owner not in owner_map)
        if missing:
            raise RuntimeError(f"以下遗留所有者必须显式映射：{missing}")
        unknown_targets = sorted(set(owner_map.values()) - set(users))
        if unknown_targets:
            raise RuntimeError(f"所有者映射目标不是现有用户：{unknown_targets}")

        moves = build_moves(db, data_dir, owner_map)
        planned = []
        for move in moves:
            before = file_manifest(move.source)
            planned.append(
                {
                    "kind": move.kind,
                    "resource_id": move.resource_id,
                    "old_owner": move.old_owner,
                    "new_owner": move.new_owner,
                    "file_count": len(before),
                    "hashes": before,
                }
            )

        changed: dict[str, int] = {}
        rewritten_paths = 0
        if args.apply:
            db.execute("BEGIN IMMEDIATE")
            expected_hashes = {
                (str(item["kind"]), str(item["resource_id"])): item["hashes"]
                for item in planned
            }
            for move in moves:
                move.target.parent.mkdir(parents=True, exist_ok=True)
                move.source.rename(move.target)
                completed_moves.append(move)
                if file_manifest(move.target) != expected_hashes[(move.kind, move.resource_id)]:
                    raise RuntimeError(f"迁移后哈希复核失败：{move.kind}/{move.resource_id}")
            rewritten_paths = rewrite_file_paths(db, moves)
            changed = update_owners(db, owner_map, users)
            db.commit()

        report = {
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "mode": mode,
            "database": str(database),
            "owner_map": owner_map,
            "resource_count": len(planned),
            "file_count": sum(int(item["file_count"]) for item in planned),
            "rewritten_file_paths": rewritten_paths,
            "updated_owner_rows": changed,
            "resources": planned,
            "status": "verified" if args.apply else "ready",
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"迁移{('完成' if args.apply else '预检完成')}：{report_path}")
        print(f"资源目录：{len(planned)}；文件：{report['file_count']}")
        return 0
    except Exception:
        db.rollback()
        for move in reversed(completed_moves):
            if move.target.exists() and not move.source.exists():
                move.source.parent.mkdir(parents=True, exist_ok=True)
                move.target.rename(move.source)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
