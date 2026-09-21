import json
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import RunRecord, RunExecutionSnapshot
from app.modules.execution.run_snapshot import assert_execution_snapshot
from app.modules.execution.preconditions import ExecutionInputChanged
from app.modules.execution.authorization import ExecutionPhase
from test_refactor_event_transactions import database, prepared_submission
from test_parallel_workers import _manifest


def create(db):
    from app.run_service import persist_run
    prepared = prepared_submission()
    prepared.run.manifest_snapshot = _manifest()
    from app.modules.execution.input_snapshot import input_snapshot_hash
    prepared.run.files_json = json.dumps({"input": {"file_id": "synthetic-file", "sha256": "c"*64}})
    prepared.run.parameters_json = "{}"
    prepared.run.input_hash = input_snapshot_hash(prepared.run.parameters_json, json.loads(prepared.run.files_json), prepared.run.skill_hash)
    persist_run(db, prepared)
    return prepared


@pytest.mark.parametrize("field,value", [("message", "changed intent"), ("parameters_json", '{"amount":2}'),
    ("files_json", '{}'), ("skill_commit", "another-commit"), ("skill_hash", "b"*64), ("skill_version", "2"),
    ("owner_id", "another"), ("department_id", "another"), ("adapter", "shell"),
    ("worker_pool", "another"), ("confirmation_required", True), ("manifest_snapshot", '{}')])
def test_execution_change_rejected(database, field, value):
    with Session(database) as db:
        run = create(db).run
        db.commit()
        setattr(run, field, value)
        with pytest.raises(ExecutionInputChanged): assert_execution_snapshot(db, run, ExecutionPhase.START)
        db.rollback()


def test_snapshot_creation_obeys_submission_rollback(database):
    with Session(database) as db:
        create(db)
        assert db.get(RunExecutionSnapshot, "synthetic-run") is not None
        db.rollback()
    with Session(database) as db:
        assert db.get(RunRecord, "synthetic-run") is None
        assert db.get(RunExecutionSnapshot, "synthetic-run") is None


@pytest.mark.parametrize("case", ["matches", "matches_commit", "message_changed", "missing", "wrong_scope", "malformed", "original_hash_changed"])
def test_legacy_snapshot_requires_bound_original_payload(database, case):
    from app.modules.execution.prepared_payload import freeze_prepared
    from app.modules.execution.idempotency_models import IdempotencyRequest
    with Session(database) as db:
        prepared = create(db)
        payload = freeze_prepared(prepared)
        if case == "original_hash_changed": payload["run"]["input_hash"] = "b"*64
        db.delete(db.get(RunExecutionSnapshot, prepared.run.id))
        if case != "missing":
            now = datetime.now(timezone.utc)
            db.add(IdempotencyRequest(id="receipt", owner_id="other" if case == "wrong_scope" else "synthetic-owner",
                department_id="finance", operation="run.create", request_key="original", request_fingerprint="a"*64,
                canonical_version=1, status="bound", reservation_token="token", reservation_expires_at=now,
                pinned_revision_json="{}", prepared_payload_json="{}" if case == "malformed" else json.dumps(payload),
                execution_kind="run", execution_id=prepared.run.id, response_version=1, created_at=now, updated_at=now))
        if case == "message_changed": prepared.run.message = "changed after original request"
        db.commit()
    with Session(database) as db:
        run = db.get(RunRecord, "synthetic-run")
        if case in {"matches", "matches_commit"}:
            assert_execution_snapshot(db, run, ExecutionPhase.CLAIM)
            assert db.get(RunExecutionSnapshot, run.id).source == "bound_submission"
            if case == "matches_commit": db.commit()
            else: db.rollback()
        else:
            with pytest.raises(ExecutionInputChanged): assert_execution_snapshot(db, run, ExecutionPhase.CLAIM)
            db.rollback()
    with Session(database) as db:
        assert (db.get(RunExecutionSnapshot, "synthetic-run") is not None) == (case == "matches_commit")
        if case == "matches_commit":
            assert_execution_snapshot(db, db.get(RunRecord, "synthetic-run"), ExecutionPhase.START)


@pytest.mark.parametrize("phase", ["confirm", "claim", "start"])
def test_changed_message_rejected_at_actual_entry(database, monkeypatch, phase):
    from unittest.mock import Mock
    from fastapi import HTTPException
    from app import worker
    from app.auth import UserContext
    from app.run_service import confirm_run
    adapter = Mock()
    monkeypatch.setattr(worker, "get_adapter", lambda _: adapter)
    with Session(database) as db:
        run = create(db).run
        if phase == "confirm": run.state = "waiting_confirmation"
        db.commit()
        if phase == "start":
            run = worker.claim_next_run(db, ("python",), "snapshot-worker")
            assert run is not None
        with Session(database) as other:
            changed = other.get(RunRecord, "synthetic-run")
            changed.message = "different instruction after submission"
            other.commit()
        if phase == "confirm":
            with pytest.raises(HTTPException) as error:
                confirm_run(db, run, UserContext("synthetic-owner", "Synthetic", "finance_user", "finance"))
            assert error.value.status_code == 409
            assert run.confirmed_at is None
            db.rollback()
        elif phase == "claim":
            assert worker.claim_next_run(db, ("python",), "snapshot-worker") is None
        else:
            worker.execute_run(db, run)
        adapter.execute.assert_not_called()
    if phase != "confirm":
        from app.models import RunEvent
        with Session(database) as db:
            assert db.get(RunRecord, "synthetic-run").state == "failed"
            event = db.scalar(select(RunEvent).where(RunEvent.state == "failed"))
            assert "INPUT_SNAPSHOT_CHANGED" in event.data_json
