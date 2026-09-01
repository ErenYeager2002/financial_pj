from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal, init_db
from app.models import FetchedBundle, FetchedBundleFile, WorkflowSession
from app.schemas import FetchedBundleRead


def _workflow(owner_id: str) -> WorkflowSession:
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
        reconciliation_date="2026-08-20",
    )


def _bundle(workflow: WorkflowSession, **overrides: object) -> FetchedBundle:
    values: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "owner_id": workflow.owner_id,
        "department_id": workflow.department_id,
        "skill_id": workflow.skill_id,
        "source_workflow_id": workflow.id,
        "source_type": "live",
        "manifest_version": "2026-09-01-v1",
        "state": "ready_for_review",
        "date_from": "2026-08-20",
        "date_to": "2026-08-20",
        "dates_json": '["2026-08-20"]',
        "storage_key": f"{workflow.owner_id}/{uuid.uuid4()}",
        "raw_available": True,
        "preview_available": False,
        "replayable": True,
        "retention_until": datetime(2026, 9, 8, tzinfo=UTC),
    }
    values.update(overrides)
    return FetchedBundle(**values)


def test_fetched_bundle_model_enforces_replay_and_member_uniqueness() -> None:
    init_db()
    owner_id = f"bundle-owner-{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        workflow = _workflow(owner_id)
        bundle = _bundle(workflow)
        db.add_all([workflow, bundle])
        db.flush()
        workflow.fetched_bundle_id = bundle.id
        first = FetchedBundleFile(
            id=str(uuid.uuid4()),
            bundle_id=bundle.id,
            reconciliation_date="2026-08-20",
            dataset="payments",
            relative_name="回款记录_20260820.xlsx",
            sha256="b" * 64,
            size_bytes=128,
        )
        db.add(first)
        db.commit()

        assert workflow.fetched_bundle_id == bundle.id
        assert [item.dataset for item in bundle.files] == ["payments"]

        duplicate = FetchedBundleFile(
            id=str(uuid.uuid4()),
            bundle_id=bundle.id,
            reconciliation_date="2026-08-20",
            dataset="payments",
            relative_name="duplicate.xlsx",
            sha256="c" * 64,
            size_bytes=1,
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    with SessionLocal() as db:
        invalid_workflow = _workflow(f"invalid-owner-{uuid.uuid4().hex[:8]}")
        db.add(invalid_workflow)
        db.flush()
        db.add(
            _bundle(
                invalid_workflow,
                raw_available=False,
                replayable=True,
                storage_key="",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_fetched_bundle_contract_exposes_only_lifecycle_metadata() -> None:
    payload = FetchedBundleRead(
        id="bundle-1",
        source_type="live",
        state="raw_purged",
        dates=["2026-08-20"],
        raw_available=False,
        preview_available=True,
        replayable=False,
        retention_until=None,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    ).model_dump()

    assert payload == {
        "id": "bundle-1",
        "source_type": "live",
        "state": "raw_purged",
        "dates": ["2026-08-20"],
        "raw_available": False,
        "preview_available": True,
        "replayable": False,
        "retention_until": None,
        "created_at": datetime(2026, 9, 1, tzinfo=UTC),
    }
    assert "storage_key" not in payload
    assert "last_error" not in payload
