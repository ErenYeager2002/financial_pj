from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.database import SessionLocal, init_db
from app.models import FetchedBundle, WorkflowAction, WorkflowSession
from app.workflow_service import confirm_fetched_data_review, execute_workflow_action


def _workflow() -> WorkflowSession:
    return WorkflowSession(
        id=str(uuid.uuid4()),
        owner_id=f"pipeline-owner-{uuid.uuid4().hex[:8]}",
        owner_name="动作拆分测试员工",
        department_id="finance",
        skill_id="ar-hexiao-daily",
        skill_name="应收核销日清",
        skill_version="1.6.12",
        skill_hash="a" * 64,
        model_connection_id="background",
        model_provider="platform",
        model_name="deterministic",
        reconciliation_date="2026-08-20",
        state="running",
        stage="preparing",
        context_json=json.dumps({"started_from_form": True}),
    )


def test_fetch_pipeline_runs_one_named_action_per_phase(monkeypatch) -> None:
    from app import workflow_service

    init_db()
    calls: list[str] = []

    def prepare(_db, _action, _workflow):
        calls.append("prepare_workspace")
        return {"workspace": "D:/controlled/workspace", "artifacts": []}

    def fetch(_db, _action, _workflow):
        calls.append("fetch_data")
        return {
            "workspace": "D:/controlled/workspace",
            "fetched_data": {
                "available": True,
                "dates": ["2026-08-20"],
                "review_status": "waiting",
            },
            "artifacts": [],
        }

    def preview(_db, _action, _workflow):
        calls.append("build_fetch_preview")
        return {"preview_dates": ["2026-08-20"], "artifacts": []}

    monkeypatch.setattr(workflow_service, "_prepare_workspace_action", prepare)
    monkeypatch.setattr(workflow_service, "_fetch_data_action", fetch)
    monkeypatch.setattr(workflow_service, "_build_fetch_preview_action", preview)
    monkeypatch.setattr(workflow_service, "assert_workflow_execution_enabled", lambda _item: None)
    monkeypatch.setattr(workflow_service, "acquire_claim_lock", lambda *_args: None)
    monkeypatch.setattr(workflow_service, "sync_reminder_from_workflow", lambda *_args: None)
    monkeypatch.setattr(workflow_service, "_cleanup_terminal_fetched_snapshot", lambda *_args: None)

    with SessionLocal() as db:
        workflow = _workflow()
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
        workflow = _workflow()
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
        workflow = _workflow()
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
        workflow = _workflow()
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


def test_fetch_action_publishes_the_workspace_export_as_a_bundle(
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
    for _, _, prefix in workflow_service.FETCHED_DATASET_SPECS:
        (export_dir / f"{prefix}_{tag}.xlsx").write_bytes(prefix.encode())
    (export_dir / f"取数摘要_{tag}.json").write_text(
        json.dumps(
            {
                "day": reconciliation_date,
                "export_schema_version": workflow_service.FETCH_SNAPSHOT_VERSION,
                "read_only": True,
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
    with SessionLocal() as db:
        workflow = _workflow()
        action = WorkflowAction(
            id=str(uuid.uuid4()),
            workflow_id=workflow.id,
            name="fetch_data",
            state="running",
            input_json=json.dumps({"context": {"workspace": str(workspace)}}),
        )
        db.add_all([workflow, action])
        db.flush()

        result = workflow_service._fetch_data_action(db, action, workflow)

        bundle = db.get(FetchedBundle, result["fetched_bundle_id"])
        assert bundle is not None
        assert bundle.source_type == "live"
        assert bundle.state == "ready_for_review"
        assert len(bundle.files) == 5
        assert workflow.fetched_bundle_id == bundle.id
        assert result["fetched_data"]["bundle_id"] == bundle.id


def test_action_failure_recovers_failed_transaction_before_recording_error(monkeypatch) -> None:
    from app import workflow_service

    init_db()
    monkeypatch.setattr(workflow_service, "assert_workflow_execution_enabled", lambda _item: None)
    monkeypatch.setattr(workflow_service, "sync_reminder_from_workflow", lambda *_args: None)
    monkeypatch.setattr(workflow_service, "_cleanup_terminal_fetched_snapshot", lambda *_args: None)

    with SessionLocal() as db:
        workflow = _workflow()
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
        workflow = _workflow()
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
    assert result["fetched_data"]["source"] == "snapshot"
    assert result["fetched_data"]["source_bundle_id"] == "source-bundle"
    assert result["fetched_data"]["summary"] == {"回款记录笔数": 3}
