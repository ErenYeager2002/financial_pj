"""Short-transaction reservation primitives. The caller owns every commit.

Only trusted application code chooses operation/scope and supplies a fingerprint
computed using an existing row's pinned inputs when replaying. Authorization is
required before using these primitives or returning their execution reference.
"""
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
import json
import re
from uuid import uuid4
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from .canonical import CANONICAL_VERSION, validate_request_key
from .idempotency_models import IdempotencyRequest as Record


class Operation(str, Enum):
    RUN_CREATE = "run.create"
    RUN_RETRY = "run.retry"
    DRAFT_CONFIRM = "draft.confirm"
    WORKFLOW_START = "workflow.start"
    PI_COMMAND_SUBMIT = "pi.command.submit"


@dataclass(frozen=True)
class Scope:
    owner_id: str
    department_id: str
    operation: Operation

    def __post_init__(self):
        if not isinstance(self.operation, Operation):
            raise ValueError("Operation must be a server-defined enum")
        if not all(isinstance(v, str) and 0 < len(v) <= 128 for v in (self.owner_id, self.department_id)):
            raise ValueError("Invalid submission scope")


class IdempotencyConflict(RuntimeError):
    pass


class ReservationLost(RuntimeError):
    pass


def _clock(db):
    # PostgreSQL now() is transaction-start time, unsuitable after lock waits.
    return func.clock_timestamp() if db.get_bind().dialect.name == "postgresql" else func.current_timestamp()


def _scope(scope, key):
    validate_request_key(key)
    return (Record.owner_id == scope.owner_id, Record.department_id == scope.department_id,
            Record.operation == scope.operation.value, Record.request_key == key)


def read(db: Session, scope: Scope, key: str):
    return db.scalar(select(Record).where(*_scope(scope, key)).execution_options(populate_existing=True))


def reserve(db: Session, scope: Scope, key: str, *, fingerprint: str,
            pinned_revision: dict, lease_seconds: int = 120):
    """Return (record, acquired). No LLM or filesystem work inside this transaction."""
    validate_request_key(key)
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("Invalid request fingerprint")
    if not isinstance(lease_seconds, int) or not 1 <= lease_seconds <= 3600:
        raise ValueError("Invalid preparation lease")
    pinned = json.dumps(pinned_revision, ensure_ascii=False, sort_keys=True, allow_nan=False)
    dialect = db.get_bind().dialect.name
    insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}.get(dialect)
    if insert is None:
        raise ValueError("Unsupported reservation database")
    # Read server time, not the API host clock. Keep this transaction short.
    now = db.scalar(select(_clock(db)))
    token, rid = str(uuid4()), str(uuid4())
    values = dict(id=rid, owner_id=scope.owner_id, department_id=scope.department_id,
                  operation=scope.operation.value, request_key=key,
                  request_fingerprint=fingerprint, canonical_version=CANONICAL_VERSION,
                  status="preparing", reservation_token=token,
                  reservation_expires_at=now + timedelta(seconds=lease_seconds),
                  pinned_revision_json=pinned, response_version=1,
                  created_at=now, updated_at=now)
    inserted = db.execute(insert(Record).values(**values).on_conflict_do_nothing(
        index_elements=["owner_id", "department_id", "operation", "request_key"]
    ).returning(Record.id)).scalar_one_or_none()
    row = read(db, scope, key)
    if row.request_fingerprint != fingerprint or row.canonical_version != CANONICAL_VERSION:
        raise IdempotencyConflict("IDEMPOTENCY_CONFLICT")
    if inserted is not None:
        return row, True
    # Only expired preparation may be reclaimed. Frozen payload stays intact.
    now = db.scalar(select(_clock(db)))
    acquired = db.execute(update(Record).where(
        *_scope(scope, key), Record.status.in_(["preparing", "prepared"]),
        Record.reservation_expires_at <= _clock(db),
    ).values(reservation_token=token, reservation_expires_at=now + timedelta(seconds=lease_seconds),
             updated_at=_clock(db)).execution_options(synchronize_session=False)).rowcount == 1
    return read(db, scope, key), acquired


def _transition(db, scope, key, token, states, **values):
    result = db.execute(update(Record).where(
        *_scope(scope, key), Record.reservation_token == token,
        Record.status.in_(states), Record.reservation_expires_at > _clock(db),
    ).values(**values, updated_at=_clock(db)).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise ReservationLost("Preparation token expired, replaced or already finalized")
    return read(db, scope, key)


def mark_prepared(db, scope, key, token, payload: dict):
    return _transition(db, scope, key, token, ["preparing"], status="prepared",
                       prepared_payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False))


def bind(db, scope, key, token, *, execution_kind: str, execution_id: str):
    if execution_kind not in {"run", "workflow", "pi_command"} or not execution_id or len(execution_id) > 128:
        raise ValueError("Invalid execution reference")
    return _transition(db, scope, key, token, ["prepared"], status="bound",
                       execution_kind=execution_kind, execution_id=execution_id)


def reject(db, scope, key, token):
    return _transition(db, scope, key, token, ["preparing", "prepared"], status="rejected")
