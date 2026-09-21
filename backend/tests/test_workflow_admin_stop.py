"""Disabled owner stopping uses a real actor and ordinary atomic-step guards."""
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.auth import UserContext
from app.auth_models import User
from app.models import WorkflowSession, WorkflowBatch, WorkflowAction, AuditEvent
from test_refactor_event_transactions import database
from test_execution_authorization import _cancellation_fixture


@pytest.mark.parametrize("target", ["single", "batch"])
@pytest.mark.parametrize("case", ["queued", "running", "atomic", "active_owner", "demoted", "foreign", "audit_failure"])
def test_admin_stop_disabled_workflow(database, monkeypatch, target, case):
    from app import workflow_service as service
    with Session(database) as db:
        _cancellation_fixture(db, "batch" if target == "batch" else "workflow")
        if target == "batch":
            db.add(WorkflowSession(id="remaining-day", batch_id="cancel-batch", batch_sequence=2,
                owner_id="synthetic-owner", department_id="finance", skill_id="synthetic",
                skill_name="Synthetic", skill_version="1", skill_hash="a" * 64,
                model_connection_id="synthetic-model", model_provider="synthetic", model_name="synthetic",
                state="queued", stage="preparing"))
        owner = db.get(User, "synthetic-owner")
        owner.status = "active" if case == "active_owner" else "disabled"
        db.add(User(id="stop-admin", username="stop-admin", department_id="other" if case == "foreign" else "finance", role="finance_user" if case == "demoted" else "skill_admin", password_hash="synthetic-only"))
        flow = db.get(WorkflowSession, "cancel-workflow")
        if case in {"running", "atomic"}:
            flow.state, flow.stage = "running", "applying" if case == "atomic" else "fetching_data"
            db.add(WorkflowAction(id="stop-action", workflow_id=flow.id, state="running", name="apply_confirmed" if case == "atomic" else "fetch_data"))
        db.commit()
    actor = UserContext("stop-admin", "Synthetic admin", "skill_admin", "other" if case == "foreign" else "finance")
    class AuditFailure(Exception): pass
    if case == "audit_failure":
        original_audit = service.record_audit
        def fail(*args, **kwargs):
            if kwargs.get("action") == "workflow.admin_stop_disabled_owner": raise AuditFailure()
            return original_audit(*args, **kwargs)
        monkeypatch.setattr(service, "record_audit", fail)
    with Session(database) as db:
        def invoke():
            return service.stop_disabled_owner_workflow(db, "cancel-batch" if target == "batch" else "cancel-workflow", actor, batch=target == "batch")
        if case in {"queued", "running"}: invoke()
        else:
            with pytest.raises(AuditFailure if case == "audit_failure" else HTTPException): invoke()
            db.rollback()
    with Session(database) as db:
        obj = db.get(WorkflowBatch if target == "batch" else WorkflowSession, "cancel-batch" if target == "batch" else "cancel-workflow")
        audits = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "workflow.admin_stop_disabled_owner")))
        if case in {"queued", "running"}:
            assert obj.state == ("cancelling" if case == "running" else "cancelled")
            if target == "batch": assert db.get(WorkflowSession, "remaining-day").state == "cancelled"
            assert len(audits) == 1 and audits[0].actor_id == "stop-admin" and audits[0].actor_role == "skill_admin"
        else:
            assert not audits and obj.state != "cancelled"
            if case == "audit_failure": assert list(db.scalars(select(AuditEvent))) == []


