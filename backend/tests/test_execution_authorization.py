"""Current identity must gate each ordinary task's claim/start, using synthetic DBs."""
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import worker
from app.auth_models import User, UserSkillPermission
from app.models import RunRecord, RunEvent, StepRun
from test_refactor_event_transactions import database, queued_worker_task


def queued(engine, configure=None):
    queued_worker_task(engine, configure)
    with Session(engine) as db:
        if db.scalar(select(UserSkillPermission).where(UserSkillPermission.user_id == "synthetic-owner",UserSkillPermission.skill_id == "synthetic")) is None:
            db.add(UserSkillPermission(id="synthetic-grant",user_id="synthetic-owner",skill_id="synthetic",can_run=True))
        db.commit()


def revoke(engine, reason):
    with Session(engine) as db:
        user=db.get(User,"synthetic-owner")
        if reason == "disabled": user.status="disabled"
        else:
            user.role="finance_user"
            db.scalar(select(UserSkillPermission).where(UserSkillPermission.user_id == user.id)).can_run=False
        db.commit()


@pytest.mark.parametrize("reason", ["disabled","revoked","demoted"])
def test_revoked_queued_task_never_claims_or_executes(database, reason):
    queued(database)
    if reason == "demoted":
        with Session(database) as db:
            db.get(User,"synthetic-owner").role="skill_admin"
            db.commit()
    revoke(database,reason)
    with Session(database) as db:
        assert worker.claim_next_run(db,("python",),"worker") is None
    with Session(database) as db:
        run=db.get(RunRecord,"synthetic-run")
        assert run.state == "failed" and run.attempt_count == 0
        assert "权限" in run.error_message
        event=db.scalar(select(RunEvent).where(RunEvent.state == "failed"))
        assert "AUTHORIZATION_REVOKED" in event.data_json
        assert db.scalar(select(StepRun).where(StepRun.state == "running")) is None


@pytest.mark.parametrize("reason", ["disabled","revoked","demoted"])
def test_revocation_after_claim_blocks_adapter(database, monkeypatch, tmp_path, reason):
    queued(database)
    if reason == "demoted":
        with Session(database) as db:
            db.get(User,"synthetic-owner").role="skill_admin"
            db.commit()
    adapter=Mock()
    monkeypatch.setattr(worker,"get_adapter",lambda _:adapter)
    monkeypatch.setattr(worker,"run_root",lambda *args:tmp_path/"work")
    with Session(database) as db:
        run=worker.claim_next_run(db,("python",),"worker")
        revoke(database,reason)
        worker.execute_run(db,run)
    adapter.execute.assert_not_called()
    with Session(database) as db:
        assert db.get(RunRecord,"synthetic-run").state == "failed"
        event=db.scalar(select(RunEvent).where(RunEvent.state == "failed"))
        assert "AUTHORIZATION_REVOKED" in event.data_json


def test_worker_receives_current_admin_role_instead_of_fixed_finance_role(database, monkeypatch, tmp_path):
    queued(database)
    with Session(database) as db:
        db.get(User,"synthetic-owner").role="skill_admin"
        db.scalar(select(UserSkillPermission)).can_run=False
        db.commit()
    seen=[]
    def execute(ctx):
        seen.append(ctx.owner)
        return {"summary":{}}
    monkeypatch.setattr(worker,"get_adapter",lambda _:SimpleNamespace(execute=execute))
    monkeypatch.setattr(worker,"run_root",lambda *args:tmp_path/"work")
    with Session(database) as db:
        run=worker.claim_next_run(db,("python",),"worker")
        worker.execute_run(db,run)
    assert len(seen)==1 and seen[0].is_admin
    with Session(database) as db:
        assert db.get(RunRecord,"synthetic-run").state == "succeeded"


@pytest.mark.parametrize("phase", ["confirm", "cancel"])
def test_stale_admin_cannot_mutate_another_owners_task(database, phase):
    from app.auth import UserContext
    from app.run_service import confirm_run, cancel_run
    from fastapi import HTTPException
    queued(database)
    with Session(database) as db:
        db.add(User(id="other-user",username="other-user",department_id="finance",role="finance_user",password_hash="synthetic-only"))
        run=db.get(RunRecord,"synthetic-run")
        run.state="waiting_confirmation"
        db.commit()
        actor=UserContext("other-user","Other","skill_admin","finance")
        with pytest.raises(HTTPException) as error:
            (confirm_run if phase == "confirm" else cancel_run)(db,run,actor)
        assert error.value.status_code==404
        db.rollback()
        assert db.get(RunRecord,run.id).state=="waiting_confirmation"


def test_active_owner_can_cancel_after_skill_revocation(database):
    from app.auth import UserContext
    from app.run_service import cancel_run
    queued(database)
    revoke(database,"revoked")
    with Session(database) as db:
        actor=UserContext("synthetic-owner","Synthetic","finance_user","finance")
        run=cancel_run(db,db.get(RunRecord,"synthetic-run"),actor)
        assert run.state=="cancelled"
        db.rollback()
    with Session(database) as db:
        assert db.get(RunRecord,"synthetic-run").state=="queued"


def test_owner_department_snapshot_cannot_follow_current_department(database):
    from app.modules.execution.authorization import execution_owner,ExecutionPhase,ExecutionAuthorizationRevoked
    queued(database)
    with Session(database) as db:
        historical=SimpleNamespace(owner_id="synthetic-owner",department_id="different-department",skill_id="synthetic")
        with pytest.raises(ExecutionAuthorizationRevoked):
            execution_owner(db,historical,ExecutionPhase.START)


@pytest.mark.parametrize("department", ["finance", "other"])
def test_administrator_cancel_records_actual_actor_and_keeps_department_scope(database,department):
    from app.auth import UserContext
    from app.main import cancel
    from app.models import AuditEvent
    from fastapi import HTTPException
    queued(database)
    revoke(database,"disabled")
    with Session(database) as db:
        db.add(User(id="cancel-admin",username="cancel-admin",department_id=department,role="skill_admin",password_hash="synthetic-only"))
        db.commit()
        actor=UserContext("cancel-admin","Admin","skill_admin",department)
        if department == "other":
            with pytest.raises(HTTPException) as error:cancel("synthetic-run",db,actor)
            assert error.value.status_code == 404
            db.rollback()
            assert db.scalar(select(AuditEvent).where(AuditEvent.action == "run.cancel")) is None
        else:
            assert cancel("synthetic-run",db,actor).state == "cancelled"
            audit=db.scalar(select(AuditEvent).where(AuditEvent.action == "run.cancel"))
            assert audit.actor_id == actor.user_id and audit.actor_role == "skill_admin"
            assert audit.resource_id == "synthetic-run" and audit.department_id == "finance"


def test_cancel_waits_for_worker_terminal_commit_without_overwriting_success(database):
    if database.dialect.name != "postgresql":pytest.skip("Real row-lock race requires PostgreSQL")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    from sqlalchemy import event
    from app.auth import UserContext
    from app.main import cancel
    from app.run_fencing import bind_run_fence
    from fastapi import HTTPException
    queued(database)
    with Session(database) as db:worker.claim_next_run(db,("python",),"worker")
    waiting=Event()
    def observe(conn,cursor,statement,parameters,context,executemany):
        if current_thread().name.startswith("cancel-race") and "FOR UPDATE" in statement and "FROM runs" in statement:
            waiting.set()
    event.listen(database,"before_cursor_execute",observe)
    def cancellation():
        with Session(database) as db:
            try:cancel("synthetic-run",db,UserContext("synthetic-owner","Synthetic","finance_user","finance"))
            except HTTPException as exc:return exc.status_code
    try:
        with Session(database) as finishing, ThreadPoolExecutor(max_workers=1,thread_name_prefix="cancel-race") as pool:
            run=finishing.get(RunRecord,"synthetic-run")
            bind_run_fence(finishing,run)
            run.state="succeeded";run.progress_message="completed before cancel"
            finishing.flush()
            future=pool.submit(cancellation)
            try:
                assert waiting.wait(5)
                assert not future.done()
            finally:
                finishing.commit()
            assert future.result(timeout=10)==409
        with Session(database) as db:
            run=db.get(RunRecord,"synthetic-run")
            assert run.state == "succeeded" and not run.cancel_requested
            assert run.progress_message == "completed before cancel"
    finally:event.remove(database,"before_cursor_execute",observe)


@pytest.mark.parametrize("operation,payload", [("stop", {}), ("jobs", {"operation":"cancel","job_id":"synthetic"})])
@pytest.mark.parametrize("change", ["disabled", "department"])
def test_pi_stop_checks_current_identity_even_without_skill_grant(database, monkeypatch, operation, payload, change):
    from app import pi_runtime_service as runtime, database as database_module
    from app.auth import UserContext
    from fastapi import HTTPException
    monkeypatch.setattr(database_module,"SessionLocal",lambda:Session(database))
    actor=UserContext("synthetic-owner","Synthetic","finance_user","finance")
    session=runtime.create_session(actor,"Synthetic identity")
    with Session(database) as db:
        owner=db.get(User,actor.user_id)
        if change == "disabled":owner.status="disabled"
        else:owner.department_id="other"
        db.commit()
    dispatched=MagicMock()
    dispatched.return_value.__enter__.return_value.post.return_value=SimpleNamespace(status_code=200,json=lambda:{"stopped":True})
    monkeypatch.setattr(runtime.httpx,"Client",dispatched)
    with pytest.raises(HTTPException) as error:
        runtime.operate(actor,session["id"],operation,payload)
    assert error.value.status_code==403
    dispatched.assert_not_called()


