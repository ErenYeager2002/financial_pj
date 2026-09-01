from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import workflow_execution_policy, workflow_service
from app.database import SessionLocal, init_db
from app.models import FetchedBundle, WorkflowFetchedDataPreview, WorkflowSession


def _snapshot_source(tmp_path: Path, reconciliation_date: str) -> tuple[SimpleNamespace, Path]:
    workspace = tmp_path / "source-workspace"
    export_dir = workspace / workflow_service.FETCH_SNAPSHOT_DIR
    export_dir.mkdir(parents=True)
    files = {
        f"{prefix}_{reconciliation_date.replace('-', '')}.xlsx": f"{key}-data".encode()
        for key, _, prefix in workflow_service.FETCHED_DATASET_SPECS
    }
    for name, content in files.items():
        (export_dir / name).write_bytes(content)
    hashes = {name: workflow_service.sha256_file(export_dir / name) for name in files}
    summary = {
        "day": reconciliation_date,
        "export_schema_version": workflow_service.FETCH_SNAPSHOT_VERSION,
        "read_only": True,
        "files": list(files),
        "file_sha256": hashes,
        "回款记录笔数": 1,
    }
    (export_dir / f"取数摘要_{reconciliation_date.replace('-', '')}.json").write_text(
        json.dumps(summary, ensure_ascii=False), encoding="utf-8"
    )
    source = SimpleNamespace(
        id="source-workflow",
        owner_id="owner-1",
        skill_id="ar-hexiao-daily",
        context_json=json.dumps(
            {
                "workspace": str(workspace),
                "fetched_data": {"available": True, "dates": [reconciliation_date]},
            }
        ),
    )
    return source, workspace


def test_snapshot_replay_requires_v5_manifest_and_matching_hashes(
    monkeypatch, tmp_path: Path
) -> None:
    reconciliation_date = "2026-08-26"
    source, workspace = _snapshot_source(tmp_path, reconciliation_date)
    monkeypatch.setattr(workflow_service, "_workflow_storage_root", lambda *_args: workspace.parent)

    validated = workflow_service._validated_snapshot_for_date(
        SimpleNamespace(), source, reconciliation_date
    )
    assert validated is not None
    assert len(validated["paths"]) == len(workflow_service.FETCHED_DATASET_SPECS)
    assert "file_sha256" not in validated["summary"]

    first_file = validated["paths"][0]
    first_file.write_bytes(b"tampered")
    assert (
        workflow_service._validated_snapshot_for_date(
            SimpleNamespace(), source, reconciliation_date
        )
        is None
    )


def test_snapshot_replay_cannot_queue_live_supplement() -> None:
    workflow = SimpleNamespace(
        stage="awaiting_fetched_data_confirmation",
        context_json=json.dumps(
            {"fetched_data": {"available": True, "source": "snapshot"}}
        ),
    )

    with pytest.raises(HTTPException) as error:
        workflow_service.request_fetched_data_supplement(
            SimpleNamespace(), workflow, ["AR26070140"], []
        )

    assert error.value.status_code == 409
    assert error.value.detail == "本地取数快照不能补取智云数据。"


def test_snapshot_policy_requires_an_opaque_source_id(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow_execution_policy,
        "settings",
        SimpleNamespace(
            ar_hexiao_execution_enabled=False,
            ar_hexiao_snapshot_replay_enabled=True,
        ),
    )
    workflow = SimpleNamespace(
        skill_id="ar-hexiao-daily",
        context_json=json.dumps({"fetched_data_source": "snapshot"}),
    )

    with pytest.raises(HTTPException) as error:
        workflow_execution_policy.assert_workflow_execution_enabled(workflow)

    assert error.value.status_code == 409


def test_fetch_history_distinguishes_replayable_bundle_from_purged_preview(
    monkeypatch,
) -> None:
    date_value = "2026-08-26"
    monkeypatch.setattr(workflow_service, "assert_skill_permission", lambda *_args: None)
    init_db()
    marker = datetime.now(UTC).strftime("%H%M%S%f")
    owner_id = f"history-owner-{marker}"
    with SessionLocal() as db:
        for index, state in enumerate(("consumed", "raw_purged"), start=1):
            workflow = WorkflowSession(
                id=f"history-workflow-{marker}-{index}",
                display_id=f"AR-HISTORY-{marker}-{index}",
                owner_id=owner_id,
                owner_name="取数历史测试",
                department_id="finance",
                skill_id="ar-hexiao-daily",
                skill_name="应收核销日清",
                skill_version="1.6.12",
                skill_hash="a" * 64,
                model_connection_id="background",
                model_provider="platform",
                model_name="deterministic",
                reconciliation_date=date_value,
            )
            db.add(workflow)
            db.flush()
            bundle = FetchedBundle(
                id=f"history-bundle-{marker}-{index}",
                owner_id=owner_id,
                department_id="finance",
                skill_id="ar-hexiao-daily",
                source_workflow_id=workflow.id,
                source_type="live",
                manifest_version="synthetic-v1",
                state=state,
                date_from=date_value,
                date_to=date_value,
                dates_json=json.dumps([date_value]),
                storage_key=f"{owner_id}/history-bundle-{marker}-{index}",
                raw_available=state == "consumed",
                preview_available=True,
                replayable=state == "consumed",
                created_at=datetime.now(UTC),
            )
            db.add(bundle)
            db.flush()
            db.add(
                WorkflowFetchedDataPreview(
                    id=f"history-preview-{marker}-{index}",
                    bundle_id=bundle.id,
                    workflow_id=workflow.id,
                    reconciliation_date=date_value,
                    revision=f"revision-{index}",
                    summary_json=json.dumps(
                        {"回款记录笔数": index, "file_sha256": {"secret": "hidden"}}
                    ),
                )
            )
        db.commit()

        options = workflow_service.list_fetched_snapshot_options(
            db,
            "ar-hexiao-daily",
            SimpleNamespace(user_id=owner_id),
        )

    assert {item.availability for item in options} == {
        "replayable_bundle",
        "historical_preview",
    }
    purged = next(item for item in options if item.availability == "historical_preview")
    assert purged.raw_available is False
    assert purged.replayable is False
    assert purged.summary_by_date[date_value] == {"回款记录笔数": 2}
