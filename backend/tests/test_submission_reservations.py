from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
import json
import pytest
from sqlalchemy import func, inspect, select, update
from sqlalchemy.orm import Session
from app.modules.execution.idempotency import (Scope, Operation, IdempotencyConflict,
    ReservationLost, reserve, read, mark_prepared, bind, reject)
from app.modules.execution.idempotency_models import IdempotencyRequest as Record
from test_refactor_event_transactions import database, new_run

SCOPE = Scope("synthetic-owner", "finance", Operation.RUN_CREATE)


def claim(db, key="intent", scope=SCOPE, fingerprint="a" * 64):
    return reserve(db, scope, key, fingerprint=fingerprint, pinned_revision={"revision":"fixed"})


def test_migration_metadata(database):
    inspector = inspect(database)
    assert "idempotency_requests" in inspector.get_table_names()
    assert {"source_session_key", "source_command_id"} <= {v["name"] for v in inspector.get_columns("runs")}
    assert any(v["column_names"] == ["owner_id", "department_id", "operation", "request_key"] for v in inspector.get_unique_constraints("idempotency_requests"))


def test_reservation_rollback_and_binding_atomicity(database):
    with Session(database) as db:
        row, acquired = claim(db)
        assert acquired
        db.rollback()
    with Session(database) as db:
        assert read(db, SCOPE, "intent") is None
        row, acquired = claim(db)
        token = row.reservation_token
        db.commit()
        mark_prepared(db, SCOPE, "intent", token, {"frozen":True})
        run = new_run(db)
        bind(db, SCOPE, "intent", token, execution_kind="run", execution_id=run.id)
        db.rollback()
    with Session(database) as db:
        row = read(db, SCOPE, "intent")
        assert row.status == "preparing"
        from app.models import RunRecord
        assert db.get(RunRecord, "synthetic-run") is None
        mark_prepared(db, SCOPE, "intent", token, {"frozen":True})
        run = new_run(db)
        bind(db, SCOPE, "intent", token, execution_kind="run", execution_id=run.id)
        db.commit()
    with Session(database) as db:
        row, acquired = claim(db)
        assert not acquired and row.execution_id == "synthetic-run" and row.status == "bound"
        assert db.get(RunRecord, "synthetic-run") is not None


def test_conflict_and_scope_isolation(database):
    with Session(database) as db:
        row, acquired = claim(db)
        db.commit()
        with pytest.raises(IdempotencyConflict):
            claim(db, fingerprint="b" * 64)
        db.rollback()
        for scope in [Scope("other", "finance", Operation.RUN_CREATE), Scope("synthetic-owner", "other", Operation.RUN_CREATE), Scope("synthetic-owner", "finance", Operation.RUN_RETRY)]:
            row, acquired = claim(db, scope=scope)
            assert acquired
            db.commit()
        assert db.scalar(select(func.count()).select_from(Record)) == 4


def test_expired_token_cannot_prepare_or_bind_and_frozen_payload_survives(database):
    with Session(database) as db:
        row, acquired = claim(db)
        old_token = row.reservation_token
        mark_prepared(db, SCOPE, "intent", old_token, {"model_result":"original"})
        db.execute(update(Record).values(reservation_expires_at=datetime.now(UTC)-timedelta(minutes=1)))
        db.commit()
        with pytest.raises(ReservationLost):
            bind(db, SCOPE, "intent", old_token, execution_kind="run", execution_id="old")
        db.rollback()
        row, acquired = claim(db)
        assert acquired and row.status == "prepared"
        assert json.loads(row.prepared_payload_json) == {"model_result":"original"}
        new_token = row.reservation_token
        assert new_token != old_token
        db.commit()
        with pytest.raises(ReservationLost):
            bind(db, SCOPE, "intent", old_token, execution_kind="run", execution_id="old")
        db.rollback()
        bind(db, SCOPE, "intent", new_token, execution_kind="run", execution_id="new")
        db.commit()
        row, acquired = claim(db)
        assert not acquired and row.execution_id == "new"


def test_rejected_request_is_not_reclaimed(database):
    with Session(database) as db:
        row, _ = claim(db)
        reject(db, SCOPE, "intent", row.reservation_token)
        db.execute(update(Record).values(reservation_expires_at=datetime.now(UTC)-timedelta(minutes=1)))
        db.commit()
        row, acquired = claim(db)
        assert not acquired and row.status == "rejected"


def test_twenty_concurrent_clients_have_one_bound_resource(database):
    if database.dialect.name != "postgresql":
        pytest.skip("Requires actual PostgreSQL uniqueness and row locking")
    barrier = Barrier(20)
    def submit(index):
        with Session(database) as db:
            barrier.wait(timeout=20)
            row, acquired = claim(db)
            token = row.reservation_token
            db.commit()
            if acquired:
                mark_prepared(db, SCOPE, "intent", token, {"winner":index})
                run = new_run(db)
                bind(db, SCOPE, "intent", token, execution_kind="run", execution_id=run.id)
                db.commit()
            return acquired
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(submit, range(20)))
    assert sum(results) == 1
    with Session(database) as db:
        row = read(db, SCOPE, "intent")
        assert row.status == "bound" and row.execution_id == "synthetic-run"
        assert db.scalar(select(func.count()).select_from(Record)) == 1
        from app.models import RunRecord
        assert db.scalar(select(func.count()).select_from(RunRecord)) == 1
