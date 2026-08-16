from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.registry import SafetyConstraintSpec, SkillManifest, registry


def test_all_published_skills_have_employee_metadata_and_confirmation() -> None:
    registry.refresh()
    assert registry.errors == []
    published = registry.list()
    assert len(published) == 11
    assert "ar-hexiao-daily" in {item.manifest.id for item in published}
    assert all(item.manifest.ui is not None for item in published)
    assert all(item.manifest.progress_stages for item in published)
    assert all(item.manifest.risk.requires_confirmation for item in published)


def test_ar_hexiao_is_published_as_a_confirmed_workflow() -> None:
    registry.refresh()
    skill = registry.get("ar-hexiao-daily")
    assert skill is not None
    assert skill.manifest.version == "1.5.1"
    assert skill.manifest.handler.adapter == "workflow"
    assert skill.manifest.runtime.network_access is True
    assert skill.manifest.runtime.network_targets == ["https://zhiyun.synthetic.example:443"]
    assert skill.manifest.risk.requires_confirmation is True
    assert skill.manifest.risk.requires_change_review is True
    assert skill.manifest.risk.requires_approval is True
    assert skill.manifest.file_inputs[0].role == "finance_workbooks"
    assert skill.manifest.file_inputs[0].multiple is True
    assert skill.manifest.file_inputs[0].min_files == 2


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
