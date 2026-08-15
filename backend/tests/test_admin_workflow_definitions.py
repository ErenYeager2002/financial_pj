from __future__ import annotations

import uuid

from helpers import auth_client

from app.auth_service import get_user_by_username
from app.database import SessionLocal
from app.models import StepDefinition, WorkflowDefinition


def test_admin_reads_only_department_workflow_topology_without_node_config() -> None:
    admin_name = f"workflow-admin-{uuid.uuid4().hex[:8]}"

    with auth_client(role="skill_admin", username=admin_name) as admin:
        with SessionLocal() as db:
            user = get_user_by_username(db, admin_name)
            assert user is not None
            visible = WorkflowDefinition(
                id=str(uuid.uuid4()),
                department_id=user.department_id,
                workflow_key=f"visible-{uuid.uuid4()}",
                name="可见流程",
                version="1",
                status="published",
                skill_id="reconcile-bank",
                skill_version="1.0.0",
                skill_hash="a" * 64,
                created_by=user.id,
            )
            hidden = WorkflowDefinition(
                id=str(uuid.uuid4()),
                department_id="other-department",
                workflow_key=f"hidden-{uuid.uuid4()}",
                name="其他部门流程",
                version="1",
                status="published",
                skill_id="reconcile-bank",
                skill_version="1.0.0",
                skill_hash="b" * 64,
                created_by=user.id,
            )
            db.add_all([visible, hidden])
            db.flush()
            db.add_all(
                [
                    StepDefinition(
                        id=str(uuid.uuid4()),
                        workflow_definition_id=visible.id,
                        department_id=visible.department_id,
                        step_key="execute",
                        name="执行 Skill",
                        step_type="python",
                        position=20,
                        config_json='{"command":"must-not-leak"}',
                        worker_pool="python",
                        is_idempotent=True,
                        retryable=True,
                        max_attempts=2,
                    ),
                    StepDefinition(
                        id=str(uuid.uuid4()),
                        workflow_definition_id=visible.id,
                        department_id=visible.department_id,
                        step_key="validate",
                        name="校验参数",
                        step_type="parameter_validation",
                        position=10,
                        config_json='{"secret":"must-not-leak"}',
                        worker_pool="python",
                    ),
                ]
            )
            db.commit()

        response = admin.get("/api/admin/workflow-definitions")
        assert response.status_code == 200, response.text
        items = response.json()
        visible_item = next(item for item in items if item["id"] == visible.id)
        assert all(item["id"] != hidden.id for item in items)
        assert [step["step_key"] for step in visible_item["steps"]] == ["validate", "execute"]
        assert "config_json" not in visible_item["steps"][0]
        assert visible_item["steps"][1]["retryable"] is True

    with auth_client(username=f"workflow-employee-{uuid.uuid4().hex[:8]}") as employee:
        assert employee.get("/api/admin/workflow-definitions").status_code == 403
