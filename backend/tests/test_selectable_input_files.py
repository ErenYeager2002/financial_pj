from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app import file_service
from app.auth import UserContext
from app.auth_service import get_user_by_username
from app.database import SessionLocal
from app.models import FileRecord, WorkflowMaterialSet, WorkflowMaterialSetFile
from helpers import auth_client


def _context(username: str, department_id: str = "finance") -> UserContext:
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
    kind: str = "input",
    skill_id: str = "",
    created_at: datetime | None = None,
) -> FileRecord:
    file_id = str(uuid.uuid4())
    record = FileRecord(
        id=file_id,
        owner_id=user.user_id,
        department_id=user.department_id,
        kind=kind,
        original_name=name,
        stored_path=str(Path("C:/synthetic") / file_id / name),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=100,
        sha256=uuid.uuid4().hex * 2,
        skill_id=skill_id,
        skill_name=skill_id,
        skill_version="1.0.0" if skill_id else "",
        workflow_id="",
        created_at=created_at or datetime.now(UTC),
    )
    db.add(record)
    db.flush()
    return record


def _bind_current_material(db, user: UserContext, skill_id: str, record: FileRecord) -> None:
    now = datetime.now(UTC)
    material_set = WorkflowMaterialSet(
        id=str(uuid.uuid4()),
        owner_id=user.user_id,
        department_id=user.department_id,
        skill_id=skill_id,
        version=1,
        state="current",
        created_at=now,
        published_at=now,
    )
    db.add(material_set)
    db.flush()
    db.add(
        WorkflowMaterialSetFile(
            id=str(uuid.uuid4()),
            material_set_id=material_set.id,
            role="profit_loss_ledgers",
            year=2026,
            file_id=record.id,
            sha256=record.sha256,
        )
    )
    db.flush()


def test_selectable_input_files_default_page_is_lightweight_and_sorted() -> None:
    username = f"selectable-page-{uuid.uuid4().hex[:8]}"
    user_department = f"finance-{uuid.uuid4().hex[:8]}"
    with auth_client(username=username, department_id=user_department) as client:
        user = _context(username, user_department)
        with SessionLocal() as db:
            base = datetime(2026, 1, 1, tzinfo=UTC)
            for index in range(26):
                _file(
                    db,
                    user,
                    name=f"input-{index}.xlsx",
                    created_at=base + timedelta(minutes=index),
                )
            _file(db, user, name="output.xlsx", kind="output", created_at=base)
            db.commit()

        response = client.get("/api/files/selectable-inputs")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 25
    assert body["total"] == 26
    assert body["pages"] == 2
    assert len(body["items"]) == 25
    assert body["items"][0]["name"] == "input-25.xlsx"
    assert body["items"][-1]["name"] == "input-1.xlsx"
    allowed_fields = {
        "id",
        "name",
        "kind",
        "size_bytes",
        "skill_id",
        "skill_name",
        "created_at",
    }
    assert all(set(item) == allowed_fields for item in body["items"])
    assert all(item["kind"] == "input" for item in body["items"])
    forbidden_fields = {
        "sha256",
        "download_url",
        "expires_at",
        "can_delete",
        "delete_block_reason",
        "referenced_run_ids",
        "referenced_workflow_ids",
    }
    assert all(forbidden_fields.isdisjoint(item) for item in body["items"])


def test_selectable_input_files_are_owner_scoped_and_queryable() -> None:
    owner_name = f"selectable-owner-{uuid.uuid4().hex[:8]}"
    other_name = f"selectable-other-{uuid.uuid4().hex[:8]}"
    owner_department = f"finance-{uuid.uuid4().hex[:8]}"
    with auth_client(username=owner_name, department_id=owner_department):
        owner = _context(owner_name, owner_department)
        with SessionLocal() as db:
            target = _file(db, owner, name="银行流水-目标.xlsx")
            _file(db, owner, name="其他文件.xlsx")
            target_id = target.id
            db.commit()

    with auth_client(username=other_name, department_id=owner_department):
        other = _context(other_name, owner_department)
        with SessionLocal() as db:
            _file(db, other, name="银行流水-越权.xlsx")
            db.commit()

    with auth_client(username=owner_name, department_id=owner_department) as client:
        response = client.get(
            "/api/files/selectable-inputs",
            params={"query": "  银行流水  "},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["name"] for item in body["items"]] == ["银行流水-目标.xlsx"]
    assert body["total"] == 1
    assert body["items"][0]["id"] == target_id


def test_selectable_input_file_ids_keep_only_authorized_current_inputs() -> None:
    owner_name = f"selectable-ids-owner-{uuid.uuid4().hex[:8]}"
    other_name = f"selectable-ids-other-{uuid.uuid4().hex[:8]}"
    owner_department = f"finance-{uuid.uuid4().hex[:8]}"
    skill_id = f"selectable-material-{uuid.uuid4().hex[:8]}"
    with auth_client(username=owner_name, department_id=owner_department):
        owner = _context(owner_name, owner_department)
        with SessionLocal() as db:
            unscoped = _file(db, owner, name="普通输入.xlsx")
            current = _file(db, owner, name="当前材料.xlsx", skill_id=skill_id)
            stale = _file(db, owner, name="旧材料.xlsx", skill_id=skill_id)
            output = _file(db, owner, name="输出文件.xlsx", kind="output")
            _bind_current_material(db, owner, skill_id, current)
            unscoped_id = unscoped.id
            current_id = current.id
            stale_id = stale.id
            output_id = output.id
            db.commit()

    with auth_client(username=other_name, department_id=owner_department):
        other = _context(other_name, owner_department)
        with SessionLocal() as db:
            outsider = _file(db, other, name="其他用户输入.xlsx")
            outsider_id = outsider.id
            db.commit()

    requested_ids = ",".join(
        [unscoped_id, current_id, stale_id, output_id, outsider_id, "not-a-real-file-id"]
    )
    with auth_client(username=owner_name, department_id=owner_department) as client:
        response = client.get(
            "/api/files/selectable-inputs",
            params={"ids": requested_ids},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    returned_ids = {item["id"] for item in body["items"]}
    assert returned_ids == {unscoped_id, current_id}
    assert stale_id not in returned_ids
    assert output_id not in returned_ids
    assert outsider_id not in returned_ids
    assert "not-a-real-file-id" not in {item["id"] for item in body["items"]}

    too_many_ids = ",".join(str(uuid.uuid4()) for _ in range(21))
    with auth_client(username=owner_name, department_id=owner_department) as client:
        too_many_response = client.get(
            "/api/files/selectable-inputs",
            params={"ids": too_many_ids},
        )
    assert too_many_response.status_code == 422


def test_selectable_input_file_ids_do_not_scan_delete_status(monkeypatch) -> None:
    username = f"selectable-no-delete-scan-{uuid.uuid4().hex[:8]}"
    department_id = f"finance-{uuid.uuid4().hex[:8]}"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("selectable input files must not scan delete status")

    monkeypatch.setattr(file_service, "file_delete_status", fail_if_called)
    monkeypatch.setattr(file_service, "file_delete_statuses", fail_if_called)

    with auth_client(username=username, department_id=department_id) as client:
        user = _context(username, department_id)
        with SessionLocal() as db:
            record = _file(db, user, name="无需删除扫描.xlsx")
            record_id = record.id
            db.commit()
        response = client.get(
            "/api/files/selectable-inputs",
            params={"ids": record_id},
        )

    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["id"] == record_id