@pytest.mark.parametrize("operation,payload", [("stop", {}), ("jobs", {"operation":"cancel","job_id":"synthetic"})])
def test_pi_revoked_skill_allows_own_stop_but_rejects_send(database, monkeypatch, operation, payload):
    from app import pi_runtime_service as runtime, database as database_module
    from app.auth import UserContext
    from fastapi import HTTPException
    monkeypatch.setattr(database_module,"SessionLocal",lambda:Session(database))
    actor=UserContext("synthetic-owner","Synthetic","skill_admin","finance")
    # Actual stored role is finance_user. No native--synthetic grant exists.
    session=runtime.create_session(actor,"Synthetic stop",{"id":"synthetic","commit":"a"*40})
    client=Mock();client.__enter__=Mock(return_value=client);client.__exit__=Mock(return_value=False)
    client.post.return_value=SimpleNamespace(status_code=200,json=lambda:{"stopped":True})
    monkeypatch.setattr(runtime.httpx,"Client",lambda **kwargs:client)
    assert runtime.operate(actor,session["id"],operation,payload)=={"stopped":True}
    assert client.post.call_count==1
    with pytest.raises(HTTPException) as error:runtime.operate(actor,session["id"],"send",{"text":"blocked"})
    assert error.value.status_code==403
    assert client.post.call_count==1


def test_pi_stop_rechecks_identity_after_session_lock(database, monkeypatch):
    from app import pi_runtime_service as runtime, database as database_module
    from app.auth import UserContext
    from fastapi import HTTPException
    monkeypatch.setattr(database_module,"SessionLocal",lambda:Session(database))
    actor=UserContext("synthetic-owner","Synthetic","finance_user","finance")
    session=runtime.create_session(actor,"Synthetic lock")
    original=runtime.fcntl.flock
    def revoke_on_lock(file, operation):
        original(file,operation)
        with Session(database) as db:
            db.get(User,actor.user_id).status="disabled"
            db.commit()
    monkeypatch.setattr(runtime.fcntl,"flock",revoke_on_lock)
    dispatched=MagicMock()
    monkeypatch.setattr(runtime.httpx,"Client",dispatched)
    with pytest.raises(HTTPException) as error:runtime.operate(actor,session["id"],"stop",{})
    assert error.value.status_code==403
    dispatched.assert_not_called()


@pytest.mark.parametrize("state", ["demoted", "disabled", "department"])
def test_pi_publish_rechecks_administrator_before_reading_proposal(database, monkeypatch, state):
    from contextlib import nullcontext
    from app import pi_skill_drafts as drafts
    from app.auth import UserContext
    from fastapi import HTTPException
    with Session(database) as db:
        user=db.get(User,"synthetic-owner")
        user.role="finance_user" if state=="demoted" else "skill_admin"
        if state=="disabled":user.status="disabled"
        if state=="department":user.department_id="other"
        db.commit()
    actor=UserContext("synthetic-owner","Synthetic","skill_admin","finance")
    read=Mock(return_value={"sha256":"a"*64,"state":"published"})
    monkeypatch.setattr(drafts,"get",read)
    monkeypatch.setattr(drafts.native.source,"_source_guard",lambda **kwargs:nullcontext())
    with Session(database) as db:
        with pytest.raises(HTTPException) as error:drafts.publish(db,actor,"synthetic-proposal","a"*64)
        assert error.value.status_code==403
    read.assert_not_called()


def test_pi_current_admin_can_read_published_proposal_replay(database, monkeypatch):
    from contextlib import nullcontext
    from app import pi_skill_drafts as drafts
    from app.auth import UserContext
    with Session(database) as db:
        db.get(User,"synthetic-owner").role="skill_admin"
        db.commit()
    actor=UserContext("synthetic-owner","Synthetic","skill_admin","finance")
    value={"sha256":"a"*64,"state":"published"}
    monkeypatch.setattr(drafts,"get",lambda *args:value)
    monkeypatch.setattr(drafts.native.source,"_source_guard",lambda **kwargs:nullcontext())
    with Session(database) as db:assert drafts.publish(db,actor,"synthetic-proposal","a"*64)==value


def test_pi_publication_waits_for_account_change_before_authorizing(database, monkeypatch):
    if database.dialect.name!="postgresql":pytest.skip("Requires real PostgreSQL row locks")
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import nullcontext
    from threading import Event, current_thread
    from sqlalchemy import event
    from app import pi_skill_drafts as drafts
    from app.auth import UserContext
    from app.scheduler import acquire_claim_lock
    from fastapi import HTTPException
    with Session(database) as db:
        db.get(User,"synthetic-owner").role="skill_admin";db.commit()
    waiting=Event();read=Mock(return_value={"sha256":"a"*64,"state":"published"})
    monkeypatch.setattr(drafts,"get",read)
    monkeypatch.setattr(drafts.native.source,"_source_guard",lambda **kwargs:nullcontext())
    def observe(conn,cursor,statement,parameters,context,executemany):
        if current_thread().name.startswith("publish-race") and "scheduler_locks" in statement and "FOR UPDATE" in statement:waiting.set()
    def publish():
        with Session(database) as db:
            try:drafts.publish(db,UserContext("synthetic-owner","Synthetic","skill_admin","finance"),"synthetic","a"*64)
            except HTTPException as error:return error.status_code
    event.listen(database,"before_cursor_execute",observe)
    try:
        with Session(database) as changing, ThreadPoolExecutor(max_workers=1,thread_name_prefix="publish-race") as pool:
            acquire_claim_lock(changing)
            changing.get(User,"synthetic-owner").role="finance_user"
            changing.flush()
            future=pool.submit(publish)
            try:
                assert waiting.wait(5)
                assert not future.done()
            finally:changing.commit()
            assert future.result(timeout=10)==403
        # Preparation may read the proposal before the concurrent revocation commits.
        # The final locked publication must reject before its second read/write.
        assert read.call_count == 1
    finally:event.remove(database,"before_cursor_execute",observe)


def test_pi_publication_source_contention_releases_scheduler_lock(database, monkeypatch):
    from contextlib import contextmanager
    from threading import Event, Thread
    from app import pi_skill_drafts as drafts
    from app.auth import UserContext
    from app.scheduler import acquire_claim_lock
    from sqlalchemy import text
    from fastapi import HTTPException
    with Session(database) as db:
        db.get(User,"synthetic-owner").role="skill_admin";db.commit()
    actor=UserContext("synthetic-owner","Synthetic","skill_admin","finance")
    original=drafts.native.source._source_guard
    held=Event();release=Event()
    def contender():
        with original():
            held.set();assert release.wait(10)
    thread=Thread(target=contender)
    @contextmanager
    def guard(*,blocking=True):
        with original(blocking=blocking):yield
        if blocking:
            thread.start();assert held.wait(5)
    monkeypatch.setattr(drafts.native.source,"_source_guard",guard)
    monkeypatch.setattr(drafts,"get",lambda *args:{"sha256":"a"*64,"state":"published"})
    try:
        with Session(database) as db:
            with pytest.raises(HTTPException) as error:drafts.publish(db,actor,"synthetic","a"*64)
            assert error.value.status_code==409
            db.rollback()
        with Session(database) as scheduling:
            if database.dialect.name=="postgresql":scheduling.execute(text("SET LOCAL lock_timeout='500ms'"))
            acquire_claim_lock(scheduling)
    finally:
        release.set();thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.mark.parametrize("revoke_after_preparation", [False, True])
def test_pi_real_candidate_publication_and_revocation(database, monkeypatch, tmp_path, revoke_after_preparation):
    import io,json,zipfile,hashlib
    from uuid import uuid4
    from contextlib import contextmanager
    from app import pi_skill_drafts as drafts
    from app.auth import UserContext
    from app.contracts import NativeSkillRead
    from app.models import AuditEvent
    from fastapi import HTTPException
    actor=UserContext("synthetic-owner","Old name","skill_admin","finance")
    with Session(database) as db:
        user=db.get(User,actor.user_id);user.role="skill_admin";user.display_name="Current name";db.commit()
    native=tmp_path/"native";(native/"installed").mkdir(parents=True)
    monkeypatch.setattr(drafts.native,"native_root",lambda:native)
    monkeypatch.setattr(drafts,"root",lambda user:tmp_path/"proposals"/drafts.owner_scope(user))
    current=NativeSkillRead(id="synthetic",name="Synthetic",description="Before",commit="b"*40,source_path="synthetic",installed_at="2026-09-20T00:00:00+00:00")
    index=native/"installed/synthetic.json";index.write_text(current.model_dump_json());before=index.read_bytes()
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w") as z:z.writestr("SKILL.md","---\nname: Synthetic\ndescription: After\n---\nSynthetic only")
    raw=buffer.getvalue();digest=hashlib.sha256(raw).hexdigest();identity=str(uuid4());directory=drafts.root(actor)/identity;directory.mkdir(parents=True)
    value={"id":identity,"owner":drafts.owner_scope(actor),"department_id":"finance","skill_id":"synthetic","base_commit":current.commit,"sha256":digest,"state":"pending"}
    (directory/"package.zip").write_bytes(raw);(directory/"proposal.json").write_text(json.dumps(value))
    original=drafts.native.source._source_guard
    @contextmanager
    def guard(*,blocking=True):
        with original(blocking=blocking):yield
        if blocking and revoke_after_preparation:
            with Session(database) as db:db.get(User,actor.user_id).role="finance_user";db.commit()
    monkeypatch.setattr(drafts.native.source,"_source_guard",guard)
    with Session(database) as db:
        if revoke_after_preparation:
            with pytest.raises(HTTPException) as error:drafts.publish(db,actor,identity,digest)
            assert error.value.status_code==403
            db.rollback()
        else:assert drafts.publish(db,actor,identity,digest)["state"]=="published"
    with Session(database) as db:
        audits=list(db.scalars(select(AuditEvent).where(AuditEvent.action=="pi.skill.publish")))
        if revoke_after_preparation:
            assert not audits and index.read_bytes()==before
            assert json.loads((directory/"proposal.json").read_text())["state"]=="pending"
        else:
            installed=drafts.native.installed_skill("synthetic")
            assert installed.commit!=current.commit
            assert (native/"packages/synthetic"/installed.commit/"SKILL.md").is_file()
            assert len(audits)==1 and audits[0].actor_id==actor.user_id and audits[0].actor_role=="skill_admin"


