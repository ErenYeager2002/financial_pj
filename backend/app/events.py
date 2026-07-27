from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from .models import RunEvent, RunRecord


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
    if commit:
        db.commit()
    return event
