from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.registry import SkillManifest

IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules", "output"}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root.resolve()):
            raise RuntimeError(f"文件超出源码目录：{path}")
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        stderr=subprocess.STDOUT,
        timeout=30,
    ).strip()


def verify_source(repo: Path, source_skill: Path) -> tuple[str, str, str]:
    if not (repo / ".git").exists():
        raise RuntimeError("源码目录不是 Git 仓库。")
    status = git(repo, "status", "--porcelain")
    if status:
        raise RuntimeError("源码仓库存在未提交改动，不能生成发布包。")
    commit = git(repo, "rev-parse", "HEAD")
    try:
        repository = git(repo, "remote", "get-url", "origin")
    except subprocess.CalledProcessError:
        repository = repo.name
    source = source_skill.resolve()
    if not source.is_relative_to(repo.resolve()) or not source.is_dir():
        raise RuntimeError("源码 Skill 必须位于指定 Git 仓库内。")
    return repository, commit, tree_hash(source)


def validate_package(skill_dir: Path) -> SkillManifest:
    manifest_path = skill_dir / "tool.yaml"
    if not manifest_path.is_file():
        raise RuntimeError("待发布目录缺少 tool.yaml。")
    manifest = SkillManifest.model_validate(
        yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    )
    if not SAFE_ID.fullmatch(manifest.id):
        raise RuntimeError("Skill ID 只能包含字母、数字、点、下划线和短横线。")
    if manifest.ui is None:
        raise RuntimeError("待发布 Skill 缺少员工展示信息。")
    if manifest.handler.entrypoint:
        entrypoint = (skill_dir / manifest.handler.entrypoint).resolve()
        if not entrypoint.is_relative_to(skill_dir.resolve()) or not entrypoint.is_file():
            raise RuntimeError("Skill 执行入口不存在或超出目录。")
    for path in skill_dir.rglob("*.py"):
        if any(part in IGNORED_PARTS for part in path.parts):
            continue
        compile(path.read_bytes(), str(path), "exec")
    return manifest


def run_tests(repo: Path, command: list[str]) -> dict[str, object]:
    if not command:
        raise RuntimeError("必须提供实际测试命令。")
    started = time.monotonic()
    result = subprocess.run(command, cwd=repo, check=False)
    duration = round(time.monotonic() - started, 3)
    if result.returncode != 0:
        raise RuntimeError(f"发布测试失败，退出码 {result.returncode}。")
    return {
        "passed": True,
        "command": command,
        "exit_code": result.returncode,
        "duration_seconds": duration,
        "summary": "受控发布测试通过",
    }


def build_release(
    skill_dir: Path,
    source_repo: Path,
    source_skill: Path,
    inbox: Path,
    test_command: list[str],
) -> Path:
    skill_dir = skill_dir.resolve()
    source_repo = source_repo.resolve()
    manifest = validate_package(skill_dir)
    repository, commit, source_hash = verify_source(source_repo, source_skill)
    tests = run_tests(source_repo, test_command)
    inbox.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="skill-release-") as temp_value:
        content = Path(temp_value) / "content"
        shutil.copytree(
            skill_dir,
            content,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                ".pytest_cache",
                ".ruff_cache",
                "node_modules",
                "output",
                "*.pyc",
            ),
        )
        (content / ".release.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source_repository": repository,
                    "source_commit": commit,
                    "source_tree_hash": source_hash,
                    "tests": tests,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        package_name = f"{manifest.id}-{manifest.version}-{commit[:12]}.zip"
        package = inbox.resolve() / package_name
        if package.exists():
            raise FileExistsError(f"发布包已经存在：{package}")
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(content.rglob("*"), key=lambda item: item.as_posix()):
                if path.is_file():
                    archive.write(path, path.relative_to(content).as_posix())
    print(f"发布包已生成：{package}")
    print(f"包 SHA-256：{sha256_file(package)}")
    print(f"源码提交：{commit}")
    return package


def main() -> int:
    parser = argparse.ArgumentParser(description="从干净 Git 源码和已同步 Skill 生成受控发布包")
    parser.add_argument("--skill-dir", type=Path, required=True, help="已同步的平台 Skill 目录")
    parser.add_argument("--source-repo", type=Path, required=True, help="干净的 finance-skills Git 仓库")
    parser.add_argument("--source-skill", type=Path, required=True, help="源码仓库中的 Skill 目录")
    parser.add_argument(
        "--inbox",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "skill-release-inbox",
        help="服务器受控发布包收件箱",
    )
    parser.add_argument(
        "--test-command",
        nargs=argparse.REMAINDER,
        required=True,
        help="在源码仓库运行的测试命令；必须放在参数末尾",
    )
    args = parser.parse_args()
    build_release(
        args.skill_dir,
        args.source_repo,
        args.source_skill,
        args.inbox,
        args.test_command,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
