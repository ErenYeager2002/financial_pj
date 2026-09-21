"""Application-owned compatibility policy; never discovers compatibility from head."""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .schema_check import SchemaCompatibility, SchemaCompatibilityError, check_schema_compatible

# Add a future additive revision only after validating both application versions.
# Contract revisions require a separate rollout; unknown heads are not accepted.
SUPPORTED_REVISIONS = frozenset({"f4b5c6d7e8f9"})
REQUIRED_TABLES = frozenset({
    "run_execution_snapshots", "scheduler_locks", "assistant_turns", "runs", "files", "idempotency_requests",
    "workflow_sessions", "workflow_batches", "workflow_actions", "task_drafts",
})

# PR-03 models require the additive Native columns and submission table.
# Prior application images retain their own explicit compatibility policy.
REQUIRED_COLUMNS = {
    "run_execution_snapshots": frozenset({"run_id", "schema_version", "digest", "snapshot_json", "source", "created_at"}),
    "task_drafts": frozenset({"content_revision"}),
    "idempotency_requests": frozenset({"id", "owner_id", "department_id", "operation", "request_key", "request_fingerprint", "canonical_version", "status", "reservation_token", "reservation_expires_at", "pinned_revision_json", "prepared_payload_json", "execution_kind", "execution_id", "response_version", "created_at", "updated_at"}),
    "runs": frozenset({"source_session_key", "source_command_id", "concurrency_limit", "worker_id", "attempt_count", "heartbeat_at", "lease_expires_at"}),
    "workflow_sessions": frozenset({"concurrency_limit", "execution_mode", "batch_id", "batch_sequence", "previous_workflow_id"}),
    "workflow_batches": frozenset({"execution_mode"}),
    "workflow_actions": frozenset({"worker_id", "attempt_count", "heartbeat_at", "lease_expires_at"}),
}


def check_runtime_database(engine: Engine) -> SchemaCompatibility:
    """Read schema and required seed state; no migration, stamp, or seed fallback."""
    with engine.connect() as connection:
        status = check_schema_compatible(
            connection,
            supported_revisions=SUPPORTED_REVISIONS,
            required_tables=REQUIRED_TABLES,
        )
        inspector = inspect(connection)
        for table, required in REQUIRED_COLUMNS.items():
            actual = {column["name"] for column in inspector.get_columns(table)}
            if not required.issubset(actual):
                raise SchemaCompatibilityError("DATABASE_REQUIRED_COLUMNS_MISSING")
        if connection.scalar(text("SELECT name FROM scheduler_locks WHERE name='global'")) is None:
            raise SchemaCompatibilityError("DATABASE_REQUIRED_SEED_MISSING")
        return status
