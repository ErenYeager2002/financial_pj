from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.database import SessionLocal, init_db
from app.auth_models import User, UserSkillPermission
from app.models import FetchedBundle, WorkflowAction, WorkflowSession
from app.resource_policy import workflow_root
from app.workflow_service import confirm_fetched_data_review, execute_workflow_action


def _workflow(db) -> WorkflowSession:
    owner_id = f"pipeline-owner-{uuid.uuid4().hex[:8]}"
    db.add(User(id=owner_id, username=owner_id, password_hash="not-used", department_id="finance"))
    db.flush()
    db.add(UserSkillPermission(id=str(uuid.uuid4()), user_id=owner_id, skill_id="ar-hexiao-daily", can_run=True))
    workflow = WorkflowSession(
        id=str(uuid.uuid4()),
        owner_id=owner_id,
        owner_name="动作拆分测试员工",
        department_id="finance",
        skill_id="ar-hexiao-daily",
        skill_name="应收核销日清",
        skill_version="1.6.12",
        skill_hash="a" * 64,
        execution_mode="workflow",
        model_connection_id="background",
        model_provider="platform",
        model_name="deterministic",
        reconciliation_date="2026-08-20",
        state="running",
        stage="preparing",
        context_json=json.dumps({"started_from_form": True}),
    )
    # These exercise the legacy fetch contract, with a task-owned old snapshot.
    (workflow_root(owner_id, workflow.id) / "skill").mkdir(parents=True)
    return workflow


def test_terminal_snapshot_cleanup_failure_preserves_completed_result(monkeypatch):
    from app import workflow_service

    init_db()
    def unavailable(*_args):
        raise PermissionError("private-path-must-not-be-disclosed")

    monkeypatch.setattr(workflow_service, "_discard_workspace_fetched_snapshot", unavailable)
    with SessionLocal() as db:
        workflow = _workflow(db)
        workspace = workflow_root(workflow.owner_id, workflow.id) / "workspace"
        workspace.mkdir()
        workflow.state, workflow.stage = "succeeded", "completed"
        workflow.context_json = json.dumps({"workspace": str(workspace), "fetched_data": {"available": True}})
        db.add(workflow)
        db.flush()
        action = WorkflowAction(id=str(uuid.uuid4()), workflow_id=workflow.id,
                                name="complete_reconciliation", state="succeeded")
        db.add(action)
        workflow_service._cleanup_terminal_fetched_snapshot(db, workflow)
        db.commit()
        db.refresh(workflow)
        db.refresh(action)
        assert workflow.state == action.state == "succeeded"
        context = json.loads(workflow.context_json)
        assert context["fetched_snapshot_cleanup"]["state"] == "failed"
        assert context["fetched_data"]["available"] is False
        assert "private-path" not in workflow.context_json


def test_fetch_pipeline_runs_one_named_action_per_phase(monkeypatch) -> None:
    from app import workflow_service

    init_db()
    calls: list[str] = []
    build_preview = workflow_service._build_fetch_preview_action

    def prepare(_db, _action, _workflow):
        calls.append("prepare_workspace")
        return {"workspace": "D:/controlled/workspace", "artifacts": []}

    def fetch(_db, _action, _workflow):
        calls.append("fetch_data")
        return {
            "workspace": "D:/controlled/workspace",
            "fetched_data": {
                "available": True,
                "bundle_id": "published-test-bundle",
                "dates": ["2026-08-20"],
                "review_status": "waiting",
            },
            "artifacts": [],
        }

    def preview(_db, _action, _workflow):
        calls.append("build_fetch_preview")
        # Exercise the real preview input guard at the chained action boundary.
        return build_preview(_db, _action, _workflow)

    def assert_mirror(_db, *, bundle_id, owner_id, dates, mirror):
        assert bundle_id == "published-test-bundle"
        assert dates == ["2026-08-20"]
        return SimpleNamespace(preview_available=False)

    monkeypatch.setattr(workflow_service, "_prepare_workspace_action", prepare)
    monkeypatch.setattr(workflow_service, "_fetch_data_action", fetch)
    monkeypatch.setattr(workflow_service, "_build_fetch_preview_action", preview)
    monkeypatch.setattr(workflow_service, "assert_bundle_preview_mirror", assert_mirror)
    monkeypatch.setattr(workflow_service, "_prime_fetched_data_previews", lambda *_args: None)
    monkeypatch.setattr(workflow_service, "assert_workflow_execution_enabled", lambda _item: None)
    monkeypatch.setattr(workflow_service, "acquire_claim_lock", lambda *_args: None)
    monkeypatch.setattr(workflow_service, "sync_reminder_from_workflow", lambda *_args: None)
    monkeypatch.setattr(workflow_service, "_cleanup_terminal_fetched_snapshot", lambda *_args: None)

    with SessionLocal() as db:
        workflow = _workflow(db)
        action = WorkflowAction(
            id=str(uuid.uuid4()),
            workflow_id=workflow.id,
            name="prepare_workspace",
            state="running",
            input_json=json.dumps({"context": {"started_from_form": True}}),
        )
        db.add_all([workflow, action])
        db.flush()

        execute_workflow_action(db, action)

        assert calls == ["prepare_workspace"]
        assert action.state == "succeeded"
        assert workflow.stage == "fetching_data"
        fetch_action = db.scalar(
            select(WorkflowAction).where(
                WorkflowAction.workflow_id == workflow.id,
                WorkflowAction.name == "fetch_data",
            )
        )
        assert fetch_action is not None
        fetch_action.state = "running"
        execute_workflow_action(db, fetch_action)

        preview_action = db.scalar(
            select(WorkflowAction).where(
                WorkflowAction.workflow_id == workflow.id,
                WorkflowAction.name == "build_fetch_preview",
            )
        )
        assert preview_action is not None
        preview_action.state = "running"
        execute_workflow_action(db, preview_action)

        assert calls == ["prepare_workspace", "fetch_data", "build_fetch_preview"]
        assert workflow.stage == "awaiting_fetched_data_confirmation"
        assert workflow.state == "waiting_confirmation"


