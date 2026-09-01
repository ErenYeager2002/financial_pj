from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, SessionLocal, init_db
from app.fetched_bundle_service import (
    FetchedBundleError,
    FetchedBundleReplayAdapter,
    FetchExportFile,
    FetchManifest,
    assert_bundle_consumable,
    assert_bundle_preview_mirror,
    assert_bundle_reviewable,
    confirm_bundle,
    finalize_bundle,
    materialize_bundle,
    purge_expired_bundles,
    purge_fetched_bundle,
    resolve_replay_bundle,
    stage_bundle_files,
    stage_bundle_preview_files,
    suspend_bundle_for_retry,
)
from app.models import FetchedBundle, WorkflowAction, WorkflowSession

DATASETS = ("payments", "orders", "writeoffs", "order_details", "summary")


def _workflow(owner_id: str, reconciliation_date: str = "2026-08-20") -> WorkflowSession:
    return WorkflowSession(
        id=str(uuid.uuid4()),
        owner_id=owner_id,
        owner_name="取数包测试员工",
        department_id="finance",
        skill_id="ar-hexiao-daily",
        skill_name="应收核销日清",
        skill_version="1.6.12",
        skill_hash="a" * 64,
        model_connection_id="background",
        model_provider="platform",
        model_name="deterministic",
        reconciliation_date=reconciliation_date,
    )


class SyntheticFetchSource:
    source_type = "live"

    def __init__(
        self,
        *,
        add_unknown_file: bool = False,
        content_marker: str = "",
        declare_missing_dataset: str = "",
        omit_dataset: str = "",
        unsafe_relative_name: str = "",
    ) -> None:
        self.add_unknown_file = add_unknown_file
        self.content_marker = content_marker
        self.declare_missing_dataset = declare_missing_dataset
        self.omit_dataset = omit_dataset
        self.unsafe_relative_name = unsafe_relative_name

    def export(self, dates: list[str], target: Path) -> FetchManifest:
        files: list[FetchExportFile] = []
        for reconciliation_date in dates:
            tag = reconciliation_date.replace("-", "")
            file_hashes: dict[str, str] = {}
            for dataset in DATASETS:
                if dataset == self.omit_dataset:
                    continue
                suffix = "json" if dataset == "summary" else "xlsx"
                name = f"{dataset}_{tag}.{suffix}"
                relative_name = (
                    self.unsafe_relative_name
                    if self.unsafe_relative_name and dataset == "payments"
                    else name
                )
                if dataset != self.declare_missing_dataset and not self.unsafe_relative_name:
                    if dataset == "summary":
                        content = json.dumps(
                            {
                                "day": reconciliation_date,
                                "export_schema_version": "synthetic-v1",
                                "read_only": True,
                                "file_sha256": file_hashes,
                            },
                            ensure_ascii=False,
                        ).encode()
                    else:
                        content = f"{dataset}:{reconciliation_date}:{self.content_marker}".encode()
                        file_hashes[name] = hashlib.sha256(content).hexdigest()
                    (target / name).write_bytes(content)
                files.append(
                    FetchExportFile(
                        dataset=dataset,
                        reconciliation_date=reconciliation_date,
                        relative_name=relative_name,
                    )
                )
        if self.add_unknown_file:
            (target / "unknown.txt").write_text("unexpected", encoding="utf-8")
        return FetchManifest(manifest_version="synthetic-v1", files=tuple(files))


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(data_dir=tmp_path, fetch_bundle_retention_days=7)


