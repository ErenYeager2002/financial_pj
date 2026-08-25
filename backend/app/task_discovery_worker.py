from __future__ import annotations

import json
import signal
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import SessionLocal, init_db
from .feature_control_service import task_discovery_enabled
from .models import TaskDiscoveryCheck, TaskReminderSubscription
from .registry import registry
from .scheduler import acquire_claim_lock, active_or_queued_workflow_count
from .settings import settings
from .task_discovery import (
    TaskDiscoveryProbe,
    execute_task_discovery,
    next_automatic_retry_at,
)
from .task_discovery_schedule import scheduled_business_dates
from .zhiyun_task_probe import probe_zhiyun_tasks

STOP = False
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _stop(*_: object) -> None:
    global STOP
    STOP = True


def _holidays() -> set[date]:
    result: set[date] = set()
    for value in settings.task_discovery_holidays:
        try:
            result.add(date.fromisoformat(value))
        except ValueError:
            continue
    return result


def _local_day_start_utc(now: datetime) -> datetime:
    local = now.astimezone(SHANGHAI)
    return datetime.combine(local.date(), clock_time.min, tzinfo=SHANGHAI).astimezone(UTC)


def _retry_due(db: Session, now: datetime) -> TaskDiscoveryCheck | None:
    return db.scalar(
        select(TaskDiscoveryCheck)
        .where(
            TaskDiscoveryCheck.state == "failed",
            TaskDiscoveryCheck.next_retry_at.is_not(None),
            TaskDiscoveryCheck.next_retry_at <= now,
        )
        .order_by(TaskDiscoveryCheck.next_retry_at.asc())
        .limit(1)
    )


def _queued(db: Session) -> TaskDiscoveryCheck | None:
    return db.scalar(
        select(TaskDiscoveryCheck)
        .where(TaskDiscoveryCheck.state == "queued")
        .order_by(TaskDiscoveryCheck.created_at.asc())
        .limit(1)
    )


def _recover_expired_checks(db: Session, now: datetime) -> None:
    expired = list(
        db.scalars(
            select(TaskDiscoveryCheck).where(
                TaskDiscoveryCheck.state == "running",
                TaskDiscoveryCheck.lease_expires_at.is_not(None),
                TaskDiscoveryCheck.lease_expires_at < now,
            )
        ).all()
    )
    for check in expired:
        check.state = "failed"
        check.error_message = "任务检查 Worker 中断，未取得完整结果。"
        check.finished_at = now
        check.worker_id = ""
        check.lease_expires_at = None
        check.next_retry_at = next_automatic_retry_at(now, check.trigger)


def _already_checked_today(
    db: Session,
    subscription_id: str,
    business_dates_json: str,
    now: datetime,
) -> bool:
    return (
        db.scalar(
            select(TaskDiscoveryCheck.id)
            .where(
                TaskDiscoveryCheck.subscription_id == subscription_id,
                TaskDiscoveryCheck.business_dates_json == business_dates_json,
                TaskDiscoveryCheck.created_at >= _local_day_start_utc(now),
            )
            .limit(1)
        )
        is not None
    )


def run_discovery_tick(
    db: Session,
    *,
    probe: TaskDiscoveryProbe = probe_zhiyun_tasks,
    now: datetime | None = None,
) -> bool:
    if probe is probe_zhiyun_tasks and not task_discovery_enabled(db):
        return False
    current = now or datetime.now(UTC)
    acquire_claim_lock(db)
    _recover_expired_checks(db, current)

    queued = _queued(db)
    if queued is not None and active_or_queued_workflow_count(db, queued.skill_id) == 0:
        queued.worker_id = "task-discovery"
        queued.lease_expires_at = current + timedelta(minutes=15)
        dates = tuple(json.loads(queued.business_dates_json or "[]"))
        try:
            execute_task_discovery(
                db,
                skill_id=queued.skill_id,
                department_id=queued.department_id,
                business_dates=dates,
                trigger=queued.trigger,
                probe=probe,
                now=current,
                check=queued,
            )
        except Exception:
            return True
        return True

    retry = _retry_due(db, current)
    if retry is not None and active_or_queued_workflow_count(db, retry.skill_id) == 0:
        retry.worker_id = "task-discovery"
        retry.lease_expires_at = current + timedelta(minutes=15)
        dates = tuple(json.loads(retry.business_dates_json or "[]"))
        department_id = retry.department_id
        skill_id = retry.skill_id
        try:
            execute_task_discovery(
                db,
                skill_id=skill_id,
                department_id=department_id,
                business_dates=dates,
                trigger="retry",
                probe=probe,
                now=current,
                check=retry,
            )
        except Exception:
            return True
        return True

    subscriptions = list(
        db.scalars(
            select(TaskReminderSubscription).where(
                TaskReminderSubscription.enabled.is_(True)
            )
        ).all()
    )
    selected: tuple[str, str, tuple[str, ...]] | None = None
    local_now = current.astimezone(SHANGHAI)
    holidays = _holidays()
    for subscription in subscriptions:
        if active_or_queued_workflow_count(db, subscription.skill_id) > 0:
            continue
        dates = scheduled_business_dates(
            subscription.last_successful_business_date,
            local_now,
            holidays=holidays,
        )
        dates_json = json.dumps(list(dates), ensure_ascii=False)
        if dates and not _already_checked_today(db, subscription.id, dates_json, current):
            selected = (subscription.skill_id, subscription.department_id, dates)
            break
    if selected is None:
        db.commit()
        return False
    try:
        execute_task_discovery(
            db,
            skill_id=selected[0],
            department_id=selected[1],
            business_dates=selected[2],
            trigger="scheduled",
            probe=probe,
            now=current,
        )
    except Exception:
        return True
    return True


def main() -> int:
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    init_db()
    registry.refresh()
    while not STOP:
        with SessionLocal() as db:
            run_discovery_tick(db)
        time.sleep(max(1.0, settings.queue_poll_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
