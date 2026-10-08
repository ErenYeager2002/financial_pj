"""Only an already-exited completion can be retained after owner revocation."""
import base64, hashlib, json
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import ar_execution_runner as runner, ar_publication as publication, ar_completion_authorization as policy
from app import workflow_service as service
from app.ar_execution_contract import PHASES, ExecutionLeaseLost
from app.ar_process_evidence import SCHEMA_VERSION
from app.auth_models import User, UserSkillPermission
from app.models import WorkflowAction, WorkflowSession, FileRecord
from test_refactor_event_transactions import database
from test_publication_current_evidence import seed


def prepare(db, root, monkeypatch, *, owner="disabled", failure="", mode="workflow", action_id="completion-action"):
    for module in [runner, publication, policy, service]:
        monkeypatch.setattr(module, "workflow_root", lambda *_: root)
    monkeypatch.setattr(service, "_workflow_storage_root", lambda *_: root)
    seed(db, root)
    flow = db.get(WorkflowSession, "cancel-workflow")
    flow.state, flow.stage, flow.execution_mode = "running", "applying", mode
    # Match the real execution contract: publication retains an original input
    # version and completion has a durable intent before the process can start.
    from app.models import WorkflowMaterialSet
    from app.ar_execution_safety import register_effect_intent
    original = WorkflowMaterialSet(id="original-material", owner_id=flow.owner_id,
        department_id=flow.department_id, skill_id=flow.skill_id, version=1, state="superseded")
    material = db.get(WorkflowMaterialSet, "published")
    material.version = 2
    db.flush()  # Free version 1 before inserting the original material.
    db.add(original)
    db.flush()
    material.parent_set_id = original.id
    context = json.loads(flow.context_json)
    context.update(workspace=str(root), plan_fingerprint="synthetic-plan")
    context["ar_execution"].update(material_set_id=original.id, material_version=1)
    context["ar_execution"]["steps"]["publish_reconciliation"]["material_version"] = 2
    flow.context_json = json.dumps(context)
    db.flush()
    proof = publication.publication_manifest(db, flow)
    raw = json.dumps({"schema_version":"ar-formal-ledgers-v1", "publication":proof,
        "json_ledgers":{"父回款顺序分配台账.json":{"parents":{}},"跑批台账.json":{"runs":{}}},
        "binary_ledgers":{"挂账台账.xlsx":{"base64":base64.b64encode(b"synthetic").decode(),"sha256":hashlib.sha256(b"synthetic").hexdigest()}}}).encode()
    stage = root / "batch-date-stage"
    candidate = stage / "formal-ledger-build" / action_id / ("核销辅助台账_" + flow.reconciliation_date.replace("-", "") + ".json")
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(raw)
    action = WorkflowAction(id=action_id, workflow_id=flow.id, name="ar_complete_reconciliation",
        state="running", worker_id="synthetic-worker", attempt_count=1,
        lease_expires_at=datetime.now(timezone.utc)+timedelta(minutes=10))
    db.add(action)
    register_effect_intent(context, flow, action, "complete_reconciliation")
    flow.context_json = json.dumps(context)
    if failure == "wrong_action": action.name = "ar_write_ledger"
    if failure == "expired_lease": action.lease_expires_at = datetime.now(timezone.utc)-timedelta(minutes=1)
    db.commit()
    state = json.loads(flow.context_json)["ar_execution"]
    record_id = "a"*32
    fact = {"schema_version":SCHEMA_VERSION,"record_id":record_id,"workflow_id":flow.id,
        "action_id":action.id,"action_name":action.name,"attempt":action.attempt_count,
        "worker_id":action.worker_id,"reconciliation_date":flow.reconciliation_date,
        "skill_hash":flow.skill_hash,"script":"complete_execution.py",
        "communication_completed":True,"direct_process_exit_confirmed":True,"returncode":0}
    if failure == "attempt_changed": fact["attempt"] = 0
    if failure == "failed_process": fact["returncode"] = 1
    if failure == "wrong_owner_task": fact["workflow_id"] = "another-task"
    journal = root/"execution-processes"/action.id/record_id/"exited.json"
    journal.parent.mkdir(parents=True)
    encoded = json.dumps(fact).encode()
    journal.write_bytes(encoded)
    reference = {"record_id":record_id,"script":"complete_execution.py","state":"exited",
        "direct_process_exit_confirmed":True,"exit_sha256":hashlib.sha256(encoded).hexdigest()}
    action._ar_process_exit_confirmed = failure != "unconfirmed_exit"
    action._ar_process_records = [reference] if failure != "missing_records" else []
    if failure == "journal_changed": journal.write_bytes(b"changed")
    formal = {"path":str(candidate),"fingerprint":hashlib.sha256(raw).hexdigest()}
    result = {"formal_ledger_candidate":formal,"publication":"verified",
        "process_evidence_version":SCHEMA_VERSION,"process_records":action._ar_process_records,
        "ar_execution":{**state,"completed":[p.name for p in PHASES],
            "steps":{**state["steps"],"complete_reconciliation":{"formal_ledger_candidate":formal}}}}
    current = db.get(User, "synthetic-owner")
    if owner == "disabled": current.status = "disabled"
    elif owner == "department": current.department_id = "another"
    elif owner == "revoked": db.scalar(select(UserSkillPermission).where(UserSkillPermission.user_id==current.id)).can_run = False
    db.commit()
    original = runner.ArExecution
    def execution(db, action, flow):
        # Skip directory/Skill construction only. Use real current owner and
        # material checks, publication proof, action lease, registration and audit.
        obj = object.__new__(original)
        obj.db, obj.workflow, obj.action, obj.service = db, flow, action, service
        obj.execution = json.loads(flow.context_json)["ar_execution"]
        obj.date = flow.reconciliation_date
        obj.tag = flow.reconciliation_date.replace("-", "")
        obj.staging = lambda: (stage, stage / "checked.json")
        return obj
    monkeypatch.setattr(runner, "ArExecution", execution)
    return action, flow, result


