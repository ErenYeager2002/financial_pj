"""Administrator stop uses real identity facts and synthetic runtime transport."""
import json
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.auth import UserContext
from app.auth_models import User
from app.models import AuditEvent
from app import pi_runtime_service as runtime
from test_refactor_event_transactions import database

@pytest.fixture
def case(database):
    actor=UserContext("synthetic-admin","Admin","skill_admin","finance")
    owner=UserContext("synthetic-owner","Owner","finance_user","finance")
    session=runtime.create_session(owner,"Synthetic disabled owner")
    with Session(database) as db:
        db.add(User(id=actor.user_id,username=actor.user_id,department_id="finance",role="skill_admin",password_hash="synthetic-only"))
        db.get(User,owner.user_id).status="disabled"
        db.commit()
    return actor,owner,session["id"]

def test_admin_stop_audits_actual_actor_and_fixed_owner(database,case,monkeypatch):
    from app.pi_admin_session_service import stop_disabled_owner_session
    actor,owner,session=case
    calls=[]
    monkeypatch.setattr(runtime,"_request_runtime",lambda body:(calls.append(body) or {"running":False,"environment_running":False}))
    with Session(database) as db:result=stop_disabled_owner_session(db,actor,owner.user_id,session)
    assert result=={"running":False,"environment_running":False}
    assert calls==[{"owner":runtime.owner_scope(owner),"session_id":session,"operation":"stop","payload":{}}]
    with Session(database) as db:
        events=list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at)))
        assert [e.action for e in events]==["pi.session.admin_stop_requested","pi.session.admin_stop"]
        assert all(e.actor_id==actor.user_id and e.actor_role=="skill_admin" for e in events)
        assert all(e.resource_id==session and json.loads(e.details_json)["owner_id"]==owner.user_id for e in events)

@pytest.mark.parametrize("reason,expected",[("demoted",403),("disabled",403),("foreign_department",404),("active_owner",409),("foreign_session",404)])
def test_admin_stop_rejects_invalid_scope_before_dispatch(database,case,monkeypatch,reason,expected):
    from app.pi_admin_session_service import stop_disabled_owner_session
    actor,owner,session=case
    with Session(database) as db:
        admin=db.get(User,actor.user_id)
        if reason=="demoted":admin.role="finance_user"
        if reason=="disabled":admin.status="disabled"
        if reason=="foreign_department":db.get(User,owner.user_id).department_id="other"
        if reason=="active_owner":db.get(User,owner.user_id).status="active"
        db.commit()
    if reason=="foreign_session":session=runtime.create_session(actor,"Other session")["id"]
    calls=[]
    monkeypatch.setattr(runtime,"_request_runtime",lambda body:calls.append(body))
    with Session(database) as db:
        with pytest.raises(HTTPException) as error:stop_disabled_owner_session(db,actor,owner.user_id,session)
        assert error.value.status_code==expected
    assert not calls
    with Session(database) as db:assert db.scalar(select(AuditEvent)) is None

def test_admin_stop_uncertain_transport_never_records_success(database,case,monkeypatch):
    from app.pi_admin_session_service import stop_disabled_owner_session
    actor,owner,session=case
    def fail(body):raise HTTPException(503,"synthetic transport failure")
    monkeypatch.setattr(runtime,"_request_runtime",fail)
    with Session(database) as db:
        with pytest.raises(HTTPException) as error:stop_disabled_owner_session(db,actor,owner.user_id,session)
        assert error.value.status_code==503
    with Session(database) as db:
        actions=list(db.scalars(select(AuditEvent.action)))
        assert set(actions)=={"pi.session.admin_stop_requested","pi.session.admin_stop_unknown"}


@pytest.mark.parametrize("change,expected",[("admin_demoted",403),("owner_reactivated",409)])
def test_admin_stop_rechecks_after_session_lock(database,case,monkeypatch,change,expected):
    from app import pi_admin_session_service as service
    actor,owner,session=case
    original=service.fcntl.flock
    def changed_while_waiting(file,operation):
        original(file,operation)
        with Session(database) as db:
            if change=="admin_demoted":db.get(User,actor.user_id).role="finance_user"
            else:db.get(User,owner.user_id).status="active"
            db.commit()
    monkeypatch.setattr(service.fcntl,"flock",changed_while_waiting)
    calls=[];monkeypatch.setattr(runtime,"_request_runtime",lambda body:calls.append(body))
    with Session(database) as db:
        with pytest.raises(HTTPException) as error:service.stop_disabled_owner_session(db,actor,owner.user_id,session)
        assert error.value.status_code==expected
    assert not calls


def test_admin_stop_matches_real_manager_protocol_without_real_docker(database,case,monkeypatch,tmp_path):
    import sys
    from pathlib import Path
    from app.pi_admin_session_service import stop_disabled_owner_session
    from app.scheduler import acquire_claim_lock
    from sqlalchemy import text
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"deployment"))
    from pi_runtime_manager import RuntimeManager
    actor,owner,session=case
    manager=RuntimeManager(tmp_path/"runtime",tmp_path/"control","synthetic-unused")
    _,_,key=manager.identity(runtime.owner_scope(owner),session)
    running=[True];commands=[]
    def inspect(name):
        assert name=="financial-pi-"+key[:32]
        return {"State":{"Running":running[0]},"Config":{"Labels":{"financial.pi.key":key,"financial.pi.owner":runtime.owner_scope(owner)}}}
    def docker(*args):
        assert args==("stop","--time","10","financial-pi-"+key[:32])
        commands.append(args);running[0]=False
    monkeypatch.setattr(manager,"inspect",inspect)
    monkeypatch.setattr(manager,"docker",docker)
    monkeypatch.setattr(manager,"call",lambda *args:{})
    def dispatch(body):
        # The request audit is durable, and scheduler global is released before transport.
        with Session(database) as db:
            assert db.scalar(select(AuditEvent).where(AuditEvent.action=="pi.session.admin_stop_requested")) is not None
            if database.dialect.name=="postgresql":db.execute(text("SET LOCAL lock_timeout='500ms'"))
            acquire_claim_lock(db)
        return manager.dispatch(body)
    monkeypatch.setattr(runtime,"_request_runtime",dispatch)
    with Session(database) as db:assert stop_disabled_owner_session(db,actor,owner.user_id,session)["environment_running"] is False
    assert len(commands)==1


def test_admin_stop_http_contract_and_anonymous_rejection(database,case,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import get_current_user
    from app.database import get_db
    from app.routers.pi_runtime import router
    actor,owner,session=case
    app=FastAPI();app.include_router(router)
    def db_session():
        with Session(database) as db:yield db
    app.dependency_overrides[get_db]=db_session
    app.dependency_overrides[get_current_user]=lambda:actor
    calls=[]
    monkeypatch.setattr(runtime,"_request_runtime",lambda body:(calls.append(body) or {"running":False,"environment_running":False}))
    path=f"/api/pi-runtime/admin/users/{owner.user_id}/sessions/{session}/stop"
    with TestClient(app) as client:
        response=client.post(path)
        assert response.status_code==200 and response.json()=={"running":False,"environment_running":False}
        def anonymous():raise HTTPException(401,"Login required")
        app.dependency_overrides[get_current_user]=anonymous
        assert client.post(path).status_code==401
    assert len(calls)==1
    schema=app.openapi()
    route=schema["paths"]["/api/pi-runtime/admin/users/{owner_id}/sessions/{session_id}/stop"]
    assert route["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/AdminStopResult")
