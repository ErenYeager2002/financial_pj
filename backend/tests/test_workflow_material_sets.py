from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import workflow_service
from app.auth import UserContext
from app.database import SessionLocal, init_db
from app.models import FileRecord, WorkflowSession
from app.storage import file_delete_status, sha256_file
from app.workflow_material_service import (
    MaterialVersionConflict,
    create_or_replace_current_set,
    current_material_set,
    list_material_sets,
    material_set_bindings,
    publish_workflow_material_set,
    restore_material_set,
)


def _user(prefix: str = "material-owner") -> UserContext:
    suffix = uuid.uuid4().hex[:8]
    return UserContext(
        user_id=f"{prefix}-{suffix}",
        display_name="材料版本测试员工",
        role="finance_user",
        department_id=f"finance-{suffix}",
    )


def _file(
    db,
    user: UserContext,
    *,
    name: str,
    kind: str = "input",
    workflow_id: str = "",
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
        skill_id="ar-hexiao-daily",
        skill_name="应收核销日清",
        skill_version="1.5.1",
        workflow_id=workflow_id,
    )
    db.add(record)
    db.flush()
    return record


def _entry(record: FileRecord) -> dict[str, object]:
    return {
        "file_id": record.id,
        "name": record.original_name,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
    }


def _workflow(user: UserContext, material_set_id: str | None) -> WorkflowSession:
    return WorkflowSession(
        id=str(uuid.uuid4()),
        owner_id=user.user_id,
        owner_name=user.display_name,
        department_id=user.department_id,
        skill_id="ar-hexiao-daily",
        skill_name="应收核销日清",
        skill_version="1.5.1",
        skill_hash="a" * 64,
        model_connection_id="background",
        model_provider="platform",
        model_name="deterministic",
        material_set_id=material_set_id,
    )


def test_legacy_started_workflow_establishes_first_material_version() -> None:
    init_db()
    user = _user("legacy-first")
    with SessionLocal() as db:
        ledger = _file(db, user, name="2026年盈亏核算表.xlsx")
        flow = _file(db, user, name="2026年到账流转表.xlsx")
        workflow = _workflow(user, None)
        workflow.files_json = json.dumps(
            {
                "profit_loss_ledgers": [_entry(ledger)],
                "receipt_flow_table": [_entry(flow)],
            },
            ensure_ascii=False,
        )
        db.add(workflow)
        db.flush()

        selected = workflow_service._ensure_legacy_workflow_material_snapshot(db, workflow)
        db.commit()

        assert selected.version == 1
        assert selected.source_workflow_id == ""
        assert workflow.material_set_id == selected.id
        assert current_material_set(
            db,
            user.user_id,
            user.department_id,
            workflow.skill_id,
        ).id == selected.id


def test_legacy_started_workflow_binds_matching_current_version() -> None:
    init_db()
    user = _user("legacy-match")
    with SessionLocal() as db:
        ledger = _file(db, user, name="2026年盈亏核算表.xlsx")
        flow = _file(db, user, name="2026年到账流转表.xlsx")
        bindings = {
            "profit_loss_ledgers": [_entry(ledger)],
            "receipt_flow_table": [_entry(flow)],
        }
        current = create_or_replace_current_set(
            db,
            user,
            "ar-hexiao-daily",
            bindings,
        )
        workflow = _workflow(user, None)
        workflow.files_json = json.dumps(bindings, ensure_ascii=False)
        db.add(workflow)
        db.flush()

        selected = workflow_service._ensure_legacy_workflow_material_snapshot(db, workflow)
        db.commit()

        assert selected.id == current.id
        assert selected.version == 1
        assert workflow.material_set_id == current.id