@pytest.mark.parametrize("owner", ["active", "disabled", "department", "revoked"])
@pytest.mark.parametrize("mode", ["workflow", "pi_harness"])
def test_finished_completion_is_saved_without_next_action(database, tmp_path, monkeypatch, owner, mode):
    with Session(database) as db:
        action, flow, result = prepare(db, tmp_path, monkeypatch, owner=owner, mode=mode)
        runner.transition_phase(db, action, flow, result)
        db.commit()
    with Session(database) as db:
        from app.models import AuditEvent
        flow = db.get(WorkflowSession, "cancel-workflow")
        context = json.loads(flow.context_json)
        assert flow.state == ("succeeded" if owner == "active" else "cancelled")
        assert db.get(WorkflowAction, "completion-action").state == "succeeded"
        assert context["formal_ledgers"]["file_id"]
        assert len(list(db.scalars(select(WorkflowAction)))) == 1
        audits = list(db.scalars(select(AuditEvent).where(AuditEvent.action=="workflow.completion_after_revocation")))
        assert len(audits) == (0 if owner == "active" else 1)
        if audits: assert audits[0].actor_id == "system" and audits[0].actor_role == "system"


@pytest.mark.parametrize("failure", ["wrong_action","expired_lease","attempt_changed","failed_process","wrong_owner_task","unconfirmed_exit","missing_records","journal_changed"])
def test_incomplete_or_wrong_process_evidence_cannot_use_exception(database, tmp_path, monkeypatch, failure):
    with Session(database) as db:
        action, flow, result = prepare(db, tmp_path, monkeypatch, failure=failure)
        with pytest.raises((ValueError, ExecutionLeaseLost)):
            runner.transition_phase(db, action, flow, result)
        db.rollback()
    with Session(database) as db:
        assert {row.id for row in db.scalars(select(FileRecord))} == {"annual","receipt"}
        assert "formal_ledgers" not in json.loads(db.get(WorkflowSession,"cancel-workflow").context_json)


