from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .audit_service import record_audit
from .auth import UserContext
from .auth_models import User
from .authorization import refresh_active_user
from .models import TaskDiscoveryCheck, TaskReminder, TaskReminderSubscription
from .registry import registry
from .redaction import sanitize_text
from .scheduler import acquire_claim_lock
from .schemas import ServiceCredentialRead
from .service_credential_service import (
    get_service_credential_status,
    remove_service_credential,
    save_service_credential,
)
from .task_reminder_contracts import (
    TaskDiscoveryCheckQueued,
    TaskDiscoveryCheckRequest,
    TaskDiscoveryFailureRead,
    TaskReminderBoard,
    TaskReminderCleanupResult,
    TaskReminderRead,
    TaskReminderSubscriptionRead,
    TaskReminderSubscriptionWrite,
)
from .task_reminder_workflow_service import reconcile_linked_task_reminders
from .task_errors import classify_task_error

SUPPORTED_REMINDER_SKILLS = {"ar-hexiao-daily"}
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _skill_name(skill_id: str) -> str:
    if skill_id not in SUPPORTED_REMINDER_SKILLS:
        raise HTTPException(status_code=404, detail="该 Skill 尚未支持任务提醒。")
    item = registry.get(skill_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Skill 不存在或尚未发布。")
    return item.manifest.name


def _department_owner(db: Session, actor: UserContext, owner_id: str) -> User:
    owner = db.scalar(
        select(User).where(
            User.id == owner_id,
            User.department_id == actor.department_id,
            User.status == "active",
        )
        .execution_options(populate_existing=True)
    )
    if owner is None:
        raise HTTPException(status_code=404, detail="负责人不存在、已禁用或不属于当前部门。")
    return owner


def _subscription(
    db: Session,
    department_id: str,
    skill_id: str,
) -> TaskReminderSubscription | None:
    return db.scalar(
        select(TaskReminderSubscription).where(
            TaskReminderSubscription.department_id == department_id,
            TaskReminderSubscription.skill_id == skill_id,
        )
        .execution_options(populate_existing=True)
    )


def _subscription_owner_context(
    db: Session,
    actor: UserContext,
    skill_id: str,
) -> UserContext:
    subscription = _subscription(db, actor.department_id, skill_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="尚未配置该 Skill 的任务提醒负责人。")
    owner = _department_owner(db, actor, subscription.owner_id)
    return UserContext(
        user_id=owner.id,
        display_name=owner.display_name,
        role=owner.role,
        department_id=owner.department_id,
    )


def get_subscription_owner_credential(
    db: Session,
    actor: UserContext,
    skill_id: str,
) -> ServiceCredentialRead:
    _skill_name(skill_id)
    owner = _subscription_owner_context(db, actor, skill_id)
    return get_service_credential_status(db, owner, "zhiyun")


def save_subscription_owner_credential(
    db: Session,
    actor: UserContext,
    skill_id: str,
    account: str,
    password: str,
) -> ServiceCredentialRead:
    _skill_name(skill_id)
    owner = _subscription_owner_context(db, actor, skill_id)
    result = save_service_credential(db, owner, "zhiyun", account, password)
    record_audit(
        db,
        actor=actor,
        action="task_reminder.owner_credential.update",
        resource_type="user",
        resource_id=owner.user_id,
        details={"skill_id": skill_id, "service": "zhiyun"},
    )
    db.commit()
    return result


def remove_subscription_owner_credential(
    db: Session,
    actor: UserContext,
    skill_id: str,
) -> None:
    _skill_name(skill_id)
    owner = _subscription_owner_context(db, actor, skill_id)
    remove_service_credential(db, owner, "zhiyun")
    record_audit(
        db,
        actor=actor,
        action="task_reminder.owner_credential.delete",
        resource_type="user",
        resource_id=owner.user_id,
        details={"skill_id": skill_id, "service": "zhiyun"},
    )
    db.commit()


def _read(
    db: Session,
    subscription: TaskReminderSubscription,
) -> TaskReminderSubscriptionRead:
    owner = db.get(User, subscription.owner_id)
    if owner is None:
        raise HTTPException(status_code=409, detail="任务提醒负责人已经不存在。")
    return TaskReminderSubscriptionRead(
        skill_id=subscription.skill_id,
        skill_name=_skill_name(subscription.skill_id),
        owner_id=subscription.owner_id,
        owner_name=owner.display_name,
        enabled=subscription.enabled,
        timezone=subscription.timezone,
        schedule_time=subscription.schedule_time,
        last_successful_business_date=subscription.last_successful_business_date,
        last_check_status=subscription.last_check_status,
        last_checked_at=subscription.last_checked_at,
    )


def get_subscription(
    db: Session,
    actor: UserContext,
    skill_id: str,
) -> TaskReminderSubscriptionRead:
    _skill_name(skill_id)
    subscription = _subscription(db, actor.department_id, skill_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="尚未配置该 Skill 的任务提醒负责人。")
    return _read(db, subscription)


def save_subscription(
    db: Session,
    actor: UserContext,
    skill_id: str,
    body: TaskReminderSubscriptionWrite,
) -> TaskReminderSubscriptionRead:
    _skill_name(skill_id)
    acquire_claim_lock(db)
    actor = refresh_active_user(db, actor)
    if not actor.is_admin:
        raise HTTPException(status_code=403, detail="只有管理员可以设置任务提醒负责人。")
    owner = _department_owner(db, actor, body.owner_id)
    subscription = _subscription(db, actor.department_id, skill_id)
    previous_owner_id = subscription.owner_id if subscription else ""
    if subscription is None:
        subscription = TaskReminderSubscription(
            id=str(uuid.uuid4()),
            department_id=actor.department_id,
            skill_id=skill_id,
            owner_id=owner.id,
        )
        db.add(subscription)
    subscription.owner_id = owner.id
    subscription.enabled = body.enabled
    if previous_owner_id and previous_owner_id != owner.id:
        transferable = list(
            db.scalars(
                select(TaskReminder).where(
                    TaskReminder.department_id == actor.department_id,
                    TaskReminder.skill_id == skill_id,
                    TaskReminder.owner_id == previous_owner_id,
                    TaskReminder.state.in_(("pending", "reopened")),
                    TaskReminder.workflow_id.is_(None),
                    TaskReminder.batch_id.is_(None),
                )
            ).all()
        )
        for reminder in transferable:
            reminder.owner_id = owner.id
        pending_checks = list(
            db.scalars(
                select(TaskDiscoveryCheck).where(
                    TaskDiscoveryCheck.subscription_id == subscription.id,
                    TaskDiscoveryCheck.state.in_(("queued", "failed")),
                )
            ).all()
        )
        for check in pending_checks:
            check.owner_id = owner.id
    record_audit(
        db,
        actor=actor,
        action="task_reminder.subscription.update",
        resource_type="task_reminder_subscription",
        resource_id=subscription.id,
        details={
            "skill_id": skill_id,
            "owner_changed": previous_owner_id != owner.id,
            "enabled": body.enabled,
        },
    )
    db.commit()
    db.refresh(subscription)
    saved = _read(db, subscription)
    if body.enabled and previous_owner_id != owner.id:
        local_today = datetime.now(SHANGHAI).date()
        day_count = 3 if local_today.weekday() == 0 else 1
        immediate_dates = [
            (local_today - timedelta(days=offset)).isoformat()
            for offset in range(day_count, 0, -1)
        ]
        enqueue_task_discovery(
            db,
            actor,
            TaskDiscoveryCheckRequest(
                skill_id=skill_id,
                business_dates=immediate_dates,
            ),
        )
    return saved


def _validated_business_dates(values: list[str]) -> tuple[str, ...]:
    today = datetime.now(SHANGHAI).date()
    lower_bound = today - timedelta(days=31)
    result: list[str] = []
    try:
        parsed = [date.fromisoformat(value) for value in values]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="检查日期格式无效。") from exc
    if len(set(parsed)) != len(parsed):
        raise HTTPException(status_code=422, detail="检查日期不能重复。")
    if any(item >= today or item < lower_bound for item in parsed):
        raise HTTPException(status_code=422, detail="只能检查昨天起向前 31 天内的日期。")
    result.extend(item.isoformat() for item in sorted(parsed))
    return tuple(result)