@pytest.fixture
def native_install_case(database, monkeypatch, tmp_path):
    import io,zipfile
    from app import native_skill_service as native
    from app.auth import UserContext
    from app.contracts import SkillInstallRequest
    with Session(database) as db:
        db.get(User,"synthetic-owner").role="skill_admin";db.commit()
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w") as z:z.writestr("SKILL.md","---\nname: Synthetic\ndescription: Native test\n---\nSynthetic only")
    raw=buffer.getvalue();root=tmp_path/"native"
    monkeypatch.setattr(native,"native_root",lambda:root)
    monkeypatch.setattr(native,"_check_tree_sizes",lambda *args:None)
    monkeypatch.setattr(native.source,"_cache_repository",lambda *args:(tmp_path/"repo","a"*40))
    monkeypatch.setattr(native.source,"_git_command",lambda *args:raw)
    return native,UserContext("synthetic-owner","Synthetic","skill_admin","finance"),SkillInstallRequest(source_path="skills/synthetic",expected_commit="a"*40),root,raw


@pytest.mark.parametrize("change", ["demoted","disabled","department"])
def test_native_install_rechecks_identity_after_package_fetch(database, monkeypatch, native_install_case,change):
    from fastapi import HTTPException
    from app.models import AuditEvent
    native,actor,body,root,raw=native_install_case
    def fetch(*args):
        with Session(database) as db:
            user=db.get(User,actor.user_id)
            if change=="demoted":user.role="finance_user"
            elif change=="disabled":user.status="disabled"
            else:user.department_id="other"
            db.commit()
        return raw
    monkeypatch.setattr(native.source,"_git_command",fetch)
    with Session(database) as db:
        with pytest.raises(HTTPException) as error:native.install_native_skill(db,actor,body)
        assert error.value.status_code==403
        db.rollback()
    assert not (root/"installed/synthetic.json").exists()
    with Session(database) as db:assert db.scalar(select(AuditEvent).where(AuditEvent.action=="native_skill.install")) is None


def test_native_install_success_keeps_fixed_package_and_actual_actor(database,native_install_case):
    from app.models import AuditEvent
    native,actor,body,root,raw=native_install_case
    with Session(database) as db:
        result=native.install_native_skill(db,actor,body)
        assert result.commit==body.expected_commit
    assert native.installed_skill("synthetic").commit==body.expected_commit
    assert (root/"packages/synthetic"/body.expected_commit/"SKILL.md").is_file()
    with Session(database) as db:
        audit=db.scalar(select(AuditEvent).where(AuditEvent.action=="native_skill.install"))
        assert audit.actor_id==actor.user_id and audit.actor_role=="skill_admin"


def test_native_install_does_not_overwrite_concurrent_activation(database, monkeypatch,native_install_case):
    from contextlib import contextmanager
    from fastapi import HTTPException
    native,actor,body,root,raw=native_install_case
    original=native.source._source_guard
    newer=b'{"commit":"newer-synthetic-version"}'
    @contextmanager
    def guard(*,blocking=True):
        with original(blocking=blocking):yield
        if blocking:
            index=root/"installed/synthetic.json";index.parent.mkdir(parents=True);index.write_bytes(newer)
    monkeypatch.setattr(native.source,"_source_guard",guard)
    with Session(database) as db:
        with pytest.raises(HTTPException) as error:native.install_native_skill(db,actor,body)
        assert error.value.status_code==409
        db.rollback()
    assert (root/"installed/synthetic.json").read_bytes()==newer


@pytest.mark.parametrize("change", ["revoked", "disabled", "demoted"])
def test_ar_started_script_finishes_readback_but_next_script_is_denied(database,monkeypatch,tmp_path,change):
    import json,time
    from datetime import datetime,UTC,timedelta
    from concurrent.futures import ThreadPoolExecutor
    from app import ar_execution_runner as runner,ar_process_evidence as evidence,workflow_service as service
    from app.models import WorkflowSession,WorkflowAction,WorkflowMaterialSet
    from fastapi import HTTPException
    root=tmp_path/"task";scripts=root/"skill/vendor/scripts";scripts.mkdir(parents=True)
    started=root/"started";release=root/"release";written=root/"written";readback=root/"readback";next_write=root/"next-write"
    (scripts/"synthetic_atomic.py").write_text(
        "from pathlib import Path\nimport sys,time\n"
        "root=Path(sys.argv[1]);(root/'written').write_text('synthetic result');(root/'started').touch()\n"
        "deadline=time.monotonic()+10\n"
        "while not (root/'release').exists():\n"
        " if time.monotonic()>deadline:raise RuntimeError('synthetic release timeout')\n"
        " time.sleep(0.01)\n"
        "assert (root/'written').read_text()=='synthetic result'\n"
        "(root/'readback').write_text('verified');print('verified')\n")
    (scripts/"synthetic_next.py").write_text("from pathlib import Path\nimport sys\n(Path(sys.argv[1])/'next-write').touch()\n")
    monkeypatch.setattr(evidence,"workflow_root",lambda *args:root)
    with Session(database) as db:
        if change=="demoted":
            db.get(User,"synthetic-owner").role="skill_admin"
            db.scalar(select(UserSkillPermission)).can_run=False
        material=WorkflowMaterialSet(id="synthetic-material",owner_id="synthetic-owner",department_id="finance",skill_id="synthetic",version=1)
        db.add(material);db.flush()
        wf=WorkflowSession(id="synthetic-wf",owner_id="synthetic-owner",department_id="finance",skill_id="synthetic",skill_name="Synthetic",skill_version="1",skill_hash="a"*64,model_connection_id="synthetic",model_provider="synthetic",model_name="synthetic",state="running",reconciliation_date="2026-09-01",material_set_id=material.id)
        db.add(wf);db.flush()
        action=WorkflowAction(id="synthetic-action",workflow_id=wf.id,name="ar_write_ledger",state="running",worker_id="synthetic-worker",attempt_count=1,lease_expires_at=datetime.now(UTC)+timedelta(minutes=5))
        db.add(action);db.commit()
        # Exercise the actual script/lease/identity/material/process seam. The
        # constructor's workbook setup belongs to separate material tests.
        execution=object.__new__(runner.ArExecution)
        execution.db=db;execution.action=action;execution.workflow=wf;execution.service=service
        execution.scripts=scripts;execution.context={};execution.date=wf.reconciliation_date
        execution.execution={"reconciliation_date":wf.reconciliation_date,"skill_hash":wf.skill_hash,"material_set_id":material.id,"material_version":1}
        def withdraw():
            deadline=time.monotonic()+10
            while not started.exists():
                if time.monotonic()>deadline:raise AssertionError("synthetic child did not start")
                time.sleep(0.01)
            try:revoke(database,change)
            finally:release.touch()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(withdraw)
            output=execution.script("synthetic_atomic.py",[str(root)])
            future.result(timeout=10)
        assert output.strip()=="verified" and readback.read_text()=="verified"
        assert written.read_text()=="synthetic result"
        assert action._ar_process_exit_confirmed is True
        facts=action._ar_process_records
        assert len(facts)==1 and facts[0]["state"]=="exited" and facts[0]["direct_process_exit_confirmed"]
        exit_fact=json.loads((root/"execution-processes"/action.id/facts[0]["record_id"]/"exited.json").read_text())
        assert exit_fact["communication_completed"] and exit_fact["returncode"]==0
        with pytest.raises(HTTPException) as error:execution.script("synthetic_next.py",[str(root)])
        assert error.value.status_code==403
        assert not next_write.exists() and len(action._ar_process_records)==1
        db.rollback()
        # Isolate publication authorization from workbook staging, while keeping
        # the actual final-report fingerprint and current material/lease checks.
        execution.execution["steps"]={"build_final_report":{"final_result":{"path":str(written),"fingerprint":service.sha256_file(written)}}}
        monkeypatch.setattr(execution,"staging",lambda:(root,root/"unused-plan.json"))
        monkeypatch.setattr(execution,"_require_staged_fingerprints",lambda *args:None)
        publish=Mock()
        monkeypatch.setattr(service,"_publish_verified_material_set",publish)
        with pytest.raises(HTTPException) as error:execution.publish_reconciliation()
        assert error.value.status_code==403
        publish.assert_not_called()
        db.rollback()
        assert db.get(WorkflowMaterialSet,"synthetic-material").version==1