@pytest.mark.parametrize("mode", ["workflow", "pi_harness"])
def test_revoked_completion_stops_remaining_batch_dates(database, tmp_path, monkeypatch, mode):
    from app.models import WorkflowBatch
    with Session(database) as db:
        action, flow, result = prepare(db, tmp_path, monkeypatch, mode=mode)
        fields = dict(owner_id=flow.owner_id, department_id=flow.department_id,
            skill_id=flow.skill_id, skill_name=flow.skill_name, skill_version=flow.skill_version,
            model_connection_id=flow.model_connection_id, model_provider=flow.model_provider,
            model_name=flow.model_name)
        db.add(WorkflowBatch(id="completion-batch", state="running", **fields))
        db.flush()
        flow.batch_id = "completion-batch"
        flow.batch_sequence = 1
        db.add(WorkflowSession(id="remaining-date", batch_id="completion-batch", batch_sequence=2,
            skill_hash=flow.skill_hash, state="queued", stage="preparing", **fields))
        db.commit()
        runner.transition_phase(db, action, flow, result)
        db.commit()
    with Session(database) as db:
        assert db.get(WorkflowBatch, "completion-batch").state == "cancelled"
        assert db.get(WorkflowSession, "remaining-date").state == "cancelled"
        assert len(list(db.scalars(select(WorkflowAction)))) == 1
        assert json.loads(db.get(WorkflowSession, "cancel-workflow").context_json)["formal_ledgers"]


def test_revoked_completion_audit_failure_does_not_commit_success(database, tmp_path, monkeypatch):
    from app import audit_service
    from app.models import AuditEvent
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")
    with Session(database) as db:
        action, flow, result = prepare(db, tmp_path, monkeypatch)
        monkeypatch.setattr(audit_service, "record_audit", fail)
        with pytest.raises(RuntimeError, match="synthetic audit failure"):
            runner.transition_phase(db, action, flow, result)
        db.rollback()
    with Session(database) as db:
        assert db.get(WorkflowAction, "completion-action").state == "running"
        assert db.get(WorkflowSession, "cancel-workflow").state == "running"
        assert "formal_ledgers" not in json.loads(db.get(WorkflowSession, "cancel-workflow").context_json)
        assert {row.id for row in db.scalars(select(FileRecord))} == {"annual", "receipt"}
        assert not list(db.scalars(select(AuditEvent).where(AuditEvent.action == "workflow.completion_after_revocation")))


@pytest.mark.parametrize("exit_code", [0, 7])
def test_real_process_exit_then_revocation_registration(database, tmp_path, monkeypatch, exit_code):
    from app import ar_process_evidence as evidence
    from app.models import AuditEvent
    with Session(database) as db:
        action, flow, result = prepare(db, tmp_path, monkeypatch, owner="active")
        monkeypatch.setattr(evidence, "workflow_root", lambda *_: tmp_path)
        scripts = tmp_path / "skill" / "scripts"
        scripts.mkdir(parents=True)
        # Real child launch and parent-owned prepared/start/exit journal. This
        # synthetic script has no business data, network or workbook writes.
        (scripts / "complete_execution.py").write_text(
            "import sys; print('synthetic completion'); sys.exit(" + str(exit_code) + ")")
        action._ar_process_records = []
        if exit_code:
            with pytest.raises(RuntimeError, match="退出码 7"):
                evidence.run_recorded_script(scripts, "complete_execution.py", [], action=action, workflow=flow)
        else:
            assert evidence.run_recorded_script(scripts, "complete_execution.py", [], action=action, workflow=flow).strip() == "synthetic completion"
        result["process_records"] = list(action._ar_process_records)
        # Independently committed revocation after process exit. Keep the old
        # User instance cached to exercise the current-owner refresh.
        cached_owner = db.get(User, flow.owner_id)
        with Session(database) as administrator:
            administrator.get(User, flow.owner_id).status = "disabled"
            administrator.commit()
        assert cached_owner.status == "active"
        if exit_code:
            with pytest.raises(ValueError, match="成功退出"):
                runner.transition_phase(db, action, flow, result)
            db.rollback()
        else:
            runner.transition_phase(db, action, flow, result)
            db.commit()
    with Session(database) as db:
        flow = db.get(WorkflowSession, "cancel-workflow")
        assert flow.state == ("running" if exit_code else "cancelled")
        assert ("formal_ledgers" in json.loads(flow.context_json)) == (exit_code == 0)
        audits = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "workflow.completion_after_revocation")))
        assert len(audits) == (0 if exit_code else 1)