@pytest.mark.parametrize(
    ("reason", "expected_code", "expected_reason"),
    [
        ("取数包尚未发布，不能建立预览。", "WORKFLOW_FETCH_PREVIEW_CONTEXT_MISSING",
         "预览动作未收到已发布取数包信息，请修复步骤交接后重新建立预览。"),
        ("取数预览文件与已发布取数包哈希不一致。", "WORKFLOW_FETCH_PREVIEW_INTEGRITY_FAILED",
         "预览文件与已发布取数包的校验值不一致，已停止处理。"),
        ("private-path secret-token", "WORKFLOW_FETCH_PREVIEW_FAILED",
         "预览构建发生内部错误，请联系管理员检查此步骤。"),
    ],
)
def test_fetch_preview_error_explains_prewrite_failure(reason, expected_code, expected_reason):
    from app import workflow_service

    workflow = SimpleNamespace(
        context_json=json.dumps({"current_step": "review_fetched_data",
                                 "current_step_label": "取数完成，正在建立检查预览"}),
        stage="building_fetch_preview", reconciliation_date="2026-09-03",
        owner_name="测试员工", owner_id="owner", skill_id="ar-hexiao-daily",
        skill_name="应收核销日清", material_set=None,
    )
    detail = workflow_service._workflow_error_detail(workflow, RuntimeError(reason))
    public = workflow_service._workflow_public_error(workflow, detail)
    assert public["error_code"] == expected_code
    assert public["reason"] == expected_reason
    assert public["write_status"] == "not_started"
    assert "尚未进入核销写入" in public["message"]
    assert "写入未完成" not in public["message"]
    assert "private-path" not in public["message"]
    assert "secret-token" not in public["message"]


def test_prepare_workspace_reuses_reviewable_bundle_by_rebuilding_preview(monkeypatch) -> None:
    from app import workflow_service

    init_db()
    monkeypatch.setattr(
        workflow_service,
        "_prepare_workspace_action",
        lambda _db, _action, _workflow: {
            "workspace": "D:/controlled/new-attempt",
            "artifacts": [],
        },
    )
    monkeypatch.setattr(workflow_service, "assert_workflow_execution_enabled", lambda _item: None)
    monkeypatch.setattr(workflow_service, "acquire_claim_lock", lambda *_args: None)
    monkeypatch.setattr(workflow_service, "sync_reminder_from_workflow", lambda *_args: None)
    monkeypatch.setattr(workflow_service, "_cleanup_terminal_fetched_snapshot", lambda *_args: None)

    with SessionLocal() as db:
        workflow = _workflow(db)
        workflow.fetched_bundle_id = "reviewable-bundle"
        workflow.context_json = json.dumps(
            {
                "started_from_form": True,
                "fetched_data": {
                    "available": True,
                    "bundle_id": "reviewable-bundle",
                    "dates": ["2026-08-20", "2026-08-22"],
                    "review_status": "waiting",
                },
            }
        )
        action = WorkflowAction(
            id=str(uuid.uuid4()),
            workflow_id=workflow.id,
            name="prepare_workspace",
            state="running",
            input_json=workflow.context_json,
        )
        db.add_all([workflow, action])
        db.flush()

        execute_workflow_action(db, action)

        queued = [item for item in workflow.actions if item.state == "queued"]
        assert [item.name for item in queued] == ["build_fetch_preview"]