@pytest.mark.parametrize("change,entry", [
    ("unchanged", "request"), ("content_and_record", "request"),
    ("department", "request"), ("owner", "request"), ("kind", "request"),
    ("copy_race", "request"), ("stale_record", "request"),
    ("admin_same_department", "request"), ("demoted_admin", "request"),
    ("copy_race", "python"), ("copy_race", "rpa"), ("content_and_record", "http"),
])
def test_ordinary_input_snapshot_is_fixed_before_execution(database, tmp_path, monkeypatch, change, entry):
    """Real file copies and DB rows must match the submitted binding, not each other only."""
    import hashlib
    import json
    from pathlib import Path
    from app import adapters
    from app.adapters import ExecutionContext, build_execution_request
    from app.auth import UserContext
    from app.models import FileRecord
    from app.registry import SkillManifest

    queued(database)
    source = tmp_path / "synthetic-input.txt"
    original = b"synthetic submitted bytes"
    source.write_bytes(original)
    pinned_hash = hashlib.sha256(original).hexdigest()
    with Session(database) as db:
        db.add(FileRecord(id="synthetic-input", owner_id="synthetic-owner",
            department_id="finance", kind="input", original_name=source.name,
            stored_path=str(source), size_bytes=len(original), sha256=pinned_hash))
        run = db.get(RunRecord, "synthetic-run")
        run.files_json = json.dumps({"input": {"file_id": "synthetic-input",
            "sha256": pinned_hash, "name": source.name, "size_bytes": len(original)}})
        from app.registry import hash_skill_directory
        skill = tmp_path / "skill"
        skill.mkdir()
        raw = json.loads(run.manifest_snapshot)
        raw["id"], raw["version"] = run.skill_id, run.skill_version
        run.manifest_snapshot = json.dumps(raw)
        (skill / "tool.yaml").write_text(json.dumps(raw))
        run.manifest_path = str(skill / "tool.yaml")
        run.skill_hash = hash_skill_directory(skill)
        from app.modules.execution.input_snapshot import input_snapshot_hash
        run.input_hash = input_snapshot_hash(run.parameters_json, json.loads(run.files_json), run.skill_hash)
        db.commit()
    with Session(database) as db:
        run = db.get(RunRecord, "synthetic-run")
        if change in {"admin_same_department", "demoted_admin"}:
            db.get(User, "synthetic-owner").role = "skill_admin"
            db.get(FileRecord, "synthetic-input").owner_id = "other-owner"
            db.commit()
            if change == "demoted_admin":
                with Session(database) as other:
                    other.get(User, "synthetic-owner").role = "finance_user"
                    other.commit()
        # Keep this object referenced so a stale identity-map row really exists.
        cached = db.get(FileRecord, "synthetic-input")
        if change in {"content_and_record", "stale_record", "department", "owner", "kind"}:
            with Session(database) as other:
                record = other.get(FileRecord, "synthetic-input")
                if change == "content_and_record":
                    source.write_bytes(b"synthetic replacement bytes")
                    record.sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
                elif change in {"department", "stale_record"}:
                    record.department_id = "other-department"
                elif change == "owner": record.owner_id = "other-owner"
                else: record.kind = "output"
                other.commit()
            if change != "stale_record": db.expire(cached)
        if change == "copy_race":
            real_copy = adapters.copy_input_to_workspace
            def replace_before_copy(*args, **kwargs):
                source.write_bytes(b"synthetic changed during copy")
                return real_copy(*args, **kwargs)
            monkeypatch.setattr(adapters, "copy_input_to_workspace", replace_before_copy)
        workspace = tmp_path / "execution"
        ctx = ExecutionContext(db, run, SkillManifest.model_validate_json(run.manifest_snapshot),
            tmp_path / "skill", workspace,
            UserContext("synthetic-owner", "Synthetic", "finance_user", "finance"))
        if change in {"admin_same_department", "demoted_admin"}:
            ctx.owner = UserContext("synthetic-owner", "Synthetic", "skill_admin", "finance")
        popen = Mock(side_effect=AssertionError("No subprocess should start"))
        post = Mock(side_effect=AssertionError("No HTTP request should be sent"))
        monkeypatch.setattr(adapters.subprocess, "Popen", popen)
        monkeypatch.setattr(adapters.httpx, "post", post)
        if change in {"unchanged", "admin_same_department"}:
            payload, request_path = build_execution_request(ctx)
            copied = Path(payload["files"]["input"]["local_path"])
            assert copied.read_bytes() == original
            assert payload["files"]["input"]["sha256"] == pinned_hash
            assert request_path.is_file()
        else:
            with pytest.raises(RuntimeError) as error:
                if entry == "request": build_execution_request(ctx)
                else: adapters.get_adapter(entry).execute(ctx)
            assert "输入文件" in str(error.value)
            assert not (workspace / "request.json").exists()
        popen.assert_not_called()
        post.assert_not_called()


@pytest.mark.parametrize("phase", ["claim", "start"])
@pytest.mark.parametrize("record", ["complete", "missing_actor", "missing_time", "missing_both", "flag_disabled"])
def test_confirmation_is_required_at_claim_and_start(database, monkeypatch, tmp_path, phase, record):
    import json
    from datetime import UTC, datetime
    def configure(run):
        manifest = json.loads(run.manifest_snapshot)
        manifest["risk"]["requires_confirmation"] = True
        run.manifest_snapshot = json.dumps(manifest)
        run.confirmation_required = True
        run.confirmed_by = "synthetic-owner"
        run.confirmed_at = datetime.now(UTC)
    queued(database, configure)
    adapter = Mock()
    adapter.execute.return_value = {"summary": {}}
    monkeypatch.setattr(worker, "get_adapter", lambda _: adapter)
    monkeypatch.setattr(worker, "run_root", lambda *args: tmp_path / "work")
    def require_confirmation(db):
        run = db.get(RunRecord, "synthetic-run")
        run.confirmation_required = record != "flag_disabled"
        run.confirmed_by = "synthetic-owner" if record not in {"missing_actor", "missing_both"} else ""
        run.confirmed_at = datetime.now(UTC) if record not in {"missing_time", "missing_both"} else None
        db.commit()
    with Session(database) as db:
        if phase == "claim": require_confirmation(db)
        run = worker.claim_next_run(db, ("python",), "worker")
        if phase == "start":
            with Session(database) as other: require_confirmation(other)
            worker.execute_run(db, run)
        if record == "complete":
            if phase == "claim": assert run is not None
            else: adapter.execute.assert_called_once()
        else:
            if phase == "claim": assert run is None
            adapter.execute.assert_not_called()
    with Session(database) as db:
        run = db.get(RunRecord, "synthetic-run")
        if record != "complete":
            assert run.state == "failed"
            assert run.attempt_count == (0 if phase == "claim" else 1)
            event = db.scalar(select(RunEvent).where(RunEvent.state == "failed"))
            assert "CONFIRMATION_INVALID" in event.data_json


@pytest.mark.parametrize("change", ["unchanged", "script", "manifest", "missing", "symlink", "database_manifest", "adapter"])
def test_adapter_requires_fixed_skill_snapshot(database, tmp_path, change):
    import json
    import shutil
    from app.adapters import ExecutionContext, build_execution_request
    from app.auth import UserContext
    from app.registry import SkillManifest, hash_skill_directory
    queued(database)
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "scripts").mkdir()
    script = skill / "scripts/entry.py"
    script.write_text("# synthetic pinned script\n")
    with Session(database) as db:
        run = db.get(RunRecord, "synthetic-run")
        raw = json.loads(run.manifest_snapshot)
        raw["id"], raw["version"] = run.skill_id, run.skill_version
        (skill / "tool.yaml").write_text(json.dumps(raw))
        run.skill_hash = hash_skill_directory(skill)
        run.manifest_path = str(skill / "tool.yaml")
        run.manifest_snapshot = json.dumps(raw)
        run.files_json = "{}"
        from app.modules.execution.input_snapshot import input_snapshot_hash
        run.input_hash = input_snapshot_hash(run.parameters_json, {}, run.skill_hash)
        db.commit()
        if change == "script": script.write_text("# changed after submission\n")
        elif change == "manifest": (skill / "tool.yaml").write_text("{}")
        elif change == "missing": shutil.rmtree(skill)
        elif change == "symlink":
            target = tmp_path / "outside.py"
            target.write_text(script.read_text())
            script.unlink()
            script.symlink_to(target)
        elif change == "database_manifest":
            raw["risk"]["requires_confirmation"] = True
        elif change == "adapter": run.adapter = "http"
        ctx = ExecutionContext(db, run, SkillManifest.model_validate(raw), skill,
            tmp_path / "attempt", UserContext("synthetic-owner", "Synthetic", "finance_user", "finance"))
        if change == "unchanged":
            _, request = build_execution_request(ctx)
            assert request.is_file()
        else:
            with pytest.raises(RuntimeError, match="快照"):
                build_execution_request(ctx)
            assert not (ctx.workspace / "request.json").exists()


@pytest.mark.parametrize("entry", ["confirm", "adapter"])
@pytest.mark.parametrize("change", ["unchanged", "parameters", "binding", "missing_hash"])
def test_input_digest_blocks_changed_submission(database, tmp_path, entry, change):
    import hashlib
    import json
    from fastapi import HTTPException
    from app.adapters import ExecutionContext, build_execution_request
    from app.auth import UserContext
    from app.registry import SkillManifest, hash_skill_directory
    from app.run_service import confirm_run
    skill = tmp_path / "skill"
    skill.mkdir()
    raw = {}
    def configure(run):
        nonlocal raw
        raw = json.loads(run.manifest_snapshot)
        raw["id"], raw["version"] = run.skill_id, run.skill_version
        (skill / "tool.yaml").write_text(json.dumps(raw))
        run.skill_hash = hash_skill_directory(skill)
        run.manifest_path = str(skill / "tool.yaml")
        run.manifest_snapshot = json.dumps(raw)
        run.files_json = "{}"
        run.parameters_json = '{"amount": 10}'
        # Existing persisted protocol: sorted role/hash digest + raw prepared
        # parameter JSON + canonical bindings + pinned Skill directory hash.
        files_digest = hashlib.sha256(b"").hexdigest()
        payload_digest = hashlib.sha256((run.parameters_json + "{}" + run.skill_hash).encode()).hexdigest()
        run.input_hash = hashlib.sha256(f"{files_digest}:{payload_digest}".encode()).hexdigest()
        run.state = "waiting_confirmation"
    queued(database, configure)
    with Session(database) as db:
        run = db.get(RunRecord, "synthetic-run")
        if change == "parameters": run.parameters_json = '{"amount": 11}'
        elif change == "binding": run.files_json = '{"unexpected": null}'
        elif change == "missing_hash": run.input_hash = ""
        db.commit()
        actor = UserContext("synthetic-owner", "Synthetic", "finance_user", "finance")
        def invoke():
            if entry == "confirm": return confirm_run(db, run, actor)
            return build_execution_request(ExecutionContext(db, run, SkillManifest.model_validate(raw),
                skill, tmp_path / "attempt", actor))
        if change == "unchanged": invoke()
        else:
            with pytest.raises((RuntimeError, HTTPException)) as error: invoke()
            message = str(getattr(error.value, "detail", error.value))
            assert "快照" in message
            assert run.confirmed_at is None and not run.confirmed_by
            assert not (tmp_path / "attempt/request.json").exists()


