"""Pi protocol boundary regressions against disposable PostgreSQL and real HTTP parsing."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from unittest.mock import Mock
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models import WorkflowSession, WorkflowAction
from app.routers import pi_harness as pi
from app.pi_harness_lease import require_harness_lease
from test_refactor_event_transactions import database


def seed(engine):
    workflow_id, action_id = str(uuid4()), str(uuid4())
    with Session(engine) as db:
        db.add(WorkflowSession(id=workflow_id, owner_id="synthetic-owner", department_id="finance",
            skill_id="synthetic", skill_name="Synthetic", skill_version="1", skill_hash="a" * 64,
            execution_mode="pi_harness", state="running", stage="preparing", context_json="{}",
            model_connection_id="synthetic", model_provider="synthetic", model_name="synthetic"))
        db.flush()
        db.add(WorkflowAction(id=action_id, workflow_id=workflow_id, name="pi_harness_execute",
            state="running", worker_id="synthetic-worker", attempt_count=2,
            lease_expires_at=datetime.now(UTC)+timedelta(minutes=5)))
        db.commit()
    return workflow_id, action_id


def client_for(engine):
    app = FastAPI()
    app.include_router(pi.router)
    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[pi.get_db] = session
    app.dependency_overrides[pi.require_pi_harness_token] = lambda: None
    return TestClient(app)


@pytest.mark.parametrize("entry", ["heartbeat", "finish", "tool", "read", "model"])
@pytest.mark.parametrize("condition", ["stale", "missing", "expired", "wrong_worker"])
def test_http_rejects_unbound_or_lost_attempt_without_outward_calls(database, monkeypatch, entry, condition):
    workflow_id, action_id = seed(database)
    if condition == "expired":
        with Session(database) as db:
            db.get(WorkflowAction, action_id).lease_expires_at = datetime.now(UTC)-timedelta(seconds=1)
            db.commit()
    outward = Mock(side_effect=AssertionError("stale request reached an outward operation"))
    monkeypatch.setattr(pi, "queue_pi_harness_tool", outward)
    monkeypatch.setattr(pi, "open_agent_model_stream", outward)
    body = {"worker_id": "other-worker" if condition == "wrong_worker" else "synthetic-worker"}
    if condition != "missing": body["attempt"] = 1 if condition == "stale" else 2
    base = pi.router.prefix
    if entry in {"heartbeat", "finish"}:
        path = f"{base}/actions/{action_id}/{entry}"
        if entry == "finish": body["outcome"] = "failed"
    else:
        body["harness_action_id"] = action_id
        if entry == "model":
            path = base + "/model/chat/completions"
            body.update(workflow_id=workflow_id, model="synthetic", messages=[{"role":"user", "content":"synthetic"}])
        elif entry == "tool":
            path = f"{base}/workflows/{workflow_id}/tools/prepare_workspace"
            body["arguments"] = {}
        else:
            path = f"{base}/workflows/{workflow_id}/actions/{action_id}"
    with client_for(database) as client:
        response = client.get(path, params=body) if entry == "read" else client.post(path, json=body)
    assert response.status_code == (422 if condition == "missing" else 409), response.text
    outward.assert_not_called()
    with Session(database) as db:
        action = db.get(WorkflowAction, action_id)
        assert action.state == "running" and action.attempt_count == 2
        assert db.get(WorkflowSession, workflow_id).state == "running"


def test_current_heartbeat_renews_and_legacy_claim_cannot_acquire(database):
    _, action_id = seed(database)
    with client_for(database) as client:
        response = client.post(f"{pi.router.prefix}/actions/{action_id}/heartbeat",
                               json={"worker_id":"synthetic-worker", "attempt":2})
        assert response.status_code == 200, response.text
        for attempt in (True, "2", 0, -1):
            assert client.post(f"{pi.router.prefix}/actions/{action_id}/heartbeat",
                json={"worker_id":"synthetic-worker", "attempt":attempt}).status_code == 422
        assert client.post(pi.router.prefix + "/claim", json={"worker_id":"old-worker"}).status_code == 422
    with Session(database) as db:
        assert db.get(WorkflowAction, action_id).heartbeat_at is not None


@pytest.mark.parametrize("entry", ["reservation", "legacy_queue", "phase_queue"])
def test_authoritative_boundary_rechecks_attempt_after_earlier_read(database, entry):
    from app.ar_agent_budget import reserve_agent_call
    from app.workflow_service import queue_pi_harness_tool
    from app.ar_execution_runner import queue_execution_phase
    workflow_id, action_id = seed(database)
    with Session(database) as db:
        flow = db.get(WorkflowSession, workflow_id)
        stale = db.get(WorkflowAction, action_id)
        assert stale.attempt_count == 2
        with Session(database) as other:
            other.get(WorkflowAction, action_id).attempt_count = 3
            other.commit()
        with pytest.raises(HTTPException) as error:
            if entry == "reservation":
                reserve_agent_call(db, flow, stale, "synthetic-worker", "tool_calls", attempt=2)
            elif entry == "legacy_queue":
                queue_pi_harness_tool(db, flow, "prepare_workspace", {}, harness_action_id=action_id, worker_id="synthetic-worker", attempt=2)
            else:
                queue_execution_phase(db, flow, "classify_reconciliation", {}, harness_action_id=action_id, worker_id="synthetic-worker", attempt=2)
        assert error.value.status_code == 409
        db.rollback()
    with Session(database) as db:
        assert len(list(db.scalars(select(WorkflowAction)))) == 1
        assert db.get(WorkflowAction, action_id).attempt_count == 3


def test_lock_wait_cannot_validate_using_transaction_start_time(database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from sqlalchemy import event, text
    if database.dialect.name != "postgresql": pytest.skip("PostgreSQL lock semantics")
    workflow_id, action_id = seed(database)
    waiting = Event()
    def observe(conn, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement: waiting.set()
    def contender():
        with Session(database) as db:
            try:
                require_harness_lease(db, workflow_id, action_id, "synthetic-worker", 2)
            except HTTPException as error: return error.status_code
            return 200
    with Session(database) as db:
        db.get(WorkflowAction, action_id).lease_expires_at = datetime.now(UTC)+timedelta(seconds=1)
        db.commit()
        db.scalar(select(WorkflowAction).where(WorkflowAction.id==action_id).with_for_update())
        event.listen(database, "before_cursor_execute", observe)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(contender)
                try:
                    assert waiting.wait(5)
                    db.execute(text("SELECT pg_sleep(1.2)"))
                finally: db.rollback()
                assert future.result(timeout=10) == 409
        finally: event.remove(database, "before_cursor_execute", observe)


@pytest.mark.parametrize("tool", ["inspect_fetched_data", "read_task_file"])
@pytest.mark.parametrize("change", ["unchanged", "new_attempt", "revoked"])
def test_read_page_revalidates_before_success_audit(database, monkeypatch, tool, change):
    from app.models import AuditEvent
    from app.auth_models import User
    workflow_id, action_id = seed(database)
    monkeypatch.setattr(pi, "_declared_tools", lambda *args: [{"name":tool}])
    def page(*args):
        with Session(database) as other:
            if change == "new_attempt": other.get(WorkflowAction, action_id).attempt_count = 3
            if change == "revoked": other.get(User, "synthetic-owner").status = "disabled"
            other.commit()
        return {"offset":0, "limit":1, "content":"synthetic"}
    monkeypatch.setattr(pi, "_fetched_preview_page" if tool == "inspect_fetched_data" else "_task_text_file_page", page)
    with client_for(database) as client:
        response = client.post(f"{pi.router.prefix}/workflows/{workflow_id}/tools/{tool}",
            json={"worker_id":"synthetic-worker", "harness_action_id":action_id, "attempt":2, "arguments":{}})
    assert response.status_code == {"unchanged":200, "new_attempt":409, "revoked":403}[change], response.text
    with Session(database) as db:
        audits = list(db.scalars(select(AuditEvent).where(AuditEvent.action=="workflow.pi_harness.data.inspected")))
        assert len(audits) == (1 if change == "unchanged" else 0)
