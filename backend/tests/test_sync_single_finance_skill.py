from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml
from scripts.sync_finance_skills import (
    CATALOG_ONLY,
    EXECUTABLES,
    OPERATIONAL_PROFILES,
    PRESERVED_PLATFORM_ONLY,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "sync_finance_skills.py"


def test_sync_catalog_profiles_cover_every_known_skill_without_false_gitee_sources() -> None:
    known = set(EXECUTABLES) | set(CATALOG_ONLY)

    assert PRESERVED_PLATFORM_ONLY == {"reconcile-bank"}
    assert set(OPERATIONAL_PROFILES) == known | PRESERVED_PLATFORM_ONLY
    reconcile_manifest = yaml.safe_load(
        (PROJECT_ROOT / "skills" / "reconcile-bank" / "tool.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert reconcile_manifest["operational_profile"] == OPERATIONAL_PROFILES["reconcile-bank"]
    assert OPERATIONAL_PROFILES["withholding-report-rename"]["employee_labels"] == [
        "只读或生成副本"
    ]
    assert "upstream" not in CATALOG_ONLY["jdy-cashflow-export"]
    assert "upstream" not in CATALOG_ONLY["jdy-cashflow-reconcile"]
    assert EXECUTABLES["compliance-spot-check"]["manifest"]["upstream"] == {
        "repository": "https://gitee.com/Lee157/finance-skills.git",
        "path": "skills/compliance-spot-check",
    }


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
    assert manifest["operational_profile"] == {
        "execution_kind": "offline_file",
        "external_sources": [],
        "employee_labels": ["上传应收台账", "本地生成建议", "输出Excel"],
    }
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


def test_project_detail_sync_keeps_portable_lightweight_workbook_guards(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--target",
            str(target),
            "--skill-id",
            "project-detail-to-ledger",
        ],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    script_dir = target / "project-detail-to-ledger" / "vendor" / "scripts"
    implementation = (script_dir / "append_project_detail.py").read_text(encoding="utf-8")
    assert (script_dir / "workbook_finalize.py").is_file()
    assert "create_portable_copy" in implementation
    assert "inspect_lightweight_output" in implementation
    assert "formula_caches_cleared" in implementation
