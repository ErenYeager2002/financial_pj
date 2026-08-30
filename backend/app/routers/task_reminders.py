from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import UserContext, get_current_user, require_admin
from ..database import get_db
from ..schemas import ServiceCredentialRead, ServiceCredentialWrite
from ..task_reminder_contracts import (
    TaskDiscoveryCheckQueued,
    TaskDiscoveryCheckRequest,
    TaskReminderBoard,
    TaskReminderCleanupResult,
    TaskReminderSubscriptionRead,
    TaskReminderSubscriptionWrite,
)
from ..task_reminder_service import (
    dismiss_resolved_task_reminders,
    enqueue_task_discovery,
    get_subscription,
    get_subscription_owner_credential,
    get_task_reminder_board,
    remove_subscription_owner_credential,
    retry_task_discovery,
    save_subscription,
    save_subscription_owner_credential,
)

router = APIRouter(prefix="/api/task-reminders", tags=["task-reminders"])

admin_router = APIRouter(
    prefix="/api/admin/task-reminder-subscriptions",
    tags=["task-reminders"],
)


@router.get("", response_model=TaskReminderBoard)
def list_task_reminders(
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> TaskReminderBoard:
    return get_task_reminder_board(db, current)


@router.delete("/resolved", response_model=TaskReminderCleanupResult)
def clear_resolved_task_reminders(
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> TaskReminderCleanupResult:
    return dismiss_resolved_task_reminders(db, current)


@router.post("/checks", response_model=TaskDiscoveryCheckQueued, status_code=202)
def queue_task_discovery_check(
    body: TaskDiscoveryCheckRequest,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> TaskDiscoveryCheckQueued:
    return enqueue_task_discovery(db, current, body)


@router.post("/checks/{check_id}/retry", response_model=TaskDiscoveryCheckQueued, status_code=202)
def retry_task_discovery_check(
    check_id: str,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> TaskDiscoveryCheckQueued:
    return retry_task_discovery(db, current, check_id)


@admin_router.get("/{skill_id}", response_model=TaskReminderSubscriptionRead)
def admin_get_task_reminder_subscription(
    skill_id: str,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> TaskReminderSubscriptionRead:
    require_admin(current)
    return get_subscription(db, current, skill_id)


@admin_router.put("/{skill_id}", response_model=TaskReminderSubscriptionRead)
def admin_save_task_reminder_subscription(
    skill_id: str,
    body: TaskReminderSubscriptionWrite,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> TaskReminderSubscriptionRead:
    require_admin(current)
    return save_subscription(db, current, skill_id, body)


@admin_router.get("/{skill_id}/credential", response_model=ServiceCredentialRead)
def admin_get_task_reminder_owner_credential(
    skill_id: str,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> ServiceCredentialRead:
    require_admin(current)
    return get_subscription_owner_credential(db, current, skill_id)


@admin_router.put("/{skill_id}/credential", response_model=ServiceCredentialRead)
def admin_save_task_reminder_owner_credential(
    skill_id: str,
    body: ServiceCredentialWrite,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> ServiceCredentialRead:
    require_admin(current)
    return save_subscription_owner_credential(
        db,
        current,
        skill_id,
        body.account,
        body.password,
    )


@admin_router.delete("/{skill_id}/credential", status_code=204)
def admin_delete_task_reminder_owner_credential(
    skill_id: str,
    db: Session = Depends(get_db),
    current: UserContext = Depends(get_current_user),
) -> None:
    require_admin(current)
    remove_subscription_owner_credential(db, current, skill_id)
