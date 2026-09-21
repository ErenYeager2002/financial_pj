"""Public submission conflicts; only non-sensitive receipt identifiers are exposed."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel


class SubmissionErrorDetail(BaseModel):
    code: Literal["IDEMPOTENCY_CONFLICT", "SUBMISSION_IN_PROGRESS", "SUBMISSION_NOT_READY", "SUBMISSION_REJECTED", "LEGACY_SUBMISSION_UNVERIFIED", "SUBMISSION_RECOVERY_ONLY"]
    message: str = ""
    request_id: UUID | None = None


class SubmissionConflictResponse(BaseModel):
    detail: SubmissionErrorDetail | str


SUBMISSION_CONFLICT_RESPONSES = {409: {"model": SubmissionConflictResponse}, 503: {"model": SubmissionConflictResponse}}
