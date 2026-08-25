from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import TaskReminder, WorkflowSession


def associate_reminder_with_workflow(db: Session, workflow: WorkflowSession) -> None:
    reminder = db.scalar(
        select(TaskReminder).where(
            TaskReminder.owner_id == workflow.owner_id,
            TaskReminder.department_id == workflow.department_id,
            TaskReminder.skill_id == workflow.skill_id,
            TaskReminder.business_date == workflow.reconciliation_date,
            TaskReminder.state.in_(("pending", "reopened")),
        )
    )
    if reminder is None:
        return
    reminder.state = "in_progress"
    reminder.workflow_id = workflow.id
    reminder.batch_id = workflow.batch_id


def sync_reminder_from_workflow(db: Session, workflow: WorkflowSession) -> None:
    reminder = db.scalar(
        select(TaskReminder).where(
            TaskReminder.owner_id == workflow.owner_id,
            TaskReminder.department_id == workflow.department_id,
            TaskReminder.skill_id == workflow.skill_id,
            TaskReminder.business_date == workflow.reconciliation_date,
        )
    )
    if reminder is None:
        return
    reminder.workflow_id = workflow.id
    reminder.batch_id = workflow.batch_id
    if workflow.state == "succeeded":
        reminder.state = "resolved"
        reminder.completed_at = datetime.now(UTC)
    elif workflow.state in {"failed", "cancelled"}:
        reminder.state = "pending"
        reminder.completed_at = None