@pytest.mark.parametrize("target", ["workflow", "batch"])
@pytest.mark.parametrize("change", ["active", "disabled", "moved_stale", "moved_current", "revoked", "demoted"])
def test_workflow_cancel_uses_current_identity(database, target, change):
    from app.auth import UserContext
    from app.models import WorkflowSession, WorkflowBatch, AuditEvent
    from app.workflow_service import cancel_workflow, cancel_workflow_batch
    from fastapi import HTTPException
    with Session(database) as db:
        _cancellation_fixture(db, target)
        owner = db.get(User, "synthetic-owner")
        if change == "disabled": owner.status = "disabled"
        elif change.startswith("moved_"): owner.department_id = "other-department"
        elif change == "revoked": db.scalar(select(UserSkillPermission)).can_run = False
        db.commit()
        actor = UserContext("synthetic-owner", "Synthetic",
            "skill_admin" if change == "demoted" else "finance_user",
            "other-department" if change == "moved_current" else "finance")
        invoke = cancel_workflow if target == "workflow" else cancel_workflow_batch
        identifier = "cancel-workflow" if target == "workflow" else "cancel-batch"
        if change in {"active", "revoked", "demoted"}:
            result = invoke(db, identifier, actor)
            assert result.state == "cancelled"
            audit = db.scalar(select(AuditEvent).where(AuditEvent.resource_id == identifier))
            assert audit.actor_id == actor.user_id and audit.department_id == "finance"
            assert audit.actor_role == "finance_user"
        else:
            with pytest.raises(HTTPException) as error: invoke(db, identifier, actor)
            assert error.value.status_code in {403, 404}
            db.rollback()
            assert db.get(WorkflowSession, "cancel-workflow").state == "queued"
            assert db.scalar(select(AuditEvent).where(AuditEvent.resource_id == identifier)) is None


def _cancellation_fixture(db, target):
    from app.models import WorkflowSession, WorkflowBatch
    fields = dict(owner_id="synthetic-owner", department_id="finance", skill_id="synthetic",
        skill_name="Synthetic", skill_version="1", model_connection_id="synthetic-model",
        model_provider="synthetic", model_name="synthetic", state="queued")
    if target == "batch":
        db.add(WorkflowBatch(id="cancel-batch", **fields))
        db.flush()
    db.add(WorkflowSession(id="cancel-workflow", skill_hash="a" * 64,
        batch_id="cancel-batch" if target == "batch" else None,
        stage="preparing", **fields))


@pytest.mark.parametrize("target", ["workflow", "batch"])
def test_workflow_cancel_rechecks_identity_after_real_lock_wait(database, target):
    if database.dialect.name != "postgresql": pytest.skip("Requires real row-lock wait")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    from sqlalchemy import event
    from fastapi import HTTPException
    from app.auth import UserContext
    from app.models import WorkflowSession, AuditEvent
    from app.scheduler import acquire_claim_lock
    from app.workflow_service import cancel_workflow, cancel_workflow_batch
    with Session(database) as db:
        _cancellation_fixture(db, target)
        db.commit()
    waiting = Event()
    def observe(conn, cursor, statement, parameters, context, executemany):
        if current_thread().name.startswith("workflow-cancel-race") and "scheduler_locks" in statement and "FOR UPDATE" in statement:
            waiting.set()
    def cancel():
        with Session(database) as db:
            actor = UserContext("synthetic-owner", "Synthetic", "finance_user", "finance")
            invoke = cancel_workflow if target == "workflow" else cancel_workflow_batch
            identifier = "cancel-workflow" if target == "workflow" else "cancel-batch"
            try: invoke(db, identifier, actor)
            except HTTPException as error: return error.status_code
            return 200
    event.listen(database, "before_cursor_execute", observe)
    try:
        with Session(database) as admin, ThreadPoolExecutor(max_workers=1, thread_name_prefix="workflow-cancel-race") as pool:
            acquire_claim_lock(admin)
            future = pool.submit(cancel)
            try:
                assert waiting.wait(5)
                assert not future.done()
                admin.get(User, "synthetic-owner").status = "disabled"
            finally:
                admin.commit()
            assert future.result(timeout=10) == 403
        with Session(database) as db:
            assert db.get(WorkflowSession, "cancel-workflow").state == "queued"
            assert db.scalar(select(AuditEvent).where(AuditEvent.action.in_(["workflow.cancel", "workflow.batch.cancel"]))) is None
    finally:
        event.remove(database, "before_cursor_execute", observe)


@pytest.mark.parametrize("target", ["workflow", "batch"])
@pytest.mark.parametrize("transition", ["atomic_write", "running_read", "finished"])
def test_workflow_cancel_refreshes_cached_execution_state(database, target, transition):
    import json
    from fastapi import HTTPException
    from app.auth import UserContext
    from app.models import WorkflowSession, WorkflowBatch, WorkflowAction
    from app.workflow_service import (get_workflow_or_404, get_workflow_batch_or_404,
        cancel_workflow, cancel_workflow_batch)
    actor = UserContext("synthetic-owner", "Synthetic", "finance_user", "finance")
    with Session(database) as db:
        _cancellation_fixture(db, target)
        db.flush()
        db.add(WorkflowAction(id="cancel-action", workflow_id="cancel-workflow",
            name="apply_confirmed" if transition == "atomic_write" else "fetch_zhiyun", state="queued"))
        db.commit()
    with Session(database) as request:
        # Mirrors the message endpoint's pre-lock visibility read. Keep all
        # objects/relationships strongly referenced across the other commit.
        cached = get_workflow_or_404(request, "cancel-workflow", actor)
        cached_actions = cached.actions
        if target == "batch": cached_batch = get_workflow_batch_or_404(request, "cancel-batch", actor)
        assert cached.stage == "preparing" and cached_actions[0].state == "queued"
        with Session(database) as executing:
            flow = executing.get(WorkflowSession, "cancel-workflow")
            flow.stage = "applying" if transition == "atomic_write" else "preparing"
            flow.state = "succeeded" if transition == "finished" else "running"
            executing.get(WorkflowAction, "cancel-action").state = "succeeded" if transition == "finished" else "running"
            if target == "batch": executing.get(WorkflowBatch, "cancel-batch").state = flow.state
            executing.commit()
        invoke = cancel_workflow if target == "workflow" else cancel_workflow_batch
        identifier = "cancel-workflow" if target == "workflow" else "cancel-batch"
        if transition == "atomic_write":
            with pytest.raises(HTTPException) as error: invoke(request, identifier, actor)
            assert error.value.status_code == 409
            request.rollback()
        else:
            result = invoke(request, identifier, actor)
            assert result.state == ("succeeded" if transition == "finished" else "cancelling")
    with Session(database) as check:
        action = check.get(WorkflowAction, "cancel-action")
        assert action.state == ("succeeded" if transition == "finished" else "running")
        if transition == "running_read":
            assert json.loads(check.get(WorkflowSession, "cancel-workflow").context_json)["stop_after_action"] is True


@pytest.mark.parametrize("entry", ["agent", "message"])
@pytest.mark.parametrize("change", ["disabled", "moved", "atomic_write"])
def test_agent_cancel_revalidates_after_decision(database, monkeypatch, entry, change):
    from fastapi import HTTPException
    from app.auth import UserContext
    from app.models import WorkflowSession, WorkflowAction, AuditEvent
    from app import workflow_service as service
    actor = UserContext("synthetic-owner", "Synthetic", "finance_user", "finance")
    with Session(database) as db:
        _cancellation_fixture(db, "workflow")
        db.flush()
        db.add(WorkflowAction(id="cancel-action", workflow_id="cancel-workflow",
            name="apply_confirmed", state="queued"))
        db.commit()
    monkeypatch.setattr(service, "workflow_owner_context", lambda *a: actor)
    monkeypatch.setattr(service, "assert_workflow_execution_enabled", lambda *a: None)
    monkeypatch.setattr(service, "assert_workflow_agent_action_enabled", lambda *a: None)
    monkeypatch.setattr(service, "is_background_model_connection", lambda *a: True)
    def transition():
        # A real independent commit while validation/model work is in progress.
        with Session(database) as other:
            if change == "disabled": other.get(User, actor.user_id).status = "disabled"
            elif change == "moved": other.get(User, actor.user_id).department_id = "other-department"
            else:
                workflow = other.get(WorkflowSession, "cancel-workflow")
                workflow.stage, workflow.state = "applying", "running"
                other.get(WorkflowAction, "cancel-action").state = "running"
            other.commit()
    def decision(*args):
        if change != "atomic_write": transition()
        return service.WorkflowDecision("cancel", {}, "synthetic")
    original_lock = service.acquire_claim_lock
    def lock(db):
        # Message insertion holds the workflow row until the pre-lock commit.
        # Transition there rather than deadlocking against our own fixture.
        if change == "atomic_write": transition()
        original_lock(db)
    monkeypatch.setattr(service, "acquire_claim_lock", lock)
    monkeypatch.setattr(service, "validate_workflow_agent_request", decision)
    monkeypatch.setattr(service, "decide_workflow_turn", decision)
    with Session(database) as db:
        workflow = service.get_workflow_or_404(db, "cancel-workflow", actor)
        with pytest.raises(HTTPException) as error:
            if entry == "agent": service.apply_workflow_agent_action(db, workflow, "cancel", {}, actor)
            else: service.send_workflow_message(db, workflow, "synthetic cancel decision", actor)
        assert error.value.status_code == (409 if change == "atomic_write" else 403)
        db.rollback()
    with Session(database) as db:
        assert db.get(WorkflowSession, "cancel-workflow").state == ("running" if change == "atomic_write" else "queued")
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "workflow.cancel")) is None


