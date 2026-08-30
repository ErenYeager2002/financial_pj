from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .models import TaskReminder, WorkflowSession

ACTIVE_REMINDER_STATES = ("pending", "in_progress", "reopened")


def _apply_workflow_state(reminder: TaskReminder, workflow: WorkflowSession) -> None:
    reminder.workflow_id = workflow.id
    reminder.batch_id = workflow.batch_id
    if workflow.state == "succeeded":
        reminder.state = "resolved"
        reminder.completed_at = datetime.now(UTC)
    elif workflow.state in {"failed", "cancelled"}:
        reminder.state = "pending"
        reminder.completed_at = None


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
    _apply_workflow_state(reminder, workflow)


def reconcile_linked_task_reminders(
    db: Session,
    *,
    department_id: str,
    owner_id: str | None = None,
) -> int:
    query = (
        select(TaskReminder, WorkflowSession)
        .join(WorkflowSession, TaskReminder.workflow_id == WorkflowSession.id)
        .where(
            TaskReminder.department_id == department_id,
            or_(
                and_(
                    TaskReminder.state.in_(ACTIVE_REMINDER_STATES),
                    WorkflowSession.state == "succeeded",
                ),
                and_(
                    TaskReminder.state == "in_progress",
                    WorkflowSession.state.in_(("failed", "cancelled")),
                ),
            ),
        )
    )
    if owner_id is not None:
        query = query.where(TaskReminder.owner_id == owner_id)
    rows = list(db.execute(query).all())
    for reminder, workflow in rows:
        _apply_workflow_state(reminder, workflow)
    return len(rows)


def restore_unfinished_batch_reminders(db: Session, batch_id: str) -> int:
    succeeded_dates = set(
        db.scalars(
            select(WorkflowSession.reconciliation_date).where(
                WorkflowSession.batch_id == batch_id,
                WorkflowSession.state == "succeeded",
            )
        ).all()
    )
    reminders = list(
        db.scalars(
            select(TaskReminder).where(
                TaskReminder.batch_id == batch_id,
                TaskReminder.state == "in_progress",
            )
        ).all()
    )
    restored = 0
    for reminder in reminders:
        if reminder.business_date in succeeded_dates:
            continue
        succeeded_workflow = db.scalar(
            select(WorkflowSession)
            .where(
                WorkflowSession.owner_id == reminder.owner_id,
                WorkflowSession.department_id == reminder.department_id,
                WorkflowSession.skill_id == reminder.skill_id,
                WorkflowSession.reconciliation_date == reminder.business_date,
                WorkflowSession.state == "succeeded",
                WorkflowSession.updated_at >= reminder.last_checked_at,
            )
            .order_by(WorkflowSession.updated_at.desc())
            .limit(1)
        )
        if succeeded_workflow is not None:
            _apply_workflow_state(reminder, succeeded_workflow)
            continue
        reminder.state = "pending"
        reminder.completed_at = None
        restored += 1
    return restored
