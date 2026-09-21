"""Current identity and serialized decision boundaries; synthetic evidence only."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from fastapi import HTTPException
from sqlalchemy import select, event
from sqlalchemy.orm import Session
from app import approval_service as service
from app.auth import UserContext
from app.auth_models import User
from app.models import AuditEvent
from app.models import ApprovalRecord, WorkflowSession, WorkflowAction
from app.scheduler import acquire_claim_lock
from test_refactor_event_transactions import database
from test_execution_authorization import _cancellation_fixture


def seed(db):
    _cancellation_fixture(db, "workflow")
    db.add(User(id="approval-admin", username="approval-admin", role="skill_admin",
                department_id="finance", password_hash="synthetic-only"))
    db.flush()
    workflow = db.get(WorkflowSession, "cancel-workflow")
    workflow.state = workflow.stage = "waiting_approval"
    db.add(ApprovalRecord(id="approval", resource_type="workflow", resource_id=workflow.id,
        workflow_id=workflow.id, department_id="finance", skill_id="synthetic",
        snapshot_sha256="a"*64, preview_sha256="b"*64, snapshot_json="{}", preview_json="{}",
        status="pending", requested_by="synthetic-owner",
        expires_at=datetime.now(timezone.utc)+timedelta(hours=1)))
    db.commit()


def actor():
    return UserContext("approval-admin", "Admin", "skill_admin", "finance")


def invoke(db, entry="decide", decision="approve"):
    if entry == "list": return service.list_approvals(db, actor())
    return service.decide_approval(db, actor(), "approval", decision=decision, reason="synthetic")


@pytest.fixture
def evidence(monkeypatch):
    monkeypatch.setattr(service, "_workflow_evidence", lambda *_: ({}, {}, "a"*64, "b"*64))


@pytest.mark.parametrize("entry", ["list", "decide"])
@pytest.mark.parametrize("change", ["demoted", "disabled", "department"])
def test_current_admin_required(database, evidence, entry, change):
    with Session(database) as db: seed(db)
    with Session(database) as db:
        cached = db.get(User, "approval-admin")
        with Session(database) as other:
            current = other.get(User, "approval-admin")
            if change == "demoted": current.role = "finance_user"
            elif change == "disabled": current.status = "disabled"
            else: current.department_id = "another"
            other.commit()
        with pytest.raises(HTTPException) as denied: invoke(db, entry)
        assert denied.value.status_code == 403
        db.rollback()
    with Session(database) as db:
        assert db.get(ApprovalRecord, "approval").status == "pending"
        assert not list(db.scalars(select(WorkflowAction)))
        assert not list(db.scalars(select(AuditEvent)))


@pytest.mark.parametrize("change", ["record_revoked", "workflow_cancelled", "owner_disabled", "owner_moved", "owner_revoked"])
def test_decision_reloads_current_records(database, evidence, change):
    with Session(database) as db: seed(db)
    with Session(database) as db:
        cached = db.get(ApprovalRecord, "approval")
        workflow = db.get(WorkflowSession, "cancel-workflow")
        with Session(database) as other:
            if change == "record_revoked": other.get(ApprovalRecord, "approval").status = "revoked"
            elif change == "workflow_cancelled":
                flow = other.get(WorkflowSession, "cancel-workflow")
                flow.state = flow.stage = "cancelled"
            elif change == "owner_moved": other.get(User, "synthetic-owner").department_id = "another"
            elif change == "owner_revoked":
                from app.auth_models import UserSkillPermission
                other.scalar(select(UserSkillPermission).where(UserSkillPermission.user_id == "synthetic-owner")).can_run = False
            else: other.get(User, "synthetic-owner").status = "disabled"
            other.commit()
        with pytest.raises(HTTPException): invoke(db)
        db.rollback()
    with Session(database) as db:
        assert not list(db.scalars(select(WorkflowAction)))
        assert db.get(ApprovalRecord, "approval").status != "approved"


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_valid_decision_audited_and_single_use(database, evidence, decision):
    with Session(database) as db: seed(db)
    with Session(database) as db:
        result = invoke(db, decision=decision)
        assert result.status == ("approved" if decision == "approve" else "rejected")
        with pytest.raises(HTTPException): invoke(db, decision=decision)
        db.rollback()
    with Session(database) as db:
        actions = list(db.scalars(select(WorkflowAction)))
        assert len(actions) == (1 if decision == "approve" else 0)
        audits = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "approval."+decision)))
        assert len(audits) == 1 and audits[0].actor_id == "approval-admin"


def test_identity_refreshed_after_actual_lock_wait(database, evidence):
    with Session(database) as db: seed(db)
    waiting = Event()
    with Session(database) as controller:
        acquire_claim_lock(controller)
        def request():
            with Session(database) as db:
                cached = db.get(User, "approval-admin")
                connection = db.connection()
                def before(conn, cursor, statement, parameters, context, executemany):
                    if "scheduler_locks" in statement and "FOR UPDATE" in statement: waiting.set()
                event.listen(connection, "before_cursor_execute", before)
                try:
                    invoke(db)
                    return 200
                except HTTPException as error:
                    db.rollback()
                    return error.status_code
                finally: event.remove(connection, "before_cursor_execute", before)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(request)
            try:
                assert waiting.wait(5), "decision did not wait for mutation lock"
                controller.get(User, "approval-admin").role = "finance_user"
                controller.commit()
                assert future.result(10) == 403
            finally:
                # Release before executor waits, including a failed observation.
                controller.rollback()
    with Session(database) as db:
        assert db.get(ApprovalRecord, "approval").status == "pending"
        assert not list(db.scalars(select(WorkflowAction)))


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_audit_failure_rolls_back_decision_and_action(database, evidence, monkeypatch, decision):
    with Session(database) as db: seed(db)
    class AuditFailure(Exception): pass
    def fail(*args, **kwargs): raise AuditFailure()
    monkeypatch.setattr(service, "record_audit", fail)
    with Session(database) as db:
        with pytest.raises(AuditFailure): invoke(db, decision=decision)
        db.rollback()
    with Session(database) as db:
        assert db.get(ApprovalRecord, "approval").status == "pending"
        assert db.get(WorkflowSession, "cancel-workflow").state == "waiting_approval"
        assert not list(db.scalars(select(WorkflowAction)))
        assert not list(db.scalars(select(AuditEvent)))


def test_rejection_allowed_after_owner_disabled(database, evidence):
    with Session(database) as db:
        seed(db)
        db.get(User, "synthetic-owner").status = "disabled"
        db.commit()
    with Session(database) as db:
        assert invoke(db, decision="reject").status == "rejected"


def test_concurrent_approvals_have_one_winner(database, evidence):
    from threading import Barrier
    with Session(database) as db: seed(db)
    ready = Barrier(2)
    def request():
        with Session(database) as db:
            cached = db.get(ApprovalRecord, "approval")
            workflow = db.get(WorkflowSession, "cancel-workflow")
            ready.wait(5)
            try:
                invoke(db)
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(request) for _ in range(2)]
        assert sorted(f.result(15) for f in futures) == [200, 409]
    with Session(database) as db:
        assert len(list(db.scalars(select(WorkflowAction)))) == 1
        assert len(list(db.scalars(select(AuditEvent).where(AuditEvent.action == "approval.approve")))) == 1


@pytest.mark.parametrize("entry", ["list", "decide"])
def test_expiry_rechecks_and_resets_waiting_task(database, evidence, entry):
    with Session(database) as db: seed(db)
    with Session(database) as db:
        cached = db.get(ApprovalRecord, "approval")
        with Session(database) as other:
            other.get(ApprovalRecord, "approval").expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
            other.commit()
        if entry == "list": invoke(db, entry)
        else:
            with pytest.raises(HTTPException) as error: invoke(db)
            assert error.value.status_code == 409
    with Session(database) as db:
        assert db.get(ApprovalRecord, "approval").status == "expired"
        assert db.get(WorkflowSession, "cancel-workflow").state == "waiting_confirmation"
        assert not list(db.scalars(select(WorkflowAction)))


@pytest.mark.parametrize("audit_fails", [False, True])
def test_snapshot_change_revocation_and_audit_are_atomic(database, monkeypatch, audit_fails):
    with Session(database) as db: seed(db)
    monkeypatch.setattr(service, "_workflow_evidence", lambda *_: ({}, {}, "c"*64, "b"*64))
    class AuditFailure(Exception): pass
    if audit_fails:
        def fail(*args, **kwargs): raise AuditFailure()
        monkeypatch.setattr(service, "record_audit", fail)
    with Session(database) as db:
        with pytest.raises(AuditFailure if audit_fails else HTTPException): invoke(db)
        db.rollback()
    with Session(database) as db:
        assert db.get(ApprovalRecord, "approval").status == ("pending" if audit_fails else "revoked")
        assert db.get(WorkflowSession, "cancel-workflow").state == ("waiting_approval" if audit_fails else "waiting_confirmation")
        audits = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "approval.revoke")))
        assert len(audits) == (0 if audit_fails else 1)
        assert not list(db.scalars(select(WorkflowAction)))


@pytest.mark.parametrize("change", ["department", "kind"])
def test_input_evidence_refreshes_file_metadata(database, tmp_path, change):
    import hashlib, json
    from app.models import FileRecord
    path = tmp_path / "synthetic.txt"
    path.write_bytes(b"synthetic")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with Session(database) as db:
        seed(db)
        db.add(FileRecord(id="approval-file", owner_id="synthetic-owner", department_id="finance",
            kind="input", original_name=path.name, stored_path=str(path), size_bytes=path.stat().st_size, sha256=digest))
        db.get(WorkflowSession, "cancel-workflow").files_json = json.dumps({"input":[{"file_id":"approval-file","sha256":digest}]})
        db.commit()
    with Session(database) as db:
        flow = db.get(WorkflowSession, "cancel-workflow")
        cached = db.get(FileRecord, "approval-file")
        assert service._input_evidence(db, flow)["input"][0]["sha256"] == digest
        with Session(database) as other:
            current = other.get(FileRecord, "approval-file")
            if change == "department": current.department_id = "another"
            else: current.kind = "output"
            other.commit()
        with pytest.raises(HTTPException): service._input_evidence(db, flow)
