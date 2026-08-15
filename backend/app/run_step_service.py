from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import UserContext
from .contracts import StepRunRead
from .models import StepDefinition, StepRun
from .redaction import sanitize_text, sanitize_value
from .run_service import get_run_or_404


def _summary(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return sanitize_value(parsed) if isinstance(parsed, dict) else {}


def list_run_steps(db: Session, run_id: str, user: UserContext) -> list[StepRunRead]:
    run = get_run_or_404(db, run_id, user)
    rows = db.execute(
        select(StepRun, StepDefinition)
        .join(StepDefinition, StepDefinition.id == StepRun.step_definition_id)
        .where(
            StepRun.run_id == run.id,
            StepRun.owner_id == run.owner_id,
            StepRun.department_id == run.department_id,
        )
        .order_by(StepDefinition.position.asc(), StepRun.created_at.asc())
    ).all()
    return [
        StepRunRead(
            id=step_run.id,
            step_key=definition.step_key,
            name=definition.name,
            step_type=definition.step_type,
            position=definition.position,
            state=step_run.state,
            attempt_count=step_run.attempt_count,
            can_retry=step_run.can_retry,
            retry_block_reason=sanitize_text(step_run.retry_block_reason),
            input_summary=_summary(step_run.input_summary_json),
            output_summary=_summary(step_run.output_summary_json),
            error_code=step_run.error_code[:64],
            error_message=sanitize_text(
                step_run.error_message,
                error=True,
                hidden_message="步骤执行失败，技术详情已隐藏。",
            ),
            created_at=step_run.created_at,
            queued_at=step_run.queued_at,
            started_at=step_run.started_at,
            finished_at=step_run.finished_at,
        )
        for step_run, definition in rows
    ]