def test_materialize_bundle_atomically_publishes_validated_members(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-owner-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        db.flush()

        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        db.commit()

        bundle = db.get(FetchedBundle, result.bundle_id)
        assert bundle is not None
        assert bundle.state == "ready_for_review"
        assert bundle.raw_available is True
        assert bundle.replayable is True
        assert workflow.fetched_bundle_id == bundle.id
        assert [(item.reconciliation_date, item.dataset) for item in bundle.files] == [
            ("2026-08-20", dataset) for dataset in sorted(DATASETS)
        ]

        bundle_root = tmp_path / "fetched-bundles" / owner_id / bundle.id
        assert (bundle_root / "manifest.json").is_file()
        assert {path.name for path in bundle_root.iterdir()} == {
            "manifest.json",
            *{item.relative_name for item in bundle.files},
        }
        assert not list(bundle_root.parent.glob(".*.tmp"))


def test_materialized_bundle_survives_a_later_caller_rollback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-durable-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        db.flush()

        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        db.rollback()

        bundle = db.get(FetchedBundle, result.bundle_id)
        stored_workflow = db.get(WorkflowSession, workflow.id)
        assert bundle is not None and bundle.state == "ready_for_review"
        assert stored_workflow is not None
        assert stored_workflow.fetched_bundle_id == bundle.id
        assert (tmp_path / "fetched-bundles" / owner_id / bundle.id).is_dir()


def test_publication_failure_leaves_a_recoverable_database_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    monkeypatch.setattr(
        fetched_bundle_service.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("synthetic publish failure")),
    )
    init_db()
    owner_id = f"bundle-publish-failure-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        with pytest.raises(OSError, match="synthetic publish failure"):
            materialize_bundle(
                db,
                workflow=workflow,
                source=SyntheticFetchSource(),
                dates=["2026-08-20"],
            )

        bundle = db.scalar(
            select(FetchedBundle).where(FetchedBundle.source_workflow_id == workflow.id)
        )
        assert bundle is not None
        assert bundle.state == "invalid"
        assert bundle.raw_available is False
        assert bundle.replayable is False
        assert bundle.last_error == "取数包发布失败，原始文件不可用。"


def test_failed_export_temp_cleanup_is_retried_by_bundle_purge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    from app import fetched_bundle_service

    class InterruptedExportSource:
        source_type = "live"

        def export(self, _dates: list[str], target: Path) -> FetchManifest:
            (target / "partial-sensitive.xlsx").write_bytes(b"synthetic-sensitive-data")
            raise RuntimeError("synthetic interrupted export")

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    real_remove_tree = fetched_bundle_service._remove_tree

    def fail_temporary_cleanup(target: Path) -> None:
        if target.name.endswith(".tmp"):
            raise OSError("synthetic locked temporary directory")
        real_remove_tree(target)

    monkeypatch.setattr(fetched_bundle_service, "_remove_tree", fail_temporary_cleanup)
    init_db()
    owner_id = f"bundle-temp-failure-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        with pytest.raises(RuntimeError, match="synthetic interrupted export"):
            materialize_bundle(
                db,
                workflow=workflow,
                source=InterruptedExportSource(),
                dates=["2026-08-20"],
            )

        bundle = db.scalar(
            select(FetchedBundle).where(FetchedBundle.source_workflow_id == workflow.id)
        )
        assert bundle is not None
        assert bundle.state == "invalid"
        assert bundle.raw_available is True
        temporary_root = tmp_path / "fetched-bundles" / owner_id / f".{bundle.id}.tmp"
        assert temporary_root.is_dir()
        workflow.state = "failed"
        workflow.stage = "failed"
        db.commit()

        monkeypatch.setattr(fetched_bundle_service, "_remove_tree", real_remove_tree)
        assert (
            purge_expired_bundles(
                db,
                now=datetime.now(UTC) + timedelta(seconds=1),
            )
            == 1
        )
        db.refresh(bundle)
        assert bundle.state == "raw_purged"
        assert bundle.raw_available is False
        assert not temporary_root.exists()


def test_bundle_rejects_unknown_file_added_after_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-injected-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        bundle_root = tmp_path / "fetched-bundles" / owner_id / result.bundle_id
        bundle_root.chmod(0o700)
        (bundle_root / "injected.txt").write_text("unexpected", encoding="utf-8")

        with pytest.raises(FetchedBundleError, match="未知文件"):
            assert_bundle_reviewable(
                db,
                bundle_id=result.bundle_id,
                owner_id=owner_id,
                dates=["2026-08-20"],
            )


def test_bundle_rejects_invalid_export_summary_before_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    class InvalidSummarySource(SyntheticFetchSource):
        def export(self, dates: list[str], target: Path) -> FetchManifest:
            manifest = super().export(dates, target)
            summary_path = target / "summary_20260820.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["read_only"] = False
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            return manifest

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-summary-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        with pytest.raises(FetchedBundleError, match="只读标记"):
            materialize_bundle(
                db,
                workflow=workflow,
                source=InvalidSummarySource(),
                dates=["2026-08-20"],
            )
        assert not (tmp_path / "fetched-bundles" / owner_id).exists()


