from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit_service import record_audit
from .models import TaskDiscoveryCheck, TaskReminder, TaskReminderSubscription
from .redaction import sanitize_text
from .service_credential_service import resolve_service_credential
from .task_discovery_schedule import automatic_retry_times


@dataclass(frozen=True)
class TaskDiscoveryDayResult:
    business_date: str
    record_count: int
    fingerprint: str


TaskDiscoveryProbe = Callable[
    [str, str, tuple[str, ...]],
    list[TaskDiscoveryDayResult],
]

SHANGHAI = ZoneInfo("Asia/Shanghai")


def next_automatic_retry_at(checked_at: datetime, trigger: str) -> datetime | None:
    if trigger not in {"scheduled", "retry"}:
        return None
    local_now = checked_at.astimezone(SHANGHAI)
    for candidate in automatic_retry_times(local_now.date()):
        localized = candidate.replace(tzinfo=SHANGHAI)
        if localized > local_now:
            return localized.astimezone(UTC)
    return None


def _attempt_count(
    db: Session,
    subscription_id: str,
    business_dates_json: str,
    trigger: str,
) -> int:
    if trigger not in {"scheduled", "retry"}:
        return 1
    previous = db.scalar(
        select(TaskDiscoveryCheck.attempt_count)
        .where(
            TaskDiscoveryCheck.subscription_id == subscription_id,
            TaskDiscoveryCheck.business_dates_json == business_dates_json,
            TaskDiscoveryCheck.state == "failed",
            TaskDiscoveryCheck.trigger.in_(("scheduled", "retry")),
        )
        .order_by(TaskDiscoveryCheck.created_at.desc())
        .limit(1)
    )
    return int(previous or 0) + 1


def _subscription(
    db: Session,
    department_id: str,
    skill_id: str,
) -> TaskReminderSubscription:
    subscription = db.scalar(
        select(TaskReminderSubscription).where(
            TaskReminderSubscription.department_id == department_id,
            TaskReminderSubscription.skill_id == skill_id,
            TaskReminderSubscription.enabled.is_(True),
        )
    )
    if subscription is None:
        raise RuntimeError("任务提醒尚未配置负责人或已经停用。")
    return subscription


def _validate_results(
    business_dates: tuple[str, ...],
    results: list[TaskDiscoveryDayResult],
) -> None:
    expected = list(business_dates)
    actual = [item.business_date for item in results]
    if actual != expected:
        raise RuntimeError("任务发现结果日期与请求日期不一致。")
    if any(item.record_count < 0 for item in results):
        raise RuntimeError("任务发现结果数量无效。")


def _upsert_reminder(
    db: Session,
    subscription: TaskReminderSubscription,
    result: TaskDiscoveryDayResult,
    now: datetime,
) -> None:
    reminder = db.scalar(
        select(TaskReminder).where(
            TaskReminder.department_id == subscription.department_id,
            TaskReminder.skill_id == subscription.skill_id,
            TaskReminder.business_date == result.business_date,
        )
    )
    if result.record_count == 0:
        if reminder is not None and reminder.state in {"pending", "reopened"}:
            reminder.state = "no_records"
            reminder.completed_at = None
            reminder.last_checked_at = now
            reminder.record_count = 0
            reminder.fingerprint = result.fingerprint
        return
    if reminder is None:
        db.add(
            TaskReminder(
                id=str(uuid.uuid4()),
                owner_id=subscription.owner_id,
                department_id=subscription.department_id,
                skill_id=subscription.skill_id,
                business_date=result.business_date,
                record_count=result.record_count,
                fingerprint=result.fingerprint,
                state="pending",
                first_discovered_at=now,
                last_checked_at=now,
            )
        )
        return
    changed_after_completion = reminder.state == "resolved" and (
        reminder.record_count != result.record_count or reminder.fingerprint != result.fingerprint
    )
    reminder.record_count = result.record_count
    reminder.fingerprint = result.fingerprint
    reminder.last_checked_at = now
    if changed_after_completion:
        reminder.owner_id = subscription.owner_id
        reminder.workflow_id = None
        reminder.batch_id = None
        reminder.state = "reopened"
        reminder.completed_at = None
    elif reminder.state == "no_records":
        reminder.owner_id = subscription.owner_id
        reminder.workflow_id = None
        reminder.batch_id = None
        reminder.state = "pending"
        reminder.completed_at = None
    elif reminder.workflow_id is None and reminder.batch_id is None:
        reminder.owner_id = subscription.owner_id