@pytest.mark.parametrize("entry", ["rebuild", "batch"])
@pytest.mark.parametrize("change", ["disabled", "moved", "demoted", "foreign_admin", "active_admin"])
def test_workflow_recovery_requires_current_actual_actor(database, monkeypatch, entry, change):
    from fastapi import HTTPException
    from app.auth import UserContext
    from app.models import WorkflowSession, WorkflowBatch
    from app import workflow_service as service, ar_report_recovery, ar_rebuild_policy
    with Session(database) as db:
        _cancellation_fixture(db, "batch" if entry == "batch" else "workflow")
        db.flush()
        workflow = db.get(WorkflowSession, "cancel-workflow")
        workflow.state, workflow.stage, workflow.reconciliation_date = "failed", "failed", "2026-08-20"
        if entry == "batch": db.get(WorkflowBatch, "cancel-batch").state = "failed"
        db.add(User(id="recovery-admin", username="recovery-admin", department_id="other" if change == "foreign_admin" else "finance",
            role="skill_admin", password_hash="synthetic-only"))
        db.commit()
    actor = UserContext("recovery-admin", "Synthetic admin", "skill_admin", "other" if change == "foreign_admin" else "finance")
    reached = Mock(return_value=True)
    monkeypatch.setattr(ar_report_recovery, "recover_report", reached)
    monkeypatch.setattr(ar_rebuild_policy, "legacy_rebuild_block_reason", lambda _: None)
    monkeypatch.setattr(service, "has_service_credential", reached)
    # Stop immediately after the real identity gate, before business effects.
    class BoundaryReached(Exception): pass
    reached.side_effect = BoundaryReached
    with Session(database) as db:
        obj = db.get(WorkflowBatch if entry == "batch" else WorkflowSession,
                     "cancel-batch" if entry == "batch" else "cancel-workflow")
        original_lock = service.acquire_claim_lock
        def lock(session):
            with Session(database) as admin:
                user = admin.get(User, actor.user_id)
                if change == "disabled": user.status = "disabled"
                elif change == "moved": user.department_id = "other"
                elif change == "demoted": user.role = "finance_user"
                admin.commit()
            original_lock(session)
        monkeypatch.setattr(service, "acquire_claim_lock", lock)
        invoke = service.retry_workflow_batch if entry == "batch" else service.rebuild_failed_workflow
        if change == "active_admin":
            with pytest.raises(BoundaryReached): invoke(db, obj, actor)
            reached.assert_called_once()
        else:
            with pytest.raises(HTTPException) as error: invoke(db, obj, actor)
            assert error.value.status_code in {403, 404}
            reached.assert_not_called()
        db.rollback()
    with Session(database) as db:
        assert db.get(WorkflowSession, "cancel-workflow").state == "failed"


@pytest.mark.parametrize("change", ["disabled", "moved", "revoked", "stale_admin", "other_user", "foreign_admin", "active_owner", "active_admin", "stage_changed"])
def test_direct_workflow_agent_action_current_actor_and_stage(database, change):
    from fastapi import HTTPException
    from app.auth import UserContext
    from app.models import WorkflowSession, WorkflowMessage
    from app import workflow_service as service
    with Session(database) as db:
        _cancellation_fixture(db, "workflow")
        db.flush()
        flow = db.get(WorkflowSession, "cancel-workflow")
        flow.stage, flow.state = "awaiting_date", "active"
        flow.reconciliation_date = "2026-08-19"
        db.add(User(id="agent-caller", username="agent-caller", department_id="other" if change == "foreign_admin" else "finance",
            role="skill_admin" if change in {"stale_admin", "foreign_admin", "active_admin"} else "finance_user", password_hash="synthetic-only"))
        db.commit()
    own = change in {"disabled", "moved", "revoked", "active_owner", "stage_changed"}
    actor = UserContext("synthetic-owner" if own else "agent-caller", "Synthetic",
        "skill_admin" if change in {"stale_admin", "foreign_admin", "active_admin"} else "finance_user",
        "other" if change == "foreign_admin" else "finance")
    with Session(database) as request:
        workflow = request.get(WorkflowSession, "cancel-workflow")
        assert workflow.stage == "awaiting_date"
        with Session(database) as other:
            user = other.get(User, actor.user_id)
            if change == "disabled": user.status = "disabled"
            elif change == "moved": user.department_id = "other"
            elif change == "revoked": other.scalar(select(UserSkillPermission).where(UserSkillPermission.user_id == user.id)).can_run = False
            elif change == "stale_admin": user.role = "finance_user"
            elif change == "stage_changed":
                flow = other.get(WorkflowSession, workflow.id)
                flow.stage, flow.state = "applying", "running"
            other.commit()
        def invoke(): return service.apply_workflow_agent_action(request, workflow, "set_reconciliation_date", {"date": "2026-08-20"}, actor)
        if change in {"active_owner", "active_admin"}:
            result = invoke()
            assert result.workflow.reconciliation_date == "2026-08-20"
        else:
            with pytest.raises(HTTPException) as error: invoke()
            assert error.value.status_code == 409 if change == "stage_changed" else error.value.status_code in {403, 404}
            request.rollback()
    with Session(database) as db:
        flow = db.get(WorkflowSession, "cancel-workflow")
        if change not in {"active_owner", "active_admin"}:
            assert flow.reconciliation_date == "2026-08-19"
            assert db.scalar(select(WorkflowMessage).where(WorkflowMessage.workflow_id == flow.id)) is None


@pytest.mark.parametrize("change", ["disabled", "moved", "revoked", "date", "stage", "context", "materials", "unchanged"])
@pytest.mark.parametrize("decision_action", ["confirm_date", "confirm_apply"])
def test_chat_decision_rechecks_after_model(database, monkeypatch, change, decision_action):
    from sqlalchemy import text
    from fastapi import HTTPException
    from app.auth import UserContext
    from app.models import WorkflowSession, WorkflowMessage, WorkflowAction
    from app import workflow_service as service
    initial_stage = "awaiting_date_confirmation" if decision_action == "confirm_date" else "awaiting_apply_confirmation"
    actor = UserContext("synthetic-owner", "Synthetic", "finance_user", "finance")
    with Session(database) as db:
        _cancellation_fixture(db, "workflow")
        db.flush()
        flow = db.get(WorkflowSession, "cancel-workflow")
        flow.stage, flow.state = initial_stage, "active"
        flow.reconciliation_date = "2026-08-19"
        db.commit()
    monkeypatch.setattr(service, "is_background_model_connection", lambda *_: True)
    def model(*args):
        # Simulates a bounded external call while another request changes facts.
        assert not request.in_transaction()
        with Session(database) as other:
            if database.dialect.name == "postgresql": other.execute(text("SET LOCAL lock_timeout = '500ms'"))
            from app.scheduler import acquire_claim_lock
            acquire_claim_lock(other)
            if change == "disabled": other.get(User, actor.user_id).status = "disabled"
            elif change == "moved": other.get(User, actor.user_id).department_id = "other"
            elif change == "revoked": other.scalar(select(UserSkillPermission).where(UserSkillPermission.user_id == actor.user_id)).can_run = False
            elif change in {"date", "stage", "context", "materials"}:
                flow = other.get(WorkflowSession, "cancel-workflow")
                if change == "date": flow.reconciliation_date = "2026-08-20"
                elif change == "stage": flow.stage, flow.state = "applying", "running"
                elif change == "context": flow.context_json = '{"new_preview":true}'
                else: flow.files_json = '{"synthetic":"new-binding"}'
            other.commit()
        return service.WorkflowDecision(decision_action, {}, "synthetic")
    monkeypatch.setattr(service, "decide_workflow_turn", model)
    with Session(database) as request:
        workflow = request.get(WorkflowSession, "cancel-workflow")
        if change == "unchanged":
            result = service.send_workflow_message(request, workflow, "确认", actor)
            assert result.stage == ("awaiting_files" if decision_action == "confirm_date" else "applying")
        else:
            with pytest.raises(HTTPException) as error:
                service.send_workflow_message(request, workflow, "确认", actor)
            assert error.value.status_code == (403 if change in {"disabled", "moved", "revoked"} else 409)
            request.rollback()
    with Session(database) as db:
        flow = db.get(WorkflowSession, "cancel-workflow")
        if change != "unchanged":
            assert flow.stage == ("applying" if change == "stage" else initial_stage)
            assert db.scalar(select(WorkflowMessage).where(WorkflowMessage.workflow_id == flow.id, WorkflowMessage.role == "assistant")) is None

            assert db.scalar(select(WorkflowAction).where(WorkflowAction.workflow_id == flow.id)) is None


@pytest.mark.parametrize("change", ["stale_admin", "other_user", "foreign_admin"])
def test_chat_rejects_caller_before_model(database, monkeypatch, change):
    from fastapi import HTTPException
    from app.auth import UserContext
    from app.models import WorkflowSession
    from app import workflow_service as service
    with Session(database) as db:
        _cancellation_fixture(db, "workflow")
        db.add(User(id="chat-caller", username="chat-caller", department_id="other" if change == "foreign_admin" else "finance",
            role="skill_admin" if change == "foreign_admin" else "finance_user", password_hash="synthetic-only"))
        db.commit()
    actor = UserContext("chat-caller", "Synthetic", "skill_admin" if change != "other_user" else "finance_user", "other" if change == "foreign_admin" else "finance")
    model = Mock(return_value=service.WorkflowDecision("reply", {"content":"synthetic"}, "synthetic"))
    monkeypatch.setattr(service, "decide_workflow_turn", model)
    monkeypatch.setattr(service, "is_background_model_connection", lambda *_: True)
    with Session(database) as db:
        with pytest.raises(HTTPException) as error:
            service.send_workflow_message(db, db.get(WorkflowSession, "cancel-workflow"), "synthetic", actor)
        assert error.value.status_code in {403, 404}
        model.assert_not_called()


