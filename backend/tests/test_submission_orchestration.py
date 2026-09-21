from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from app.models import RunRecord
from app.modules.execution.idempotency import Scope, Operation, IdempotencyConflict
from app.modules.execution.idempotency_models import IdempotencyRequest
from app.modules.execution.submission import prepare_submission, persist_submission, SubmissionInProgress
from test_refactor_event_transactions import database
from test_prepared_payload import prepared as synthetic_prepared

SCOPE = Scope("synthetic-owner", "finance", Operation.RUN_CREATE)


def authorization(db):
    # Synthetic adapter; actual HTTP adapter must refresh user and permissions.
    assert db.scalar(select(func.count()).select_from(RunRecord)) >= 0


def prepare(pin):
    assert pin == {"revision":"original"}
    value = synthetic_prepared()
    value.run.owner_id = SCOPE.owner_id
    value.run.id = "synthetic-submission"
    return value


def start(engine, **overrides):
    options = dict(scope=SCOPE, key="intent", submitted={"text":"request"},
        authorize=authorization, select_pin=lambda db:{"revision":"original"}, prepare=prepare)
    options.update(overrides)
    return prepare_submission(engine, **options)


def finish(db, ticket, **overrides):
    def load(db, kind, rid):
        assert kind == "run"
        run = db.get(RunRecord, rid)
        assert run.owner_id == SCOPE.owner_id and run.department_id == SCOPE.department_id
        return run
    options = dict(authorize=authorization, validate_prepared=lambda db, value:None, load_bound=load)
    options.update(overrides)
    return persist_submission(db, ticket, **options)


def test_prepare_outside_transaction_and_bound_replay_after_publication(database):
    calls=[]
    def external(pin):
        assert database.pool.checkedout() == 0
        calls.append(pin)
        return prepare(pin)
    ticket = start(database, prepare=external)
    with Session(database) as db:
        run = finish(db,ticket)
        db.commit()
        rid = run.id
    def must_not_run(*args):
        pytest.fail("Bound replay must not select new revision or invoke preparation")
    replay = start(database, select_pin=must_not_run, prepare=must_not_run)
    with Session(database) as db:
        assert finish(db,replay).id == rid
        db.commit()
    assert len(calls)==1
    with pytest.raises(IdempotencyConflict):
        start(database, submitted={"text":"changed"}, prepare=must_not_run)


def test_frozen_preparation_recovered_after_expiry_without_model(database):
    ticket = start(database)
    with Session(database) as db:
        db.execute(update(IdempotencyRequest).values(reservation_expires_at=datetime.now(UTC)-timedelta(minutes=1)))
        db.commit()
    def must_not_run(*args):
        pytest.fail("Frozen preparation must be reused")
    recovered = start(database, select_pin=must_not_run, prepare=must_not_run)
    assert recovered.token != ticket.token
    with Session(database) as db:
        run = finish(db,recovered)
        db.commit()
        assert run.id == "synthetic-submission"


def test_persist_failure_savepoint_preserves_prepared_without_partial_run(database, monkeypatch):
    from app import run_service
    ticket = start(database)
    original = run_service.persist_run
    def failure(db, value):
        original(db,value)
        raise RuntimeError("injected persist failure")
    monkeypatch.setattr(run_service,"persist_run",failure)
    with Session(database) as db:
        with pytest.raises(RuntimeError,match="injected"):
            finish(db,ticket)
        db.commit()  # Even a caller that catches the error cannot commit a half bind.
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(RunRecord)) == 0
        assert db.scalar(select(IdempotencyRequest)).status == "prepared"
    monkeypatch.setattr(run_service,"persist_run",original)
    with Session(database) as db:
        finish(db,ticket)
        db.commit()


def test_revoked_authorization_cannot_replay(database):
    ticket = start(database)
    with Session(database) as db:
        finish(db,ticket)
        db.commit()
    def denied(db):
        raise PermissionError("revoked")
    with pytest.raises(PermissionError):
        start(database, authorize=denied)
    with Session(database) as db, pytest.raises(PermissionError):
        finish(db,ticket,authorize=denied)


def test_twenty_clients_prepare_and_bind_once(database):
    if database.dialect.name != "postgresql":
        pytest.skip("Real concurrent orchestration requires PostgreSQL")
    barrier=Barrier(20)
    calls=[]
    def external(pin):
        calls.append(pin)
        return prepare(pin)
    def client(index):
        barrier.wait(timeout=20)
        try:
            ticket=start(database,prepare=external)
        except SubmissionInProgress:
            return None
        with Session(database) as db:
            run=finish(db,ticket)
            db.commit()
            return run.id
    with ThreadPoolExecutor(max_workers=20) as pool:
        results=list(pool.map(client,range(20)))
    assert {v for v in results if v} == {"synthetic-submission"}
    assert len(calls)==1
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(RunRecord)) == 1
        assert db.scalar(select(IdempotencyRequest)).status == "bound"