@pytest.mark.parametrize("phase", ["start", "write", "publish"])
def test_workflow_authorization_observation_tracks_current_facts(database, tmp_path, monkeypatch, phase):
    from app.workflow_execution_policy import workflow_owner_context
    from app.models import AuditEvent
    with Session(database) as db:
        action, flow, _ = prepare(db, tmp_path, monkeypatch, owner="active")
        workflow_owner_context(db, flow)
        assert not list(db.scalars(select(AuditEvent).where(AuditEvent.action == "execution.authorized")))
        workflow_owner_context(db, flow, observe_phase=phase, action=action)
        db.commit()
        first = db.scalar(select(AuditEvent).where(AuditEvent.action == "execution.authorized"))
        first_details = json.loads(first.details_json)
        assert first.resource_type == "workflow" and first.resource_id == flow.id
        assert first_details["phase"] == phase and first_details["attempt"] == 1
        assert first_details["action_id"] == action.id
        assert len(first_details["observation_sha256"]) == 64
        with Session(database) as admin:
            permission = admin.scalar(select(UserSkillPermission).where(UserSkillPermission.user_id == flow.owner_id))
            permission.can_upload = not permission.can_upload
            admin.commit()
        workflow_owner_context(db, flow, observe_phase=phase, action=action)
        db.commit()
        hashes = {json.loads(row.details_json)["observation_sha256"] for row in db.scalars(select(AuditEvent).where(AuditEvent.action == "execution.authorized"))}
        assert len(hashes) == 2
        # Observation and the caller's mutation are rolled back together.
        flow.progress = 19
        workflow_owner_context(db, flow, observe_phase=phase, action=action)
        db.rollback()
        assert db.get(WorkflowSession, flow.id).progress != 19
        assert len(list(db.scalars(select(AuditEvent).where(AuditEvent.action == "execution.authorized")))) == 2


@pytest.mark.parametrize("owner", ["disabled", "department", "revoked"])
def test_rejected_workflow_has_no_authorized_observation(database, tmp_path, monkeypatch, owner):
    from fastapi import HTTPException
    from app.workflow_execution_policy import workflow_owner_context
    from app.models import AuditEvent
    with Session(database) as db:
        action, flow, _ = prepare(db, tmp_path, monkeypatch, owner=owner)
        with pytest.raises(HTTPException) as error:
            workflow_owner_context(db, flow, observe_phase="write", action=action)
        assert error.value.status_code == 403
        assert not list(db.scalars(select(AuditEvent).where(AuditEvent.action == "execution.authorized")))


@pytest.mark.parametrize("audit_fails", [False, True])
def test_script_boundary_requires_committed_authorization_observation(database, tmp_path, monkeypatch, audit_fails):
    from app import ar_process_evidence as evidence
    from app.modules.execution import authorization
    from app.models import AuditEvent
    with Session(database) as db:
        action, flow, _ = prepare(db, tmp_path, monkeypatch, owner="active")
        monkeypatch.setattr(evidence, "workflow_root", lambda *_: tmp_path)
        execution = runner.ArExecution(db, action, flow)
        execution.context = json.loads(flow.context_json)
        execution.scripts = tmp_path / "skill" / "scripts"
        execution.scripts.mkdir(parents=True)
        marker = tmp_path / "child-ran"
        (execution.scripts / "complete_execution.py").write_text(
            "from pathlib import Path; Path(" + repr(str(marker)) + ").write_text('ran')")
        if audit_fails:
            def fail(*args, **kwargs):
                raise RuntimeError("synthetic authorization audit failure")
            monkeypatch.setattr(authorization, "record_audit", fail)
            with pytest.raises(RuntimeError, match="authorization audit failure"):
                execution.script("complete_execution.py", [])
            db.rollback()
            assert not marker.exists()
        else:
            original = evidence.run_recorded_script
            def require_committed_observation(*args, **kwargs):
                with Session(database) as other:
                    event = other.scalar(select(AuditEvent).where(AuditEvent.action == "execution.authorized"))
                    assert event is not None
                    assert json.loads(event.details_json)["phase"] == "start"
                return original(*args, **kwargs)
            monkeypatch.setattr(evidence, "run_recorded_script", require_committed_observation)
            execution.script("complete_execution.py", [])
            assert marker.read_text() == "ran"


