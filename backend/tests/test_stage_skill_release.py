from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import yaml

from app.registry import registry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "stage_skill_release.py"


def _utf8_env() -> dict[str, str]:
    return {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "source"
    source_skill = repo / "skills" / "reconcile-bank"
    package_skill = tmp_path / "package-skill"
    source_skill.mkdir(parents=True)
    (source_skill / "source.txt").write_text("source", encoding="utf-8")
    registry.refresh()
    registered = registry.get("reconcile-bank", include_unpublished=True)
    assert registered is not None
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import shutil,sys; shutil.copytree(sys.argv[1],sys.argv[2])",
            str(registered.directory),
            str(package_skill),
        ],
        check=True,
    )
    manifest_path = package_skill / "tool.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "8.0.0"
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Skill Release Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo, source_skill, package_skill


def test_stage_release_requires_clean_git_and_records_test_evidence(tmp_path: Path) -> None:
    repo, source_skill, package_skill = _fixture(tmp_path)
    inbox = tmp_path / "inbox"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--skill-dir",
            str(package_skill),
            "--source-repo",
            str(repo),
            "--source-skill",
            str(source_skill),
            "--inbox",
            str(inbox),
            "--test-command",
            sys.executable,
            "-c",
            "raise SystemExit(0)",
        ],
        cwd=PROJECT_ROOT,
        env=_utf8_env(),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    packages = list(inbox.glob("*.zip"))
    assert len(packages) == 1
    with zipfile.ZipFile(packages[0]) as archive:
        metadata = json.loads(archive.read(".release.json"))
    assert metadata["tests"]["passed"] is True
    assert len(metadata["source_commit"]) == 40
    assert len(metadata["source_tree_hash"]) == 64

    (source_skill / "source.txt").write_text("dirty", encoding="utf-8")
    rejected = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--skill-dir",
            str(package_skill),
            "--source-repo",
            str(repo),
            "--source-skill",
            str(source_skill),
            "--inbox",
            str(tmp_path / "other-inbox"),
            "--test-command",
            sys.executable,
            "-c",
            "raise SystemExit(0)",
        ],
        cwd=PROJECT_ROOT,
        env=_utf8_env(),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert rejected.returncode != 0
    assert "未提交改动" in rejected.stderr