def execute_task_discovery(
    db: Session,
    *,
    skill_id: str,
    department_id: str,
    business_dates: tuple[str, ...],
    trigger: str,
    probe: TaskDiscoveryProbe,
    now: datetime | None = None,
    check: TaskDiscoveryCheck | None = None,
) -> TaskDiscoveryCheck:
    if not business_dates:
        raise ValueError("任务发现至少需要一个业务日期。")
    checked_at = now or datetime.now(UTC)
    subscription = _subscription(db, department_id, skill_id)
    business_dates_json = json.dumps(list(business_dates), ensure_ascii=False)
    if check is None:
        check = TaskDiscoveryCheck(
            id=str(uuid.uuid4()),
            subscription_id=subscription.id,
            owner_id=subscription.owner_id,
            department_id=subscription.department_id,
            skill_id=subscription.skill_id,
            trigger=trigger,
            business_dates_json=business_dates_json,
            state="running",
            attempt_count=_attempt_count(
                db,
                subscription.id,
                business_dates_json,
                trigger,
            ),
            started_at=checked_at,
            created_at=checked_at,
            worker_id="task-discovery",
            lease_expires_at=checked_at + timedelta(minutes=15),
        )
        db.add(check)
    else:
        if (
            check.subscription_id != subscription.id
            or check.business_dates_json != business_dates_json
        ):
            raise RuntimeError("任务检查队列记录与执行请求不一致。")
        check.owner_id = subscription.owner_id
        check.state = "running"
        check.attempt_count += 1
        check.error_message = ""
        check.next_retry_at = None
        check.started_at = checked_at
        check.finished_at = None
    db.commit()
    check_id = check.id
    subscription_id = subscription.id
    account = ""
    password = ""
    try:
        account, password = resolve_service_credential(
            db,
            subscription.owner_id,
            subscription.department_id,
            "zhiyun",
        )
        results = probe(account, password, business_dates)
        _validate_results(business_dates, results)
        for result in results:
            _upsert_reminder(db, subscription, result, checked_at)
        check.state = "succeeded"
        check.finished_at = checked_at
        check.worker_id = ""
        check.lease_expires_at = None
        subscription.last_check_status = "succeeded"
        subscription.last_checked_at = checked_at
        subscription.last_successful_business_date = max(business_dates)
        record_audit(
            db,
            actor_id=subscription.owner_id,
            actor_role="system",
            department_id=subscription.department_id,
            action="task_reminder.discovery.succeeded",
            resource_type="task_discovery_check",
            resource_id=check.id,
            details={
                "skill_id": skill_id,
                "business_dates": list(business_dates),
                "reminder_dates": [
                    item.business_date for item in results if item.record_count > 0
                ],
            },
        )
        db.commit()
        db.refresh(check)
        return check
    except Exception as exc:
        db.rollback()
        check = db.get(TaskDiscoveryCheck, check_id)
        subscription = db.get(TaskReminderSubscription, subscription_id)
        if check is None or subscription is None:
            raise
        safe_error = sanitize_text(str(exc), error=True)
        check.state = "failed"
        check.error_message = safe_error
        check.finished_at = checked_at
        check.next_retry_at = next_automatic_retry_at(checked_at, trigger)
        check.worker_id = ""
        check.lease_expires_at = None
        subscription.last_check_status = "failed"
        subscription.last_checked_at = checked_at
        record_audit(
            db,
            actor_id=subscription.owner_id,
            actor_role="system",
            department_id=subscription.department_id,
            action="task_reminder.discovery.failed",
            resource_type="task_discovery_check",
            resource_id=check.id,
            outcome="failed",
            details={"skill_id": skill_id, "business_dates": list(business_dates)},
        )
        db.commit()
        raise
    finally:
        account = ""
        password = ""