def test_failed_workflow_invalidates_and_purges_its_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service, workflow_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-failed-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        confirm_bundle(
            db,
            bundle_id=result.bundle_id,
            actor=SimpleNamespace(user_id=owner_id),
        )
        workflow.state = "failed"
        workflow.stage = "failed"
        db.commit()
        bundle_root = tmp_path / "fetched-bundles" / owner_id / result.bundle_id

        workflow_service._cleanup_terminal_fetched_snapshot(db, workflow)
        db.commit()

        bundle = db.get(FetchedBundle, result.bundle_id)
        assert bundle is not None
        assert bundle.state == "raw_purged"
        assert bundle.raw_available is False
        assert bundle.replayable is False
        assert not bundle_root.exists()


def test_retryable_preview_failure_preserves_reviewable_bundle_for_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service, workflow_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-preview-retry-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        workflow.state = "failed"
        workflow.stage = "failed"
        db.add(
            WorkflowAction(
                id=str(uuid.uuid4()),
                workflow_id=workflow.id,
                name="build_fetch_preview",
                state="failed",
            )
        )
        db.commit()
        bundle_root = tmp_path / "fetched-bundles" / owner_id / result.bundle_id

        workflow_service._cleanup_terminal_fetched_snapshot(db, workflow)
        db.commit()

        bundle = db.get(FetchedBundle, result.bundle_id)
        assert bundle is not None
        assert bundle.state == "ready_for_review"
        assert bundle.raw_available is True
        assert bundle.replayable is False
        assert bundle_root.is_dir()


@pytest.mark.parametrize("confirmed", [False, True])
def test_retryable_failure_keeps_raw_bundle_but_removes_replay_listing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    confirmed: bool,
) -> None:
    from datetime import UTC, datetime, timedelta

    from app import fetched_bundle_service

    retention_days = 7 if confirmed else 0
    monkeypatch.setattr(
        fetched_bundle_service,
        "settings",
        SimpleNamespace(
            data_dir=tmp_path,
            fetch_bundle_retention_days=retention_days,
        ),
    )
    init_db()
    owner_id = f"bundle-retry-only-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        if confirmed:
            confirm_bundle(
                db,
                bundle_id=result.bundle_id,
                actor=SimpleNamespace(user_id=owner_id),
            )

        suspend_bundle_for_retry(db, bundle_id=result.bundle_id)

        assertion = assert_bundle_consumable if confirmed else assert_bundle_reviewable
        bundle = assertion(
            db,
            bundle_id=result.bundle_id,
            owner_id=owner_id,
            dates=["2026-08-20"],
        )
        assert bundle.state == ("confirmed" if confirmed else "ready_for_review")
        assert bundle.raw_available is True
        assert bundle.replayable is False
        assert bundle.retention_until is not None
        assert bundle.retention_until.replace(tzinfo=UTC) > datetime.now(UTC) + timedelta(hours=23)
        assert (tmp_path / "fetched-bundles" / owner_id / bundle.id).is_dir()


def test_stale_creating_bundle_is_recovered_by_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    now = datetime(2026, 9, 1, 12, tzinfo=UTC)
    owner_id = f"bundle-creating-{uuid.uuid4().hex[:8]}"
    bundle_id = str(uuid.uuid4())
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        workflow.state = "failed"
        workflow.stage = "failed"
        db.add(workflow)
        db.flush()
        db.add(
            FetchedBundle(
                id=bundle_id,
                owner_id=owner_id,
                department_id=workflow.department_id,
                skill_id=workflow.skill_id,
                source_workflow_id=workflow.id,
                source_type="live",
                manifest_version="synthetic-v1",
                state="creating",
                date_from="2026-08-20",
                date_to="2026-08-20",
                dates_json='["2026-08-20"]',
                storage_key=f"{owner_id}/{bundle_id}",
                raw_available=False,
                replayable=False,
                created_at=now - timedelta(minutes=16),
                retention_until=now + timedelta(days=7),
            )
        )
        db.commit()
        bundle_root = tmp_path / "fetched-bundles" / owner_id / bundle_id
        temporary_root = tmp_path / "fetched-bundles" / owner_id / f".{bundle_id}.tmp"
        temporary_root.mkdir(parents=True)
        (temporary_root / "partial.xlsx").write_bytes(b"partial")

        real_remove_tree = fetched_bundle_service._remove_tree

        def fail_temporary_once(target: Path) -> None:
            if target == temporary_root:
                raise OSError("synthetic temporary cleanup failure")
            real_remove_tree(target)

        monkeypatch.setattr(fetched_bundle_service, "_remove_tree", fail_temporary_once)
        assert purge_expired_bundles(db, now=now) == 0
        bundle = db.get(FetchedBundle, bundle_id)
        assert bundle is not None and bundle.state == "purge_pending"
        assert temporary_root.is_dir()

        monkeypatch.setattr(fetched_bundle_service, "_remove_tree", real_remove_tree)
        assert purge_expired_bundles(db, now=now + timedelta(hours=2)) == 1
        bundle = db.get(FetchedBundle, bundle_id)
        assert bundle is not None and bundle.state == "raw_purged"
        assert not bundle_root.exists()
        assert not temporary_root.exists()


