"""Owner-scoped, read-only receipt status; never exposes reservation material."""
import json
from typing import Literal
from uuid import UUID
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from ...authorization import refresh_active_user, assert_skill_permission
from ...models import RunRecord
from .idempotency_models import IdempotencyRequest


class SubmissionReceiptRead(BaseModel):
    request_id: UUID
    operation: Literal["run.create", "run.retry", "draft.confirm"]
    status: Literal["preparing", "prepared", "bound", "rejected"]
    run_id: str | None
    response_version: int


def read_submission_receipt(db, request_id, user):
    active = refresh_active_user(db, user)
    receipt = db.scalar(select(IdempotencyRequest).where(
        IdempotencyRequest.id == str(request_id),
        IdempotencyRequest.owner_id == active.user_id,
        IdempotencyRequest.department_id == active.department_id,
        IdempotencyRequest.operation.in_(("run.create", "run.retry", "draft.confirm")),
    ))
    if receipt is None:
        raise HTTPException(404, "提交记录不存在。")
    try:
        skill_id = json.loads(receipt.pinned_revision_json)["skill"]["manifest"]["id"]
        if not isinstance(skill_id, str) or not skill_id:
            raise ValueError("Invalid pinned skill")
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, "提交记录需要管理员核查。") from exc
    assert_skill_permission(db, active, skill_id)
    if receipt.operation == "draft.confirm":
        assert_skill_permission(db, active, skill_id, "can_create_draft")
    run_id = None
    if receipt.status == "bound":
        run = db.get(RunRecord, receipt.execution_id)
        if (receipt.execution_kind != "run" or run is None or run.owner_id != active.user_id
                or run.department_id != active.department_id or run.skill_id != skill_id):
            raise HTTPException(404, "关联任务不存在或不可访问。")
        run_id = run.id
    return SubmissionReceiptRead(request_id=receipt.id, operation=receipt.operation,
        status=receipt.status, run_id=run_id, response_version=receipt.response_version)
