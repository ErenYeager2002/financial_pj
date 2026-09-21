from __future__ import annotations

import json
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from .audit_service import record_audit
from .models import RunEvent, RunRecord
from .redaction import sanitize_value


def append_run_event(
    db: Session,
    run: RunRecord,
    *,
    event_type: str = "progress",
    state: str | None = None,
    progress: int | None = None,
    message: str = "",
    data: dict[str, Any] | None = None,
) -> RunEvent:
    """Append to the caller-owned transaction; never commit it."""
    if state is not None:
        run.state = state
    if progress is not None:
        run.progress = max(0, min(100, int(progress)))
    if message:
        run.progress_message = message
    event = RunEvent(
        run_id=run.id,
        event_type=event_type,
        state=state or run.state,
        progress=progress,
        message=message,
        data_json=json.dumps(data or {}, ensure_ascii=False),
    )
    db.add(event)
    db.add(run)
    if event_type == "state" and state in {"failed", "timed_out"}:
        record_audit(
            db,
            actor_id=run.owner_id,
            actor_role="system",
            department_id=run.department_id,
            action=f"run.execution.{state}",
            resource_type="run",
            resource_id=run.id,
            outcome="failed",
            details={
                "skill_id": run.skill_id,
                "attempt": run.attempt_count,
                "progress": run.progress,
                "error": sanitize_value((data or {}).get("error") or {"reason": message}),
            },
        )
    return event


def emit_event(
    db: Session,
    run: RunRecord,
    *,
    event_type: str = "progress",
    state: str | None = None,
    progress: int | None = None,
    message: str = "",
    data: dict[str, Any] | None = None,
    commit: bool = True,
) -> RunEvent:
    """Compatibility wrapper; migrate callers to explicit transaction ownership."""
    event = append_run_event(
        db, run, event_type=event_type, state=state, progress=progress,
        message=message, data=data,
    )
    if commit:
        db.commit()
    return event


def publish_run_progress(
    db: Session,
    run: RunRecord,
    *,
    event_type: str = "progress",
    state: str | None = None,
    progress: int | None = None,
    message: str = "",
    data: dict[str, Any] | None = None,
) -> None:
    """Publish fenced progress independently of unpublished execution results.

    Call before flushing execution writes: their fence holds this Run row lock.
    A conflicting parent write transaction is never committed or rolled back here;
    PostgreSQL instead raises after the bounded lock wait.
    """
    from .run_fencing import RunLeaseLost, assert_run_fence

    fence = db.info.get("ordinary_run_fence")
    run_state = inspect(run)
    if fence is None or run_state.identity != (fence[0],):
        raise RunLeaseLost("Progress requires the original execution fence")
    if state not in {None, "running", "waiting_user_action"}:
        raise ValueError("Terminal events belong to the execution transaction")
    fields = [name for name, present in (
        ("state", state is not None), ("progress", progress is not None),
        ("progress_message", bool(message)),
    ) if present]
    if any(run_state.attrs[name].history.has_changes() for name in fields):
        raise RuntimeError("Progress cannot replace pending caller state")
    bind = db.get_bind()
    with Session(bind=getattr(bind, "engine", bind), expire_on_commit=False) as progress_db:
        progress_db.info["ordinary_run_fence"] = fence
        if progress_db.get_bind().dialect.name == "postgresql":
            progress_db.execute(text("SET LOCAL lock_timeout = '5s'"))
        assert_run_fence(progress_db, lock=True)
        current = progress_db.get(RunRecord, fence[0])
        if current is None:
            raise RunLeaseLost("Task disappeared before progress publication")
        append_run_event(
            progress_db, current, event_type=event_type, state=state,
            progress=progress, message=message, data=data,
        )
        progress_db.commit()
        values = {name: getattr(current, name) for name in fields}
    # Mirror only independently committed progress, preserving all other pending work.
    for name, value in values.items():
        set_committed_value(run, name, value)