def enqueue_task_discovery(
    db: Session,
    actor: UserContext,
    body: TaskDiscoveryCheckRequest,
) -> TaskDiscoveryCheckQueued:
    _skill_name(body.skill_id)
    acquire_claim_lock(db)
    actor = refresh_active_user(db, actor)
    subscription = _subscription(db, actor.department_id, body.skill_id)
    if subscription is None or not subscription.enabled:
        raise HTTPException(status_code=409, detail="该 Skill 尚未启用任务提醒。")
    if not actor.is_admin and subscription.owner_id != actor.user_id:
        raise HTTPException(status_code=403, detail="只有当前负责人或管理员可以发起检查。")
    _department_owner(db, actor, subscription.owner_id)
    dates = _validated_business_dates(body.business_dates)
    dates_json = json.dumps(list(dates), ensure_ascii=False)
    existing = db.scalar(
        select(TaskDiscoveryCheck).where(
            TaskDiscoveryCheck.subscription_id == subscription.id,
            TaskDiscoveryCheck.business_dates_json == dates_json,
            TaskDiscoveryCheck.state.in_(("queued", "running")),
        )
    )
    if existing is None:
        existing = TaskDiscoveryCheck(
            id=str(uuid.uuid4()),
            subscription_id=subscription.id,
            owner_id=subscription.owner_id,
            department_id=subscription.department_id,
            skill_id=subscription.skill_id,
            trigger="manual",
            business_dates_json=dates_json,
            state="queued",
            attempt_count=0,
            started_at=datetime.now(UTC),
        )
        db.add(existing)
        record_audit(
            db,
            actor=actor,
            action="task_reminder.discovery.queued",
            resource_type="task_discovery_check",
            resource_id=existing.id,
            details={"skill_id": body.skill_id, "business_dates": list(dates)},
        )
        db.commit()
        db.refresh(existing)
    return TaskDiscoveryCheckQueued(
        id=existing.id,
        state=existing.state,
        business_dates=list(dates),
    )


