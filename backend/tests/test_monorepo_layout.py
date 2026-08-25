from __future__ import annotations

from pathlib import Path

from scripts import prepare_production_env, sync_finance_skills

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_project_owned_sources_live_under_one_root() -> None:
    assert prepare_production_env.default_next_root(PROJECT_ROOT) == PROJECT_ROOT / "web"
    assert sync_finance_skills.SOURCE_SKILLS == (
        PROJECT_ROOT / "sources" / "finance-skills" / "skills"
    )
    for relative in (
        "web/package.json",
        "backend/app/main.py",
        "skills/ar-hexiao-daily/tool.yaml",
        "sources/finance-skills/skills/ar-hexiao-daily/SKILL.md",
        "tools/xlsx_lightweight_audit.py",
    ):
        assert (PROJECT_ROOT / relative).is_file(), relative


def test_active_runtime_configuration_has_no_old_web_or_skill_source_path() -> None:
    active_files = (
        PROJECT_ROOT / "scripts" / "prepare_production_env.py",
        PROJECT_ROOT / "scripts" / "sync_finance_skills.py",
        PROJECT_ROOT / "deploy" / "production" / "compose.yaml",
        PROJECT_ROOT / "deploy" / "production" / ".env.example",
    )
    forbidden = (
        "D:/anything/next-shadcn-dashboard-starter",
        "D:\\anything\\next-shadcn-dashboard-starter",
        "D:/BESTEASY/finance-skills/skills",
        "D:\\BESTEASY\\finance-skills\\skills",
    )
    for path in active_files:
        content = path.read_text(encoding="utf-8")
        assert not any(value in content for value in forbidden), path
