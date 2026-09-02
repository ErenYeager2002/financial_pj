from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from helpers import auth_client
from sqlalchemy.exc import IntegrityError

from app.auth_service import get_user_by_username
from app.database import SessionLocal
from app.models import ModelTraceRecord, RunRecord, TaskDraftRecord


def test_model_trace_allows_pre_draft_record_and_enforces_parent_scope() -> None:
    owner_name = f"trace-owner-{uuid.uuid4().hex[:8]}"
    other_name = f"trace-other-{uuid.uuid4().hex[:8]}"
    run_id = str(uuid.uuid4())
    draft_id = str(uuid.uuid4())

    with auth_client(username=owner_name, department_id="trace-finance"):
        with SessionLocal() as db:
            owner = get_user_by_username(db, owner_name)
            assert owner is not None
            owner_id = owner.id
            db.add(
                RunRecord(
                    id=run_id,
                    owner_id=owner.id,
                    owner_name=owner.display_name,
                    department_id=owner.department_id,
                    skill_id="trace-test",
                    skill_name="Trace 测试",
                    skill_version="1.0.0",
                    skill_hash="a" * 64,
                    manifest_path="tool.yaml",
                    manifest_snapshot="{}",
                    adapter="python",
                    worker_pool="python",
                )
            )
            db.add(
                TaskDraftRecord(
                    id=draft_id,
                    owner_id=owner.id,
                    department_id=owner.department_id,
                    skill_id="trace-test",
                    skill_name="Trace 测试",
                    skill_version="1.0.0",
                    skill_hash="b" * 64,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
            db.commit()

    with auth_client(username=other_name, department_id="trace-other"):
        with SessionLocal() as db:
            other = get_user_by_username(db, other_name)
            assert other is not None
            other_id = other.id

    with SessionLocal() as db:
        db.add(
            _trace(
                run_id=run_id,
                task_draft_id=None,
                owner_id=owner_id,
                department_id="trace-finance",
            )
        )
        db.add(
            _trace(
                run_id=None,
                task_draft_id=None,
                owner_id=owner_id,
                department_id="trace-finance",
            )
        )
        db.commit()

    with SessionLocal() as db:
        db.add(
            _trace(
                run_id=run_id,
                task_draft_id=None,
                owner_id=other_id,
                department_id="trace-other",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        db.add(
            _trace(
                run_id=run_id,
                task_draft_id=draft_id,
                owner_id=owner_id,
                department_id="trace-finance",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def _trace(
    *,
    run_id: str | None,
    task_draft_id: str | None,
    owner_id: str,
    department_id: str,
) -> ModelTraceRecord:
    return ModelTraceRecord(
        id=str(uuid.uuid4()),
        owner_id=owner_id,
        department_id=department_id,
        run_id=run_id,
        task_draft_id=task_draft_id,
        purpose="parameter_interpretation",
        provider="synthetic",
        model="synthetic",
        status="succeeded",
        duration_ms=1,
    )
