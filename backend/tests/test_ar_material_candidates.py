from pathlib import Path
from types import SimpleNamespace
import json
import uuid
from app.database import SessionLocal, init_db
from app.models import FileRecord, AuditEvent
from app.ar_material_candidates import candidate_year, material_candidates


def test_year_requires_one_unambiguous_four_digit_year():
    assert candidate_year("2026年盈亏.xlsx") == 2026
    assert candidate_year("2025-2026.xlsx") is None
    assert candidate_year("盈亏.xlsx") is None


def test_candidates_preserve_defaults_scope_roles_and_distinct_same_year_files(tmp_path):
    init_db()
    owner = uuid.uuid4().hex
    user = SimpleNamespace(user_id=owner, department_id=owner)
    with SessionLocal() as db:
        def add(name, role=None, other_owner=False, kind="input", exists=True, skill="ar-hexiao-daily"):
            file_id = str(uuid.uuid4())
            path = tmp_path / file_id
            if exists: path.write_bytes(b"fixture")
            db.add(FileRecord(id=file_id, owner_id="other" if other_owner else owner,
                department_id=owner, kind=kind, original_name=name, stored_path=str(path),
                size_bytes=7, sha256="a"*64, skill_id=skill))
            if role:
                db.add(AuditEvent(actor_id=owner, department_id=owner, action="file.upload",
                    resource_type="file", resource_id=file_id, details_json=json.dumps({"role":role})))
            db.flush()
            return file_id
        first = add("2026年盈亏.xlsx")
        second = add("2026年盈亏新版.xlsx")
        neutral_flow = add("银行表.xlsx", "receipt_flow_table")
        add("2025年盈亏别人的.xlsx", other_owner=True)
        add("2025年盈亏其他工具.xlsx", skill="other-tool")
        add("2024年盈亏已删除.xlsx", exists=False)
        add("2023年盈亏输出.xlsx", kind="output")
        bound = {"profit_loss_ledgers": [{"file_id": first, "name": "2026年盈亏.xlsx", "year": 2026}]}
        result, next_page = material_candidates(db, user, "ar-hexiao-daily", bound)
        entries = result["profit_loss_ledgers"]
        assert len(entries) == 2
        assert entries[0]["file_id"] == first and entries[0]["selected"] is True
        assert entries[1]["file_id"] == second and entries[1]["selected"] is False
        assert entries[1]["year"] == 2026
        assert result["receipt_flow_table"][0]["file_id"] == neutral_flow
        assert result["receipt_flow_table"][0]["selected"] is False
        assert "selected" not in bound["profit_loss_ledgers"][0]
        seen = set()
        page = 1
        while page:
            page_entries, page = material_candidates(db, user, "ar-hexiao-daily", {}, page=page, page_size=1)
            for entries in page_entries.values():
                seen.update(e["file_id"] for e in entries)
        assert seen == {first, second, neutral_flow}
        initial, _ = material_candidates(db, user, "ar-hexiao-daily", {})
        assert all(not e["selected"] for entries in initial.values() for e in entries)


def test_stale_material_version_rejected_and_unchanged_selection_needs_no_upload(monkeypatch):
    from app import workflow_service as service
    from fastapi import HTTPException
    import pytest
    current = SimpleNamespace(id="new")
    monkeypatch.setattr(service, "current_material_set", lambda *args: current)
    monkeypatch.setattr(service, "material_set_bindings", lambda *args: {"profit_loss_ledgers": [{"file_id": "ledger"}]})
    permissions = []
    monkeypatch.setattr(service, "assert_skill_permission", lambda *args: permissions.append(args[-1]))
    request = SimpleNamespace(skill_id="ar-hexiao-daily", expected_material_set_id="old",
        files={"profit_loss_ledgers": ["ledger"]}, replace_roles=["profit_loss_ledgers"])
    user = SimpleNamespace(user_id="owner", department_id="finance")
    with pytest.raises(HTTPException) as exc:
        service._assert_start_material_selection(None, user, request)
    assert exc.value.status_code == 409
    request.expected_material_set_id = "new"
    service._assert_start_material_selection(None, user, request)
    assert permissions == []
    request.files = {"profit_loss_ledgers": ["other"]}
    service._assert_start_material_selection(None, user, request)
    assert permissions == ["can_upload"]


def test_hide_referenced_current_files_and_bulk_candidates_without_deleting(tmp_path):
    from app.auth import UserContext
    from app.ar_material_candidates import remove_material_candidates
    from app.workflow_material_service import create_or_replace_current_set, material_set_bindings, current_material_set
    from app.storage import sha256_file
    from fastapi import HTTPException
    import pytest
    init_db()
    owner = uuid.uuid4().hex
    user = UserContext(user_id=owner, display_name="test", department_id=owner, role="finance_user")
    with SessionLocal() as db:
        def add(name, file_owner=owner, skill="ar-hexiao-daily"):
            file_id = str(uuid.uuid4()); path = tmp_path / file_id; path.write_bytes(b"fixture")
            record = FileRecord(id=file_id, owner_id=file_owner, department_id=owner, kind="input",
                original_name=name, stored_path=str(path), size_bytes=7, sha256=sha256_file(path), skill_id=skill)
            db.add(record); db.flush()
            return record
        ledger = add("2026年盈亏.xlsx"); flow = add("到账.xlsx"); extra = add("2025年盈亏.xlsx")
        other = add("2024年盈亏.xlsx", file_owner="another-owner")
        other_tool = add("2024年盈亏.xlsx", skill="other-tool")
        bindings = {"profit_loss_ledgers": [{"file_id": ledger.id, "name": ledger.original_name}],
                    "receipt_flow_table": [{"file_id": flow.id, "name": flow.original_name}]}
        current = create_or_replace_current_set(db, user, "ar-hexiao-daily", bindings)
        ledger.kind = "output"  # A published output must also be hideable.
        ledger.skill_id = ""  # Legacy bindings may have no direct tool provenance.
        db.commit(); db.expire_all()
        original = material_set_bindings(db, current)
        assert remove_material_candidates(db, user, "ar-hexiao-daily", file_id=ledger.id) == 1
        db.commit(); db.expire_all()
        choices, _ = material_candidates(db, user, "ar-hexiao-daily", original)
        assert ledger.id not in {e["file_id"] for entries in choices.values() for e in entries}
        assert material_set_bindings(db, current) == original
        assert remove_material_candidates(db, user, "ar-hexiao-daily", file_id=ledger.id) == 0
        assert remove_material_candidates(db, user, "ar-hexiao-daily", all_files=True) == 2
        db.commit(); db.expire_all()
        choices, page = material_candidates(db, user, "ar-hexiao-daily", original, page_size=1)
        assert not any(choices.values()) and page is None
        assert current_material_set(db, owner, owner, "ar-hexiao-daily").id == current.id
        for record in [ledger, flow, extra, other, other_tool]:
            assert db.get(FileRecord, record.id) is not None
            assert Path(record.stored_path).read_bytes() == b"fixture"
        with pytest.raises(HTTPException) as exc:
            remove_material_candidates(db, user, "ar-hexiao-daily", file_id=other.id)
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException):
            remove_material_candidates(db, user, "ar-hexiao-daily", file_id=other_tool.id)
        with pytest.raises(HTTPException):
            remove_material_candidates(db, user, "ar-hexiao-daily")
        assert remove_material_candidates(db, user, "ar-hexiao-daily", all_files=True) == 0
