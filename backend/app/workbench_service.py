from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import UserContext
from .authorization import allowed_skill_ids
from .contracts import (
    SkillSummary,
    Workbench,
    WorkbenchCounts,
    WorkbenchSkillUsage,
    WorkbenchTaskReminderSummary,
)
from .file_service import serialize_file
from .models import FileRecord, RunRecord, TaskDiscoveryCheck, TaskReminder
from .registry import registry
from .resource_policy import owner_list_filter
from .run_service import retry_status, serialize_run

ACTIVE_STATES = {"created", "parsing", "queued", "running", "cancelling"}
FAILED_STATES = {"failed", "timed_out"}


def _run_summary(db: Session, record: RunRecord, user: UserContext):
    can_retry, reason = retry_status(db, record, user)
    return serialize_run(record, can_retry=can_retry, retry_block_reason=reason)


def get_workbench(db: Session, user: UserContext) -> Workbench:
    run_filter = owner_list_filter(RunRecord, user)
    file_filter = owner_list_filter(FileRecord, user)
    state_counts = {
        state: int(count)
        for state, count in db.execute(
            select(RunRecord.state, func.count())
            .where(run_filter)
            .group_by(RunRecord.state)
        ).all()
    }
    counts = WorkbenchCounts(
        waiting_confirmation=state_counts.get("waiting_confirmation", 0),
        active=sum(state_counts.get(state, 0) for state in ACTIVE_STATES),
        succeeded=state_counts.get("succeeded", 0),
        failed=sum(state_counts.get(state, 0) for state in FAILED_STATES),
        files=int(
            db.scalar(select(func.count()).select_from(FileRecord).where(file_filter)) or 0
        ),
    )
    reminder_filters = [
        TaskReminder.department_id == user.department_id,
        TaskReminder.state.in_(("pending", "in_progress", "reopened")),
    ]
    failure_filters = [
        TaskDiscoveryCheck.department_id == user.department_id,
        TaskDiscoveryCheck.state == "failed",
        TaskDiscoveryCheck.next_retry_at.is_(None),
    ]
    if not user.is_admin:
        reminder_filters.append(TaskReminder.owner_id == user.user_id)
        failure_filters.append(TaskDiscoveryCheck.owner_id == user.user_id)
    task_reminders = WorkbenchTaskReminderSummary(
        pending_dates=int(
            db.scalar(select(func.count(TaskReminder.id)).where(*reminder_filters)) or 0
        ),
        active_skills=int(
            db.scalar(
                select(func.count(func.distinct(TaskReminder.skill_id))).where(
                    *reminder_filters
                )
            )
            or 0
        ),
        failed_checks=int(
            db.scalar(select(func.count(TaskDiscoveryCheck.id)).where(*failure_filters)) or 0
        ),
    )

    usage_rows = db.execute(
        select(RunRecord.skill_id, func.count(), func.max(RunRecord.created_at))
        .where(run_filter)
        .group_by(RunRecord.skill_id)
    ).all()
    usage = {skill_id: (int(count), last_run_at) for skill_id, count, last_run_at in usage_rows}
    allowed = allowed_skill_ids(db, user)
    available = [
        item
        for item in registry.list(include_disabled=False)
        if user.is_admin or item.manifest.id in allowed
    ]
    available.sort(
        key=lambda item: (
            -(usage.get(item.manifest.id, (0, None))[0]),
            not bool(item.manifest.ui and item.manifest.ui.popular),
            item.manifest.name,
        )
    )
    common_skills = [
        WorkbenchSkillUsage(
            skill=SkillSummary.model_validate(item.employee_dict(include_schema=False)),
            run_count=usage.get(item.manifest.id, (0, None))[0],
            last_run_at=usage.get(item.manifest.id, (0, None))[1],
        )
        for item in available[:5]
    ]

    pending = db.scalars(
        select(RunRecord)
        .where(
            run_filter,
            RunRecord.state.in_(("waiting_confirmation", "failed", "timed_out")),
        )
        .order_by(RunRecord.created_at.desc())
        .limit(5)
    ).all()
    recent_results = db.scalars(
        select(RunRecord)
        .where(run_filter, RunRecord.state == "succeeded")
        .order_by(RunRecord.finished_at.desc(), RunRecord.created_at.desc())
        .limit(5)
    ).all()
    recent_files = db.scalars(
        select(FileRecord)
        .where(file_filter)
        .order_by(FileRecord.created_at.desc())
        .limit(5)
    ).all()
    return Workbench(
        counts=counts,
        task_reminders=task_reminders,
        common_skills=common_skills,
        pending_runs=[_run_summary(db, item, user) for item in pending],
        recent_results=[_run_summary(db, item, user) for item in recent_results],
        recent_files=[serialize_file(db, item) for item in recent_files],
    )