def test_fetched_data_confirmation_is_idempotent_for_plan_action() -> None:
    init_db()
    with SessionLocal() as db:
        workflow = _workflow(db)
        workflow.stage = "awaiting_fetched_data_confirmation"
        workflow.state = "waiting_confirmation"
        workflow.context_json = json.dumps(
            {
                "workspace": "D:/controlled/workspace",
                "fetched_data": {
                    "available": True,
                    "dates": ["2026-08-20"],
                    "review_status": "waiting",
                },
            }
        )
        db.add(workflow)
        db.commit()

        actor = SimpleNamespace(user_id=workflow.owner_id)
        confirm_fetched_data_review(db, workflow, actor)
        confirm_fetched_data_review(db, workflow, actor)

        actions = [item for item in workflow.actions if item.name == "build_reconciliation_plan"]
        assert len(actions) == 1
        assert actions[0].state == "queued"


def test_named_fetch_pipeline_cannot_confirm_without_a_bundle() -> None:
    init_db()
    with SessionLocal() as db:
        workflow = _workflow(db)
        workflow.stage = "awaiting_fetched_data_confirmation"
        workflow.state = "waiting_confirmation"
        workflow.context_json = json.dumps(
            {
                "fetched_data": {
                    "available": True,
                    "dates": ["2026-08-20"],
                    "review_status": "waiting",
                }
            }
        )
        db.add(workflow)
        db.flush()
        db.add(
            WorkflowAction(
                id=str(uuid.uuid4()),
                workflow_id=workflow.id,
                name="build_fetch_preview",
                state="succeeded",
                input_json="{}",
            )
        )
        db.commit()

        with pytest.raises(HTTPException, match="取数包标识缺失"):
            confirm_fetched_data_review(
                db,
                workflow,
                SimpleNamespace(user_id=workflow.owner_id),
            )


