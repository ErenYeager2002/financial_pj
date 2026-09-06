from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TaskReminderSubscriptionWrite(BaseModel):
    owner_id: str = Field(min_length=1, max_length=128)
    enabled: bool = True


class TaskReminderSubscriptionRead(BaseModel):
    skill_id: str
    skill_name: str
    owner_id: str
    owner_name: str
    enabled: bool
    timezone: str
    schedule_time: str
    last_successful_business_date: str | None = None
    last_check_status: str
    last_checked_at: datetime | None = None


class TaskReminderRead(BaseModel):
    id: str
    skill_id: str
    skill_name: str
    owner_id: str
    owner_name: str
    business_date: str
    record_count: int
    state: str
    last_checked_at: datetime
    reopened: bool = False
    workflow_id: str | None = None
    batch_id: str | None = None


class TaskDiscoveryFailureRead(BaseModel):
    id: str
    skill_id: str
    skill_name: str
    owner_id: str
    owner_name: str
    business_dates: list[str] = Field(default_factory=list)
    error_message: str
    error_code: str = "TASK_DISCOVERY_FAILED"
    error_category: str = "unknown"
    attempt_count: int
    last_checked_at: datetime
    audit_href: str | None = None


class TaskReminderBoard(BaseModel):
    reminders: list[TaskReminderRead] = Field(default_factory=list)
    check_failures: list[TaskDiscoveryFailureRead] = Field(default_factory=list)
    resolved_count: int = 0


class TaskReminderCleanupResult(BaseModel):
    dismissed_count: int = 0


class TaskDiscoveryCheckRequest(BaseModel):
    skill_id: str = Field(min_length=1, max_length=128)
    business_dates: list[str] = Field(min_length=1, max_length=31)


class TaskDiscoveryCheckQueued(BaseModel):
    id: str
    state: str
    business_dates: list[str]