def retry_task_discovery(
    db: Session,
    actor: UserContext,
    check_id: str,
) -> TaskDiscoveryCheckQueued:
    acquire_claim_lock(db)
    actor = refresh_active_user(db, actor)
    check = db.get(TaskDiscoveryCheck, check_id, populate_existing=True)
    if check is None or check.department_id != actor.department_id:
        raise HTTPException(status_code=404, detail="任务检查记录不存在。")
    if not actor.is_admin and check.owner_id != actor.user_id:
        raise HTTPException(status_code=403, detail="只有当前负责人或管理员可以重试。")
    if check.state != "failed":
        raise HTTPException(status_code=409, detail="只有失败的检查可以重试。")
    subscription = _subscription(db, actor.department_id, check.skill_id)
    if (subscription is None or not subscription.enabled or subscription.id != check.subscription_id
            or subscription.owner_id != check.owner_id):
        raise HTTPException(status_code=409, detail="任务提醒已停用或负责人已变更，不能重试旧检查。")
    _department_owner(db, actor, check.owner_id)
    check.state = "queued"
    check.trigger = "manual"
    check.next_retry_at = None
    check.error_message = ""
    record_audit(
        db,
        actor=actor,
        action="task_reminder.discovery.retry_queued",
        resource_type="task_discovery_check",
        resource_id=check.id,
    )
    db.commit()
    return TaskDiscoveryCheckQueued(
        id=check.id,
        state=check.state,
        business_dates=json.loads(check.business_dates_json or "[]"),
    )