def test_legacy_started_workflow_cannot_replace_different_current_version() -> None:
    init_db()
    user = _user("legacy-conflict")
    with SessionLocal() as db:
        current_ledger = _file(db, user, name="2026年盈亏核算表.xlsx")
        current_flow = _file(db, user, name="2026年到账流转表.xlsx")
        current = create_or_replace_current_set(
            db,
            user,
            "ar-hexiao-daily",
            {
                "profit_loss_ledgers": [_entry(current_ledger)],
                "receipt_flow_table": [_entry(current_flow)],
            },
        )
        old_ledger = _file(db, user, name="2026年盈亏核算表_旧任务.xlsx")
        old_flow = _file(db, user, name="2026年到账流转表_旧任务.xlsx")
        workflow = _workflow(user, None)
        workflow.files_json = json.dumps(
            {
                "profit_loss_ledgers": [_entry(old_ledger)],
                "receipt_flow_table": [_entry(old_flow)],
            },
            ensure_ascii=False,
        )
        db.add(workflow)
        db.flush()

        with pytest.raises(MaterialVersionConflict, match="已有更新版本"):
            workflow_service._ensure_legacy_workflow_material_snapshot(db, workflow)

        selected = current_material_set(
            db,
            user.user_id,
            user.department_id,
            workflow.skill_id,
        )
        assert selected is not None and selected.id == current.id
        assert selected.version == 1
        assert workflow.material_set_id is None


def test_bound_stale_workflow_is_rejected_before_writing() -> None:
    init_db()
    user = _user("bound-stale")
    with SessionLocal() as db:
        ledger_v1 = _file(db, user, name="2026年盈亏核算表.xlsx")
        flow_v1 = _file(db, user, name="2026年到账流转表.xlsx")
        version_one = create_or_replace_current_set(
            db,
            user,
            "ar-hexiao-daily",
            {
                "profit_loss_ledgers": [_entry(ledger_v1)],
                "receipt_flow_table": [_entry(flow_v1)],
            },
        )
        stale = _workflow(user, version_one.id)
        db.add(stale)
        ledger_v2 = _file(db, user, name="2026年盈亏核算表_新版本.xlsx")
        flow_v2 = _file(db, user, name="2026年到账流转表_新版本.xlsx")
        version_two = create_or_replace_current_set(
            db,
            user,
            "ar-hexiao-daily",
            {
                "profit_loss_ledgers": [_entry(ledger_v2)],
                "receipt_flow_table": [_entry(flow_v2)],
            },
            expected_current_id=version_one.id,
        )
        db.flush()

        with pytest.raises(MaterialVersionConflict, match="已有更新版本"):
            workflow_service._ensure_legacy_workflow_material_snapshot(db, stale)

        selected = current_material_set(
            db,
            user.user_id,
            user.department_id,
            stale.skill_id,
        )
        assert selected is not None and selected.id == version_two.id


def test_prepare_workspace_rejects_a_superseded_material_version() -> None:
    init_db()
    user = _user("prepare-stale")
    with SessionLocal() as db:
        ledger_v1 = _file(db, user, name="2026年盈亏核算表.xlsx")
        flow_v1 = _file(db, user, name="2026年到账流转表.xlsx")
        version_one = create_or_replace_current_set(
            db,
            user,
            "ar-hexiao-daily",
            {
                "profit_loss_ledgers": [_entry(ledger_v1)],
                "receipt_flow_table": [_entry(flow_v1)],
            },
        )
        workflow = _workflow(user, version_one.id)
        db.add(workflow)
        ledger_v2 = _file(db, user, name="2026年盈亏核算表_修订.xlsx")
        flow_v2 = _file(db, user, name="2026年到账流转表_修订.xlsx")
        create_or_replace_current_set(
            db,
            user,
            "ar-hexiao-daily",
            {
                "profit_loss_ledgers": [_entry(ledger_v2)],
                "receipt_flow_table": [_entry(flow_v2)],
            },
            expected_current_id=version_one.id,
        )
        action = SimpleNamespace(name="prepare_workspace", input_json="{}")

        with pytest.raises(MaterialVersionConflict, match="已有更新版本"):
            workflow_service._copy_inputs(
                db,
                action,
                workflow,
                workflow_service.workflow_root(user.user_id, workflow.id) / "workspace",
            )


