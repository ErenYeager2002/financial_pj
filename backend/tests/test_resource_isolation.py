from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path

from helpers import auth_client

from app.auth_service import get_user_by_username
from app.database import SessionLocal
from app.models import FileRecord, RunRecord, WorkflowBatch, WorkflowSession
from app.resource_policy import run_root, workflow_root
from app.settings import settings


def _upload(client, name: str = "隔离测试.xlsx") -> str:
    response = client.post(
        "/api/files",
        files={"upload": (name, BytesIO(b"synthetic-test-data"), "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_employee_file_is_owner_only_and_uses_user_directory() -> None:
    owner_name = "resource-file-owner"
    with auth_client(username=owner_name) as owner:
        file_id = _upload(owner)
        with SessionLocal() as db:
            user = get_user_by_username(db, owner_name)
            assert user is not None
            record = db.get(FileRecord, file_id)
            assert record is not None
            stored = Path(record.stored_path).resolve()
            assert stored.parent == (settings.upload_dir / user.id / file_id).resolve()

        with auth_client(username="resource-file-other") as other:
            assert other.get(f"/api/files/{file_id}/download").status_code == 404
            assert other.delete(f"/api/files/{file_id}").status_code == 404

        assert owner.get(f"/api/files/{file_id}/download").status_code == 200


def test_employee_run_endpoints_and_sse_are_owner_only() -> None:
    owner_name = "resource-run-owner"
    run_id = str(uuid.uuid4())
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
                    skill_name="隔离测试任务",
                    skill_version="1.0.0",
                    skill_hash="synthetic-hash",
                    manifest_path="synthetic/tool.yaml",
                    manifest_snapshot="{}",
                    adapter="python",
                    worker_pool="python",
                    state="waiting_confirmation",
                    confirmation_required=True,
                )
            )
            db.commit()
            assert run_root(user.id, run_id).parent == (settings.run_dir / user.id).resolve()

        with auth_client(username="resource-run-other") as other:
            assert all(
                item["id"] != run_id
                for item in other.get("/api/runs").json()["items"]
            )
            assert other.get(f"/api/runs/{run_id}").status_code == 404
            assert other.post(f"/api/runs/{run_id}/confirm").status_code == 404
            assert other.post(f"/api/runs/{run_id}/cancel").status_code == 404
            assert other.get(f"/api/runs/{run_id}/events").status_code == 404

        assert owner.get(f"/api/runs/{run_id}").status_code == 200


def test_employee_workflow_and_batch_endpoints_are_owner_only() -> None:
    owner_name = "resource-workflow-owner"
    workflow_id = str(uuid.uuid4())
    batch_id = f"BAT-TEST-{uuid.uuid4().hex[:8]}"
    with auth_client(username=owner_name) as owner:
        with SessionLocal() as db:
            user = get_user_by_username(db, owner_name)
            assert user is not None
            batch = WorkflowBatch(
                id=batch_id,
                owner_id=user.id,
                owner_name=user.display_name,
                department_id=user.department_id,
                skill_id="ar-hexiao-daily",
                skill_name="隔离测试批次",
                skill_version="1.0.0",
                model_connection_id="synthetic-model",
                model_provider="synthetic",
                model_name="synthetic",
            )
            workflow = WorkflowSession(
                id=workflow_id,
                owner_id=user.id,
                owner_name=user.display_name,
                department_id=user.department_id,
                skill_id="ar-hexiao-daily",
                skill_name="隔离测试工作流",
                skill_version="1.0.0",
                skill_hash="synthetic-hash",
                model_connection_id="synthetic-model",
                model_provider="synthetic",
                model_name="synthetic",
                context_json='{"started_from_form": true}',
            )
            db.add_all([batch, workflow])
            db.commit()
            assert workflow_root(user.id, workflow_id).parent == (
                settings.workflow_dir / user.id
            ).resolve()

        with auth_client(username="resource-workflow-other") as other:
            assert all(
                item["id"] != workflow_id for item in other.get("/api/workflows").json()
            )
            assert all(
                item["id"] != batch_id for item in other.get("/api/workflow-batches").json()
            )
            assert other.get(f"/api/workflows/{workflow_id}").status_code == 404
            assert other.put(
                f"/api/workflows/{workflow_id}/files", json={"files": {}}
            ).status_code == 404
            assert other.post(
                f"/api/workflows/{workflow_id}/messages", json={"content": "测试"}
            ).status_code == 404
            assert other.get(f"/api/workflow-batches/{batch_id}").status_code == 404
            assert other.post(f"/api/workflow-batches/{batch_id}/retry").status_code == 404

        assert owner.get(f"/api/workflows/{workflow_id}").status_code == 200
        assert owner.get(f"/api/workflow-batches/{batch_id}").status_code == 200
        assert any(item["id"] == workflow_id for item in owner.get("/api/workflows").json())
