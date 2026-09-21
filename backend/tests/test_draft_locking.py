from datetime import UTC, datetime, timedelta
import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from app.auth import UserContext
from app.models import TaskDraftRecord
from app.draft_service import update_task_draft, delete_task_draft
from app.schemas_assistant import TaskDraftUpdate
from test_refactor_event_transactions import database


@pytest.mark.parametrize("action", ["edit", "delete"])
def test_draft_mutation_waits_for_consumption_and_rechecks_state(database, action):
    if database.dialect.name != "postgresql":
        pytest.skip("Row-lock behavior requires PostgreSQL")
    user=UserContext(user_id="synthetic-owner",display_name="Synthetic",role="finance_user")
    with Session(database) as db:
        db.add(TaskDraftRecord(id="locked-draft",owner_id=user.user_id,department_id="finance",skill_id="synthetic",skill_name="Synthetic",skill_version="1",skill_hash="a"*64,state="ready",expires_at=datetime.now(UTC)+timedelta(hours=1)))
        db.commit()
    def mutate(db):
        if action == "edit":
            update_task_draft(db,"locked-draft",user,TaskDraftUpdate(parameters={}))
        else:
            delete_task_draft(db,"locked-draft",user)
    with Session(database) as holder, Session(database) as contender:
        record=holder.scalar(select(TaskDraftRecord).where(TaskDraftRecord.id=="locked-draft").with_for_update())
        contender.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(OperationalError) as caught:
            mutate(contender)
        assert caught.value.orig.sqlstate == "55P03"
        contender.rollback()
        record.state="consumed"
        holder.commit()
        with pytest.raises(HTTPException) as denied:
            mutate(contender)
        assert denied.value.status_code == 409
        contender.rollback()
    with Session(database) as db:
        assert db.get(TaskDraftRecord,"locked-draft").state == "consumed"
