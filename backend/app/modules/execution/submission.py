"""Short-transaction submission orchestration, independent of HTTP response shape.

Application adapters provide current authorization, pin selection and preparation.
No model or filesystem preparation runs while this service owns a DB transaction.
The final business transaction remains caller-owned, including any draft/audit.
"""
from dataclasses import dataclass
import json
from uuid import uuid4
from ...audit_service import record_audit
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...models import AuditEvent
from . import idempotency
from .canonical import request_fingerprint
from .prepared_payload import freeze_prepared, restore_prepared


class SubmissionInProgress(RuntimeError):
    def __init__(self, receipt_id):
        self.receipt_id = receipt_id
        super().__init__("SUBMISSION_IN_PROGRESS")


class SubmissionRecoveryOnly(RuntimeError):
    def __init__(self, receipt_id=None):
        self.receipt_id = receipt_id
        super().__init__("SUBMISSION_RECOVERY_ONLY")


class SubmissionRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class SubmissionTicket:
    scope: idempotency.Scope
    key: str
    token: str
    receipt_id: str


def _fingerprint(scope, submitted, pinned):
    return request_fingerprint(operation=scope.operation.value, owner_id=scope.owner_id,
                               department_id=scope.department_id,
                               submitted=submitted, pinned_revision=pinned)


def prepare_submission(engine, *, scope, key, submitted, authorize, select_pin,
                       prepare, lease_seconds=120, canonicalize=None, replay_only=False):
    """authorize(db) runs before every DB phase and must check current identity.

    select_pin(db) returns credential-free frozen metadata, not a live ORM object.
    prepare(pinned) performs external preparation using exactly that selection.
    The input submitted has validated, explicit defaults; no relative values may
    be resolved again on replay. Callbacks must not commit the supplied Session.
    """
    def fingerprint_for(pin):
        value = canonicalize(submitted, pin) if canonicalize else submitted
        return _fingerprint(scope, value, pin)

    with Session(engine) as db:
        authorize(db)
        existing = idempotency.read(db, scope, key)
        if replay_only and (existing is None or existing.status != "bound"):
            raise SubmissionRecoveryOnly(existing.id if existing is not None else None)
        pinned = json.loads(existing.pinned_revision_json) if existing else select_pin(db)
        fingerprint = fingerprint_for(pinned)
        try:
            row, acquired = idempotency.reserve(db, scope, key, fingerprint=fingerprint,
                pinned_revision=pinned, lease_seconds=lease_seconds)
        except idempotency.IdempotencyConflict:
            # Another reservation can win between read and INSERT, including a
            # publication. Recompare against its pin, never the latest revision.
            existing = idempotency.read(db, scope, key)
            if existing is None:
                raise
            pinned = json.loads(existing.pinned_revision_json)
            row, acquired = idempotency.reserve(db, scope, key,
                fingerprint=fingerprint_for(pinned),
                pinned_revision=pinned, lease_seconds=lease_seconds)
        ticket = SubmissionTicket(scope, key, row.reservation_token, row.id)
        status, payload = row.status, row.prepared_payload_json
        pinned = json.loads(row.pinned_revision_json)
        attempt_id = str(uuid4()) if acquired and status == "preparing" else None
        if attempt_id is not None:
            _record_prepare_attempt(db, ticket, attempt_id, "started")
        db.commit()
    if status == "bound":
        return ticket
    if status == "rejected":
        raise SubmissionRejected("SUBMISSION_REJECTED")
    if not acquired:
        raise SubmissionInProgress(ticket.receipt_id)
    if status == "prepared":
        # Fail closed on invalid stored data; do not silently rerun the model.
        restore_prepared(json.loads(payload))
        return ticket
    commit_attempted = False
    try:
        prepared = prepare(pinned)
        if (prepared.run.owner_id, prepared.run.department_id) != (scope.owner_id, scope.department_id):
            raise ValueError("Prepared task does not match reservation scope")
        payload = freeze_prepared(prepared)
        with Session(engine) as db:
            authorize(db)
            idempotency.mark_prepared(db, scope, key, ticket.token, payload)
            _record_prepare_attempt(db, ticket, attempt_id, "prepared")
            commit_attempted = True
            db.commit()
    except BaseException:
        # This is an observed attempt failure, not proof that a remote model did
        # no work. A process crash leaves its durable started event unmatched.
        # Do not include exception text, model response, request key or token.
        with Session(engine) as db:
            # A commit error may be a lost acknowledgement. Its durable prepared
            # fact is authoritative; an unconfirmed commit remains unknown.
            durable = db.scalar(select(AuditEvent.id).where(
                AuditEvent.action == "submission.prepare",
                AuditEvent.resource_id == ticket.receipt_id,
                AuditEvent.outcome == "prepared",
                AuditEvent.details_json == json.dumps({"attempt_id":attempt_id,
                    "operation":scope.operation.value}, ensure_ascii=False, sort_keys=True),
            )) if commit_attempted else None
            if durable is None:
                _record_prepare_attempt(db, ticket, attempt_id,
                                        "unknown" if commit_attempted else "failed")
                db.commit()
        raise
    return ticket


def _record_prepare_attempt(db, ticket, attempt_id, outcome):
    record_audit(db, action="submission.prepare", actor_id=ticket.scope.owner_id,
        department_id=ticket.scope.department_id, resource_type="submission",
        resource_id=ticket.receipt_id, outcome=outcome,
        details={"attempt_id":attempt_id, "operation":ticket.scope.operation.value})


def persist_submission(db, ticket, *, authorize, validate_prepared, load_bound, on_persist=None, replay_only=False):
    """Return the original or new Run; caller commits with its other business data.

    load_bound(db, kind, id) must enforce current resource read permission and
    scope. validate_prepared(db, prepared) rechecks mutable authorization/files.
    A savepoint prevents callers who catch an exception from committing a partial
    binding. It is not an independent transaction or commit.
    """
    from ...run_service import persist_run
    if db.get_bind().dialect.name == "sqlite":
        # sqlite3 legacy transaction mode does not BEGIN on reads/SAVEPOINT.
        # Releasing the first savepoint would otherwise commit the business data
        # before the caller's commit. Respect any already-active transaction.
        connection = db.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
    with db.begin_nested():
        authorize(db)
        row = idempotency.read(db, ticket.scope, ticket.key)
        if row is None or row.id != ticket.receipt_id:
            raise idempotency.ReservationLost("Submission receipt changed")
        if row.status == "bound":
            run = load_bound(db, row.execution_kind, row.execution_id)
            if on_persist is not None:
                on_persist(db, run)
            return run
        if replay_only:
            raise SubmissionRecoveryOnly(row.id)
        if row.status != "prepared" or row.reservation_token != ticket.token:
            raise idempotency.ReservationLost("Submission is not prepared by this holder")
        prepared = restore_prepared(json.loads(row.prepared_payload_json))
        if (prepared.run.owner_id, prepared.run.department_id) != (ticket.scope.owner_id, ticket.scope.department_id):
            raise ValueError("Stored task scope mismatch")
        validate_prepared(db, prepared)
        idempotency.bind(db, ticket.scope, ticket.key, ticket.token,
                         execution_kind="run", execution_id=prepared.run.id)
        run = persist_run(db, prepared)
        if on_persist is not None:
            on_persist(db, run)
        db.flush()
        return run