def test_outer_rollback_undoes_business_and_binding(database):
    ticket = start(database)
    with Session(database) as db:
        finish(db, ticket)
        db.rollback()
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(RunRecord)) == 0
        assert db.scalar(select(IdempotencyRequest)).status == "prepared"


def test_recovery_mode_blocks_unbound_work_and_preserves_bound_replay(database):
    from app.modules.execution.submission import SubmissionRecoveryOnly
    def no_work(*args):
        pytest.fail("Recovery mode must not prepare or validate new execution")
    with pytest.raises(SubmissionRecoveryOnly):
        start(database, replay_only=True, select_pin=no_work, prepare=no_work)
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(IdempotencyRequest)) == 0
    ticket = start(database)
    with Session(database) as db:
        before = db.scalar(select(IdempotencyRequest)).reservation_token
    with pytest.raises(SubmissionRecoveryOnly):
        start(database, replay_only=True, prepare=no_work)
    with Session(database) as db:
        with pytest.raises(SubmissionRecoveryOnly):
            finish(db,ticket,replay_only=True,validate_prepared=no_work)
        db.commit()
        assert db.scalar(select(func.count()).select_from(RunRecord)) == 0
        receipt = db.scalar(select(IdempotencyRequest))
        assert receipt.status == "prepared" and receipt.reservation_token == before
    with Session(database) as db:
        finish(db,ticket)
        db.commit()
    replay = start(database,replay_only=True,select_pin=no_work,prepare=no_work)
    with Session(database) as db:
        assert finish(db,replay,replay_only=True,validate_prepared=no_work).id == "synthetic-submission"
        db.commit()
    with pytest.raises(IdempotencyConflict):
        start(database,replay_only=True,submitted={"text":"different"},prepare=no_work)
    with pytest.raises(PermissionError):
        start(database,replay_only=True,authorize=lambda db:(_ for _ in ()).throw(PermissionError("revoked")))


def test_failed_prepare_attempt_is_durable_redacted_and_retry_is_distinct(database):
    import json
    from app.models import AuditEvent
    def failed(pin):
        assert database.pool.checkedout() == 0
        raise RuntimeError("secret model response must never enter audit")
    with pytest.raises(RuntimeError, match="secret model"):
        start(database, prepare=failed)
    with Session(database) as db:
        events=list(db.scalars(select(AuditEvent).where(AuditEvent.action == "submission.prepare").order_by(AuditEvent.id)))
        assert [e.outcome for e in events] == ["started", "failed"]
        first=[json.loads(e.details_json) for e in events]
        assert first[0]["attempt_id"] == first[1]["attempt_id"]
        assert all(set(v) == {"attempt_id", "operation"} for v in first)
        assert all(e.actor_id == SCOPE.owner_id and e.department_id == SCOPE.department_id for e in events)
        assert all("secret" not in e.details_json for e in events)
        assert db.scalar(select(func.count()).select_from(RunRecord)) == 0
        receipt=db.scalar(select(IdempotencyRequest))
        assert receipt.status == "preparing"
        db.execute(update(IdempotencyRequest).values(reservation_expires_at=datetime.now(UTC)-timedelta(minutes=1)))
        db.commit()
    ticket=start(database)
    with Session(database) as db:
        events=list(db.scalars(select(AuditEvent).where(AuditEvent.action == "submission.prepare").order_by(AuditEvent.id)))
        assert [e.outcome for e in events] == ["started", "failed", "started", "prepared"]
        values=[json.loads(e.details_json) for e in events]
        assert values[2]["attempt_id"] == values[3]["attempt_id"] != values[0]["attempt_id"]
        assert all(e.resource_id == ticket.receipt_id for e in events)
        finish(db,ticket)
        db.rollback()
    # Caller rollback cannot erase external preparation facts.
    with Session(database) as db:
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "submission.prepare")) == 4
        assert db.scalar(select(func.count()).select_from(RunRecord)) == 0


@pytest.mark.parametrize("committed", [False, True])
def test_prepare_commit_acknowledgement_loss_is_not_misreported_failed(database, monkeypatch, committed):
    from app.models import AuditEvent
    original=Session.commit
    fired=[]
    def commit(db):
        prepared_fact=db.scalar(select(AuditEvent.id).where(AuditEvent.action == "submission.prepare",AuditEvent.outcome == "prepared"))
        if prepared_fact is not None and not fired:
            fired.append(True)
            if committed:original(db)
            raise RuntimeError("commit observation lost")
        return original(db)
    monkeypatch.setattr(Session,"commit",commit)
    with pytest.raises(RuntimeError,match="observation lost"):
        start(database)
    with Session(database) as db:
        outcomes=list(db.scalars(select(AuditEvent.outcome).where(AuditEvent.action == "submission.prepare").order_by(AuditEvent.id)))
        assert outcomes == ["started", "prepared" if committed else "unknown"]
        assert db.scalar(select(IdempotencyRequest)).status == ("prepared" if committed else "preparing")
