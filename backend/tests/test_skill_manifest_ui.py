from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.registry import (
    SafetyConstraintSpec,
    SkillManifest,
    registry,
    validate_declared_operational_profile,
)
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


def test_all_platform_skills_declare_an_operational_profile() -> None:
    registry.refresh()
    skills = registry.list(include_disabled=True)

    assert len(skills) == 19
    assert all("operational_profile" in skill.manifest.model_fields_set for skill in skills)
    assert all(skill.manifest.operational_profile.employee_labels for skill in skills)


def test_operational_profiles_distinguish_direct_fetch_from_uploaded_exports() -> None:
    registry.refresh()
    ar = registry.get("ar-hexiao-daily", include_unpublished=True)
    order_summary = registry.get("order-daily-summary", include_unpublished=True)

    assert ar is not None
    assert order_summary is not None
    assert [source.model_dump() for source in ar.manifest.operational_profile.external_sources] == [
        {"system": "智云", "access": "direct_read", "required": True}
    ]
    assert ar.manifest.runtime.network_access is True
    assert [
        source.model_dump()
        for source in order_summary.manifest.operational_profile.external_sources
    ] == [{"system": "智云", "access": "uploaded_export", "required": True}]
    assert order_summary.manifest.runtime.network_access is False


def test_withholding_report_uses_the_requested_copy_safety_label_only() -> None:
    registry.refresh()
    skill = registry.get("withholding-report-rename", include_unpublished=True)

    assert skill is not None
    assert skill.manifest.operational_profile.employee_labels == ["只读或生成副本"]


def test_employee_catalog_exposes_only_safe_operational_labels() -> None:
    registry.refresh()
    ar = registry.get("ar-hexiao-daily", include_unpublished=True)

    assert ar is not None
    employee = ar.employee_dict()
    assert employee["operation_labels"] == ["智云取数", "复用业务材料", "写入工作副本"]
    assert "operational_profile" not in employee
    assert "external_sources" not in employee
    assert "runtime" not in employee
    assert "upstream" not in employee


def test_direct_external_access_requires_manifest_network_access() -> None:
    registry.refresh()
    skill = registry.get("reconcile-bank", include_unpublished=True)
    assert skill is not None
    payload = skill.manifest.model_dump()
    payload["runtime"]["network_access"] = False
    payload["operational_profile"] = {
        "execution_kind": "offline_file",
        "external_sources": [
            {"system": "示例系统", "access": "direct_read", "required": True}
        ],
        "employee_labels": ["示例系统取数", "输出报告"],
    }

    with pytest.raises(ValidationError, match="外部直连取数必须启用 runtime.network_access"):
        SkillManifest.model_validate(payload)


@pytest.mark.parametrize(
    "unsafe_label",
    [
        "http://10.0.0.8",
        "账号：admin",
        "账号admin",
        "token abc",
        "github.com/a/b",
        "skills/foo",
        "D:\\finance\\input",
        "c6d2154",
        "commit:c6d2154",
    ],
)
def test_employee_operation_labels_reject_sensitive_values(unsafe_label: str) -> None:
    registry.refresh()
    skill = registry.get("reconcile-bank", include_unpublished=True)
    assert skill is not None
    payload = skill.manifest.model_dump()
    payload["operational_profile"]["employee_labels"] = [unsafe_label, "输出报告"]

    with pytest.raises(ValidationError, match="employee_labels 不能包含"):
        SkillManifest.model_validate(payload)


def test_rpa_adapter_and_operational_profile_must_match_in_both_directions() -> None:
    registry.refresh()
    skill = registry.get("reconcile-bank", include_unpublished=True)
    assert skill is not None
    payload = skill.manifest.model_dump()
    payload["handler"]["adapter"] = "rpa"

    with pytest.raises(ValidationError, match="rpa handler 必须声明 browser_rpa"):
        SkillManifest.model_validate(payload)


def test_current_packages_require_profiles_but_legacy_snapshots_still_parse() -> None:
    registry.refresh()
    skill = registry.get("reconcile-bank", include_unpublished=True)
    assert skill is not None
    payload = skill.manifest.model_dump()
    payload.pop("operational_profile")

    with pytest.raises(ValueError, match="显式声明 operational_profile"):
        validate_declared_operational_profile(payload)

    legacy = SkillManifest.model_validate(payload)
    assert legacy.operational_profile.employee_labels == ["历史运行快照", "按原配置执行"]


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
        "receivables-merge-and-split",
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
