from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path


SECRET_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
    b"CLERK_SECRET_KEY=sk_test_",
    b"CLERK_SECRET_KEY=sk_live_",
)
SENSITIVE_NAME = re.compile(
    r"(^|/)(\.env($|\.)|credential\.key$|id_rsa$|id_ed25519$)",
    re.IGNORECASE,
)
SAFE_ENV_EXAMPLES = {".env.example", "env.example.txt"}


def _run(repo: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=not binary,
        encoding=None if binary else "utf-8",
    )
    return result.stdout


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_safe(path: str, content: bytes) -> None:
    normalized = path.replace("\\", "/")
    is_example = Path(normalized).name in SAFE_ENV_EXAMPLES
    is_scanner_source = normalized.endswith("scripts/create_source_rollback.py")
    if SENSITIVE_NAME.search(normalized) and not is_example:
        raise RuntimeError(f"回滚快照拒绝敏感路径：{normalized}")
    for marker in SECRET_MARKERS:
        if is_scanner_source:
            continue
        if is_example and marker.startswith(b"CLERK_SECRET_KEY="):
            continue
        if marker in content:
            raise RuntimeError(f"回滚快照检测到密钥内容：{normalized}")


def snapshot(repo: Path, name: str, output: Path) -> dict[str, object]:
    repo = repo.resolve()
    if not (repo / ".git").exists():
        raise RuntimeError(f"不是 Git 仓库：{repo}")
    target = output / name
    target.mkdir(parents=True, exist_ok=False)
    head = str(_run(repo, "rev-parse", "HEAD")).strip()
    patch = _run(repo, "diff", "--binary", "HEAD", binary=True)
    assert isinstance(patch, bytes)
    _assert_safe("tracked.patch", patch)
    patch_path = target / "tracked.patch"
    patch_path.write_bytes(patch)

    raw_untracked = _run(repo, "ls-files", "-z", "--others", "--exclude-standard", binary=True)
    assert isinstance(raw_untracked, bytes)
    untracked = [item.decode("utf-8") for item in raw_untracked.split(b"\0") if item]
    zip_path = target / "untracked.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(untracked):
            source = (repo / relative).resolve()
            if not source.is_relative_to(repo) or not source.is_file() or source.is_symlink():
                raise RuntimeError(f"回滚快照拒绝异常路径：{relative}")
            content = source.read_bytes()
            _assert_safe(relative, content)
            archive.writestr(relative.replace("\\", "/"), content)

    bundle_path = target / "base.bundle"
    subprocess.run(
        ["git", "bundle", "create", str(bundle_path), "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    status = str(_run(repo, "status", "--porcelain=v1")).splitlines()
    manifest = {
        "name": name,
        "head": head,
        "created_at": datetime.now(UTC).isoformat(),
        "dirty_entries": len(status),
        "untracked_files": len(untracked),
        "artifacts": {
            "base.bundle": _sha256(bundle_path),
            "tracked.patch": _sha256(patch_path),
            "untracked.zip": _sha256(zip_path),
        },
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="创建不含忽略文件的 Git 源码回滚快照")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--repo",
        action="append",
        required=True,
        help="格式为名称=仓库绝对路径，可重复传入。",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifests = []
    for item in args.repo:
        name, separator, path = item.partition("=")
        if not separator or not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
            raise RuntimeError("--repo 必须使用 名称=绝对路径 格式。")
        manifests.append(snapshot(Path(path), name, output))
    summary = {
        "verified": True,
        "output": str(output),
        "repositories": [
            {
                "name": item["name"],
                "head": item["head"],
                "dirty_entries": item["dirty_entries"],
                "untracked_files": item["untracked_files"],
            }
            for item in manifests
        ],
    }
    (output / "README.txt").write_text(
        "恢复方法：先用 base.bundle 取回基线提交，再在仓库根目录应用 tracked.patch，"
        "最后把 untracked.zip 解压到仓库根目录。快照不包含 Git 忽略文件或生产密钥。\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
