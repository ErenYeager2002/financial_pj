from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .auth import UserContext
from .contracts import StepDefinitionRead, WorkflowDefinitionRead
from .models import WorkflowDefinition


def list_workflow_definitions(
    db: Session, user: UserContext
) -> list[WorkflowDefinitionRead]:
    records = db.scalars(
        select(WorkflowDefinition)
        .options(selectinload(WorkflowDefinition.steps))
        .where(WorkflowDefinition.department_id == user.department_id)
        .order_by(WorkflowDefinition.updated_at.desc(), WorkflowDefinition.id.desc())
    ).all()
    return [
        WorkflowDefinitionRead(
            id=record.id,
            workflow_key=record.workflow_key,
            name=record.name,
            description=record.description,
            version=record.version,
            status=record.status,
            skill_id=record.skill_id,
            skill_version=record.skill_version,
            steps=[
                StepDefinitionRead(
                    id=step.id,
                    step_key=step.step_key,
                    name=step.name,
                    step_type=step.step_type,
                    position=step.position,
                    timeout_seconds=step.timeout_seconds,
                    max_attempts=step.max_attempts,
                    risk_level=step.risk_level,
                    worker_pool=step.worker_pool,
                    is_idempotent=step.is_idempotent,
                    retryable=step.retryable,
                )
                for step in sorted(record.steps, key=lambda item: item.position)
            ],
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        for record in records
    ]
