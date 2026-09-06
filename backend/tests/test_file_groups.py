from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app import file_service
from app.auth import UserContext
from app.auth_service import get_user_by_username
from app.database import SessionLocal
from app.models import FileRecord, RunRecord
from helpers import auth_client


def _context(username: str, department_id: str) -> UserContext:
    with SessionLocal() as db:
        user = get_user_by_username(db, username)
        assert user is not None
        return UserContext(
            user_id=user.id,
            display_name=user.display_name,
            role=user.role,
            department_id=department_id,
            username=user.username,
        )


def _file(
    db,
    user: UserContext,
    *,
    name: str,
    skill_id: str = "",
    kind: str = "input",
    created_at: datetime,
    run_id: str | None = None,
    skill_name: str | None = None,
    skill_version: str | None = None,
) -> FileRecord:
    record = FileRecord(
        id=str(uuid.uuid4()),
        owner_id=user.user_id,
        department_id=user.department_id,
        kind=kind,
        original_name=name,
        stored_path=str(Path("C:/synthetic") / name),
        content_type="application/octet-stream",
        size_bytes=100,
        sha256=uuid.uuid4().hex * 2,
        skill_id=skill_id,
        run_id=run_id,
        skill_name=skill_name if skill_name is not None else skill_id,
        skill_version=skill_version if skill_version is not None else ("1.0.0" if skill_id else ""),
        workflow_id="",
        created_at=created_at,
    )
    db.add(record)
    db.flush()
    return record


def test_file_groups_use_real_aggregate_counts_and_the_same_group_filter() -> None:
    username = f"file-groups-owner-{uuid.uuid4().hex[:8]}"
    other_username = f"file-groups-other-{uuid.uuid4().hex[:8]}"
    department_id = f"finance-{uuid.uuid4().hex[:8]}"
    skill_a = f"skill-a-{uuid.uuid4().hex[:8]}"
    skill_b = f"skill-b-{uuid.uuid4().hex[:8]}"
    base = datetime(2026, 1, 1, tzinfo=UTC)

    with auth_client(username=username, department_id=department_id):
        owner = _context(username, department_id)
        with SessionLocal() as db:
            for index in range(26):
                _file(
                    db,
                    owner,
                    name=f"同一业务组-{index}.xlsx",
                    skill_id=skill_a,
                    created_at=base + timedelta(minutes=index),
                )
            old_output = _file(
                db,
                owner,
                name="相同结果.xlsx",
                skill_id=skill_a,
                kind="output",
                created_at=base + timedelta(hours=1),
            )
            latest_output = _file(
                db,
                owner,
                name="相同结果.xlsx",
                skill_id=skill_a,
                kind="output",
                created_at=base + timedelta(hours=2),
            )
            for index in range(2):
                _file(
                    db,
                    owner,
                    name=f"另一业务组-{index}.xlsx",
                    skill_id=skill_b,
                    created_at=base + timedelta(hours=3, minutes=index),
                )
            _file(
                db,
                owner,
                name="未归类.xlsx",
                created_at=base + timedelta(hours=4),
            )
            db.commit()

    with auth_client(username=other_username, department_id=department_id):
        other = _context(other_username, department_id)
        with SessionLocal() as db:
            _file(
                db,
                other,
                name="其他用户文件.xlsx",
                skill_id=skill_a,
                created_at=base + timedelta(hours=5),
            )
            db.commit()

    with auth_client(username=username, department_id=department_id) as client:
        groups_response = client.get("/api/files/groups")
        skill_response = client.get(
            "/api/files",
            params={
                "skill_id": skill_a,
                "latest_only": "true",
                "include_delete_status": "false",
            },
        )
        unassigned_response = client.get(
            "/api/files",
            params={"unassigned": "true", "include_delete_status": "false"},
        )
        query_response = client.get(
            "/api/files/groups",
            params={"query": "相同结果"},
        )
        conflicting_response = client.get(
            "/api/files",
            params={"skill_id": skill_a, "unassigned": "true"},
        )

    assert groups_response.status_code == 200, groups_response.text
    groups_body = groups_response.json()
    groups = groups_body["items"]
    assert all(
        set(item) == {"skill_id", "skill_name", "unassigned", "file_count", "latest_created_at"}
        for item in groups
    )
    assert [item["skill_id"] for item in groups] == ["", skill_b, skill_a]
    skill_a_group = next(item for item in groups if item["skill_id"] == skill_a)
    assert skill_a_group["file_count"] == 27
    assert skill_a_group["unassigned"] is False
    assert groups_body["total_files"] == 30
    assert groups_body["total_groups"] == 3
    assert groups[0]["skill_name"] == "未归类文件"
    assert groups[0]["unassigned"] is True

    assert skill_response.status_code == 200, skill_response.text
    skill_body = skill_response.json()
    assert skill_body["total"] == 27
    assert skill_body["page_size"] == 25
    assert len(skill_body["items"]) == 25
    assert all(item["skill_id"] == skill_a for item in skill_body["items"])
    assert unassigned_response.status_code == 200, unassigned_response.text
    assert unassigned_response.json()["total"] == 1

    assert query_response.status_code == 200, query_response.text
    query_body = query_response.json()
    assert query_body["total_files"] == 1
    assert query_body["items"][0]["skill_id"] == skill_a

    assert conflicting_response.status_code == 422
    assert old_output.id not in {item["id"] for item in skill_body["items"]}
    assert latest_output.id in {item["id"] for item in skill_body["items"]}


