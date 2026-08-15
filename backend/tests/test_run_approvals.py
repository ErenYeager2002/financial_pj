from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from helpers import auth_client

from app.auth_service import get_user_by_username
from app.database import SessionLocal
from app.models import ApprovalRecord, RunRecord


def test_run_owner_reads_bounded_approval_timeline_and_other_user_gets_404() -> None:
    username = f"run-approval-{uuid.uuid4().hex[:8]}"
    other_department_username = f"run-approval-other-dept-{uuid.uuid4().hex[:8]}"
    run_id = str(uuid.uuid4())
    approval_id = str(uuid.uuid4())

    with auth_client(
        username=other_department_username,
        department_id="other-department",
    ):
        with SessionLocal() as db:
            other_department_user = get_user_by_username(db, other_department_username)
            assert other_department_user is not None
            other_department_user_id = other_department_user.id

    with auth_client(username=username) as owner:
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            db.add(
                RunRecord(
                    id=run_id,
                    owner_id=user.id,
                    owner_name=user.display_name,
                    department_id=user.department_id,
                    skill_id="controlled-write",
                    skill_name="受控写入",
                    skill_version="1.0.0",
                    skill_hash="a" * 64,
                    manifest_path="skills/controlled-write/tool.yaml",
                    manifest_snapshot="{}",
                    adapter="python",
                    worker_pool="python",
                )
            )
            db.flush()
            db.add(
                ApprovalRecord(
                    id=approval_id,
                    resource_type="run",
                    resource_id=run_id,
                    run_id=run_id,
                    department_id=user.department_id,
                    skill_id="controlled-write",
                    snapshot_sha256="b" * 64,
                    preview_sha256="c" * 64,
                    snapshot_json='{"internal_path":"must-not-leak"}',
                    preview_json=json.dumps(
                        {
                            "change_count": 2,
                            "nested": {
                                "message": "token=preview-secret C:\\private\\preview.xlsx",
                                "items": [
                                    {"note": "/srv/private/result.xlsx"},
                                    {"password": "nested-secret"},
                                ],
                            },
                            "trace": (
                                "Traceback (most recent call last):\n"
                                '  File "D:\\private\\worker.py", line 12'
                            ),
                        },
                        ensure_ascii=False,
                    ),
                    status="approved",
                    requested_by=user.id,
                    decided_by=other_department_user_id,
                    reason=(
                        "token=reason-secret C:\\private\\approval.txt " + "x" * 1000
                    ),
                    decided_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
            db.commit()

        response = owner.get(f"/api/runs/{run_id}/approvals")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload[0]["id"] == approval_id
        assert payload[0]["status"] == "approved"
        assert payload[0]["preview"]["change_count"] == 2
        assert payload[0]["preview"]["nested"]["message"] == (
            "token=<已隐藏> <已隐藏路径>"
        )
        assert payload[0]["preview"]["nested"]["items"] == [
            {"note": "<已隐藏路径>"},
            {},
        ]
        assert payload[0]["preview"]["trace"] == "步骤执行失败，技术详情已隐藏。"
        assert payload[0]["decided_by_name"] == ""
        assert len(payload[0]["reason"]) <= 500
        assert "snapshot_sha256" not in payload[0]
        assert "preview_sha256" not in payload[0]
        assert "snapshot_json" not in payload[0]
        serialized = json.dumps(payload, ensure_ascii=False)
        for secret in (
            "preview-secret",
            "nested-secret",
            "reason-secret",
            "private",
            "preview.xlsx",
            "result.xlsx",
            "worker.py",
            "approval.txt",
        ):
            assert secret not in serialized

    with auth_client(username=f"run-approval-other-{uuid.uuid4().hex[:8]}") as other:
        assert other.get(f"/api/runs/{run_id}/approvals").status_code == 404