@pytest.mark.parametrize("change", ["disabled", "moved", "revoked", "stale_admin", "other_user", "foreign_admin", "active_owner", "active_admin", "stage_changed"])
def test_workflow_reset_current_actor_and_stage(database, change):
    from fastapi import HTTPException
    from app.auth import UserContext
    from app.models import WorkflowSession, WorkflowMessage, AuditEvent
    from app import workflow_service as service
    with Session(database) as db:
        _cancellation_fixture(db, "workflow")
        db.flush()
        flow = db.get(WorkflowSession, "cancel-workflow")
        flow.stage, flow.state = "awaiting_date_confirmation", "active"
        flow.reconciliation_date = "2026-08-19"
        flow.files_json, flow.context_json = '{"synthetic":"binding"}', '{"synthetic":"context"}'
        db.add(User(id="reset-caller", username="reset-caller", department_id="other" if change == "foreign_admin" else "finance",
            role="skill_admin" if change in {"stale_admin", "foreign_admin", "active_admin"} else "finance_user", password_hash="synthetic-only"))
        db.commit()
    own = change in {"disabled", "moved", "revoked", "active_owner", "stage_changed"}
    actor = UserContext("synthetic-owner" if own else "reset-caller", "Synthetic",
        "skill_admin" if change in {"stale_admin", "foreign_admin", "active_admin"} else "finance_user",
        "other" if change == "foreign_admin" else "finance")
    with Session(database) as request:
        workflow = request.get(WorkflowSession, "cancel-workflow")
        assert workflow.stage == "awaiting_date_confirmation"
        with Session(database) as other:
            user = other.get(User, actor.user_id)
            if change == "disabled": user.status = "disabled"
            elif change == "moved": user.department_id = "other"
            elif change == "revoked": other.scalar(select(UserSkillPermission).where(UserSkillPermission.user_id == user.id)).can_run = False
            elif change == "stale_admin": user.role = "finance_user"
            elif change == "stage_changed":
                flow = other.get(WorkflowSession, workflow.id)
                flow.stage, flow.state = "applying", "running"
            other.commit()
        if change in {"active_owner", "active_admin"}:
            result = service.reset_workflow(request, workflow, actor)
            assert result.stage == "awaiting_date" and result.reconciliation_date == ""
        else:
            with pytest.raises(HTTPException) as error: service.reset_workflow(request, workflow, actor)
            assert error.value.status_code in ({409} if change == "stage_changed" else {403, 404})
            request.rollback()
    with Session(database) as db:
        flow = db.get(WorkflowSession, "cancel-workflow")
        if change not in {"active_owner", "active_admin"}:
            assert flow.reconciliation_date == "2026-08-19"
            assert flow.files_json == '{"synthetic":"binding"}' and flow.context_json == '{"synthetic":"context"}'
            assert db.scalar(select(WorkflowMessage).where(WorkflowMessage.workflow_id == flow.id)) is None
        else:
            assert flow.files_json == "{}" and flow.context_json == "{}"
            audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "workflow.reset"))
            assert audit.actor_id == actor.user_id and audit.actor_role == actor.role


@pytest.mark.parametrize("target", ["single", "batch"])
@pytest.mark.parametrize("change", ["stale_admin", "foreign_admin", "stage_changed", "active_owner", "active_admin", "audit_failure", "snapshot"])
def test_supplement_endpoint_identity_state_and_atomic_audit(database, monkeypatch, target, change):
    import json
    from fastapi import HTTPException
    from app.auth import UserContext
    from app.models import WorkflowSession, WorkflowBatch, WorkflowMaterialSet, WorkflowAction, AuditEvent
    from app import main, workflow_service as service
    from app.schemas import WorkflowFetchedDataSupplement, WorkflowBatchFetchedDataSupplement
    with Session(database) as db:
        _cancellation_fixture(db, "batch" if target == "batch" else "workflow")
        db.add(WorkflowMaterialSet(id="supplement-material", owner_id="synthetic-owner", department_id="finance", skill_id="synthetic", version=1, state="current"))
        db.flush()
        flow = db.get(WorkflowSession, "cancel-workflow")
        flow.stage, flow.state = "awaiting_fetched_data_confirmation", "active"
        flow.reconciliation_date = "2026-08-19"
        flow.material_set_id = "supplement-material"
        flow.context_json = json.dumps({"fetched_data":{"available":True,"source":"snapshot" if change == "snapshot" else "live"}})
        if target == "batch":
            batch = db.get(WorkflowBatch, "cancel-batch")
            batch.material_set_id, batch.reconciliation_dates_json = "supplement-material", '["2026-08-19"]'
        db.add(User(id="supplement-admin", username="supplement-admin", department_id="other" if change == "foreign_admin" else "finance", role="skill_admin", password_hash="synthetic-only"))
        db.commit()
    admin = change in {"stale_admin", "foreign_admin", "active_admin"}
    actor = UserContext("supplement-admin" if admin else "synthetic-owner", "Synthetic", "skill_admin" if admin else "finance_user", "other" if change == "foreign_admin" else "finance")
    monkeypatch.setattr(main, "serialize_workflow", lambda obj: obj)
    monkeypatch.setattr(main, "_serialize_workflow_batch_for_user", lambda _db, _user, obj: obj)
    class AuditFailure(Exception): pass
    if change == "audit_failure":
        def fail(*args, **kwargs): raise AuditFailure("synthetic audit append failure")
        monkeypatch.setattr(main, "record_audit", fail)
        monkeypatch.setattr(service, "record_audit", fail)
    with Session(database) as request:
        cached = request.get(WorkflowSession, "cancel-workflow")
        cached_batch = request.get(WorkflowBatch, "cancel-batch") if target == "batch" else None
        with Session(database) as other:
            if change == "stale_admin": other.get(User, actor.user_id).role = "finance_user"
            elif change == "stage_changed":
                flow = other.get(WorkflowSession, cached.id)
                flow.stage, flow.state = "applying", "running"
            other.commit()
        def invoke():
            if target == "single":
                return main.supplement_workflow_fetched_data("cancel-workflow", WorkflowFetchedDataSupplement(ar_ids=["AR26080156"], so_ids=[]), request, actor)
            return main.supplement_workflow_batch_fetched_data("cancel-batch", WorkflowBatchFetchedDataSupplement(reconciliation_date="2026-08-19", ar_ids=["AR26080156"], so_ids=[]), request, actor)
        if change in {"active_owner", "active_admin"}: invoke()
        elif change == "audit_failure":
            with pytest.raises(AuditFailure): invoke()
            request.rollback()
        else:
            with pytest.raises(HTTPException) as error: invoke()
            assert error.value.status_code in ({409} if change in {"stage_changed", "snapshot"} else {403, 404})
            request.rollback()
    with Session(database) as db:
        actions = list(db.scalars(select(WorkflowAction).where(WorkflowAction.workflow_id == "cancel-workflow")))
        audits = list(db.scalars(select(AuditEvent).where(AuditEvent.action.in_(["workflow.fetched_data.supplement", "workflow_batch.fetched_data.supplement.requested"]))))
        flow = db.get(WorkflowSession, "cancel-workflow")
        if change in {"active_owner", "active_admin"}:
            assert len(actions) == len(audits) == 1 and actions[0].state == "queued"
            assert audits[0].actor_id == actor.user_id and audits[0].actor_role == actor.role
            assert flow.stage == "supplementing_fetched_data"
        else:
            assert actions == [] and audits == []
            assert flow.stage == ("applying" if change == "stage_changed" else "awaiting_fetched_data_confirmation")

