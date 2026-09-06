from __future__ import annotations

from app.contracts import CONTRACT_VERSION
from app.main import app


def test_openapi_contains_frozen_domain_contracts() -> None:
    specification = app.openapi()
    schemas = specification["components"]["schemas"]
    required = {
        "PlatformUser",
        "SkillSummary",
        "SkillDetail",
        "AdminSkillDetail",
        "SkillReleaseInboxItem",
        "SkillReleaseRead",
        "RunSummary",
        "RunDetail",
        "TaskCenterItem",
        "TaskCenterPage",
        "TaskCenterStateCounts",
        "RunEventRead",
        "RunApprovalRead",
        "WorkflowDefinitionRead",
        "PlatformFile",
        "AuditEventRead",
        "TaskDraft",
        "ApprovalRecord",
    }
    assert required <= schemas.keys()
    assert CONTRACT_VERSION == "2026-08-31-operational-profile"
    assert specification["info"]["version"] == "0.4.0"


def test_employee_skill_contract_excludes_admin_execution_fields() -> None:
    properties = app.openapi()["components"]["schemas"]["SkillDetail"]["properties"]
    assert "operation_labels" in properties
    assert "operational_profile" not in properties
    assert "external_sources" not in properties
    assert "handler" not in properties
    assert "runtime" not in properties
    assert "permissions" not in properties
    assert "output_schema" not in properties
    assert "skill_hash" not in properties
    assert "source" not in properties


def test_core_routes_publish_explicit_contracts() -> None:
    paths = app.openapi()["paths"]
    session_schema = paths["/api/session"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    run_list_schema = paths["/api/runs"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    run_steps_schema = paths["/api/runs/{run_id}/steps"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    upload_schema = paths["/api/files"]["post"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert session_schema["$ref"].endswith("/PlatformUser")
    assert run_list_schema["$ref"].endswith("/RunPage")
    assert run_steps_schema["type"] == "array"
    assert run_steps_schema["items"]["$ref"].endswith("/StepRunRead")
    assert upload_schema["$ref"].endswith("/PlatformFile")
    assert "/api/workbench" in paths
    assert "/api/files/{file_id}" in paths
    summary_schema = paths["/api/catalog/skill-summaries"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert summary_schema["type"] == "array"
    assert summary_schema["items"]["$ref"].endswith("/SkillSummary")
    group_schema = paths["/api/files/groups"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert group_schema["$ref"].endswith("/PlatformFileGroupSummaryPage")
    assert "/api/runs/{run_id}/retry" in paths
    assert "/api/assistant/prepare" in paths
    assert "/api/task-drafts/{draft_id}/confirm" in paths
    assert "/api/admin/assistant-profile" in paths
    assert "/api/admin/skill-releases" in paths
    assert "/api/admin/skill-releases/{release_id}/publish" in paths
    assert "/api/admin/skill-releases/{release_id}/rollback" not in paths
    assert "/api/admin/skills/{skill_id}/update" in paths
    assert "/api/admin/approvals" in paths
    assert "/api/admin/approvals/{approval_id}/decision" in paths
    assert "/api/admin/workflow-definitions" in paths
    assert "/api/runs/{run_id}/approvals" in paths
    task_center_schema = paths["/api/task-center"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert task_center_schema["$ref"].endswith("/TaskCenterPage")
    assert "/api/workflows/reusable-files" in paths