def test_materialize_bundle_persists_bundle_before_linking_workflow_with_foreign_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    owner_id = f"bundle-foreign-key-{uuid.uuid4().hex[:8]}"
    try:
        with session_factory() as db:
            workflow = _workflow(owner_id)
            db.add(workflow)
            db.commit()

            result = materialize_bundle(
                db,
                workflow=workflow,
                source=SyntheticFetchSource(),
                dates=["2026-08-20"],
            )
            db.commit()

            assert db.get(FetchedBundle, result.bundle_id) is not None
            assert workflow.fetched_bundle_id == result.bundle_id
    finally:
        engine.dispose()


def test_materialize_bundle_rejects_unknown_files_without_publishing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-invalid-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        db.flush()

        with pytest.raises(FetchedBundleError, match="未知文件"):
            materialize_bundle(
                db,
                workflow=workflow,
                source=SyntheticFetchSource(add_unknown_file=True),
                dates=["2026-08-20"],
            )
        db.rollback()

        failed = db.scalar(
            select(FetchedBundle).where(FetchedBundle.source_workflow_id == workflow.id)
        )
        assert failed is not None
        assert failed.state == "invalid"
        assert failed.raw_available is False
        owner_root = tmp_path / "fetched-bundles" / owner_id
        assert not owner_root.exists() or not list(owner_root.iterdir())


