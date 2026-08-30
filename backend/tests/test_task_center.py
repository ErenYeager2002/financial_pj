from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from helpers import auth_client
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.auth import UserContext
from app.auth_service import get_user_by_username
from app.database import SessionLocal
from app.models import RunRecord, WorkflowBatch, WorkflowSession
from app.task_center_service import task_center_candidates_query, task_center_view_state


def _run(*, record_id: str, owner_id: str, department_id: str, created_at: datetime) -> RunRecord:
    return RunRecord(
        id=record_id,
        owner_id=owner_id,
        owner_name="任务中心员工",
        department_id=department_id,
        skill_id="xlsx",
        skill_name="表格处理",
        skill_version="1.0.0",
        skill_hash="test-hash",
        manifest_path="skills/xlsx/tool.yaml",
        manifest_snapshot="{}",
        adapter="python",
        worker_pool="python",
        state="queued",
        progress=10,
        progress_message="等待 Worker",
        parameters_json=json.dumps({"business_date": "2026-08-20"}),
        error_message="",
        created_at=created_at,
        queued_at=created_at,
    )


def _workflow(
    *,
    record_id: str,
    display_id: str,
    owner_id: str,
    department_id: str,
    updated_at: datetime,
    started_from_form: bool = True,
) -> WorkflowSession:
    return WorkflowSession(
        id=record_id,
        display_id=display_id,
        owner_id=owner_id,
        owner_name="任务中心员工",
        department_id=department_id,
        skill_id="ar-hexiao-daily",
        skill_name="应收核销日清",
        skill_version="1.0.0",
        skill_hash="test-hash",
        model_connection_id="test-connection",
        model_provider="test",
        model_name="test-model",
        state="waiting_confirmation",
        stage="awaiting_apply_confirmation",
        reconciliation_date="2026-08-22",
        progress=80,
        progress_message="等待确认写入",
        error_message="",
        context_json=json.dumps({"started_from_form": started_from_form}),
        created_at=updated_at - timedelta(hours=1),
        updated_at=updated_at,
    )


def _batch(
    *, record_id: str, display_id: str, owner_id: str, department_id: str, updated_at: datetime
) -> WorkflowBatch:
    return WorkflowBatch(
        id=record_id,
        display_id=display_id,
        owner_id=owner_id,
        owner_name="任务中心员工",
        department_id=department_id,
        skill_id="ar-hexiao-daily",
        skill_name="应收核销日清",
        skill_version="1.0.0",
        model_connection_id="test-connection",
        model_provider="test",
        model_name="test-model",
        reconciliation_dates_json=json.dumps(["2026-08-21", "2026-08-22", "2026-08-23"]),
        state="failed",
        progress=45,
        progress_message="处理失败",
        error_message=(
            'Traceback (most recent call last): File "C:\\finance\\secret.py", line 1; '
            "token=secret https://internal.example/task"
        ),
        created_at=updated_at - timedelta(hours=2),
        updated_at=updated_at,
    )


def _seed_owner_records(username: str, prefix: str) -> tuple[datetime, datetime, datetime]:
    first = datetime(2026, 8, 21, 2, 0, tzinfo=UTC)
    second = first
    third = second + timedelta(hours=1)
    with SessionLocal() as db:
        user = get_user_by_username(db, username)
        assert user is not None
        db.add_all(
            [
                _run(
                    record_id=f"{prefix}-run",
                    owner_id=user.id,
                    department_id=user.department_id,
                    created_at=first,
                ),
                _workflow(
                    record_id=f"{prefix}-workflow",
                    display_id=f"AR-{prefix}",
                    owner_id=user.id,
                    department_id=user.department_id,
                    updated_at=second,
                ),
                _batch(
                    record_id=f"{prefix}-batch",
                    display_id=f"ARB-{prefix}",
                    owner_id=user.id,
                    department_id=user.department_id,
                    updated_at=third,
                ),
                _workflow(
                    record_id=f"{prefix}-unstarted",
                    display_id=f"AR-{prefix}-unstarted",
                    owner_id=user.id,
                    department_id=user.department_id,
                    updated_at=third + timedelta(minutes=1),
                    started_from_form=False,
                ),
            ]
        )
        db.commit()
    return first, second, third


def test_task_center_returns_three_types_with_stable_pagination_and_safe_errors() -> None:
    username = "task-center-three-types"
    with auth_client(username=username) as client:
        _seed_owner_records(username, "tc-three")

        first_page = client.get("/api/task-center", params={"page": 1, "page_size": 2})
        assert first_page.status_code == 200, first_page.text
        first_body = first_page.json()
        second_page = client.get("/api/task-center", params={"page": 2, "page_size": 2})
        assert second_page.status_code == 200, second_page.text
        second_body = second_page.json()

        items = first_body["items"] + second_body["items"]
        assert first_body["total"] == 3
        assert first_body["pages"] == 2
        assert [item["reference_type"] for item in items] == [
            "workflow_batch",
            "run",
            "workflow",
        ]
        assert [item["detail_href"] for item in items] == [
            "/dashboard/workflows/batches/tc-three-batch",
            "/dashboard/runs/tc-three-run",
            "/dashboard/workflows/tc-three-workflow",
        ]
        assert len({(item["reference_type"], item["reference_id"]) for item in items}) == 3
        assert first_body["state_counts"] == {
            "pending": 2,
            "running": 0,
            "failed": 1,
            "succeeded": 0,
            "cancelled": 0,
        }
        failed = items[0]
        assert failed["view_state"] == "failed"
        assert failed["original_state"] == "failed"
        assert failed["business_date_start"] == "2026-08-21"
        assert failed["business_date_end"] == "2026-08-23"
        assert failed["business_date_count"] == 3
        assert failed["error_summary"]
        forbidden = ["Traceback", "C:\\", "token=secret", "https://", "secret.py"]
        assert all(value not in failed["error_summary"] for value in forbidden)
        assert all("unstarted" not in item["reference_id"] for item in items)


