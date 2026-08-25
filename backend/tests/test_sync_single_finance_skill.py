from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "sync_finance_skills.py"


def test_sync_single_skill_records_bound_source_and_version(tmp_path: Path) -> None:
    source_root = tmp_path / "source" / "skills"
    source_skill = source_root / "compliance-spot-check"
    source_skill.mkdir(parents=True)
    (source_skill / "SKILL.md").write_text(
        "---\nname: compliance-spot-check\n---\n\n# 合规抽查\n",
        encoding="utf-8",
    )
    target = tmp_path / "target"
    commit = "7f4f2d8622a3c50a8159c1ff4fc1c3a9e818be16"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source",
            str(source_root),
            "--target",
            str(target),
            "--skill-id",
            "compliance-spot-check",
            "--repository-url",
            "https://gitee.com/Lee157/finance-skills.git",
            "--source-path",
            "skills/compliance-spot-check",
            "--source-commit",
            commit,
            "--version",
            "2.4.0",
        ],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert {item.name for item in target.iterdir()} == {"compliance-spot-check"}
    manifest = yaml.safe_load(
        (target / "compliance-spot-check" / "tool.yaml").read_text(encoding="utf-8")
    )
    assert manifest["id"] == "compliance-spot-check"
    assert manifest["version"] == "2.4.0"
    assert manifest["upstream"] == {
        "repository": "https://gitee.com/Lee157/finance-skills.git",
        "path": "skills/compliance-spot-check",
        "commit": commit,
    }


def test_sync_source_name_must_match_requested_skill(tmp_path: Path) -> None:
    source_root = tmp_path / "source" / "skills"
    source_skill = source_root / "compliance-spot-check"
    source_skill.mkdir(parents=True)
    (source_skill / "SKILL.md").write_text(
        "---\nname: another-skill\n---\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source",
            str(source_root),
            "--target",
            str(tmp_path / "target"),
            "--skill-id",
            "compliance-spot-check",
        ],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode != 0
    assert "name" in result.stderr