def test_snapshot_replay_revalidates_hashes_and_stays_with_original_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-replay-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        source_workflow = _workflow(owner_id)
        db.add(source_workflow)
        db.flush()
        source = materialize_bundle(
            db,
            workflow=source_workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        actor = SimpleNamespace(user_id=owner_id)
        confirm_bundle(db, bundle_id=source.bundle_id, actor=actor)
        assert_bundle_consumable(
            db,
            bundle_id=source.bundle_id,
            owner_id=owner_id,
            dates=["2026-08-20"],
        )

        replay_workflow = _workflow(owner_id)
        db.add(replay_workflow)
        db.flush()
        replay = materialize_bundle(
            db,
            workflow=replay_workflow,
            source=FetchedBundleReplayAdapter(
                db=db,
                bundle_id=source.bundle_id,
                owner_id=owner_id,
            ),
            dates=["2026-08-20"],
        )
        db.commit()
        replay_bundle = db.get(FetchedBundle, replay.bundle_id)
        assert replay_bundle is not None and replay_bundle.source_type == "replay"
        assert [item.sha256 for item in replay_bundle.files] == [
            item.sha256 for item in db.get(FetchedBundle, source.bundle_id).files
        ]

        with pytest.raises(FetchedBundleError, match="不存在"):
            FetchedBundleReplayAdapter(
                db=db,
                bundle_id=source.bundle_id,
                owner_id="another-owner",
            ).export(["2026-08-20"], tmp_path / "cross-owner")

        source_bundle = db.get(FetchedBundle, source.bundle_id)
        first = source_bundle.files[0]
        source_path = (
            tmp_path / "fetched-bundles" / owner_id / source_bundle.id / first.relative_name
        )
        source_path.chmod(0o600)
        source_path.write_bytes(b"tampered")
        tampered_workflow = _workflow(owner_id)
        db.add(tampered_workflow)
        db.flush()
        with pytest.raises(FetchedBundleError, match="哈希"):
            materialize_bundle(
                db,
                workflow=tampered_workflow,
                source=FetchedBundleReplayAdapter(
                    db=db,
                    bundle_id=source.bundle_id,
                    owner_id=owner_id,
                ),
                dates=["2026-08-20"],
            )


def test_manifest_requires_every_dataset_once_per_date(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    with SessionLocal() as db:
        workflow = _workflow(f"bundle-missing-{uuid.uuid4().hex[:8]}")
        db.add(workflow)
        db.flush()
        with pytest.raises(FetchedBundleError, match="数据集"):
            materialize_bundle(
                db,
                workflow=workflow,
                source=SyntheticFetchSource(omit_dataset="summary"),
                dates=["2026-08-20"],
            )


@pytest.mark.parametrize("relative_name", ["../escape.xlsx", "C:/escape.xlsx"])
def test_materialize_bundle_rejects_unsafe_member_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    relative_name: str,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    with SessionLocal() as db:
        workflow = _workflow(f"bundle-path-{uuid.uuid4().hex[:8]}")
        db.add(workflow)
        db.flush()
        with pytest.raises(FetchedBundleError, match="路径"):
            materialize_bundle(
                db,
                workflow=workflow,
                source=SyntheticFetchSource(unsafe_relative_name=relative_name),
                dates=["2026-08-20"],
            )


def test_materialize_bundle_rejects_declared_but_missing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    with SessionLocal() as db:
        workflow = _workflow(f"bundle-file-{uuid.uuid4().hex[:8]}")
        db.add(workflow)
        db.flush()
        with pytest.raises(FetchedBundleError, match="缺少清单成员"):
            materialize_bundle(
                db,
                workflow=workflow,
                source=SyntheticFetchSource(declare_missing_dataset="summary"),
                dates=["2026-08-20"],
            )


def test_materialize_bundle_rejects_symlink_members(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    original_is_symlink = Path.is_symlink

    def looks_like_symlink(path: Path) -> bool:
        return path.name.startswith("payments_") or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", looks_like_symlink)
    init_db()
    with SessionLocal() as db:
        workflow = _workflow(f"bundle-link-{uuid.uuid4().hex[:8]}")
        db.add(workflow)
        db.flush()
        with pytest.raises(FetchedBundleError, match="普通文件"):
            materialize_bundle(
                db,
                workflow=workflow,
                source=SyntheticFetchSource(),
                dates=["2026-08-20"],
            )


def test_repeated_materialization_is_idempotent_only_for_identical_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-repeat-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        db.flush()
        first = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        db.commit()

        repeated = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        assert repeated.bundle_id == first.bundle_id
        assert db.query(FetchedBundle).filter_by(source_workflow_id=workflow.id).count() == 1

        with pytest.raises(FetchedBundleError, match="内容.*不一致"):
            materialize_bundle(
                db,
                workflow=workflow,
                source=SyntheticFetchSource(content_marker="changed"),
                dates=["2026-08-20"],
            )
        assert db.query(FetchedBundle).filter_by(source_workflow_id=workflow.id).count() == 1
        owner_root = tmp_path / "fetched-bundles" / owner_id
        assert {path.name for path in owner_root.iterdir()} == {first.bundle_id}


def test_database_failure_removes_published_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-db-failure-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        db.flush()

        def fail_flush() -> None:
            raise RuntimeError("synthetic database failure")

        monkeypatch.setattr(db, "flush", fail_flush)
        with pytest.raises(RuntimeError, match="synthetic database failure"):
            materialize_bundle(
                db,
                workflow=workflow,
                source=SyntheticFetchSource(),
                dates=["2026-08-20"],
            )
        db.rollback()
        owner_root = tmp_path / "fetched-bundles" / owner_id
        assert not owner_root.exists() or not list(owner_root.iterdir())


def test_confirm_and_finalize_are_owner_scoped_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-state-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        db.flush()
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        with pytest.raises(FetchedBundleError, match="不存在"):
            confirm_bundle(
                db,
                bundle_id=result.bundle_id,
                actor=SimpleNamespace(user_id="another-owner"),
            )

        actor = SimpleNamespace(user_id=owner_id)
        first_confirmation = confirm_bundle(db, bundle_id=result.bundle_id, actor=actor)
        confirmed_at = first_confirmation.confirmed_at
        second_confirmation = confirm_bundle(db, bundle_id=result.bundle_id, actor=actor)
        assert second_confirmation.confirmed_at == confirmed_at

        finalize_bundle(db, bundle_id=result.bundle_id, outcome="succeeded")
        consumed_at = db.get(FetchedBundle, result.bundle_id).consumed_at
        finalize_bundle(db, bundle_id=result.bundle_id, outcome="succeeded")
        bundle = db.get(FetchedBundle, result.bundle_id)
        assert bundle.state == "consumed"
        assert bundle.consumed_at == consumed_at
        finalize_bundle(db, bundle_id=result.bundle_id, outcome="failed")
        bundle = db.get(FetchedBundle, result.bundle_id)
        assert bundle.state == "invalid"
        assert bundle.replayable is False
        assert bundle.retention_until is not None
        assert bundle.consumed_at == consumed_at


def test_preview_mirror_must_match_the_published_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-preview-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        db.flush()
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        bundle = db.get(FetchedBundle, result.bundle_id)
        mirror = tmp_path / "preview-mirror"
        mirror.mkdir()
        source_root = tmp_path / "fetched-bundles" / owner_id / bundle.id
        for item in bundle.files:
            shutil.copy2(source_root / item.relative_name, mirror / item.relative_name)

        assert_bundle_preview_mirror(
            db,
            bundle_id=bundle.id,
            owner_id=owner_id,
            dates=["2026-08-20"],
            mirror=mirror,
        )
        changed = mirror / bundle.files[0].relative_name
        changed.chmod(0o600)
        changed.write_bytes(b"changed")
        with pytest.raises(FetchedBundleError, match="哈希"):
            assert_bundle_preview_mirror(
                db,
                bundle_id=bundle.id,
                owner_id=owner_id,
                dates=["2026-08-20"],
                mirror=mirror,
            )


def test_stage_bundle_files_copies_only_the_requested_date_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-stage-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        db.flush()
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20", "2026-08-22"],
        )
        confirm_bundle(
            db,
            bundle_id=result.bundle_id,
            actor=SimpleNamespace(user_id=owner_id),
        )
        target = tmp_path / "date-workspace" / "01_智云导出"
        target.parent.mkdir()

        staged = stage_bundle_files(
            db,
            bundle_id=result.bundle_id,
            owner_id=owner_id,
            dates=["2026-08-22"],
            target=target,
        )

        assert staged == target.resolve()
        assert {path.name for path in target.iterdir()} == {
            f"{dataset}_20260822.{'json' if dataset == 'summary' else 'xlsx'}"
            for dataset in DATASETS
        }
        assert not list(target.parent.glob(".*.tmp"))

        repeated = stage_bundle_files(
            db,
            bundle_id=result.bundle_id,
            owner_id=owner_id,
            dates=["2026-08-22"],
            target=target,
        )
        assert repeated == target.resolve()

        changed = next(target.iterdir())
        changed.chmod(0o600)
        changed.write_bytes(b"changed")
        with pytest.raises(FetchedBundleError, match="哈希|不一致"):
            stage_bundle_files(
                db,
                bundle_id=result.bundle_id,
                owner_id=owner_id,
                dates=["2026-08-22"],
                target=target,
            )


def test_stage_bundle_preview_files_allows_reviewable_but_unconfirmed_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-review-stage-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        db.flush()
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20", "2026-08-22"],
        )
        target = tmp_path / "preview-workspace" / "01_智云导出"
        target.parent.mkdir()

        stage_bundle_preview_files(
            db,
            bundle_id=result.bundle_id,
            owner_id=owner_id,
            dates=["2026-08-20", "2026-08-22"],
            target=target,
        )

        assert len(list(target.iterdir())) == len(DATASETS) * 2
        with pytest.raises(FetchedBundleError, match="不能用于核销计划"):
            stage_bundle_files(
                db,
                bundle_id=result.bundle_id,
                owner_id=owner_id,
                dates=["2026-08-20"],
                target=tmp_path / "unconfirmed-plan",
            )


def test_expired_bundle_purge_is_terminal_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    now = datetime(2026, 9, 1, 12, tzinfo=UTC)
    owner_id = f"bundle-purge-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        workflow.state = "succeeded"
        workflow.stage = "completed"
        db.add(workflow)
        db.flush()
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        confirm_bundle(
            db,
            bundle_id=result.bundle_id,
            actor=SimpleNamespace(user_id=owner_id),
        )
        finalize_bundle(db, bundle_id=result.bundle_id, outcome="succeeded")
        bundle = db.get(FetchedBundle, result.bundle_id)
        bundle.preview_available = True
        bundle.retention_until = now - timedelta(seconds=1)
        db.commit()
        bundle_root = tmp_path / "fetched-bundles" / owner_id / bundle.id

        assert purge_expired_bundles(db, now=now, limit=10) == 1
        db.refresh(bundle)
        attempts = bundle.purge_attempts
        assert bundle.state == "raw_purged"
        assert bundle.raw_available is False
        assert bundle.replayable is False
        assert bundle.preview_available is True
        assert bundle.purged_at.replace(tzinfo=UTC) == now
        assert not bundle_root.exists()

        assert purge_fetched_bundle(db, bundle_id=bundle.id, now=now) is True
        db.refresh(bundle)
        assert bundle.purge_attempts == attempts


def test_active_workflow_reference_blocks_expired_bundle_purge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    now = datetime(2026, 9, 1, 12, tzinfo=UTC)
    owner_id = f"bundle-active-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        workflow.state = "running"
        db.add(workflow)
        db.flush()
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        confirm_bundle(
            db,
            bundle_id=result.bundle_id,
            actor=SimpleNamespace(user_id=owner_id),
        )
        finalize_bundle(db, bundle_id=result.bundle_id, outcome="succeeded")
        bundle = db.get(FetchedBundle, result.bundle_id)
        bundle.retention_until = now - timedelta(seconds=1)
        db.commit()

        assert purge_expired_bundles(db, now=now, limit=10) == 0
        db.refresh(bundle)
        assert bundle.state == "consumed"
        assert bundle.purge_attempts == 0
        assert (tmp_path / "fetched-bundles" / owner_id / bundle.id).is_dir()


def test_bundle_purge_failure_is_sanitized_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    now = datetime(2026, 9, 1, 12, tzinfo=UTC)
    owner_id = f"bundle-retry-purge-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        workflow.state = "succeeded"
        workflow.stage = "completed"
        db.add(workflow)
        db.flush()
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        confirm_bundle(
            db,
            bundle_id=result.bundle_id,
            actor=SimpleNamespace(user_id=owner_id),
        )
        finalize_bundle(db, bundle_id=result.bundle_id, outcome="succeeded")
        bundle = db.get(FetchedBundle, result.bundle_id)
        bundle.retention_until = now - timedelta(seconds=1)
        db.commit()
        real_remove_tree = fetched_bundle_service._remove_tree

        def fail_remove(_target: Path) -> None:
            raise OSError(f"cannot delete {tmp_path / 'private-customer-file'}")

        monkeypatch.setattr(fetched_bundle_service, "_remove_tree", fail_remove)
        assert purge_expired_bundles(db, now=now, limit=10) == 0
        db.refresh(bundle)
        assert bundle.state == "purge_pending"
        assert bundle.purge_attempts == 1
        assert "private-customer-file" not in bundle.last_error
        assert workflow.state == "succeeded"

        monkeypatch.setattr(fetched_bundle_service, "_remove_tree", real_remove_tree)
        assert (
            purge_expired_bundles(
                db,
                now=now + timedelta(hours=2),
                limit=10,
            )
            == 1
        )
        db.refresh(bundle)
        assert bundle.state == "raw_purged"
        assert bundle.purge_attempts == 2
        assert bundle.last_error == ""


def test_replay_bundle_resolution_prefers_bundle_id_and_scopes_legacy_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-resolve-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        db.add(workflow)
        db.flush()
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        confirm_bundle(
            db,
            bundle_id=result.bundle_id,
            actor=SimpleNamespace(user_id=owner_id),
        )
        finalize_bundle(db, bundle_id=result.bundle_id, outcome="succeeded")
        db.commit()

        direct = resolve_replay_bundle(
            db,
            owner_id=owner_id,
            skill_id="ar-hexiao-daily",
            dates=["2026-08-20"],
            bundle_id=result.bundle_id,
        )
        legacy = resolve_replay_bundle(
            db,
            owner_id=owner_id,
            skill_id="ar-hexiao-daily",
            dates=["2026-08-20"],
            source_workflow_id=workflow.id,
        )

        assert direct.bundle.id == result.bundle_id
        assert direct.deprecated_reference is False
        assert legacy.bundle.id == result.bundle_id
        assert legacy.deprecated_reference is True
        with pytest.raises(FetchedBundleError, match="不存在"):
            resolve_replay_bundle(
                db,
                owner_id="another-owner",
                skill_id="ar-hexiao-daily",
                dates=["2026-08-20"],
                bundle_id=result.bundle_id,
            )
        with pytest.raises(FetchedBundleError, match="不能同时"):
            resolve_replay_bundle(
                db,
                owner_id=owner_id,
                skill_id="ar-hexiao-daily",
                dates=["2026-08-20"],
                bundle_id=result.bundle_id,
                source_workflow_id=workflow.id,
            )


def test_expired_bundle_cannot_be_selected_for_replay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-expired-replay-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        workflow.state = "succeeded"
        db.add(workflow)
        db.flush()
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        confirm_bundle(db, bundle_id=result.bundle_id, actor=SimpleNamespace(user_id=owner_id))
        finalize_bundle(db, bundle_id=result.bundle_id, outcome="succeeded")
        bundle = db.get(FetchedBundle, result.bundle_id)
        bundle.retention_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

        with pytest.raises(FetchedBundleError, match="不可回放"):
            resolve_replay_bundle(
                db,
                owner_id=owner_id,
                skill_id="ar-hexiao-daily",
                dates=["2026-08-20"],
                bundle_id=bundle.id,
            )
        with pytest.raises(FetchedBundleError, match="没有可回放"):
            resolve_replay_bundle(
                db,
                owner_id=owner_id,
                skill_id="ar-hexiao-daily",
                dates=["2026-08-20"],
                source_workflow_id=workflow.id,
            )


def test_replay_adapter_rechecks_retention_at_export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    owner_id = f"bundle-export-expired-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        workflow.state = "succeeded"
        db.add(workflow)
        db.flush()
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        confirm_bundle(db, bundle_id=result.bundle_id, actor=SimpleNamespace(user_id=owner_id))
        finalize_bundle(db, bundle_id=result.bundle_id, outcome="succeeded")
        adapter = FetchedBundleReplayAdapter(
            db=db,
            bundle_id=result.bundle_id,
            owner_id=owner_id,
        )
        bundle = db.get(FetchedBundle, result.bundle_id)
        bundle.retention_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

        with pytest.raises(FetchedBundleError, match="不可回放"):
            adapter.export(["2026-08-20"], tmp_path / "expired-replay")


def test_expired_unconfirmed_bundle_is_purged_after_task_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    now = datetime(2026, 9, 1, 12, tzinfo=UTC)
    owner_id = f"bundle-unconfirmed-purge-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        workflow.state = "cancelled"
        db.add(workflow)
        db.flush()
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        bundle = db.get(FetchedBundle, result.bundle_id)
        bundle.retention_until = now - timedelta(seconds=1)
        db.commit()

        assert purge_fetched_bundle(db, bundle_id=bundle.id, now=now) is True
        db.refresh(bundle)
        assert bundle.state == "raw_purged"
        assert bundle.raw_available is False


def test_purge_pending_lease_blocks_a_second_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    now = datetime(2026, 9, 1, 12, tzinfo=UTC)
    owner_id = f"bundle-purge-lease-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        workflow.state = "succeeded"
        db.add(workflow)
        db.flush()
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        bundle = db.get(FetchedBundle, result.bundle_id)
        bundle.state = "purge_pending"
        bundle.retention_until = now - timedelta(seconds=1)
        bundle.purge_attempts = 1
        bundle.purge_retry_at = now + timedelta(minutes=5)
        db.commit()

        assert purge_fetched_bundle(db, bundle_id=bundle.id, now=now) is False
        db.refresh(bundle)
        assert bundle.purge_attempts == 1
        assert bundle.state == "purge_pending"


def test_expired_purge_worker_cannot_overwrite_newer_attempt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    from app import fetched_bundle_service

    monkeypatch.setattr(fetched_bundle_service, "settings", _settings(tmp_path))
    init_db()
    now = datetime(2026, 9, 1, 12, tzinfo=UTC)
    owner_id = f"bundle-purge-fence-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        workflow.state = "succeeded"
        db.add(workflow)
        db.flush()
        result = materialize_bundle(
            db,
            workflow=workflow,
            source=SyntheticFetchSource(),
            dates=["2026-08-20"],
        )
        bundle = db.get(FetchedBundle, result.bundle_id)
        bundle.retention_until = now - timedelta(seconds=1)
        db.commit()

        def replace_lease(_target: Path) -> None:
            with SessionLocal() as competing_db:
                competing = competing_db.get(FetchedBundle, bundle.id)
                competing.state = "purge_pending"
                competing.purge_attempts = 2
                competing.purge_retry_at = now + timedelta(minutes=10)
                competing.last_error = "newer worker owns cleanup"
                competing_db.commit()

        monkeypatch.setattr(fetched_bundle_service, "_remove_tree", replace_lease)

        assert purge_fetched_bundle(db, bundle_id=bundle.id, now=now) is False
        db.refresh(bundle)
        assert bundle.state == "purge_pending"
        assert bundle.purge_attempts == 2
        assert bundle.last_error == "newer worker owns cleanup"
