from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.registry import SafetyConstraintSpec, SkillManifest, registry


def test_all_published_skills_have_employee_metadata_and_confirmation() -> None:
    registry.refresh()
    assert registry.errors == []
    published = registry.list()
    assert len(published) == 10
    assert all(item.manifest.id != "ar-hexiao-daily" for item in published)
    assert all(item.manifest.ui is not None for item in published)
    assert all(item.manifest.progress_stages for item in published)
    assert all(item.manifest.risk.requires_confirmation for item in published)


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
