from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from .audit_service import record_audit
from .models import RunEvent, RunRecord
from .redaction import sanitize_value


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
    if commit:
        db.commit()
    return event