@pytest.mark.parametrize("target", ["single", "batch"])
@pytest.mark.parametrize("change", ["stale_admin", "foreign_admin", "stage_changed", "active_owner", "active_admin", "audit_failure"])
def test_confirmation_endpoint_identity_state_and_atomic_audit(database, monkeypatch, target, change):
    import json
    from fastapi import HTTPException
    from app.auth import UserContext
    from app.models import WorkflowSession, WorkflowBatch, WorkflowMaterialSet, WorkflowAction, AuditEvent
    from app import main, workflow_service as service
    
    with Session(database) as db:
        _cancellation_fixture(db, "batch" if target == "batch" else "workflow")
        db.add(WorkflowMaterialSet(id="supplement-material", owner_id="synthetic-owner", department_id="finance", skill_id="synthetic", version=1, state="current"))
        db.flush()
        flow = db.get(WorkflowSession, "cancel-workflow")
        flow.stage, flow.state = "awaiting_fetched_data_confirmation", "active"
        flow.reconciliation_date = "2026-08-19"
        flow.material_set_id = "supplement-material"
        flow.context_json = json.dumps({"fetched_data":{"available":True,"source":"live"}})
        if target == "batch":
            batch = db.get(WorkflowBatch, "cancel-batch")
            batch.material_set_id, batch.reconciliation_dates_json = "supplement-material", '["2026-08-19"]'
        db.add(User(id="supplement-admin", username="supplement-admin", department_id="other" if change == "foreign_admin" else "finance", role="skill_admin", password_hash="synthetic-only"))
        db.commit()
    admin = change in {"stale_admin", "foreign_admin", "active_admin"}
    actor = UserContext("supplement-admin" if admin else "synthetic-owner", "Synthetic", "skill_admin" if admin else "finance_user", "other" if change == "foreign_admin" else "finance")
    monkeypatch.setattr(main, "serialize_workflow", lambda obj: obj)
    monkeypatch.setattr(main, "_serialize_workflow_batch_for_user", lambda _db, _user, obj: obj)
    class AuditFailure(Exception): pass
    if change == "audit_failure":
        def fail(*args, **kwargs): raise AuditFailure("synthetic audit append failure")
        monkeypatch.setattr(main, "record_audit", fail)
        monkeypatch.setattr(service, "record_audit", fail)
    with Session(database) as request:
        cached = request.get(WorkflowSession, "cancel-workflow")
        cached_batch = request.get(WorkflowBatch, "cancel-batch") if target == "batch" else None
        with Session(database) as other:
            if change == "stale_admin": other.get(User, actor.user_id).role = "finance_user"
            elif change == "stage_changed":
                flow = other.get(WorkflowSession, cached.id)
                flow.stage, flow.state = "applying", "running"
            other.commit()
        def invoke():
            if target == "single":
                return main.confirm_workflow_fetched_data("cancel-workflow", request, actor)
            return main.confirm_workflow_batch_fetched_data("cancel-batch", request, actor)
        if change in {"active_owner", "active_admin"}: invoke()
        elif change == "audit_failure":
            with pytest.raises(AuditFailure): invoke()
            request.rollback()
        else:
            with pytest.raises(HTTPException) as error: invoke()
            assert error.value.status_code in ({409} if change in {"stage_changed", "snapshot"} else {403, 404})
            request.rollback()
    with Session(database) as db:
        actions = list(db.scalars(select(WorkflowAction).where(WorkflowAction.workflow_id == "cancel-workflow")))
        audits = list(db.scalars(select(AuditEvent).where(AuditEvent.action.in_(["workflow.fetched_data.confirm", "workflow_batch.fetched_data.confirm"]))))
        flow = db.get(WorkflowSession, "cancel-workflow")
        if change in {"active_owner", "active_admin"}:
            assert len(actions) == len(audits) == 1 and actions[0].state == "queued"
            assert audits[0].actor_id == actor.user_id and audits[0].actor_role == actor.role
            assert flow.stage == "preparing"
        else:
            assert actions == [] and audits == []
            assert flow.stage == ("applying" if change == "stage_changed" else "awaiting_fetched_data_confirmation")


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("empty", [False, True])
def test_confirmation_core_obeys_caller_rollback(database, monkeypatch, automatic, empty):
    import json
    from app.auth import UserContext
    from app.models import WorkflowSession, WorkflowAction, AuditEvent
    from app import workflow_service as service
    with Session(database) as db:
        _cancellation_fixture(db, "workflow")
        flow = db.get(WorkflowSession, "cancel-workflow")
        flow.stage, flow.state = "awaiting_fetched_data_confirmation", "waiting_confirmation"
        flow.reconciliation_date = "2026-08-19"
        fetched = {"available": True}
        if empty:
            fetched["summary_by_date"] = {"2026-08-19": {key: 0 for key in service.FETCHED_DATASET_COUNT_KEYS.values()}}
        flow.context_json = json.dumps({"fetched_data": fetched})
        db.commit()
    from app.resource_policy import workflow_root
    (workflow_root("synthetic-owner", "cancel-workflow") / "skill").mkdir(parents=True, exist_ok=True)
    # Only replace external snapshot verification; transaction/state code is real.
    monkeypatch.setattr(service, "is_ar_skill", lambda _: True)
    monkeypatch.setattr(service, "_validated_snapshot_for_date", lambda *args: object())
    actor = UserContext("synthetic-owner", "Synthetic", "finance_user", "finance")
    with Session(database) as db:
        service.acquire_claim_lock(db)
        flow = db.get(WorkflowSession, "cancel-workflow")
        service.confirm_fetched_data_review(db, flow, actor, automatic=automatic)
        assert flow.stage == ("completed" if empty else "preparing")
        if not empty:
            service.confirm_fetched_data_review(db, flow, actor, automatic=automatic)
            assert len(list(db.scalars(select(WorkflowAction)))) == 1
        db.rollback()
    with Session(database) as db:
        assert db.get(WorkflowSession, "cancel-workflow").stage == "awaiting_fetched_data_confirmation"
        assert list(db.scalars(select(WorkflowAction))) == []
        assert list(db.scalars(select(AuditEvent))) == []


@pytest.mark.parametrize("case", ["valid", "expired", "wrong_worker", "wrong_action", "audit_failure"])
def test_pi_confirmation_checks_exact_lease_and_atomic_audit(database, monkeypatch, case):
    import json
    from datetime import datetime, timezone, timedelta
    from fastapi import HTTPException
    from app.models import WorkflowSession, WorkflowAction, AuditEvent
    from app import workflow_service as service
    with Session(database) as db:
        _cancellation_fixture(db, "workflow")
        flow = db.get(WorkflowSession, "cancel-workflow")
        flow.execution_mode = "pi_harness"
        flow.stage, flow.state = "awaiting_fetched_data_confirmation", "running"
        flow.reconciliation_date = "2026-08-19"
        flow.context_json = json.dumps({"fetched_data": {"available": True}})
        db.add(WorkflowAction(id="confirmation-harness", workflow_id=flow.id,
            name=service.PI_HARNESS_ACTION, state="running", worker_id="synthetic-worker", attempt_count=1,
            lease_expires_at=datetime.now(timezone.utc)+timedelta(minutes=-1 if case == "expired" else 5)))
        db.commit()
    class AuditFailure(Exception): pass
    if case == "audit_failure":
        def fail(*args, **kwargs): raise AuditFailure("synthetic audit append failure")
        monkeypatch.setattr(service, "record_audit", fail)
    with Session(database) as db:
        flow = db.get(WorkflowSession, "cancel-workflow")
        def invoke():
            return service.queue_pi_harness_tool(db, flow, "accept_fetched_data", {},
                harness_action_id="missing" if case == "wrong_action" else "confirmation-harness",
                worker_id="wrong" if case == "wrong_worker" else "synthetic-worker", attempt=1)
        if case == "valid": invoke()
        else:
            with pytest.raises(AuditFailure if case == "audit_failure" else HTTPException): invoke()
            db.rollback()
    with Session(database) as db:
        flow = db.get(WorkflowSession, "cancel-workflow")
        audits = list(db.scalars(select(AuditEvent)))
        assert flow.stage == ("preparing" if case == "valid" else "awaiting_fetched_data_confirmation")
        assert len(audits) == (1 if case == "valid" else 0)
        assert len(list(db.scalars(select(WorkflowAction)))) == 1


@pytest.mark.parametrize("finish", ["commit", "rollback"])
@pytest.mark.parametrize("empty", [False, True])
def test_worker_auto_confirmation_and_action_share_final_transaction(database, monkeypatch, finish, empty):
    import json
    from app.models import WorkflowSession, WorkflowAction, AuditEvent
    from app.resource_policy import workflow_root
    from app import workflow_service as service
    with Session(database) as db:
        _cancellation_fixture(db, "workflow")
        flow = db.get(WorkflowSession, "cancel-workflow")
        flow.state, flow.stage = "running", "preparing"
        flow.reconciliation_date = "2026-08-19"
        db.add(WorkflowAction(id="automatic-fetch", workflow_id=flow.id,
            name="prepare_workspace", state="running", worker_id="synthetic-worker"))
        db.commit()
    (workflow_root("synthetic-owner", "cancel-workflow") / "skill").mkdir(parents=True, exist_ok=True)
    fetched = {"available": True, "dates": ["2026-08-19"]}
    if empty:
        fetched["summary_by_date"] = {"2026-08-19": {key: 0 for key in service.FETCHED_DATASET_COUNT_KEYS.values()}}
    # Replace only external fetch/preview IO. The worker, transition, confirmation,
    # audit, action completion, and caller commit/rollback are production code.
    monkeypatch.setattr(service, "_prepare_workspace_action", lambda *args: {
        "awaiting_fetched_data_confirmation": True, "fetched_data": fetched, "artifacts": []})
    monkeypatch.setattr(service, "_prime_fetched_data_previews", lambda *args: None)
    monkeypatch.setattr(service, "_validated_snapshot_for_date", lambda *args: object())
    monkeypatch.setattr(service, "is_ar_skill", lambda _: True)
    with Session(database) as db:
        action = db.get(WorkflowAction, "automatic-fetch")
        service.execute_workflow_action(db, action)
        assert action.state == "succeeded", action.error_message
        assert db.get(WorkflowSession, "cancel-workflow").stage == ("completed" if empty else "preparing")
        getattr(db, finish)()
    with Session(database) as db:
        flow = db.get(WorkflowSession, "cancel-workflow")
        action = db.get(WorkflowAction, "automatic-fetch")
        audits = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "workflow.fetched_data.auto_validated")))
        plans = list(db.scalars(select(WorkflowAction).where(WorkflowAction.name == "build_reconciliation_plan")))
        if finish == "commit":
            assert action.state == "succeeded" and action.finished_at is not None
            context = json.loads(flow.context_json)
            # Empty legacy dates finish immediately and then delete their raw
            # fetch snapshot; the automatic validation audit remains authoritative.
            assert context["fetched_data"]["review_status"] == ("deleted" if empty else "confirmed")
            assert flow.stage == ("completed" if empty else "preparing")
            if empty:
                assert context["empty_day_skipped"] is True
                assert context["fetched_data"]["available"] is False
            assert len(audits) == 1 and len(plans) == (0 if empty else 1)
        else:
            assert action.state == "running" and action.finished_at is None
            assert flow.stage == "preparing" and flow.context_json == "{}"
            assert not audits and not plans