def test_upload_set_becomes_current_and_preserves_all_annual_ledgers() -> None:
    init_db()
    user = _user()
    with SessionLocal() as db:
        ledger_2025 = _file(db, user, name="2025年盈亏核算表.xlsx")
        ledger_2026 = _file(db, user, name="2026年盈亏核算表.xlsx")
        flow = _file(db, user, name="2026年到账流转表.xlsx")
        created = create_or_replace_current_set(
            db,
            user,
            "ar-hexiao-daily",
            {
                "profit_loss_ledgers": [_entry(ledger_2025), _entry(ledger_2026)],
                "receipt_flow_table": [_entry(flow)],
            },
        )
        db.commit()

        assert created.version == 1
        assert created.state == "current"
        bindings = material_set_bindings(db, created)
        assert [item["year"] for item in bindings["profit_loss_ledgers"]] == [2025, 2026]
        assert bindings["receipt_flow_table"][0]["file_id"] == flow.id
        assert all(
            entry["material_set_id"] == created.id
            for entries in bindings.values()
            for entry in entries
        )


def test_successful_workflow_publishes_successor_used_by_next_task() -> None:
    init_db()
    user = _user()
    with SessionLocal() as db:
        source_ledger = _file(db, user, name="2026年盈亏核算表.xlsx")
        source_flow = _file(db, user, name="2026年到账流转表.xlsx")
        baseline = create_or_replace_current_set(
            db,
            user,
            "ar-hexiao-daily",
            {
                "profit_loss_ledgers": [_entry(source_ledger)],
                "receipt_flow_table": [_entry(source_flow)],
            },
        )
        workflow = _workflow(user, baseline.id)
        db.add(workflow)
        db.flush()
        written_ledger = _file(
            db,
            user,
            name="2026年盈亏核算表_已写入.xlsx",
            kind="output",
            workflow_id=workflow.id,
        )
        written_flow = _file(
            db,
            user,
            name="2026年到账流转表_已写入.xlsx",
            kind="output",
            workflow_id=workflow.id,
        )

        published = publish_workflow_material_set(
            db,
            workflow,
            {
                "profit_loss_ledgers": [_entry(written_ledger)],
                "receipt_flow_table": [_entry(written_flow)],
            },
        )
        db.commit()

        assert published.version == 2
        assert published.parent_set_id == baseline.id
        assert baseline.state == "superseded"
        current = current_material_set(
            db,
            user.user_id,
            user.department_id,
            workflow.skill_id,
        )
        assert current is not None and current.id == published.id
        published_bindings = material_set_bindings(db, published)
        assert published_bindings["profit_loss_ledgers"][0]["file_id"] == written_ledger.id


def test_stale_workflow_cannot_replace_a_newer_current_version() -> None:
    init_db()
    user = _user()
    with SessionLocal() as db:
        source_ledger = _file(db, user, name="2026年盈亏核算表.xlsx")
        source_flow = _file(db, user, name="2026年到账流转表.xlsx")
        baseline = create_or_replace_current_set(
            db,
            user,
            "ar-hexiao-daily",
            {
                "profit_loss_ledgers": [_entry(source_ledger)],
                "receipt_flow_table": [_entry(source_flow)],
            },
        )
        first = _workflow(user, baseline.id)
        stale = _workflow(user, baseline.id)
        db.add_all([first, stale])
        db.flush()

        first_ledger = _file(
            db,
            user,
            name="2026年盈亏核算表_V2.xlsx",
            kind="output",
            workflow_id=first.id,
        )
        first_flow = _file(
            db,
            user,
            name="2026年到账流转表_V2.xlsx",
            kind="output",
            workflow_id=first.id,
        )
        published = publish_workflow_material_set(
            db,
            first,
            {
                "profit_loss_ledgers": [_entry(first_ledger)],
                "receipt_flow_table": [_entry(first_flow)],
            },
        )
        stale_ledger = _file(
            db,
            user,
            name="2026年盈亏核算表_旧任务.xlsx",
            kind="output",
            workflow_id=stale.id,
        )
        stale_flow = _file(
            db,
            user,
            name="2026年到账流转表_旧任务.xlsx",
            kind="output",
            workflow_id=stale.id,
        )

        with pytest.raises(MaterialVersionConflict):
            publish_workflow_material_set(
                db,
                stale,
                {
                    "profit_loss_ledgers": [_entry(stale_ledger)],
                    "receipt_flow_table": [_entry(stale_flow)],
                },
            )
        current = current_material_set(
            db,
            user.user_id,
            user.department_id,
            stale.skill_id,
        )
        assert current is not None and current.id == published.id


