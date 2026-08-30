from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.registry import SafetyConstraintSpec, SkillManifest, registry
from app.skill_execution_experiences import (
    BUSINESS_EXECUTION_EXPERIENCE_IDS,
    FOUNDATION_SKILL_IDS,
    validate_published_execution_experience,
)


def test_all_published_skills_have_employee_metadata_and_risk_configuration() -> None:
    registry.refresh()
    assert registry.errors == []
    published = registry.list()
    assert len(published) == 11
    assert "ar-hexiao-daily" in {item.manifest.id for item in published}
    assert all(item.manifest.ui is not None for item in published)
    assert all(item.manifest.progress_stages for item in published)
    assert all(item.manifest.risk.level for item in published)


def test_ar_hexiao_is_published_as_a_confirmed_workflow() -> None:
    registry.refresh()
    skill = registry.get("ar-hexiao-daily")
    assert skill is not None
    assert skill.manifest.version == "1.6.11"
    assert skill.manifest.handler.adapter == "workflow"
    assert skill.manifest.runtime.network_access is True
    assert skill.manifest.runtime.network_targets == ["https://zhiyun.synthetic.example:443"]
    assert skill.manifest.risk.requires_confirmation is True
    assert skill.manifest.risk.requires_change_review is True
    assert skill.manifest.risk.requires_approval is True
    assert [item.role for item in skill.manifest.file_inputs] == [
        "profit_loss_ledgers",
        "receipt_flow_table",
    ]
    assert skill.manifest.file_inputs[0].multiple is True
    assert skill.manifest.file_inputs[0].min_files == 1
    assert skill.manifest.file_inputs[1].multiple is False
    assert skill.manifest.file_inputs[1].min_files == 1


def test_first_manifest_batch_has_expected_employee_metadata() -> None:
    expected = {
        "reconcile-bank",
        "labor-invoice-check",
        "receivables-merge",
        "dept-expense-alloc",
        "withholding-report-rename",
        "ar-hexiao-daily",
        "jdy-cashflow-reconcile",
    }
    registry.refresh()
    for skill_id in expected:
        skill = registry.get(skill_id, include_unpublished=True)
        assert skill is not None
        assert skill.manifest.ui is not None
        assert skill.manifest.ui.action_label
        assert skill.manifest.progress_stages


def test_safety_constraint_rejects_empty_and_reversed_ranges() -> None:
    with pytest.raises(ValidationError):
        SafetyConstraintSpec.model_validate({})
    with pytest.raises(ValidationError):
        SafetyConstraintSpec.model_validate({"minimum": 2, "maximum": 1})


def test_manifest_rejects_constraint_for_unknown_parameter() -> None:
    skill = registry.get("reconcile-bank", include_unpublished=True)
    assert skill is not None
    payload = skill.manifest.model_dump()
    payload["safety_constraints"] = {"unknown": {"minimum": 0}}
    with pytest.raises(ValidationError):
        SkillManifest.model_validate(payload)


def test_every_published_skill_has_a_controlled_execution_experience() -> None:
    registry.refresh()
    configured = BUSINESS_EXECUTION_EXPERIENCE_IDS | FOUNDATION_SKILL_IDS
    assert {item.manifest.id for item in registry.list()} <= configured


def test_published_python_skills_do_not_use_the_unavailable_placeholder() -> None:
    registry.refresh()
    unavailable_message = "此 Skill 尚未发布，不能创建执行任务。"
    for skill in registry.list():
        if skill.manifest.handler.adapter != "python":
            continue
        entrypoint = skill.manifest.handler.entrypoint
        assert entrypoint is not None
        entry = skill.directory / entrypoint
        assert unavailable_message not in entry.read_text(encoding="utf-8"), skill.manifest.id


def test_unpublished_catalog_skills_keep_the_unavailable_placeholder() -> None:
    registry.refresh()
    unavailable_message = "此 Skill 尚未发布，不能创建执行任务。"
    unpublished = [
        skill
        for skill in registry.list(include_disabled=True)
        if skill.manifest.status != "published"
    ]
    assert {skill.manifest.id for skill in unpublished} == {
        "docx",
        "env-doctor",
        "jdy-cashflow-export",
        "jdy-cashflow-reconcile",
        "pdf",
        "pptx",
        "task-clarifier",
        "xlsx",
    }
    for skill in unpublished:
        entrypoint = skill.manifest.handler.entrypoint
        assert entrypoint is not None
        entry = skill.directory / entrypoint
        assert unavailable_message in entry.read_text(encoding="utf-8"), skill.manifest.id


def test_unknown_business_skill_cannot_be_published_without_an_experience() -> None:
    with pytest.raises(ValueError, match="专属执行体验"):
        validate_published_execution_experience("new-business-skill", "published")


def test_draft_skill_may_be_reviewed_before_its_experience_is_ready() -> None:
    validate_published_execution_experience("new-business-skill", "draft")
