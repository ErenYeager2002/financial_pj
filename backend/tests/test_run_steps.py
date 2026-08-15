from __future__ import annotations

import uuid

from helpers import auth_client

from app.auth_service import get_user_by_username
from app.database import SessionLocal
from app.models import RunRecord, StepDefinition, StepRun, WorkflowDefinition


def test_run_owner_can_read_sanitized_step_timeline() -> None:
    owner_name = f"step-owner-{uuid.uuid4().hex[:8]}"
    run_id = str(uuid.uuid4())
    definition_id = str(uuid.uuid4())
    step_id = str(uuid.uuid4())
    step_run_id = str(uuid.uuid4())

    with auth_client(username=owner_name) as owner:
        with SessionLocal() as db:
            user = get_user_by_username(db, owner_name)
            assert user is not None
            db.add(
                RunRecord(
                    id=run_id,
                    owner_id=user.id,
                    owner_name=user.display_name,
                    department_id=user.department_id,
                    skill_id="reconcile-bank",
                    skill_name="银行流水核对",
                    skill_version="1.0.0",
                    skill_hash="a" * 64,
                    manifest_path="skills/reconcile-bank/tool.yaml",
                    manifest_snapshot="{}",
                    adapter="python",
                    worker_pool="python",
                )
            )
            db.add(
                WorkflowDefinition(
                    id=definition_id,
                    department_id=user.department_id,
                    workflow_key=f"run-timeline-{run_id}",
                    name="银行流水核对标准流程",
                    version="1",
                    status="published",
                    skill_id="reconcile-bank",
                    skill_version="1.0.0",
                    skill_hash="a" * 64,
                    created_by=user.id,
                )
            )
            db.flush()
            db.add(
                StepDefinition(
                    id=step_id,
                    workflow_definition_id=definition_id,
                    step_key="validate-files",
                    name="校验平台文件",
                    step_type="file_validation",
                    position=0,
                    config_json='{"internal_path":"must-not-leak"}',
                    timeout_seconds=60,
                    max_attempts=1,
                    worker_pool="python",
                )
            )
            db.flush()
            db.add(
                StepRun(
                    id=step_run_id,
                    step_definition_id=step_id,
                    run_id=run_id,
                    owner_id=user.id,
                    department_id=user.department_id,
                    state="failed",
                    attempt_count=1,
                    input_summary_json=(
                        '{"file_count":2,"password":"must-not-leak",'
                        '"source_path":"C:\\\\finance\\\\input.xlsx"}'
                    ),
                    output_summary_json=(
                        '{"valid":true,"artifact":"/srv/private/result.xlsx",'
                        '"nested":{"token":"must-not-leak","rows":3}}'
                    ),
                    error_code="adapter_failure",
                    error_message=(
                        'Traceback (most recent call last):\n  File "D:\\\\private\\\\worker.py", '
                        'line 12\nRuntimeError: token=must-not-leak'
                    ),
                )
            )
            db.commit()

        response = owner.get(f"/api/runs/{run_id}/steps")
        assert response.status_code == 200, response.text
        payload = response.json()
        created_at = payload[0].pop("created_at")
        assert created_at
        assert payload == [
            {
                "id": step_run_id,
                "step_key": "validate-files",
                "name": "校验平台文件",
                "step_type": "file_validation",
                "position": 0,
                "state": "failed",
                "attempt_count": 1,
                "can_retry": False,
                "retry_block_reason": "",
                "input_summary": {"file_count": 2},
                "output_summary": {
                    "valid": True,
                    "artifact": "<已隐藏路径>",
                    "nested": {"rows": 3},
                },
                "error_code": "adapter_failure",
                "error_message": "步骤执行失败，技术详情已隐藏。",
                "queued_at": None,
                "started_at": None,
                "finished_at": None,
            }
        ]

    with auth_client(username=f"step-other-{uuid.uuid4().hex[:8]}") as other:
        assert other.get(f"/api/runs/{run_id}/steps").status_code == 404

    with auth_client(
        role="skill_admin",
        username=f"step-admin-{uuid.uuid4().hex[:8]}",
        department_id="finance",
    ) as same_department_admin:
        response = same_department_admin.get(f"/api/runs/{run_id}/steps")
        assert response.status_code == 200, response.text
        assert [item["id"] for item in response.json()] == [step_run_id]

    with auth_client(
        role="skill_admin",
        username=f"step-admin-other-{uuid.uuid4().hex[:8]}",
        department_id="other-department",
    ) as other_department_admin:
        assert other_department_admin.get(f"/api/runs/{run_id}/steps").status_code == 404


def test_step_timeline_is_ordered_and_legacy_run_returns_empty_list() -> None:
    owner_name = f"step-order-{uuid.uuid4().hex[:8]}"
    run_id = str(uuid.uuid4())
    legacy_run_id = str(uuid.uuid4())
    definition_id = str(uuid.uuid4())

    with auth_client(username=owner_name) as owner:
        with SessionLocal() as db:
            user = get_user_by_username(db, owner_name)
            assert user is not None
            for item_id in (run_id, legacy_run_id):
                db.add(
                    RunRecord(
                        id=item_id,
                        owner_id=user.id,
                        owner_name=user.display_name,
                        department_id=user.department_id,
                        skill_id="reconcile-bank",
                        skill_name="银行流水核对",
                        skill_version="1.0.0",
                        skill_hash="a" * 64,
                        manifest_path="skills/reconcile-bank/tool.yaml",
                        manifest_snapshot="{}",
                        adapter="python",
                        worker_pool="python",
                    )
                )
            db.add(
                WorkflowDefinition(
                    id=definition_id,
                    department_id=user.department_id,
                    workflow_key=f"ordered-timeline-{run_id}",
                    name="有序时间线",
                    version="1",
                    status="published",
                    skill_id="reconcile-bank",
                    skill_version="1.0.0",
                    skill_hash="a" * 64,
                    created_by=user.id,
                )
            )
            db.flush()
            later = StepDefinition(
                id=str(uuid.uuid4()),
                workflow_definition_id=definition_id,
                step_key="archive",
                name="归档结果",
                step_type="artifact_archive",
                position=20,
                timeout_seconds=60,
                max_attempts=1,
                worker_pool="python",
            )
            earlier = StepDefinition(
                id=str(uuid.uuid4()),
                workflow_definition_id=definition_id,
                step_key="validate",
                name="校验文件",
                step_type="file_validation",
                position=10,
                timeout_seconds=60,
                max_attempts=1,
                worker_pool="python",
            )
            db.add_all([later, earlier])
            db.flush()
            db.add_all(
                [
                    StepRun(
                        id=str(uuid.uuid4()),
                        step_definition_id=later.id,
                        run_id=run_id,
                        owner_id=user.id,
                        department_id=user.department_id,
                    ),
                    StepRun(
                        id=str(uuid.uuid4()),
                        step_definition_id=earlier.id,
                        run_id=run_id,
                        owner_id=user.id,
                        department_id=user.department_id,
                    ),
                ]
            )
            db.commit()

        ordered = owner.get(f"/api/runs/{run_id}/steps")
        assert ordered.status_code == 200, ordered.text
        assert [item["step_key"] for item in ordered.json()] == ["validate", "archive"]

        legacy = owner.get(f"/api/runs/{legacy_run_id}/steps")
        assert legacy.status_code == 200, legacy.text
        assert legacy.json() == []