@pytest.mark.parametrize("entry", ["workflow", "pi"])
@pytest.mark.parametrize("outcome", ["allowed", "revoked", "audit_failure"])
def test_claim_observation_commits_with_actual_claim(database, tmp_path, monkeypatch, entry, outcome):
    from app.models import AuditEvent
    from app.routers import pi_harness as pi
    from app.modules.execution import authorization
    with Session(database) as db:
        action, flow, _ = prepare(db, tmp_path, monkeypatch,
            owner="revoked" if outcome == "revoked" else "active",
            mode="pi_harness" if entry == "pi" else "workflow")
        action.name = pi.PI_HARNESS_ACTION if entry == "pi" else "prepare_workspace"
        action._stored_state = "queued"
        action.worker_id = ""
        action.attempt_count = 0
        action.lease_expires_at = None
        flow.stage = "preparing"
        db.commit()
    monkeypatch.setattr(runner, "execution_version", lambda *_: "")
    monkeypatch.setattr(pi, "_claim_payload", lambda *_: {"skill": {}})
    if outcome == "audit_failure":
        def fail(*args, **kwargs):
            raise RuntimeError("synthetic claim audit failure")
        monkeypatch.setattr(authorization, "record_audit", fail)
    with Session(database) as db:
        def claim():
            if entry == "pi":
                return pi.claim_pi_harness_work(pi.PiHarnessClaimRequest(worker_id="claim-worker", protocol_version="pi-harness-attempt-v1"), None, db)
            return service.claim_next_workflow_action(db, ("workflow",), "claim-worker")
        if outcome == "audit_failure":
            with pytest.raises(RuntimeError, match="claim audit failure"):
                claim()
            db.rollback()
        else:
            assert (claim() is not None) == (outcome == "allowed")
    with Session(database) as db:
        action = db.get(WorkflowAction, "completion-action")
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "execution.authorized")))
        if outcome == "allowed":
            assert action.state == "running" and action.attempt_count == 1
            assert len(events) == 1
            details = json.loads(events[0].details_json)
            assert details["phase"] == "claim" and details["attempt"] == 1
            assert details["action_id"] == action.id
        else:
            assert action.state == ("queued" if outcome == "audit_failure" else "failed")
            assert action.attempt_count == 0 and not events


@pytest.mark.parametrize("contract", ["current", "legacy"])
@pytest.mark.parametrize("outcome", ["allowed", "revoked", "expired", "cancelled", "audit_failure"])
def test_agent_call_reservation_observes_current_authorization(database, tmp_path, monkeypatch, contract, outcome):
    from app.ar_agent_budget import reserve_agent_call, initial_budget
    from app.modules.execution import authorization
    from app.models import AuditEvent
    from fastapi import HTTPException
    with Session(database) as db:
        action, flow, _ = prepare(db, tmp_path, monkeypatch, owner="revoked" if outcome == "revoked" else "active")
        action.name = "pi_harness_execute"
        context = json.loads(flow.context_json)
        context["ar_agent_budget"] = initial_budget()
        if contract == "legacy": context.pop("ar_execution")
        flow.context_json = json.dumps(context)
        if outcome == "expired": action.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        if outcome == "cancelled": flow.state = "cancelled"
        db.commit()
        if outcome == "audit_failure":
            def fail(*args, **kwargs):
                raise RuntimeError("synthetic reservation audit failure")
            monkeypatch.setattr(authorization, "record_audit", fail)
        if outcome == "allowed":
            reserve_agent_call(db, flow, action, "synthetic-worker", "model_calls", attempt=1)
        else:
            expected = RuntimeError if outcome == "audit_failure" else HTTPException
            with pytest.raises(expected):
                reserve_agent_call(db, flow, action, "synthetic-worker", "model_calls", attempt=1)
            db.rollback()
    with Session(database) as db:
        flow = db.get(WorkflowSession, "cancel-workflow")
        budget = json.loads(flow.context_json)["ar_agent_budget"]
        assert budget["model_calls"] == (1 if contract == "current" and outcome == "allowed" else 0)
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "execution.authorized")))
        assert len(events) == (1 if outcome == "allowed" else 0)
        if events:
            details = json.loads(events[0].details_json)
            assert details["phase"] == "start" and details["action_id"] == "completion-action"