@pytest.mark.parametrize("target", ["single", "batch"])
@pytest.mark.parametrize("action_state", ["queued", "running"])
def test_admin_stop_terminal_task_cancels_investigation(database, target, action_state):
    import json
    from app import workflow_service as service
    from app.ar_execution_contract import INVESTIGATION_ACTION
    with Session(database) as db:
        _cancellation_fixture(db, "batch" if target == "batch" else "workflow")
        db.get(User, "synthetic-owner").status = "disabled"
        db.add(User(id="stop-admin", username="stop-admin", department_id="finance", role="skill_admin", password_hash="synthetic-only"))
        flow = db.get(WorkflowSession, "cancel-workflow")
        flow.state, flow.stage = "failed", "failed"
        if target == "batch": db.get(WorkflowBatch, "cancel-batch").state = "failed"
        db.add(WorkflowAction(id="investigation", workflow_id=flow.id, state=action_state, name=INVESTIGATION_ACTION))
        db.commit()
    actor = UserContext("stop-admin", "Admin", "skill_admin", "finance")
    with Session(database) as db:
        service.stop_disabled_owner_workflow(db, "cancel-batch" if target == "batch" else "cancel-workflow", actor, batch=target == "batch")
    with Session(database) as db:
        action = db.get(WorkflowAction, "investigation")
        assert json.loads(action.input_json)["cancel_requested"] is True
        assert action.state == ("cancelled" if action_state == "queued" else "running")
        assert db.get(WorkflowSession, "cancel-workflow").state == "failed"
        audits = list(db.scalars(select(AuditEvent)))
        assert {a.action for a in audits} == {"workflow.ar_execution.investigation.cancel", "workflow.admin_stop_disabled_owner"}
        assert all(a.actor_id == "stop-admin" for a in audits)


def test_admin_stop_routes_require_authentication(database):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth import get_current_user
    from app.database import get_db
    original = dict(app.dependency_overrides)
    def anonymous(): raise HTTPException(401, "Login required")
    def connection():
        with Session(database) as db: yield db
    try:
        app.dependency_overrides[get_current_user] = anonymous
        app.dependency_overrides[get_db] = connection
        client = TestClient(app)
        for path in ["/api/admin/workflows/unknown/stop-disabled-owner", "/api/admin/workflow-batches/unknown/stop-disabled-owner"]:
            assert client.post(path).status_code == 401
        client.close()
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)


@pytest.mark.parametrize("target", ["single", "batch"])
@pytest.mark.parametrize("change", ["reactivated", "owner_moved", "admin_demoted"])
def test_admin_stop_rechecks_after_actual_scheduler_wait(database, target, change):
    if database.dialect.name != "postgresql": pytest.skip("Requires PostgreSQL lock wait")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    from sqlalchemy import event
    from app.scheduler import acquire_claim_lock
    from app.workflow_service import stop_disabled_owner_workflow
    with Session(database) as db:
        _cancellation_fixture(db, "batch" if target == "batch" else "workflow")
        db.get(User, "synthetic-owner").status = "disabled"
        db.add(User(id="stop-admin", username="stop-admin", department_id="finance", role="skill_admin", password_hash="synthetic-only"))
        db.commit()
    waiting = Event()
    def observe(conn, cursor, statement, parameters, context, executemany):
        if current_thread().name.startswith("admin-stop-race") and "scheduler_locks" in statement and "FOR UPDATE" in statement:
            waiting.set()
    def stop():
        with Session(database) as db:
            # Retain cached rows across the wait to expose identity-map mistakes.
            cached_owner = db.get(User, "synthetic-owner")
            cached_admin = db.get(User, "stop-admin")
            actor = UserContext("stop-admin", "Admin", "skill_admin", "finance")
            try:
                stop_disabled_owner_workflow(db, "cancel-batch" if target == "batch" else "cancel-workflow", actor, batch=target == "batch")
            except HTTPException as error: return error.status_code
            return 200
    event.listen(database, "before_cursor_execute", observe)
    try:
        with Session(database) as controller, ThreadPoolExecutor(max_workers=1, thread_name_prefix="admin-stop-race") as pool:
            acquire_claim_lock(controller)
            future = pool.submit(stop)
            try:
                assert waiting.wait(5) and not future.done()
                if change == "reactivated": controller.get(User, "synthetic-owner").status = "active"
                elif change == "owner_moved": controller.get(User, "synthetic-owner").department_id = "other"
                else: controller.get(User, "stop-admin").role = "finance_user"
            finally:
                controller.commit()
            assert future.result(timeout=10) == {"reactivated": 409, "owner_moved": 404, "admin_demoted": 404}[change]
        with Session(database) as db:
            assert db.get(WorkflowSession, "cancel-workflow").state == "queued"
            assert list(db.scalars(select(AuditEvent))) == []
    finally:
        event.remove(database, "before_cursor_execute", observe)
