"""Versioned immutable execution intent, separate from mutable task state/events."""
import hashlib
import json
from sqlalchemy import select
from ...models import RunExecutionSnapshot
from .preconditions import ExecutionInputChanged, assert_run_input_snapshot

VERSION = 1


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def execution_snapshot(run):
    parameters, files, manifest = (json.loads(getattr(run, field)) for field in
                                  ("parameters_json", "files_json", "manifest_snapshot"))
    if not all(isinstance(value, dict) for value in (parameters, files, manifest)) or not isinstance(run.message, str):
        raise ValueError("Invalid execution snapshot")
    value = {"version": VERSION, "run_id": run.id, "owner_id": run.owner_id,
             "department_id": run.department_id, "skill_id": run.skill_id,
             "skill_version": run.skill_version, "skill_hash": run.skill_hash, "skill_commit": run.skill_commit,
             "manifest_sha256": hashlib.sha256(_json(manifest).encode()).hexdigest(),
             "adapter": run.adapter, "worker_pool": run.worker_pool,
             "message_sha256": hashlib.sha256(run.message.encode()).hexdigest(),
             "parameters": parameters, "files": files,
             "confirmation_required": run.confirmation_required}
    encoded = _json(value)
    return encoded, hashlib.sha256(encoded.encode()).hexdigest()


def persist_execution_snapshot(db, run, *, source="created"):
    with db.no_autoflush:
        encoded, digest = execution_snapshot(run)
        existing = db.get(RunExecutionSnapshot, run.id, populate_existing=True)
    if existing is not None:
        if existing.schema_version != VERSION or existing.digest != digest or existing.snapshot_json != encoded:
            raise ValueError("Execution snapshot already differs")
        return existing
    record = RunExecutionSnapshot(run_id=run.id, schema_version=VERSION,
                                  digest=digest, snapshot_json=encoded, source=source)
    db.add(record)
    db.flush()
    return record


def assert_execution_snapshot(db, run, phase):
    """Caller holds the task/scheduler lock and owns any legacy recovery commit."""
    from .idempotency_models import IdempotencyRequest
    from .prepared_payload import restore_prepared
    # Expired ORM attributes may issue reads before explicit snapshot queries.
    with db.no_autoflush:
        try:
            encoded, digest = execution_snapshot(run)
            with db.no_autoflush:
                record = db.get(RunExecutionSnapshot, run.id, populate_existing=True)
            if record is None:
                with db.no_autoflush:
                    receipts = list(db.scalars(select(IdempotencyRequest).where(
                        IdempotencyRequest.execution_kind == "run", IdempotencyRequest.execution_id == run.id,
                        IdempotencyRequest.status == "bound", IdempotencyRequest.owner_id == run.owner_id,
                        IdempotencyRequest.department_id == run.department_id)))
                if len(receipts) != 1 or not receipts[0].prepared_payload_json:
                    raise ValueError("Missing original execution intent")
                original = restore_prepared(json.loads(receipts[0].prepared_payload_json)).run
                assert_run_input_snapshot(original, phase)
                assert_run_input_snapshot(run, phase)
                if original.input_hash != run.input_hash or execution_snapshot(original) != (encoded, digest):
                    raise ValueError("Original execution intent differs")
                record = persist_execution_snapshot(db, original, source="bound_submission")
            if record.schema_version != VERSION or record.digest != digest or record.snapshot_json != encoded:
                raise ValueError("Execution intent changed")
        except (ValueError, TypeError, AttributeError):
            raise ExecutionInputChanged(phase) from None