def test_fetch_action_accepts_current_skill_export_schema_and_publishes_bundle(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service, workflow_service

    init_db()
    workspace = tmp_path / "workflow-space"
    export_dir = workspace / workflow_service.FETCH_SNAPSHOT_DIR
    export_dir.mkdir(parents=True)
    reconciliation_date = "2026-08-20"
    tag = reconciliation_date.replace("-", "")
    file_hashes: dict[str, str] = {}
    for _, _, prefix in workflow_service.FETCHED_DATASET_SPECS:
        name = f"{prefix}_{tag}.xlsx"
        content = prefix.encode()
        (export_dir / name).write_bytes(content)
        file_hashes[name] = hashlib.sha256(content).hexdigest()
    (export_dir / f"取数摘要_{tag}.json").write_text(
        json.dumps(
            {
                "day": reconciliation_date,
                "export_schema_version": workflow_service.FETCH_SNAPSHOT_VERSION,
                "read_only": True,
                "file_sha256": file_hashes,
            }
        ),
        encoding="utf-8",
    )

    def fetched(_db, _action, _workflow):
        return {
            "workspace": str(workspace),
            "fetched_data": {
                "available": True,
                "dates": [reconciliation_date],
                "review_status": "waiting",
            },
            "awaiting_fetched_data_confirmation": True,
            "artifacts": [],
        }

    monkeypatch.setattr(workflow_service, "_execute_named_workflow_phase", fetched)
    monkeypatch.setattr(
        fetched_bundle_service,
        "settings",
        SimpleNamespace(data_dir=tmp_path, fetch_bundle_retention_days=7),
    )
    monkeypatch.setattr(workflow_service, "assert_workflow_execution_enabled", lambda _item: None)
    monkeypatch.setattr(workflow_service, "acquire_claim_lock", lambda *_args: None)
    monkeypatch.setattr(workflow_service, "sync_reminder_from_workflow", lambda *_args: None)
    monkeypatch.setattr(workflow_service, "_cleanup_terminal_fetched_snapshot", lambda *_args: None)
    with SessionLocal() as db:
        workflow = _workflow(db)
        action = WorkflowAction(
            id=str(uuid.uuid4()),
            workflow_id=workflow.id,
            name="fetch_data",
            state="running",
            input_json=json.dumps({"context": {"workspace": str(workspace)}}),
        )
        db.add_all([workflow, action])
        db.flush()

        execute_workflow_action(db, action)

        result = json.loads(action.result_json)
        assert action.state == "succeeded", action.error_message
        bundle = db.get(FetchedBundle, result["fetched_bundle_id"])
        assert bundle is not None
        assert bundle.source_type == "live"
        assert bundle.state == "ready_for_review"
        assert len(bundle.files) == 5
        assert action.state == "succeeded"
        assert workflow.stage == "building_fetch_preview"
        assert workflow.fetched_bundle_id == bundle.id
        assert result["fetched_data"]["bundle_id"] == bundle.id


def test_action_failure_recovers_failed_transaction_before_recording_error(monkeypatch) -> None:
    from app import workflow_service

    init_db()
    monkeypatch.setattr(workflow_service, "assert_workflow_execution_enabled", lambda _item: None)
    monkeypatch.setattr(workflow_service, "sync_reminder_from_workflow", lambda *_args: None)
    monkeypatch.setattr(workflow_service, "_cleanup_terminal_fetched_snapshot", lambda *_args: None)

    with SessionLocal() as db:
        workflow = _workflow(db)
        action = WorkflowAction(
            id=str(uuid.uuid4()),
            workflow_id=workflow.id,
            name="fetch_data",
            state="running",
            input_json="{}",
        )
        db.add_all([workflow, action])
        db.commit()

        def fail_with_invalid_flush(_db, _action, _workflow):
            _db.execute(
                text(
                    "INSERT INTO workflow_actions "
                    "SELECT * FROM workflow_actions WHERE id = :action_id"
                ),
                {"action_id": action.id},
            )

        monkeypatch.setattr(workflow_service, "_fetch_data_action", fail_with_invalid_flush)

        execute_workflow_action(db, action)
        db.commit()
        db.refresh(action)
        db.refresh(workflow)

        assert action.state == "failed"
        assert workflow.state == "failed"
        assert workflow.stage == "failed"


def test_fetch_action_replays_bundle_without_live_fetch(monkeypatch, tmp_path: Path) -> None:
    from app import workflow_service

    init_db()
    workspace = tmp_path / "replay-workspace"
    workspace.mkdir()
    reconciliation_date = "2026-08-20"
    staged: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(workflow_service, "_workflow_storage_root", lambda *_args: tmp_path)
    monkeypatch.setattr(
        workflow_service,
        "_execute_named_workflow_phase",
        lambda *_args: (_ for _ in ()).throw(AssertionError("live fetch must not run")),
    )

    def materialize(_db, *, workflow, source, dates):
        assert source.bundle_id == "source-bundle"
        assert source.owner_id == workflow.owner_id
        assert dates == [reconciliation_date]
        return SimpleNamespace(bundle_id="replayed-bundle")

    def stage(_db, *, bundle_id, owner_id, dates, target):
        staged.append((bundle_id, dates))
        target.mkdir()
        tag = reconciliation_date.replace("-", "")
        (target / f"取数摘要_{tag}.json").write_text(
            json.dumps({"回款记录笔数": 3}, ensure_ascii=False), encoding="utf-8"
        )
        return target

    monkeypatch.setattr(workflow_service, "materialize_bundle", materialize)
    monkeypatch.setattr(workflow_service, "stage_bundle_preview_files", stage)

    with SessionLocal() as db:
        workflow = _workflow(db)
        action = WorkflowAction(
            id=str(uuid.uuid4()),
            workflow_id=workflow.id,
            name="fetch_data",
            state="running",
            input_json=json.dumps(
                {
                    "context": {
                        "workspace": str(workspace),
                        "replay_source_bundle_id": "source-bundle",
                        "ledger_years": {"2026": "ledger.xlsx"},
                        "flow_file": "flow.xlsx",
                    }
                }
            ),
        )
        db.add_all([workflow, action])
        db.flush()

        result = workflow_service._fetch_data_action(db, action, workflow)

    assert staged == [("replayed-bundle", [reconciliation_date])]
    assert result["fetched_bundle_id"] == "replayed-bundle"
    assert result["fetched_data"]["source"] == "replay"
    assert result["fetched_data"]["source_bundle_id"] == "source-bundle"
    assert result["fetched_data"]["summary"] == {"回款记录笔数": 3}