def get_task_reminder_board(db: Session, actor: UserContext) -> TaskReminderBoard:
    reconciled_count = reconcile_linked_task_reminders(
        db,
        department_id=actor.department_id,
        owner_id=None if actor.is_admin else actor.user_id,
    )
    if reconciled_count:
        record_audit(
            db,
            actor=actor,
            action="task_reminder.workflow_state.reconciled",
            resource_type="task_reminder",
            resource_id=actor.user_id,
            details={"reconciled_count": reconciled_count},
        )
        db.commit()
    reminder_query = select(TaskReminder).where(
        TaskReminder.department_id == actor.department_id,
        TaskReminder.state.in_(("pending", "in_progress", "reopened")),
    )
    failure_query = select(TaskDiscoveryCheck).where(
        TaskDiscoveryCheck.department_id == actor.department_id,
        TaskDiscoveryCheck.state == "failed",
        TaskDiscoveryCheck.next_retry_at.is_(None),
    )
    if not actor.is_admin:
        reminder_query = reminder_query.where(TaskReminder.owner_id == actor.user_id)
        failure_query = failure_query.where(TaskDiscoveryCheck.owner_id == actor.user_id)
    resolved_query = select(TaskReminder).where(
        TaskReminder.department_id == actor.department_id,
        TaskReminder.owner_id == actor.user_id,
        TaskReminder.state == "resolved",
    )
    reminders = list(
        db.scalars(
            reminder_query.order_by(TaskReminder.skill_id, TaskReminder.business_date)
        ).all()
    )
    failures = list(
        db.scalars(
            failure_query.order_by(TaskDiscoveryCheck.finished_at.desc()).limit(20)
        ).all()
    )
    owner_ids = {item.owner_id for item in reminders} | {item.owner_id for item in failures}
    owners = {
        item.id: item
        for item in db.scalars(select(User).where(User.id.in_(owner_ids))).all()
    }
    return TaskReminderBoard(
        reminders=[
            TaskReminderRead(
                id=item.id,
                skill_id=item.skill_id,
                skill_name=_skill_name(item.skill_id),
                owner_id=item.owner_id,
                owner_name=owners[item.owner_id].display_name,
                business_date=item.business_date,
                record_count=item.record_count,
                state=item.state,
                last_checked_at=_utc(item.last_checked_at),
                reopened=item.state == "reopened",
                workflow_id=item.workflow_id,
                batch_id=item.batch_id,
            )
            for item in reminders
            if item.owner_id in owners
        ],
        check_failures=[
            TaskDiscoveryFailureRead(
                id=item.id,
                skill_id=item.skill_id,
                skill_name=_skill_name(item.skill_id),
                owner_id=item.owner_id,
                owner_name=owners[item.owner_id].display_name,
                business_dates=json.loads(item.business_dates_json or "[]"),
                error_message=sanitize_text(
                    item.error_message,
                    error=True,
                    max_length=1200,
                    hidden_message="检查失败详情已隐藏，请联系管理员查看审计记录。",
                ),
                error_code=classify_task_error(item.error_message)[0],
                error_category=classify_task_error(item.error_message)[1],
                attempt_count=item.attempt_count,
                last_checked_at=_utc(item.finished_at or item.started_at),
                audit_href=(
                    f"/dashboard/users?tab=audit&audit_resource_type=task_discovery_check"
                    f"&audit_resource_id={item.id}"
                    if actor.is_admin
                    else None
                ),
            )
            for item in failures
            if item.owner_id in owners
        ],
        resolved_count=int(
            db.scalar(
                select(func.count()).select_from(resolved_query.subquery())
            )
            or 0
        ),
    )


def dismiss_resolved_task_reminders(
    db: Session,
    actor: UserContext,
) -> TaskReminderCleanupResult:
    acquire_claim_lock(db)
    query = select(TaskReminder).where(
        TaskReminder.department_id == actor.department_id,
        TaskReminder.owner_id == actor.user_id,
        TaskReminder.state == "resolved",
    )
    reminders = list(db.scalars(query).all())
    for reminder in reminders:
        reminder.state = "dismissed"
    record_audit(
        db,
        actor=actor,
        action="task_reminder.resolved.dismissed",
        resource_type="task_reminder_collection",
        resource_id=actor.user_id,
        details={
            "dismissed_count": len(reminders),
            "dismissed_reminder_ids": sorted(reminder.id for reminder in reminders),
        },
    )
    db.commit()
    return TaskReminderCleanupResult(dismissed_count=len(reminders))
