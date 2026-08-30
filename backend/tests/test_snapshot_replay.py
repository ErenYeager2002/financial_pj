from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from app import workflow_execution_policy, workflow_service
from fastapi import HTTPException


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


def test_snapshot_options_deduplicate_shared_workspace_validation(monkeypatch) -> None:
    date_value = "2026-08-26"
    workflows = [
        SimpleNamespace(
            id=f"source-{index}",
            owner_id="owner-1",
            skill_id="ar-hexiao-daily",
            skill_version="1.6.11",
            display_id=f"AR-{index}",
            reconciliation_date=date_value,
            batch_id="batch-1",
            updated_at=None,
            created_at=datetime.now(UTC),
            context_json=json.dumps(
                {
                    "workspace": "D:/controlled/shared-workspace",
                    "fetched_data": {"available": True, "dates": [date_value]},
                }
            ),
        )
        for index in range(2)
    ]

    class FakeResult:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class FakeDb:
        def __init__(self):
            self.calls = 0

        def scalars(self, _query):
            self.calls += 1
            return FakeResult(workflows if self.calls == 1 else [])

    calls = []
    monkeypatch.setattr(workflow_service, "assert_skill_permission", lambda *_args: None)
    monkeypatch.setattr(
        workflow_service,
        "_workflow_storage_root",
        lambda *_args: Path("D:/controlled"),
    )
    monkeypatch.setattr(
        workflow_service,
        "_snapshot_context_workspace",
        lambda *_args, **_kwargs: (
            {},
            {"available": True},
            Path("D:/controlled/shared-workspace"),
            Path("D:/controlled/shared-workspace/01_智云导出"),
        ),
    )
    monkeypatch.setattr(
        workflow_service,
        "_validated_snapshot_for_date",
        lambda _db, _source, item, **_kwargs: calls.append(item)
        or {"summary": {"回款记录笔数": 1}},
    )

    options = workflow_service.list_fetched_snapshot_options(
        FakeDb(),
        "ar-hexiao-daily",
        SimpleNamespace(user_id="owner-1"),
    )

    assert len(options) == 1
    assert calls == [date_value]


def test_snapshot_options_skip_workflows_without_available_snapshot(monkeypatch) -> None:
    date_value = "2026-08-26"
    workflows = [
        SimpleNamespace(
            id="workflow-without-snapshot",
            owner_id="owner-1",
            skill_id="ar-hexiao-daily",
            skill_version="1.6.11",
            display_id="AR-empty",
            reconciliation_date=date_value,
            batch_id=None,
            updated_at=None,
            created_at=datetime.now(UTC),
            context_json=json.dumps({}),
        ),
        SimpleNamespace(
            id="workflow-with-snapshot",
            owner_id="owner-1",
            skill_id="ar-hexiao-daily",
            skill_version="1.6.11",
            display_id="AR-snapshot",
            reconciliation_date=date_value,
            batch_id=None,
            updated_at=None,
            created_at=datetime.now(UTC),
            context_json=json.dumps(
                {
                    "workspace": "D:/controlled/snapshot-workspace",
                    "fetched_data": {"available": True, "dates": [date_value]},
                }
            ),
        ),
    ]

    class FakeResult:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class FakeDb:
        def __init__(self):
            self.calls = 0

        def scalars(self, _query):
            self.calls += 1
            return FakeResult(workflows if self.calls == 1 else [])

    calls = []
    monkeypatch.setattr(workflow_service, "assert_skill_permission", lambda *_args: None)
    monkeypatch.setattr(
        workflow_service,
        "_workflow_storage_root",
        lambda *_args: Path("D:/controlled"),
    )
    monkeypatch.setattr(
        workflow_service,
        "_snapshot_context_workspace",
        lambda *_args, **_kwargs: (
            {},
            {"available": True},
            Path("D:/controlled/snapshot-workspace"),
            Path("D:/controlled/snapshot-workspace/01_智云导出"),
        ),
    )
    monkeypatch.setattr(
        workflow_service,
        "_validated_snapshot_for_date",
        lambda _db, source, item, **_kwargs: calls.append(source.id)
        or {"summary": {"回款记录笔数": 1}},
    )

    options = workflow_service.list_fetched_snapshot_options(
        FakeDb(),
        "ar-hexiao-daily",
        SimpleNamespace(user_id="owner-1"),
    )

    assert [item.source_workflow_id for item in options] == ["workflow-with-snapshot"]
    assert calls == ["workflow-with-snapshot"]


def test_snapshot_options_reuse_persisted_preview_for_shared_workspace(monkeypatch) -> None:
    date_value = "2026-08-26"
    workflows = [
        SimpleNamespace(
            id="source-first",
            owner_id="owner-1",
            skill_id="ar-hexiao-daily",
            skill_version="1.6.11",
            display_id="AR-first",
            reconciliation_date=date_value,
            batch_id="batch-1",
            updated_at=None,
            created_at=datetime.now(UTC),
            context_json=json.dumps(
                {
                    "workspace": "D:/controlled/shared-workspace",
                    "fetched_data": {"available": True, "dates": [date_value]},
                }
            ),
        ),
        SimpleNamespace(
            id="source-with-preview",
            owner_id="owner-1",
            skill_id="ar-hexiao-daily",
            skill_version="1.6.11",
            display_id="AR-preview",
            reconciliation_date=date_value,
            batch_id="batch-1",
            updated_at=None,
            created_at=datetime.now(UTC),
            context_json=json.dumps(
                {
                    "workspace": "D:/controlled/shared-workspace",
                    "fetched_data": {"available": True, "dates": [date_value]},
                }
            ),
        ),
    ]
    previews = [
        SimpleNamespace(
            workflow_id="source-with-preview",
            reconciliation_date=date_value,
            summary_json=json.dumps({"回款记录笔数": 7}),
        )
    ]

    class FakeResult:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class FakeDb:
        def __init__(self):
            self.calls = 0

        def scalars(self, _query):
            self.calls += 1
            return FakeResult(workflows if self.calls == 1 else previews)

    monkeypatch.setattr(workflow_service, "assert_skill_permission", lambda *_args: None)
    monkeypatch.setattr(
        workflow_service,
        "_workflow_storage_root",
        lambda *_args: Path("D:/controlled"),
    )
    monkeypatch.setattr(
        workflow_service,
        "_snapshot_context_workspace",
        lambda *_args, **_kwargs: (
            {},
            {"available": True},
            Path("D:/controlled/shared-workspace"),
            Path("D:/controlled/shared-workspace/01_智云导出"),
        ),
    )
    monkeypatch.setattr(
        workflow_service,
        "_validated_snapshot_for_date",
        lambda *_args, **_kwargs: pytest.fail("persisted preview should avoid file probing"),
    )

    options = workflow_service.list_fetched_snapshot_options(
        FakeDb(),
        "ar-hexiao-daily",
        SimpleNamespace(user_id="owner-1"),
    )

    assert len(options) == 1
    assert options[0].source_workflow_id == "source-first"
    assert options[0].dates == [date_value]
    assert options[0].summary_by_date[date_value] == {"回款记录笔数": 7}
