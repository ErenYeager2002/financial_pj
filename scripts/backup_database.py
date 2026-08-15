from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
BACKUP_ROOT = DATA_DIR / "backups"


def _filesystem_path(path: str | Path) -> str:
    raw = os.fspath(path)
    if raw.startswith("\\\\?\\"):
        return raw
    resolved = str(Path(raw).resolve())
    if os.name == "nt" and not resolved.startswith("\\\\?\\"):
        return f"\\\\?\\{resolved}"
    return resolved


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(_filesystem_path(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_database(db_path: Path, target: Path) -> None:
    """使用 SQLite 在线备份 API，保证 WAL 模式下副本一致。"""
    source = sqlite3.connect(str(db_path))
    try:
        target_conn = sqlite3.connect(str(target))
        try:
            source.backup(target_conn)
        finally:
            target_conn.close()
    finally:
        source.close()


def copy_tree(source: Path, target: Path, report: dict[str, str]) -> int:
    """复制目录并把 manifest 键记录为相对备份根目录的完整路径。"""
    if not source.is_dir():
        return 0
    count = 0
    for path in source.rglob("*"):
        if path.is_file():
            relative = path.relative_to(source)
            dest = target / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(_filesystem_path(path), _filesystem_path(dest))
            except FileNotFoundError as exc:
                raise RuntimeError(f"备份文件复制失败：{path} -> {dest}") from exc
            key = dest.relative_to(target.parent).as_posix()
            if key in report:
                raise RuntimeError(f"备份清单出现重复路径：{key}")
            report[key] = sha256_file(dest)
            count += 1
    return count


def _verify_backup(
    backup_dir: Path,
    report: dict[str, str],
    *,
    include_prefix: str = "",
    exclude_prefixes: tuple[str, ...] = (),
) -> None:
    """备份结束后重新读取全部文件并校验哈希，与 manifest 一致才通过。"""
    actual: dict[str, str] = {}
    root = _filesystem_path(backup_dir)
    for directory, _, filenames in os.walk(root):
        for filename in filenames:
            if filename == "manifest.json":
                continue
            path = os.path.join(directory, filename)
            key = os.path.relpath(path, root).replace(os.sep, "/")
            if include_prefix and not key.startswith(include_prefix):
                continue
            if any(key.startswith(prefix) for prefix in exclude_prefixes):
                continue
            actual[key] = sha256_file(path)
    if set(actual) != set(report):
        missing = sorted(set(report) - set(actual))
        extra = sorted(set(actual) - set(report))
        raise RuntimeError(
            f"备份校验失败：manifest 与文件不一致。缺失 {len(missing)}、多余 {len(extra)}。"
        )
    mismatched = [key for key in actual if actual[key] != report[key]]
    if mismatched:
        raise RuntimeError(f"备份校验失败：{len(mismatched)} 个文件哈希不匹配：{mismatched[:5]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="财务 Skill 平台数据库与文件目录备份")
    parser.add_argument(
        "--label",
        default="migration",
        help="备份用途标签，例如 migration / scheduled / pre-release",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
        help="数据目录；默认读取项目 data/",
    )
    parser.add_argument(
        "--include-keys",
        action="store_true",
        help=(
            "把 data/credential.key 放入独立 credential-recovery/ 目录"
            "（视为高敏，需单独限制 ACL）"
        ),
    )
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = data_dir / "backups" / f"{timestamp}_{args.label}"
    backup_dir.mkdir(parents=True, exist_ok=False)

    report: dict[str, str] = {}
    db_path = data_dir / "financial.db"
    if db_path.is_file():
        db_backup = backup_dir / "financial.db"
        _backup_database(db_path, db_backup)
        report["financial.db"] = sha256_file(db_backup)
    else:
        print(f"未找到 {db_path}，跳过数据库备份。")

    for folder in ("uploads", "runs", "workflows", "logs"):
        source = data_dir / folder
        if source.is_dir():
            count = copy_tree(source, backup_dir / folder, report)
            print(f"{folder}: {count} 个文件")

    key_manifest: dict[str, str] = {}
    if args.include_keys:
        key_file = data_dir / "credential.key"
        if key_file.is_file():
            key_dir = backup_dir / "credential-recovery"
            key_dir.mkdir(parents=True, exist_ok=True)
            dest = key_dir / "credential.key"
            shutil.copy2(key_file, dest)
            key_manifest["credential-recovery/credential.key"] = sha256_file(dest)
        else:
            print("未找到 credential.key，跳过密钥恢复包。")

    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    manifest = {
        "label": args.label,
        "created_at": created_at,
        "source_data_dir": str(data_dir),
        "files": report,
        "credential_key_included": bool(key_manifest),
        "credential_recovery_note": (
            "数据库中的模型连接和业务凭据使用 data/credential.key 加密。"
            "默认备份不包含该密钥：仅恢复本备份无法解密这些凭据。"
            "如需凭据恢复能力，请使用 --include-keys 并把 credential-recovery/"
            "目录与主备份分开、使用受限 ACL 单独保管。"
        ),
    }
    manifest_path = backup_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if key_manifest:
        key_manifest_path = backup_dir / "credential-recovery" / "manifest.json"
        key_manifest_path.write_text(
            json.dumps(
                {
                    "created_at": created_at,
                    "warning": (
                        "此密钥文件为高敏恢复包，必须与主备份分开存储并设置严格 ACL；"
                        "泄露该密钥等同于泄露所有加密凭据。"
                    ),
                    "files": key_manifest,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    recovery_prefixes = ("credential-recovery/",) if key_manifest else ()
    _verify_backup(backup_dir, report, exclude_prefixes=recovery_prefixes)
    if key_manifest:
        _verify_backup(
            backup_dir,
            key_manifest,
            include_prefix="credential-recovery/",
        )
    print(f"备份完成并校验通过：{backup_dir}")
    print(f"manifest：{manifest_path}")
    print(f"数据库 SHA-256：{report.get('financial.db', '未备份')}")
    key_status = "是（见 credential-recovery/）" if key_manifest else "否（加密凭据不可恢复）"
    print(f"凭据密钥包含：{key_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