def test_task_center_view_state_covers_raw_execution_states() -> None:
    assert task_center_view_state("queued") == "pending"
    assert task_center_view_state("waiting_confirmation") == "pending"
    assert task_center_view_state("active", "awaiting_files") == "pending"
    assert task_center_view_state("running") == "running"
    assert task_center_view_state("cancelling") == "running"
    assert task_center_view_state("finalizing") == "running"
    assert task_center_view_state("timed_out") == "failed"
    assert task_center_view_state("failed") == "failed"
    assert task_center_view_state("succeeded") == "succeeded"
    assert task_center_view_state("cancelled") == "cancelled"


def test_task_center_union_query_compiles_for_postgresql() -> None:
    candidates = task_center_candidates_query(
        "postgresql",
        UserContext(
            user_id="compile-user",
            display_name="编译测试",
            role="finance_user",
            department_id="finance",
        ),
    )
    compiled = str(select(candidates).compile(dialect=postgresql.dialect()))
    assert "UNION ALL" in compiled
    assert "workflow_sessions.context_json LIKE" in compiled
    assert "workflow_sessions.batch_id IS NULL" in compiled


def test_task_center_combines_type_skill_date_update_and_state_filters() -> None:
    username = "task-center-filtering"
    with auth_client(username=username) as client:
        _, second, _ = _seed_owner_records(username, "tc-filter")
        response = client.get(
            "/api/task-center",
            params={
                "item_type": "workflow",
                "skill_id": "ar-hexiao-daily",
                "business_date_from": "2026-08-22",
                "business_date_to": "2026-08-22",
                "updated_from": second.isoformat(),
                "updated_to": second.isoformat(),
                "view_state": "pending",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert [item["reference_id"] for item in body["items"]] == ["tc-filter-workflow"]
        assert body["items"][0]["original_stage"] == "awaiting_apply_confirmation"

        overlap = client.get(
            "/api/task-center",
            params={"business_date_from": "2026-08-23", "business_date_to": "2026-08-23"},
        )
        assert overlap.status_code == 200
        assert [item["reference_id"] for item in overlap.json()["items"]] == ["tc-filter-batch"]

        after_range = client.get("/api/task-center", params={"business_date_from": "2026-08-24"})
        assert after_range.status_code == 200
        assert after_range.json()["total"] == 0
        before_update = client.get(
            "/api/task-center", params={"updated_to": (second - timedelta(seconds=1)).isoformat()}
        )
        assert before_update.status_code == 200
        assert before_update.json()["total"] == 0
        missing_skill = client.get("/api/task-center", params={"skill_id": "missing-skill"})
        assert missing_skill.status_code == 200
        assert missing_skill.json()["total"] == 0
        assert sum(missing_skill.json()["state_counts"].values()) == 0
        reverse_dates = client.get(
            "/api/task-center",
            params={
                "business_date_from": "2026-08-23",
                "business_date_to": "2026-08-21",
            },
        )
        assert reverse_dates.status_code == 422
        reverse_updates = client.get(
            "/api/task-center",
            params={
                "updated_from": (second + timedelta(seconds=1)).isoformat(),
                "updated_to": second.isoformat(),
            },
        )
        assert reverse_updates.status_code == 422


def test_task_center_counts_follow_owner_and_admin_department_visibility() -> None:
    owner_name = "task-center-visible-owner"
    other_name = "task-center-hidden-owner"
    with auth_client(username=owner_name) as owner:
        _seed_owner_records(owner_name, "tc-visible")
    with auth_client(username=other_name, department_id="other"):
        _seed_owner_records(other_name, "tc-hidden")
    with auth_client(username="task-center-same-department-peer"):
        _seed_owner_records("task-center-same-department-peer", "tc-peer")

    with auth_client(username=owner_name) as owner:
        body = owner.get("/api/task-center").json()
        assert body["total"] == 3
        assert sum(body["state_counts"].values()) == 3
        assert all(not item["reference_id"].startswith("tc-peer") for item in body["items"])

    with auth_client(
        role="skill_admin", username="task-center-finance-admin", department_id="finance"
    ) as admin:
        response = admin.get("/api/task-center", params={"page_size": 100})
        assert response.status_code == 200, response.text
        body = response.json()
        visible_ids = {item["reference_id"] for item in body["items"]}
        for page in range(2, body["pages"] + 1):
            response = admin.get(
                "/api/task-center", params={"page": page, "page_size": 100}
            )
            assert response.status_code == 200, response.text
            visible_ids.update(item["reference_id"] for item in response.json()["items"])
        assert "tc-visible-run" in visible_ids
        assert "tc-peer-run" in visible_ids
        assert sum(body["state_counts"].values()) == body["total"]
        assert all(not item["reference_id"].startswith("tc-hidden") for item in body["items"])
