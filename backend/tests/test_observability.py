from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from helpers import auth_client

from app.auth_service import get_user_by_username
from app.database import SessionLocal
from app.models import (
    ApprovalRecord,
    ModelTraceRecord,
    RunModelAudit,
    RunRecord,
    StepDefinition,
    StepRun,
    WorkflowDefinition,
)
from app.step_runtime_service import finish_run_execution_step, initialize_run_steps


def test_admin_observability_summary_is_aggregate_only_and_department_scoped() -> None:
    admin_name = f"observability-admin-{uuid.uuid4().hex[:8]}"
    department_id = f"observability-{uuid.uuid4().hex[:8]}"
    run_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    with auth_client(
        role="skill_admin",
        username=admin_name,
        department_id=department_id,
    ) as admin:
        with SessionLocal() as db:
            user = get_user_by_username(db, admin_name)
            assert user is not None
            run = RunRecord(
                id=run_id,
                owner_id=user.id,
                owner_name=user.display_name,
                department_id=user.department_id,
                skill_id="reconcile-bank",
                skill_name="银行流水核对",
                skill_version="1.0.0",
                skill_hash="a" * 64,
                manifest_path="D:\\private\\skill\\tool.yaml",
                manifest_snapshot='{"secret":"must-not-leak"}',
                adapter="python",
                worker_pool="python",
                state="failed",
                message="敏感财务原文 must-not-leak",
                parameters_json='{"password":"must-not-leak"}',
                files_json='{"source":"D:\\\\private\\\\finance.xlsx"}',
                error_message="D:\\private\\worker.py token=must-not-leak",
                created_at=now - timedelta(minutes=5),
                queued_at=now - timedelta(minutes=4),
                started_at=now - timedelta(minutes=3),
                finished_at=now - timedelta(minutes=1),
            )
            db.add(run)
            db.flush()
            initialize_run_steps(db, run)
            finish_run_execution_step(
                db,
                run,
                state="failed",
                error_code="adapter_failure",
                error_message="must-not-leak",
            )
            db.add(
                RunModelAudit(
                    run_id=run_id,
                    connection_id="observability-test",
                    provider="openai",
                    model="gpt-test",
                )
            )
            db.add(
                ModelTraceRecord(
                    id=str(uuid.uuid4()),
                    owner_id=user.id,
                    department_id=department_id,
                    run_id=run_id,
                    connection_id="observability-test",
                    purpose="parameter_interpretation",
                    provider="openai",
                    model="gpt-test",
                    status="fallback",
                    duration_ms=25,
                    input_tokens=11,
                    output_tokens=7,
                    failure_code="no_tool_call",
                )
            )
            workflow = WorkflowDefinition(
                id=str(uuid.uuid4()),
                department_id=department_id,
                workflow_key=f"observability-duration-{uuid.uuid4()}",
                name="可观测性时长测试",
                version="1",
                status="published",
                skill_id="reconcile-bank",
                skill_version="1.0.0",
                skill_hash="d" * 64,
                created_by=user.id,
            )
            db.add(workflow)
            db.flush()
            zero_step = StepDefinition(
                id=str(uuid.uuid4()),
                workflow_definition_id=workflow.id,
                department_id=department_id,
                step_key="zero-duration",
                name="零时长步骤",
                step_type="post_write_verification",
                position=10,
                worker_pool="python",
            )
            ten_second_step = StepDefinition(
                id=str(uuid.uuid4()),
                workflow_definition_id=workflow.id,
                department_id=department_id,
                step_key="ten-second-duration",
                name="十秒步骤",
                step_type="post_write_verification",
                position=20,
                worker_pool="python",
            )
            db.add_all([zero_step, ten_second_step])
            db.flush()
            db.add_all(
                [
                    StepRun(
                        id=str(uuid.uuid4()),
                        step_definition_id=zero_step.id,
                        run_id=run_id,
                        owner_id=user.id,
                        department_id=department_id,
                        state="succeeded",
                        started_at=now,
                        finished_at=now,
                    ),
                    StepRun(
                        id=str(uuid.uuid4()),
                        step_definition_id=ten_second_step.id,
                        run_id=run_id,
                        owner_id=user.id,
                        department_id=department_id,
                        state="succeeded",
                        started_at=now - timedelta(seconds=10),
                        finished_at=now,
                    ),
                ]
            )
            for approval_department in (department_id, "other-department"):
                db.add(
                    ApprovalRecord(
                        id=str(uuid.uuid4()),
                        resource_type="run",
                        resource_id=run_id,
                        run_id=run_id,
                        department_id=approval_department,
                        skill_id="reconcile-bank",
                        snapshot_sha256="e" * 64,
                        preview_sha256="f" * 64,
                        snapshot_json="{}",
                        preview_json="{}",
                        status="pending",
                        requested_by=user.id,
                        expires_at=now + timedelta(hours=1),
                    )
                )
            db.commit()

        response = admin.get("/api/admin/observability/summary?hours=24")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["run_count"] == 1
        assert payload["failed_run_count"] == 1
        assert payload["approval_count"] == 1
        duration_metric = next(
            item
            for item in payload["step_metrics"]
            if item["step_type"] == "post_write_verification"
        )
        assert duration_metric["average_duration_seconds"] == 5.0
        assert payload["model_usage"][0]["provider"] == "openai"
        assert payload["model_usage"][0] == {
            "provider": "openai",
            "model": "gpt-test",
            "request_count": 1,
            "failed_count": 0,
            "fallback_count": 1,
            "average_duration_ms": 25.0,
            "input_tokens": 11,
            "output_tokens": 7,
        }
        serialized = response.text
        assert "must-not-leak" not in serialized
        assert "private" not in serialized.lower()
        assert "finance.xlsx" not in serialized

    with auth_client(username=f"observability-user-{uuid.uuid4().hex[:8]}") as employee:
        assert employee.get("/api/admin/observability/summary").status_code == 403
