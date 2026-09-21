"""Authoritative Pi claim identity. Caller owns transaction/commit boundaries."""
from datetime import UTC, datetime
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .models import WorkflowAction

PROTOCOL_VERSION = "pi-harness-attempt-v1"


def lease_now(db: Session) -> datetime:
    # Read after locks: transaction_timestamp would accept a lease that expired
    # while waiting for another executor to release its lock.
    return db.scalar(select(func.clock_timestamp())) if db.get_bind().dialect.name == "postgresql" else datetime.now(UTC)


def require_harness_lease(db: Session, workflow_id: str, action_id: str,
                          worker_id: str, attempt: int) -> WorkflowAction:
    from .scheduler import acquire_claim_lock
    if not action_id or type(attempt) is not int or attempt < 1:
        raise HTTPException(status_code=409, detail="Pi Harness 执行代次缺失或无效。")
    acquire_claim_lock(db)
    action = db.scalar(select(WorkflowAction).where(WorkflowAction.id == action_id)
                       .with_for_update().execution_options(populate_existing=True))
    now = lease_now(db)
    deadline = action.lease_expires_at if action is not None else None
    if deadline is not None and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if (action is None or action.workflow_id != workflow_id or action.name != "pi_harness_execute"
            or action.state != "running" or action.worker_id != worker_id
            or action.attempt_count != attempt or deadline is None or deadline <= now):
        raise HTTPException(status_code=409, detail="Pi Harness 租约或执行代次已经失效。")
    return action