def test_material_version_readback_failure_keeps_previous_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_db()
    user = _user("material-readback")
    with SessionLocal() as db:
        ledger = _file(db, user, name="2026年盈亏核算表.xlsx")
        flow = _file(db, user, name="2026年到账流转表.xlsx")
        baseline = create_or_replace_current_set(
            db,
            user,
            "ar-hexiao-daily",
            {
                "profit_loss_ledgers": [_entry(ledger)],
                "receipt_flow_table": [_entry(flow)],
            },
        )
        workflow = _workflow(user, baseline.id)
        db.add(workflow)
        db.flush()
        output_ledger = _file(
            db,
            user,
            name="2026年盈亏核算表_写后.xlsx",
            kind="output",
            workflow_id=workflow.id,
        )
        output_flow = _file(
            db,
            user,
            name="2026年到账流转表_写后.xlsx",
            kind="output",
            workflow_id=workflow.id,
        )
        original_readback = workflow_service.material_set_bindings

        def fail_new_version_readback(db_session, material_set):
            if material_set.id != baseline.id:
                raise ValueError("synthetic material readback failure")
            return original_readback(db_session, material_set)

        monkeypatch.setattr(
            workflow_service,
            "material_set_bindings",
            fail_new_version_readback,
        )
        with pytest.raises(ValueError, match="synthetic material readback failure"):
            workflow_service._publish_verified_material_set(
                db,
                workflow,
                {
                    "profit_loss_ledgers": [_entry(output_ledger)],
                    "receipt_flow_table": [_entry(output_flow)],
                },
            )

        db.expire_all()
        current = current_material_set(
            db,
            user.user_id,
            user.department_id,
            "ar-hexiao-daily",
        )
        assert current is not None and current.id == baseline.id
        assert current.state == "current"


def test_material_set_rejects_files_from_another_owner() -> None:
    init_db()
    owner = _user("owner")
    other = UserContext(
        user_id=f"other-{uuid.uuid4().hex[:8]}",
        display_name="其他员工",
        role="finance_user",
        department_id=owner.department_id,
    )
    with SessionLocal() as db:
        foreign_ledger = _file(db, other, name="2026年盈亏核算表.xlsx")
        foreign_flow = _file(db, other, name="2026年到账流转表.xlsx")
        with pytest.raises(ValueError, match="所有者"):
            create_or_replace_current_set(
                db,
                owner,
                "ar-hexiao-daily",
                {
                    "profit_loss_ledgers": [_entry(foreign_ledger)],
                    "receipt_flow_table": [_entry(foreign_flow)],
                },
            )


def test_next_independent_workflow_can_copy_published_output_version() -> None:
    init_db()
    user = _user()
    with SessionLocal() as db:
        source_ledger = _file(db, user, name="2026年盈亏核算表.xlsx")
        source_flow = _file(db, user, name="2026年到账流转表.xlsx")
        baseline = create_or_replace_current_set(
            db,
            user,
            "ar-hexiao-daily",
            {
                "profit_loss_ledgers": [_entry(source_ledger)],
                "receipt_flow_table": [_entry(source_flow)],
            },
        )
        completed = _workflow(user, baseline.id)
        db.add(completed)
        db.flush()
        output_dir = workflow_service.workflow_root(user.user_id, completed.id) / "outputs" / "done"
        output_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = output_dir / "2026年盈亏核算表_已写入.xlsx"
        flow_path = output_dir / "2026年到账流转表_已写入.xlsx"
        ledger_path.write_bytes(b"ledger-v2")
        flow_path.write_bytes(b"flow-v2")
        written_ledger = _file(
            db,
            user,
            name=ledger_path.name,
            kind="output",
            workflow_id=completed.id,
        )
        written_flow = _file(
            db,
            user,
            name=flow_path.name,
            kind="output",
            workflow_id=completed.id,
        )
        for record, path in ((written_ledger, ledger_path), (written_flow, flow_path)):
            record.stored_path = str(path.resolve())
            record.size_bytes = path.stat().st_size
            record.sha256 = sha256_file(path)
        db.flush()
        published = publish_workflow_material_set(
            db,
            completed,
            {
                "profit_loss_ledgers": [_entry(written_ledger)],
                "receipt_flow_table": [_entry(written_flow)],
            },
        )

        next_workflow = _workflow(user, published.id)
        db.add(next_workflow)
        db.flush()
        stale_bindings = material_set_bindings(db, baseline)
        action = SimpleNamespace(
            name="prepare_workspace",
            input_json=json.dumps({"files": stale_bindings}, ensure_ascii=False),
        )
        business = (
            workflow_service.workflow_root(user.user_id, next_workflow.id)
            / "actions"
            / "copy-current"
            / "工作区"
        )
        copied = workflow_service._copy_inputs(db, action, next_workflow, business)

        assert copied["profit_loss_ledgers"][0].read_bytes() == b"ledger-v2"
        assert copied["receipt_flow_table"][0].read_bytes() == b"flow-v2"


