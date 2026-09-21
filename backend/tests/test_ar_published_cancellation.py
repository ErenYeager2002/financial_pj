"""Real cancellation transitions retain already-published completion work."""
import json
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth import UserContext
from app.models import WorkflowAction, WorkflowBatch, WorkflowSession
from app import workflow_service as service
from test_refactor_event_transactions import database
from test_execution_authorization import _cancellation_fixture


@pytest.mark.parametrize("target", ["single", "batch"])
@pytest.mark.parametrize("completion_state", ["queued", "running"])
def test_cancel_after_publication_retains_completion_and_stops_next_dates(database, target, completion_state):
    with Session(database) as db:
        _cancellation_fixture(db, "batch" if target == "batch" else "workflow")
        flow = db.get(WorkflowSession, "cancel-workflow")
        flow.state, flow.stage = "running", "applying"
        flow.context_json = json.dumps({"ar_execution":{"publication":"verified"}})
        db.add(WorkflowAction(id="necessary-completion", workflow_id=flow.id,
            name="ar_complete_reconciliation", state=completion_state))
        if target == "batch":
            db.get(WorkflowBatch, "cancel-batch").state = "running"
            db.add(WorkflowSession(id="next-day", batch_id="cancel-batch", batch_sequence=2,
                owner_id="synthetic-owner", department_id="finance", skill_id="synthetic", skill_name="Synthetic",
                skill_version="1", skill_hash="a"*64, model_connection_id="synthetic-model",
                model_provider="synthetic", model_name="synthetic", state="queued", stage="preparing"))
        db.commit()
    actor = UserContext("synthetic-owner", "Synthetic", "finance_user", "finance")
    with Session(database) as db:
        if target == "batch": service.cancel_workflow_batch(db, "cancel-batch", actor)
        else: service.cancel_workflow(db, "cancel-workflow", actor)
    with Session(database) as db:
        flow = db.get(WorkflowSession, "cancel-workflow")
        assert flow.state == "running"
        assert json.loads(flow.context_json)["stop_after_action"] is True
        assert json.loads(flow.context_json)["ar_execution"]["publication"] == "verified"
        actions = list(db.scalars(select(WorkflowAction)))
        assert len(actions) == 1
        assert actions[0].id == "necessary-completion"
        assert actions[0].name == "ar_complete_reconciliation" and actions[0].state == completion_state
        if target == "batch":
            assert db.get(WorkflowBatch, "cancel-batch").state == "cancelling"
            assert db.get(WorkflowSession, "next-day").state == "cancelled"
