"""Event append must participate in its caller's real database transaction."""
from pathlib import Path
import os
import sys
from uuid import uuid4
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import Session
from app.events import append_run_event, emit_event
from app.models import RunRecord, RunEvent, AuditEvent
from app.infrastructure.database.migrate import DatabaseTarget, migrate_database

@pytest.fixture
def database(tmp_path):
    url = os.environ.get("REFACTOR_POSTGRES_URL")
    admin = None
    schema = None
    if url:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/refactor"))
        from verify_isolation import verify
        verify({**os.environ, "FINANCIAL_DATABASE_URL": url})
        assert url.startswith("postgresql+psycopg://")
        schema = "refactor_tx_" + uuid4().hex[:12]
        admin = create_engine(url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": "-csearch_path=" + schema})
    else:
        engine = create_engine("sqlite:///" + str(tmp_path / "events.db"))
    try:
        cfg = Config()
        cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
        migrate_database(engine, cfg, expected_target=DatabaseTarget.from_engine(engine), expected_revision=None, target_revision=ScriptDirectory.from_config(cfg).get_current_head())
        from app.auth_models import User, UserSkillPermission
        with Session(engine) as db:
            db.add(User(id="synthetic-owner", username="synthetic-owner", department_id="finance", password_hash="synthetic-unusable-password"))
            db.flush()
            db.add(UserSkillPermission(id="synthetic-permission",user_id="synthetic-owner",skill_id="synthetic",can_run=True))
            db.commit()
        yield engine
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def new_run(db):
    run = RunRecord(id="synthetic-run", owner_id="synthetic-owner", skill_id="synthetic", skill_name="Synthetic", skill_version="1", skill_hash="a" * 64, manifest_path="/synthetic/tool.yaml", manifest_snapshot="{}", adapter="python", worker_pool="python")
    db.add(run)
    db.flush()
    return run

def counts(engine):
    with Session(engine) as db:
        return tuple(db.scalar(select(func.count()).select_from(model)) for model in (RunRecord, RunEvent, AuditEvent))

@pytest.mark.parametrize("state", ["queued", "failed", "timed_out"])
def test_append_rolls_back_run_event_and_failure_audit(database, state):
    with Session(database) as db:
        run = new_run(db)
        append_run_event(db, run, event_type="state", state=state, progress=10, data={"error": {"token": "synthetic-secret"}})
        db.flush()
        assert counts(database) == (0, 0, 0)
        db.rollback()
    assert counts(database) == (0, 0, 0)

def test_caller_commit_preserves_whole_failure_event(database):
    with Session(database) as db:
        run = new_run(db)
        append_run_event(db, run, event_type="state", state="failed", data={"error": {"token": "synthetic-secret"}})
        db.commit()
    assert counts(database) == (1, 1, 1)
    with Session(database) as db:
        audit = db.scalar(select(AuditEvent))
        assert "synthetic-secret" not in audit.details_json
        assert db.get(RunRecord, "synthetic-run").state == "failed"

@pytest.mark.parametrize("commit", [True, False])
def test_legacy_wrapper_retains_commit_option(database, commit):
    with Session(database) as db:
        run = new_run(db)
        emit_event(db, run, event_type="state", state="queued", commit=commit)
        db.rollback()
    assert counts(database) == ((1, 1, 0) if commit else (0, 0, 0))


def test_audit_append_failure_leaves_no_partial_event(database, monkeypatch):
    from app import events
    original = events.record_audit
    def fail_after_audit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic audit failure")
    monkeypatch.setattr(events, "record_audit", fail_after_audit)
    with Session(database) as db:
        run = new_run(db)
        with pytest.raises(RuntimeError, match="synthetic audit failure"):
            append_run_event(db, run, event_type="state", state="failed")
        db.rollback()
    assert counts(database) == (0, 0, 0)


def test_fenced_worker_cannot_append_after_lease_loss(database):
    from datetime import UTC, datetime, timedelta
    from app.run_fencing import bind_run_fence, RunLeaseLost
    with Session(database) as db:
        run = new_run(db)
        run.state = "running"
        run.worker_id = "synthetic-worker"
        run.attempt_count = 1
        run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        bind_run_fence(db, run)
        append_run_event(db, run, progress=25, message="stale worker")
        with pytest.raises(RunLeaseLost):
            db.flush()
        db.rollback()
    assert counts(database) == (1, 0, 0)
    with Session(database) as db:
        assert db.get(RunRecord, "synthetic-run").progress == 0


def prepared_submission():
    from types import SimpleNamespace
    from app.run_service import PreparedRun
    run = RunRecord(id="synthetic-run", owner_id="synthetic-owner", owner_name="Synthetic", department_id="finance", skill_id="synthetic", skill_name="Synthetic", skill_version="1", skill_hash="a" * 64, manifest_path="/synthetic/tool.yaml", manifest_snapshot="{}", adapter="python", worker_pool="python", state="queued", progress=0, progress_message="queued", files_json='{"input":{"file_id":"synthetic-file"}}')
    return PreparedRun(run, SimpleNamespace(connection_id="synthetic-model", provider="synthetic", model="synthetic"), {"status":"succeeded"})


def submission_counts(engine):
    from app.models import StepRun, RunModelAudit, ModelTraceRecord
    with Session(engine) as db:
        return tuple(db.scalar(select(func.count()).select_from(model)) for model in (RunRecord, StepRun, RunEvent, RunModelAudit, ModelTraceRecord, AuditEvent))


@pytest.mark.parametrize("stage", ["run", "steps", "event", "audit"])
def test_submission_failure_rolls_back_all_records(database, monkeypatch, stage):
    from app import run_service
    from app.audit_service import record_audit
    if stage in {"run", "steps"}:
        original = run_service.initialize_run_steps
        def fail_steps(db, run):
            if stage == "steps":
                original(db, run)
            raise RuntimeError("synthetic submission failure")
        monkeypatch.setattr(run_service, "initialize_run_steps", fail_steps)
    elif stage == "event":
        original = run_service.append_run_event
        def fail_event(*args, **kwargs):
            original(*args, **kwargs)
            args[0].flush()
            raise RuntimeError("synthetic submission failure")
        monkeypatch.setattr(run_service, "append_run_event", fail_event)
    with Session(database) as db:
        with pytest.raises(RuntimeError, match="synthetic submission failure"):
            run = run_service.persist_run(db, prepared_submission())
            record_audit(db, actor_id=run.owner_id, actor_role="system", department_id=run.department_id, action="synthetic.submit", resource_type="run", resource_id=run.id)
            raise RuntimeError("synthetic submission failure")
        db.rollback()
    assert submission_counts(database) == (0, 0, 0, 0, 0, 0)


def test_submission_survives_response_loss_after_commit(database):
    from app.run_service import persist_run
    with Session(database) as db:
        run = persist_run(db, prepared_submission())
        db.flush()
        assert submission_counts(database) == (0, 0, 0, 0, 0, 0)
        db.commit()
        # Closing without serializing a response cannot undo the committed task.
    assert submission_counts(database) == (1, 5, 1, 1, 1, 0)
    with Session(database) as db:
        assert "synthetic-file" in db.get(RunRecord, "synthetic-run").files_json


@pytest.mark.parametrize("fail_binding", [True, False])
@pytest.mark.parametrize("confirmation", [True, False])
def test_draft_consumption_and_task_share_transaction(database, monkeypatch, fail_binding, confirmation):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace
    from sqlalchemy import event
    from app import draft_service, run_service
    from app.auth import UserContext
    from app.models import TaskDraftRecord
    user = UserContext(user_id="synthetic-owner", display_name="Synthetic", role="finance_user")
    with Session(database) as db:
        db.add(TaskDraftRecord(id="synthetic-draft", owner_id=user.user_id, department_id="finance", skill_id="synthetic", skill_name="Synthetic", skill_version="1", skill_hash="a" * 64, state="ready", expires_at=datetime.now(UTC) + timedelta(hours=1)))
        db.commit()
    monkeypatch.setattr(draft_service.registry, "get", lambda _: SimpleNamespace(skill_hash="a" * 64, manifest=SimpleNamespace(version="1")))
    monkeypatch.setattr(draft_service, "assert_skill_permission", lambda *a, **k: None)
    monkeypatch.setattr(draft_service, "_validate_parameters", lambda *a: None)
    monkeypatch.setattr(draft_service, "validate_files", lambda *a: None)
    def prepare(*args):
        value = prepared_submission()
        value.run.state = "waiting_confirmation" if confirmation else "queued"
        return value
    monkeypatch.setattr(run_service, "prepare_run", prepare)
    monkeypatch.setattr(run_service, "_revalidate_prepared_run", lambda *a: None)
    with Session(database) as db:
        if fail_binding:
            def reject_binding(session, context, instances):
                if any(isinstance(obj, TaskDraftRecord) and obj.state == "consumed" for obj in session.dirty):
                    raise RuntimeError("synthetic binding failure")
            event.listen(db, "before_flush", reject_binding)
            with pytest.raises(RuntimeError, match="synthetic binding failure"):
                draft_service.confirm_task_draft(db, "synthetic-draft", user)
            db.rollback()
        else:
            run = draft_service.confirm_task_draft(db, "synthetic-draft", user)
            assert run.state == "queued"
            assert submission_counts(database) == (0, 0, 0, 0, 0, 0)
            db.commit()
    with Session(database) as db:
        draft = db.get(TaskDraftRecord, "synthetic-draft")
        assert draft.state == ("ready" if fail_binding else "consumed")
        assert draft.run_id == (None if fail_binding else "synthetic-run")
    assert submission_counts(database) == ((0, 0, 0, 0, 0, 0) if fail_binding else (1, 5, 2 if confirmation else 1, 1, 1, 0))


def test_expired_draft_read_does_not_commit_callers_pending_task(database):
    from datetime import UTC, datetime, timedelta
    from app.draft_service import get_task_draft
    from app.auth import UserContext
    from app.models import TaskDraftRecord
    user = UserContext(user_id="synthetic-owner", display_name="Synthetic", role="finance_user")
    with Session(database) as db:
        db.add(TaskDraftRecord(id="expired-draft", owner_id=user.user_id, department_id="finance", skill_id="synthetic", skill_name="Synthetic", skill_version="1", skill_hash="a" * 64, state="ready", expires_at=datetime.now(UTC) - timedelta(hours=1)))
        db.commit()
    with Session(database) as db:
        new_run(db)
        draft = get_task_draft(db, "expired-draft", user)
        assert draft.state == "expired"
        db.rollback()
    assert counts(database) == (0, 0, 0)
    with Session(database) as db:
        assert db.get(TaskDraftRecord, "expired-draft").state == "ready"


def test_independent_model_fact_does_not_commit_callers_pending_record(database):
    from app.draft_service import _persist_model_trace
    from app.models import ModelTraceRecord
    with Session(database) as db:
        prepared = prepared_submission()
        db.add(prepared.run)  # Intentionally pending caller-owned data.
        trace = ModelTraceRecord(id="independent-trace", owner_id="synthetic-owner", department_id="finance", connection_id="synthetic-connection", purpose="assistant_recommendation", provider="synthetic", model="synthetic", status="failed", failure_code="synthetic_failure")
        _persist_model_trace(db, trace)
        db.rollback()
    assert counts(database) == (0, 0, 0)
    with Session(database) as db:
        saved = db.get(ModelTraceRecord, "independent-trace")
        assert saved.status == "failed" and saved.task_draft_id is None


def queued_worker_task(database, configure=None):
    from test_parallel_workers import _manifest
    from app.run_service import persist_run
    prepared = prepared_submission()
    prepared.run.manifest_snapshot = _manifest()
    if configure is not None:
        configure(prepared.run)
    with Session(database) as db:
        persist_run(db, prepared)
        db.commit()


def test_claim_step_failure_cannot_leave_claimed_task(database, monkeypatch):
    from app import worker
    queued_worker_task(database)
    original = worker.start_run_execution_step
    def fail_after_step(*args):
        original(*args)
        raise RuntimeError("synthetic claim failure")
    monkeypatch.setattr(worker, "start_run_execution_step", fail_after_step)
    with Session(database) as db:
        with pytest.raises(RuntimeError, match="synthetic claim failure"):
            worker.claim_next_run(db, ("python",), "synthetic-worker")
        db.rollback()
    with Session(database) as db:
        run = db.get(RunRecord, "synthetic-run")
        assert run.state == "queued" and run.worker_id == "" and run.attempt_count == 0
        assert db.scalar(select(func.count()).select_from(RunEvent)) == 1


def test_claim_commits_lease_event_and_step_once(database):
    from sqlalchemy import event
    from app import worker
    from app.models import StepRun
    queued_worker_task(database)
    commits = []
    with Session(database) as db:
        event.listen(db, "after_commit", lambda _: commits.append(True))
        assert worker.claim_next_run(db, ("python",), "synthetic-worker").state == "running"
    assert commits == [True]
    with Session(database) as db:
        assert db.get(RunRecord, "synthetic-run").attempt_count == 1
        assert db.scalar(select(func.count()).select_from(RunEvent)) == 2
        assert db.scalar(select(func.count()).select_from(StepRun).where(StepRun.state == "running")) == 1


@pytest.mark.parametrize("error", [RuntimeError, TimeoutError, InterruptedError])
def test_worker_failure_discards_unpublished_changes(database, monkeypatch, tmp_path, error):
    from app import worker
    from types import SimpleNamespace
    queued_worker_task(database)
    def execute(ctx):
        ctx.run.result_json = '{"unpublished":true}'
        ctx.db.add(RunEvent(run_id=ctx.run.id, event_type="synthetic-unpublished", state="running", message="pending", data_json="{}"))
        ctx.db.flush()
        raise error("synthetic execution failure")
    monkeypatch.setattr(worker, "get_adapter", lambda _: SimpleNamespace(execute=execute))
    monkeypatch.setattr(worker, "run_root", lambda *a: tmp_path / "work")
    with Session(database) as db:
        run = worker.claim_next_run(db, ("python",), "synthetic-worker")
        worker.execute_run(db, run)
    with Session(database) as db:
        saved = db.get(RunRecord, "synthetic-run")
        assert saved.state == {RuntimeError:"failed", TimeoutError:"timed_out", InterruptedError:"cancelled"}[error]
        assert saved.result_json == "{}"
        assert db.scalar(select(func.count()).select_from(RunEvent).where(RunEvent.event_type == "synthetic-unpublished")) == 0


def test_terminal_commit_response_loss_does_not_overwrite_success(database, monkeypatch, tmp_path):
    from app import worker
    from types import SimpleNamespace
    queued_worker_task(database)
    monkeypatch.setattr(worker, "get_adapter", lambda _: SimpleNamespace(execute=lambda ctx: {"summary": {"synthetic": True}}))
    monkeypatch.setattr(worker, "run_root", lambda *a: tmp_path / "work")
    with Session(database) as db:
        run = worker.claim_next_run(db, ("python",), "synthetic-worker")
        original = db.commit
        def committed_but_response_lost():
            terminal = run.state == "succeeded"
            original()
            if terminal:
                raise RuntimeError("synthetic connection loss after commit")
        monkeypatch.setattr(db, "commit", committed_but_response_lost)
        worker.execute_run(db, run)
    with Session(database) as db:
        run = db.get(RunRecord, "synthetic-run")
        assert run.state == "succeeded"
        assert '"synthetic": true' in run.result_json
        assert db.scalar(select(func.count()).select_from(RunEvent).where(RunEvent.state == "failed")) == 0


def test_progress_transaction_preserves_pending_result(database):
    from app import worker
    from app.events import publish_run_progress
    from app.run_fencing import bind_run_fence
    queued_worker_task(database)
    with Session(database) as db:
        run = worker.claim_next_run(db, ("python",), "synthetic-worker")
        bind_run_fence(db, run)
        run.result_json = '{"unpublished":true}'
        publish_run_progress(db, run, progress=33, message="synthetic progress")
        assert run.progress == 33 and "unpublished" in run.result_json
        db.rollback()
    with Session(database) as db:
        saved = db.get(RunRecord, "synthetic-run")
        assert saved.result_json == "{}" and saved.progress == 33
        assert saved.progress_message == "synthetic progress"


@pytest.mark.parametrize("invalid", ["missing", "stale"])
def test_progress_rejects_missing_or_stale_original_fence(database, invalid):
    from app import worker
    from app.events import publish_run_progress
    from app.run_fencing import bind_run_fence, RunLeaseLost
    queued_worker_task(database)
    with Session(database) as db:
        run = worker.claim_next_run(db, ("python",), "synthetic-worker")
        if invalid == "stale":
            bind_run_fence(db, run)
            rid, owner, attempt = db.info["ordinary_run_fence"]
            db.info["ordinary_run_fence"] = (rid, owner, attempt + 1)
        with pytest.raises(RunLeaseLost):
            publish_run_progress(db, run, progress=99)
        db.rollback()
    with Session(database) as db:
        assert db.get(RunRecord, "synthetic-run").progress == 1


def test_failed_snapshot_copy_never_publishes_partial_skill(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app import run_service
    source = tmp_path / "source"
    source.mkdir()
    (source / "tool.yaml").write_text("synthetic")
    target = tmp_path / "unique-task"
    monkeypatch.setattr(run_service, "run_root", lambda *a: target)
    def partial_copy(src, dst, **kwargs):
        dst.mkdir()
        (dst / "partial").write_text("synthetic incomplete copy")
        raise OSError("synthetic copy failure")
    monkeypatch.setattr(run_service.shutil, "copytree", partial_copy)
    with pytest.raises(OSError, match="synthetic copy failure"):
        run_service._snapshot_skill(SimpleNamespace(directory=source, skill_hash=run_service.hash_skill_directory(source)), "owner", "run")
    assert not (target / "skill").exists()
    assert len(list(target.glob("skill.staging-*/partial"))) == 1


def test_snapshot_publishes_complete_copy_and_never_replaces_existing(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app import run_service
    source = tmp_path / "source"
    source.mkdir()
    (source / "tool.yaml").write_text("original")
    target = tmp_path / "unique-task"
    monkeypatch.setattr(run_service, "run_root", lambda *a: target)
    result = run_service._snapshot_skill(SimpleNamespace(directory=source, skill_hash=run_service.hash_skill_directory(source)), "owner", "run")
    assert (result / "tool.yaml").read_text() == "original"
    (source / "tool.yaml").write_text("changed")
    with pytest.raises(FileExistsError):
        run_service._snapshot_skill(SimpleNamespace(directory=source, skill_hash=run_service.hash_skill_directory(source)), "owner", "run")
    assert (result / "tool.yaml").read_text() == "original"


def test_progress_cannot_commit_already_flushed_parent_work(database):
    if database.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row-lock boundary")
    from sqlalchemy.exc import DBAPIError
    from app import worker
    from app.events import publish_run_progress
    from app.run_fencing import bind_run_fence
    queued_worker_task(database)
    with Session(database) as db:
        run = worker.claim_next_run(db, ("python",), "synthetic-worker")
        bind_run_fence(db, run)
        run.result_json = '{"unpublished":true}'
        db.flush()
        with pytest.raises(DBAPIError) as failure:
            publish_run_progress(db, run, progress=90)
        assert getattr(failure.value.orig, "sqlstate", None) == "55P03"
        # Independent session failure leaves the parent transaction usable.
        assert "unpublished" in run.result_json
        db.rollback()
    with Session(database) as db:
        saved = db.get(RunRecord, "synthetic-run")
        assert saved.progress == 1 and saved.result_json == "{}"
        assert db.scalar(select(func.count()).select_from(RunEvent)) == 2


def test_preparation_closes_owned_reads_without_ending_caller_transaction(database, monkeypatch, tmp_path):
    from app import run_service
    from app.auth_models import User
    from app.auth import UserContext
    from app.registry import registry
    from app.schemas import RunCreate
    registry.refresh()
    skill = registry.get("reconcile-bank")
    assert skill is not None
    user = UserContext(user_id="synthetic-owner", display_name="Synthetic", role="finance_user")
    reads = []
    def resolve(read_db, request, actor):
        assert read_db.get(User, actor.user_id) is not None
        reads.append(read_db)
        return skill, actor, None
    def interpret(*args):
        assert all(not session.in_transaction() for session in reads)
        return {"amount_tolerance":1,"date_tolerance_days":2}, [], None, None
    def files(read_db, *args):
        assert read_db.get(User, user.user_id) is not None
        reads.append(read_db)
        return {}, "synthetic-hash"
    def snapshot(*args):
        assert all(not session.in_transaction() for session in reads)
        return tmp_path / "synthetic-snapshot"
    monkeypatch.setattr(run_service, "_resolve_preparation_context", resolve)
    monkeypatch.setattr(run_service, "interpret_parameters", interpret)
    monkeypatch.setattr(run_service, "validate_files", files)
    monkeypatch.setattr(run_service, "_snapshot_skill", snapshot)
    with Session(database) as db:
        pending = new_run(db)  # Flushed, so new/dirty emptiness is not sufficient.
        assert db.in_transaction()
        prepared = run_service.prepare_run(db, RunCreate(skill_id="reconcile-bank", message="synthetic", parameters={}, files={}), user)
        assert isinstance(prepared, run_service.PreparedRun)
        assert db.in_transaction() and db.get(RunRecord, pending.id) is pending
        assert counts(database) == (0, 0, 0)
        db.commit()
    assert counts(database) == (1, 0, 0)


@pytest.mark.parametrize("change", ["disabled", "department", "skill", "binding"])
def test_prepared_submission_rechecks_mutable_facts_before_inserting(database, monkeypatch, change):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app import run_service
    from app.auth import UserContext
    from app.auth_models import User
    from app.schemas import RunCreate
    prepared = prepared_submission()
    prepared.run.parameters_json = "{}"
    prepared.run.input_hash = "synthetic-original"
    user = UserContext(user_id="synthetic-owner", display_name="Synthetic", role="finance_user")
    monkeypatch.setattr(run_service, "prepare_run", lambda *a: prepared)
    monkeypatch.setattr(run_service.registry, "get", lambda _: SimpleNamespace(skill_hash="changed" if change == "skill" else "a" * 64, manifest=SimpleNamespace(version="1")))
    monkeypatch.setattr(run_service, "assert_skill_permission", lambda *a: None)
    monkeypatch.setattr(run_service, "assert_skill_accepting_new_work", lambda *a: None)
    monkeypatch.setattr(run_service, "validate_files", lambda *a: ({}, "changed"))
    with Session(database) as db:
        if change in {"disabled", "department"}:
            account = db.get(User, user.user_id)
            if change == "disabled":
                account.status = "disabled"
            else:
                account.department_id = "other"
            db.commit()
        with pytest.raises(HTTPException) as failure:
            run_service.create_run(db, RunCreate(skill_id="synthetic", parameters={}, files={}), user)
        assert failure.value.status_code == (403 if change in {"disabled", "department"} else 409)
        db.rollback()
    assert submission_counts(database) == (0, 0, 0, 0, 0, 0)


@pytest.mark.parametrize("consumed", [False, True])
def test_draft_changed_during_preparation(database, monkeypatch, consumed):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app import draft_service, run_service
    from app.auth import UserContext
    from app.models import TaskDraftRecord
    user = UserContext(user_id="synthetic-owner", display_name="Synthetic", role="finance_user")
    with Session(database) as db:
        db.add(TaskDraftRecord(id="changing-draft", owner_id=user.user_id, department_id="finance", skill_id="synthetic", skill_name="Synthetic", skill_version="1", skill_hash="a" * 64, state="ready", expires_at=datetime.now(UTC) + timedelta(hours=1)))
        db.commit()
    monkeypatch.setattr(draft_service.registry, "get", lambda _: SimpleNamespace(skill_hash="a" * 64, manifest=SimpleNamespace(version="1")))
    monkeypatch.setattr(draft_service, "assert_skill_permission", lambda *a, **k: None)
    monkeypatch.setattr(draft_service, "_validate_parameters", lambda *a: None)
    monkeypatch.setattr(draft_service, "validate_files", lambda *a: None)
    def reject_persist(*args):
        pytest.fail("A changed or consumed draft must not persist the prepared task")
    monkeypatch.setattr(run_service, "persist_run", reject_persist)
    with Session(database) as db:
        request = draft_service.prepare_draft_run_request(db, "changing-draft", user)
        db.rollback()  # Same boundary as the HTTP entrypoint before external work.
        with Session(database) as other:
            draft = other.get(TaskDraftRecord, "changing-draft")
            if consumed:
                existing = new_run(other)
                draft.state = "consumed"
                draft.run_id = existing.id
            else:
                draft.parameters_json = '{"changed":true}'
            other.commit()
        if consumed:
            run = draft_service.confirm_task_draft(db, "changing-draft", user, prepared=prepared_submission(), expected_request=request)
            assert run.id == "synthetic-run"
        else:
            with pytest.raises(HTTPException) as error:
                draft_service.confirm_task_draft(db, "changing-draft", user, prepared=prepared_submission(), expected_request=request)
            assert error.value.status_code == 409
        db.rollback()
    assert counts(database) == ((1, 0, 0) if consumed else (0, 0, 0))
