from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path

import yaml


IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules", "output"}
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _manifest(skill_dir: Path) -> dict[str, object]:
    path = skill_dir / "tool.yaml"
    if not path.is_file():
        raise RuntimeError(f"Skill 缺少 tool.yaml：{skill_dir.name}")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Skill Manifest 格式无效：{skill_dir.name}")
    if value.get("id") != skill_dir.name:
        raise RuntimeError(f"Skill 目录名与 Manifest ID 不一致：{skill_dir.name}")
    return value


def _version(value: object, skill_id: str) -> tuple[int, int, int]:
    match = VERSION.fullmatch(str(value or ""))
    if not match:
        raise RuntimeError(f"Skill 版本号必须为三段数字：{skill_id}")
    return tuple(int(item) for item in match.groups())


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _replace(source: Path, target: Path) -> None:
    root = target.parent.resolve()
    temp = (root / f".sync-{target.name}-{uuid.uuid4().hex}").resolve()
    backup = (root / f".sync-backup-{target.name}-{uuid.uuid4().hex}").resolve()
    if not temp.is_relative_to(root) or not backup.is_relative_to(root):
        raise RuntimeError("Skill 同步临时目录越界。")
    moved = False
    try:
        shutil.copytree(
            source,
            temp,
            ignore=shutil.ignore_patterns(*IGNORED_PARTS, "*.pyc"),
        )
        if target.exists():
            os.replace(target, backup)
            moved = True
        os.replace(temp, target)
        shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        if moved and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise


def _plan_skill(source: Path, target_root: Path) -> tuple[str, Path, bool]:
    source_manifest = _manifest(source)
    skill_id = str(source_manifest["id"])
    source_version = _version(source_manifest.get("version"), skill_id)
    target = (target_root / skill_id).resolve()
    if not target.is_relative_to(target_root.resolve()):
        raise RuntimeError(f"Skill 目标目录越界：{skill_id}")
    if not target.exists():
        return f"installed {skill_id} {source_manifest['version']}", target, True

    target_manifest = _manifest(target)
    target_version = _version(target_manifest.get("version"), skill_id)
    if source_version < target_version:
        return f"kept-newer {skill_id} {target_manifest['version']}", target, False
    if source_version > target_version:
        return (
            (
                f"upgraded {skill_id} {target_manifest['version']} -> "
                f"{source_manifest['version']}"
            ),
            target,
            True,
        )
    if _tree_hash(source) != _tree_hash(target):
        raise RuntimeError(
            f"Skill {skill_id} {source_manifest['version']} 内容已变化但版本号未升级；"
            "拒绝覆盖运行时版本。"
        )
    return f"unchanged {skill_id} {source_manifest['version']}", target, False


def sync_skill(source: Path, target_root: Path) -> str:
    message, target, should_replace = _plan_skill(source, target_root)
    if should_replace:
        _replace(source, target)
    return message


def sync_all(
    source_root: Path,
    target_root: Path,
    skill_ids: list[str] | None = None,
) -> list[str]:
    source_root = source_root.resolve()
    target_root = target_root.resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    sources = {
        manifest.parent.name: manifest.parent
        for manifest in sorted(source_root.glob("*/tool.yaml"))
    }
    selected = sorted(set(skill_ids or sources))
    missing = [skill_id for skill_id in selected if skill_id not in sources]
    if missing:
        raise RuntimeError(f"镜像中缺少指定 Skill：{', '.join(missing)}")
    if not selected:
        raise RuntimeError("镜像中没有可同步的 Skill。")
    # 先完成全部校验，再修改数据卷，避免后续 Skill 校验失败时出现部分升级。
    plans = [_plan_skill(sources[skill_id], target_root) for skill_id in selected]
    for skill_id, (_, target, should_replace) in zip(selected, plans, strict=True):
        if should_replace:
            _replace(sources[skill_id], target)
    return [message for message, _, _ in plans]


def main() -> int:
    parser = argparse.ArgumentParser(description="按版本原子同步镜像 Skill 到运行时数据卷")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument(
        "--skill",
        action="append",
        default=[],
        help="只同步指定 Skill，可重复；省略时校验并同步全部 Skill。",
    )
    args = parser.parse_args()
    for result in sync_all(args.source, args.target, args.skill):
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