def test_file_groups_do_not_scan_delete_status(monkeypatch) -> None:
    username = f"file-groups-no-delete-{uuid.uuid4().hex[:8]}"
    department_id = f"finance-{uuid.uuid4().hex[:8]}"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("file groups must not scan delete status")

    monkeypatch.setattr(file_service, "file_delete_status", fail_if_called)
    monkeypatch.setattr(file_service, "file_delete_statuses", fail_if_called)

    with auth_client(username=username, department_id=department_id) as client:
        user = _context(username, department_id)
        with SessionLocal() as db:
            _file(
                db,
                user,
                name="分组汇总不需要删除状态.xlsx",
                created_at=datetime.now(UTC),
            )
            db.commit()
        response = client.get("/api/files/groups")

    assert response.status_code == 200, response.text


def test_historical_output_uses_run_skill_for_group_filter_and_serialization() -> None:
    username = f"historical-output-skill-{uuid.uuid4().hex[:8]}"
    department_id = f"finance-{uuid.uuid4().hex[:8]}"
    skill_id = f"historical-skill-{uuid.uuid4().hex[:8]}"
    run_id = str(uuid.uuid4())
    base = datetime(2026, 2, 1, tzinfo=UTC)

    with auth_client(username=username, department_id=department_id):
        owner = _context(username, department_id)
        with SessionLocal() as db:
            db.add(
                RunRecord(
                    id=run_id,
                    owner_id=owner.user_id,
                    owner_name=owner.display_name,
                    department_id=department_id,
                    skill_id=skill_id,
                    skill_name="历史结果 Skill",
                    skill_version="2.0.0",
                    skill_hash="historical-skill-hash",
                    manifest_path="skills/historical/tool.yaml",
                    manifest_snapshot="{}",
                    adapter="python",
                    worker_pool="python",
                    state="succeeded",
                    created_at=base,
                )
            )
            _file(
                db,
                owner,
                name="历史结果.xlsx",
                kind="output",
                run_id=run_id,
                created_at=base + timedelta(minutes=1),
            )
            latest = _file(
                db,
                owner,
                name="历史结果.xlsx",
                kind="output",
                run_id=run_id,
                created_at=base + timedelta(minutes=2),
            )
            db.commit()

    with auth_client(username=username, department_id=department_id) as client:
        groups_response = client.get("/api/files/groups")
        skill_response = client.get(
            "/api/files",
            params={
                "skill_id": skill_id,
                "latest_only": "true",
                "include_delete_status": "false",
            },
        )
        unassigned_response = client.get(
            "/api/files",
            params={"unassigned": "true", "include_delete_status": "false"},
        )

    assert groups_response.status_code == 200, groups_response.text
    historical_group = next(
        item for item in groups_response.json()["items"] if item["skill_id"] == skill_id
    )
    assert historical_group["skill_name"] == "历史结果 Skill"
    assert historical_group["file_count"] == 1

    assert skill_response.status_code == 200, skill_response.text
    skill_body = skill_response.json()
    assert skill_body["total"] == 1
    assert skill_body["items"][0]["id"] == latest.id
    assert skill_body["items"][0]["skill_id"] == skill_id
    assert skill_body["items"][0]["skill_name"] == "历史结果 Skill"

    assert unassigned_response.status_code == 200, unassigned_response.text
    assert unassigned_response.json()["total"] == 0