@pytest.mark.parametrize("entry", ["model", "tool"])
@pytest.mark.parametrize("contract", ["current", "legacy"])
def test_pi_http_rechecks_revocation_before_outward_call(database, tmp_path, monkeypatch, entry, contract):
    # The request owns the scheduler write lock while this injected second
    # transaction revokes access. SQLite's database-wide write lock cannot
    # represent this production row-lock race; run it against isolated Postgres.
    if database.dialect.name != "postgresql":
        pytest.skip("concurrent authorization revocation requires PostgreSQL row locks")
    from uuid import uuid4
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import pi_harness as pi
    from app.ar_agent_budget import initial_budget
    from unittest.mock import Mock
    workflow_id, action_id = str(uuid4()), str(uuid4())
    with Session(database) as db:
        _, original, _ = prepare(db, tmp_path, monkeypatch, owner="active")
        context = json.loads(original.context_json)
        context["ar_agent_budget"] = initial_budget()
        if contract == "legacy": context.pop("ar_execution")
        db.add(WorkflowSession(id=workflow_id, owner_id=original.owner_id,
            department_id=original.department_id, skill_id=original.skill_id,
            skill_name=original.skill_name, skill_version=original.skill_version,
            skill_hash=original.skill_hash, model_connection_id=original.model_connection_id,
            model_provider=original.model_provider, model_name=original.model_name,
            state="running", stage="preparing", execution_mode="pi_harness",
            context_json=json.dumps(context)))
        db.flush()
        db.add(WorkflowAction(id=action_id, workflow_id=workflow_id, name="pi_harness_execute",
            state="running", worker_id="http-worker", attempt_count=1,
            lease_expires_at=datetime.now(timezone.utc)+timedelta(minutes=10)))
        db.commit()
    def revoke():
        with Session(database) as admin:
            admin.get(User, "synthetic-owner").status = "disabled"
            admin.commit()
    app = FastAPI()
    app.include_router(pi.router)
    def session():
        with Session(database) as db: yield db
    app.dependency_overrides[pi.get_db] = session
    # Token validation is outside this test; exercise real HTTP body parsing,
    # current owner checks, reservation lock, and the no-outward-call boundary.
    app.dependency_overrides[pi.require_pi_harness_token] = lambda: None
    outward = Mock(side_effect=AssertionError("outward call after revocation"))
    if entry == "model":
        def resolve(*args):
            revoke()
            return SimpleNamespace(provider="synthetic")
        monkeypatch.setattr(pi, "resolve_agent_model_config", resolve)
        monkeypatch.setattr(pi, "build_agent_model_payload", lambda *args: {})
        monkeypatch.setattr(pi, "open_agent_model_stream", outward)
        path = next(route.path for route in pi.router.routes if route.name == "stream_pi_harness_model")
        body = dict(workflow_id=workflow_id, harness_action_id=action_id,
            worker_id="http-worker", attempt=1, model="synthetic", messages=[{"role":"user","content":"synthetic"}])
    else:
        def declared(*args):
            revoke()
            return [{"name":"synthetic_tool"}]
        monkeypatch.setattr(pi, "_declared_tools", declared)
        monkeypatch.setattr(pi, "queue_pi_harness_tool", outward)
        path = next(route.path for route in pi.router.routes if route.name == "request_pi_harness_tool")
        path = path.replace("{workflow_id}",workflow_id).replace("{tool_name}","synthetic_tool")
        body = dict(harness_action_id=action_id, worker_id="http-worker", attempt=1, arguments={})
    with TestClient(app) as client:
        response = client.post(path, json=body)
    assert response.status_code == 403, response.text
    outward.assert_not_called()


