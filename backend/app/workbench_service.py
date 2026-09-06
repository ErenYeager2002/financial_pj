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
from .file_service import serialize_files
from .models import FileRecord, TaskDiscoveryCheck, TaskReminder
from .registry import registry
from .resource_policy import owner_list_filter
from .runtime_health_service import runtime_health
from .task_center_service import task_center_overview, task_center_scope

def get_workbench(db: Session, user: UserContext) -> Workbench:
    overview = task_center_overview(db, user, limit=5)
    file_filter = owner_list_filter(FileRecord, user)
    counts = WorkbenchCounts(
        waiting_confirmation=overview.state_counts.pending,
        active=overview.state_counts.running,
        succeeded=overview.state_counts.succeeded,
        failed=overview.state_counts.failed,
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

    usage = {
        skill_id: (count, last_run_at)
        for skill_id, _skill_name, count, last_run_at in overview.skill_usage
    }
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
        pending_tasks=overview.pending_items,
        recent_tasks=overview.recent_items,
        task_scope=task_center_scope(user),
        runtime=runtime_health(db, user),
        recent_files=serialize_files(db, recent_files),
    )