def test_history_lists_current_first_and_restore_creates_a_new_version() -> None:
    init_db()
    user = _user()
    with SessionLocal() as db:
        ledger_v1 = _file(db, user, name="2026年盈亏核算表.xlsx")
        flow_v1 = _file(db, user, name="2026年到账流转表.xlsx")
        version_one = create_or_replace_current_set(
            db,
            user,
            "ar-hexiao-daily",
            {
                "profit_loss_ledgers": [_entry(ledger_v1)],
                "receipt_flow_table": [_entry(flow_v1)],
            },
        )
        ledger_v2 = _file(db, user, name="2026年盈亏核算表_修订.xlsx")
        flow_v2 = _file(db, user, name="2026年到账流转表_修订.xlsx")
        version_two = create_or_replace_current_set(
            db,
            user,
            "ar-hexiao-daily",
            {
                "profit_loss_ledgers": [_entry(ledger_v2)],
                "receipt_flow_table": [_entry(flow_v2)],
            },
            expected_current_id=version_one.id,
        )
        db.commit()

        history = list_material_sets(db, user, "ar-hexiao-daily")
        assert [item.version for item in history] == [2, 1]
        assert history[0].state == "current"
        assert history[1].state == "superseded"

        restored = restore_material_set(db, user, "ar-hexiao-daily", version_one.id)
        db.commit()

        assert restored.version == 3
        assert restored.parent_set_id == version_two.id
        restored_ledger = material_set_bindings(db, restored)["profit_loss_ledgers"][0]
        assert restored_ledger["file_id"] == ledger_v1.id
        assert version_one.state == "superseded"
        assert version_two.state == "superseded"


def test_restore_rejects_material_set_from_another_user() -> None:
    init_db()
    owner = _user("restore-owner")
    other = _user("restore-other")
    with SessionLocal() as db:
        ledger = _file(db, other, name="2026年盈亏核算表.xlsx")
        flow = _file(db, other, name="2026年到账流转表.xlsx")
        foreign = create_or_replace_current_set(
            db,
            other,
            "ar-hexiao-daily",
            {
                "profit_loss_ledgers": [_entry(ledger)],
                "receipt_flow_table": [_entry(flow)],
            },
        )
        db.commit()

        with pytest.raises(ValueError, match="不存在"):
            restore_material_set(db, owner, "ar-hexiao-daily", foreign.id)


def test_file_in_material_version_cannot_be_deleted() -> None:
    init_db()
    user = _user()
    with SessionLocal() as db:
        ledger = _file(db, user, name="2026年盈亏核算表.xlsx")
        flow = _file(db, user, name="2026年到账流转表.xlsx")
        create_or_replace_current_set(
            db,
            user,
            "ar-hexiao-daily",
            {
                "profit_loss_ledgers": [_entry(ledger)],
                "receipt_flow_table": [_entry(flow)],
            },
        )
        db.commit()

        can_delete, reason = file_delete_status(db, ledger)
        assert can_delete is False
        assert "业务材料版本" in reason