@pytest.mark.parametrize("condition", ["valid", "superseded", "expired", "missing_attempt"])
def test_workflow_heartbeat_cannot_renew_another_or_expired_attempt(database, tmp_path, monkeypatch, condition):
    from app import leases
    with Session(database) as db:
        action, flow, _ = prepare(db, tmp_path, monkeypatch, owner="active")
        if condition == "superseded": action.attempt_count = 2
        if condition == "expired": action.lease_expires_at = datetime.now(timezone.utc)-timedelta(seconds=10)
        db.commit()
        deadline = action.lease_expires_at
    monkeypatch.setattr(leases, "SessionLocal", lambda: Session(database))
    heartbeat = leases.LeaseHeartbeat("workflow_action", "completion-action", "synthetic-worker",
        attempt=None if condition == "missing_attempt" else 1)
    updated = heartbeat._touch()
    with Session(database) as db:
        current = db.get(WorkflowAction, "completion-action")
        if condition == "valid": assert current.heartbeat_at is not None
        else: assert current.lease_expires_at == deadline
    assert updated is (condition == "valid")


def test_ar_lock_rejects_reassigned_attempt_with_same_worker(database, tmp_path, monkeypatch):
    with Session(database) as db:
        action, flow, _ = prepare(db, tmp_path, monkeypatch, owner="active")
        action._ar_claim_worker_id = action.worker_id
        action._ar_claim_attempt = action.attempt_count
        with Session(database) as reclaimer:
            current = reclaimer.get(WorkflowAction, action.id)
            current.attempt_count += 1
            reclaimer.commit()
        with pytest.raises(ExecutionLeaseLost):
            runner.lock_execution(db, action, flow)
        db.rollback()
    with Session(database) as db:
        current = db.get(WorkflowAction, "completion-action")
        assert current.attempt_count == 2 and current.state == "running"



def test_heartbeat_waiting_for_row_lock_cannot_revive_expired_lease(database, tmp_path, monkeypatch):
    from app import leases
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    from sqlalchemy import event, text
    if database.dialect.name != "postgresql": pytest.skip("requires PostgreSQL row locks")
    with Session(database) as db:
        action, _, _ = prepare(db, tmp_path, monkeypatch, owner="active")
        action.lease_expires_at = datetime.now(timezone.utc)+timedelta(seconds=1)
        db.commit()
        original_deadline = action.lease_expires_at
    monkeypatch.setattr(leases, "SessionLocal", lambda: Session(database))
    waiting = Event()
    def observe(conn, cursor, statement, parameters, context, executemany):
        if current_thread().name.startswith("late-heartbeat") and "workflow_actions" in statement:
            waiting.set()
    event.listen(database, "before_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="late-heartbeat") as pool:
            with Session(database) as controller:
                controller.execute(select(WorkflowAction.id).where(WorkflowAction.id == "completion-action").with_for_update())
                future = pool.submit(leases.LeaseHeartbeat("workflow_action", "completion-action", "synthetic-worker", attempt=1)._touch)
                try:
                    assert waiting.wait(5)
                    assert not future.done()
                    controller.execute(text("SELECT pg_sleep(1.2)"))
                finally:
                    controller.rollback()
                assert future.result(timeout=10) is False
        with Session(database) as db:
            assert db.get(WorkflowAction, "completion-action").lease_expires_at == original_deadline
    finally:
        event.remove(database, "before_cursor_execute", observe)


@pytest.mark.parametrize("after_outage", ["valid", "expired", "superseded"])
def test_heartbeat_loop_rechecks_database_after_transient_outage(database, tmp_path, monkeypatch, after_outage):
    """A transient connection failure never proves eligibility for a later renewal."""
    from app import leases
    from sqlalchemy.exc import OperationalError
    with Session(database) as db:
        action, _, _ = prepare(db, tmp_path, monkeypatch, owner="active")
        action.lease_expires_at = datetime.now(timezone.utc)+timedelta(seconds=10)
        db.commit()
    attempts = []
    deadlines = []
    def session_factory():
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise OperationalError("synthetic heartbeat", {}, RuntimeError("synthetic unavailable"))
        if len(attempts) == 2:
            with Session(database) as controller:
                action = controller.get(WorkflowAction, "completion-action")
                if after_outage == "expired":
                    action.lease_expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
                elif after_outage == "superseded":
                    action.attempt_count += 1
                controller.commit()
                deadlines.append(action.lease_expires_at)
        return Session(database)
    monkeypatch.setattr(leases, "SessionLocal", session_factory)
    heartbeat = leases.LeaseHeartbeat("workflow_action", "completion-action", "synthetic-worker", attempt=1)
    class ControlledStop:
        def __init__(self): self.calls = 0
        def wait(self, _timeout):
            self.calls += 1
            return self.calls > 2
    heartbeat._stop = ControlledStop()
    heartbeat._loop()
    assert len(attempts) == 2
    assert heartbeat.lease_lost is (after_outage != "valid")
    with Session(database) as db:
        current = db.get(WorkflowAction, "completion-action")
        if after_outage == "valid":
            assert current.heartbeat_at is not None
            assert current.lease_expires_at >= deadlines[0]
        else:
            assert current.lease_expires_at == deadlines[0]
        assert current.attempt_count == (2 if after_outage == "superseded" else 1)
        assert current.state == "running"


@pytest.mark.parametrize("change", ["unchanged", "missing", "hash", "token", "returncode"])
def test_completion_revalidates_descendant_exit_receipt(database, tmp_path, monkeypatch, change):
    from app import ar_process_evidence as evidence
    with Session(database) as db:
        action, flow, result = prepare(db, tmp_path, monkeypatch, owner="active")
        monkeypatch.setattr(evidence, "workflow_root", lambda *_: tmp_path)
        scripts = tmp_path / "skill" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "complete_execution.py").write_text("print('synthetic completion')")
        action._ar_process_records = []
        evidence.run_recorded_script(scripts, "complete_execution.py", [], action=action, workflow=flow)
        result["process_records"] = list(action._ar_process_records)
        reference = result["process_records"][0]
        domain = tmp_path / "execution-processes" / action.id / reference["record_id"] / "domain-exited.json"
        if change == "missing":
            domain.unlink()
        elif change in {"hash", "token", "returncode"}:
            fact = json.loads(domain.read_text())
            if change == "returncode": fact["script_returncode"] = 7
            else: fact["token"] = "0" * 32
            raw = json.dumps(fact).encode()
            domain.write_bytes(raw)
            if change != "hash": reference["domain_exit_sha256"] = hashlib.sha256(raw).hexdigest()
        assert action._ar_process_exit_confirmed is True
        if change == "unchanged":
            assert policy.require_finished_completion(action, flow, result)
        else:
            with pytest.raises((ValueError, OSError)):
                policy.require_finished_completion(action, flow, result)


@pytest.mark.parametrize("owner", ["active", "disabled"])
@pytest.mark.parametrize("missing", [False, True])
def test_actual_registration_checks_domain_for_active_and_revoked_owner(database, tmp_path, monkeypatch, owner, missing):
    from app import ar_process_evidence as evidence
    with Session(database) as db:
        action, flow, result = prepare(db, tmp_path, monkeypatch, owner="active")
        monkeypatch.setattr(evidence, "workflow_root", lambda *_: tmp_path)
        scripts = tmp_path / "skill" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "complete_execution.py").write_text("print('synthetic completion')")
        action._ar_process_records = []
        evidence.run_recorded_script(scripts, "complete_execution.py", [], action=action, workflow=flow)
        result["process_records"] = list(action._ar_process_records)
        if owner == "disabled":
            db.get(User, flow.owner_id).status = "disabled"
            db.commit()
        if missing:
            reference = result["process_records"][0]
            (tmp_path / "execution-processes" / action.id / reference["record_id"] / "domain-exited.json").unlink()
            with pytest.raises(ValueError, match="凭据缺失"):
                runner.transition_phase(db, action, flow, result)
            db.rollback()
            assert {row.id for row in db.scalars(select(FileRecord))} == {"annual", "receipt"}
            assert "formal_ledgers" not in json.loads(flow.context_json)
        else:
            runner.transition_phase(db, action, flow, result)
            db.commit()
            assert json.loads(flow.context_json)["formal_ledgers"]["file_id"]
            assert flow.state == ("succeeded" if owner == "active" else "cancelled")
