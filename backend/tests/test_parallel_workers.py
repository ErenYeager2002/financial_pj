from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime, timedelta

from app import worker
from app.database import SessionLocal, init_db
from app.models import RunRecord, WorkflowAction, WorkflowSession
from app.worker import claim_next_run, run_once
from app.workflow_service import claim_next_workflow_action
from sqlalchemy import select

from scripts import serve_control
from scripts.serve_control import worker_specs


def setup_module() -> None:
    init_db()


def _manifest(*, risk: str = "read_only", concurrency_limit: int = 1) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "id": "parallel-test",
            "name": "并行测试",
            "version": "1.0.0",
            "status": "published",
            "description": "并行执行测试",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "handler": {
                "adapter": "python",
                "entrypoint": "scripts/entry.py",
                "worker_pool": "python",
            },
            "runtime": {
                "timeout_seconds": 30,
                "memory_mb": 128,
                "concurrency_limit": concurrency_limit,
            },
            "risk": {"level": risk, "requires_confirmation": False},
        },
        ensure_ascii=False,
    )


def _queued_run(
    *,
    skill_id: str,
    concurrency_limit: int,
    risk: str = "read_only",
) -> RunRecord:
    run_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    return RunRecord(
        id=run_id,
        owner_id="parallel-user",
        owner_name="并行测试",
        department_id="finance",
        skill_id=skill_id,
        skill_name="并行测试",
        skill_version="1.0.0",
        skill_commit="test",
        skill_hash=uuid.uuid4().hex,
        manifest_path=f"/test/{run_id}/tool.yaml",
        manifest_snapshot=_manifest(
            risk=risk,
            concurrency_limit=concurrency_limit,
        ),
        adapter="python",
        worker_pool="python",
        concurrency_limit=concurrency_limit,
        state="queued",
        queued_at=now,
        created_at=now,
    )


def _workflow(skill_id: str, concurrency_limit: int = 1) -> tuple[WorkflowSession, WorkflowAction]:
    workflow_id = str(uuid.uuid4())
    workflow = WorkflowSession(
        id=workflow_id,
        owner_id="parallel-user",
        owner_name="并行测试",
        department_id="finance",
        skill_id=skill_id,
        skill_name="并行工作流",
        skill_version="1.0.0",
        skill_hash=uuid.uuid4().hex,
        skill_commit="test",
        concurrency_limit=concurrency_limit,
        model_connection_id="model-test",
        model_provider="qwen",
        model_name="qwen-test",
        state="running",
        stage="preparing",
        reconciliation_date="2026-07-27",
    )
    action = WorkflowAction(
        id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        name="prepare_worklist",
        state="queued",
    )
    return workflow, action


def test_two_workers_execute_tasks_with_real_overlap(monkeypatch) -> None:
    skill_id = f"parallel-overlap-{uuid.uuid4()}"
    runs = [
        _queued_run(skill_id=skill_id, concurrency_limit=2),
        _queued_run(skill_id=skill_id, concurrency_limit=2),
    ]
    with SessionLocal() as db:
        db.add_all(runs)
        db.commit()

    lock = threading.Lock()
    second_started = threading.Event()
    active = 0
    max_active = 0

    class TrackingAdapter:
        def execute(self, _ctx):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
                if active == 2:
                    second_started.set()
            second_started.wait(timeout=3)
            with lock:
                active -= 1
            return {}

    monkeypatch.setattr(worker, "get_adapter", lambda _name: TrackingAdapter())
    start = threading.Barrier(3)
    results: list[bool] = []

    def execute(worker_id: str) -> None:
        start.wait()
        results.append(run_once(("python",), worker_id))

    threads = [
        threading.Thread(target=execute, args=("python-test-1",)),
        threading.Thread(target=execute, args=("python-test-2",)),
    ]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert sorted(results) == [True, True]
    assert max_active == 2
    with SessionLocal() as db:
        states = list(
            db.scalars(
                select(RunRecord.state).where(RunRecord.id.in_([item.id for item in runs]))
            ).all()
        )
    assert states == ["succeeded", "succeeded"]


def test_skill_concurrency_limit_blocks_second_worker() -> None:
    skill_id = f"parallel-limit-{uuid.uuid4()}"
    first = _queued_run(skill_id=skill_id, concurrency_limit=1)
    second = _queued_run(skill_id=skill_id, concurrency_limit=1)
    with SessionLocal() as db:
        db.add_all([first, second])
        db.commit()

    with SessionLocal() as db:
        claimed = claim_next_run(db, ("python",), "limit-worker-1")
        assert claimed is not None
        assert claimed.id == first.id
    with SessionLocal() as db:
        assert claim_next_run(db, ("python",), "limit-worker-2") is None
    with SessionLocal() as db:
        claimed = db.get(RunRecord, first.id)
        assert claimed is not None
        claimed.state = "succeeded"
        claimed.lease_expires_at = None
        db.commit()
    with SessionLocal() as db:
        next_run = claim_next_run(db, ("python",), "limit-worker-2")
        assert next_run is not None
        assert next_run.id == second.id
        next_run.state = "succeeded"
        next_run.lease_expires_at = None
        db.commit()


def test_two_claimers_never_receive_the_same_run() -> None:
    run = _queued_run(
        skill_id=f"single-claim-{uuid.uuid4()}",
        concurrency_limit=2,
    )
    with SessionLocal() as db:
        db.add(run)
        db.commit()

    start = threading.Barrier(3)
    claimed_ids: list[str | None] = []

    def claim(worker_id: str) -> None:
        start.wait()
        with SessionLocal() as db:
            claimed = claim_next_run(db, ("python",), worker_id)
            claimed_ids.append(claimed.id if claimed else None)

    threads = [
        threading.Thread(target=claim, args=("claim-worker-1",)),
        threading.Thread(target=claim, args=("claim-worker-2",)),
    ]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert claimed_ids.count(run.id) == 1
    assert claimed_ids.count(None) == 1
    with SessionLocal() as db:
        claimed = db.get(RunRecord, run.id)
        assert claimed is not None
        claimed.state = "succeeded"
        claimed.lease_expires_at = None
        db.commit()


def test_expired_read_only_run_is_reclaimed_but_write_run_is_not() -> None:
    read_run = _queued_run(
        skill_id=f"expired-read-{uuid.uuid4()}",
        concurrency_limit=1,
    )
    write_run = _queued_run(
        skill_id=f"expired-write-{uuid.uuid4()}",
        concurrency_limit=1,
        risk="write",
    )
    expired = datetime.now(UTC) - timedelta(minutes=1)
    for item in (read_run, write_run):
        item.state = "running"
        item.worker_id = "dead-worker"
        item.attempt_count = 1
        item.heartbeat_at = expired
        item.lease_expires_at = expired
    with SessionLocal() as db:
        db.add_all([read_run, write_run])
        db.commit()

    with SessionLocal() as db:
        reclaimed = claim_next_run(db, ("python",), "recovery-worker")
        assert reclaimed is not None
        assert reclaimed.id == read_run.id
        assert reclaimed.attempt_count == 2
    with SessionLocal() as db:
        rejected = db.get(RunRecord, write_run.id)
        assert rejected is not None
        assert rejected.state == "failed"
        assert "人工检查" in rejected.error_message
        reclaimed = db.get(RunRecord, read_run.id)
        assert reclaimed is not None
        reclaimed.state = "succeeded"
        reclaimed.lease_expires_at = None
        db.commit()


def test_workflow_limit_and_different_skills_can_be_claimed() -> None:
    first_workflow, first_action = _workflow(f"workflow-limit-{uuid.uuid4()}")
    second_workflow, second_action = _workflow(first_workflow.skill_id)
    other_workflow, other_action = _workflow(f"workflow-other-{uuid.uuid4()}")
    with SessionLocal() as db:
        db.add_all(
            [
                first_workflow,
                second_workflow,
                other_workflow,
                first_action,
                second_action,
                other_action,
            ]
        )
        db.commit()

    with SessionLocal() as db:
        first_claim = claim_next_workflow_action(db, ("workflow",), "workflow-worker-1")
        assert first_claim is not None
        assert first_claim.id == first_action.id
    with SessionLocal() as db:
        other_claim = claim_next_workflow_action(db, ("workflow",), "workflow-worker-2")
        assert other_claim is not None
        assert other_claim.id == other_action.id
    with SessionLocal() as db:
        assert claim_next_workflow_action(db, ("workflow",), "workflow-worker-3") is None
        for action_id in (first_action.id, other_action.id):
            action = db.get(WorkflowAction, action_id)
            assert action is not None
            action.state = "succeeded"
            action.lease_expires_at = None
        db.commit()
    with SessionLocal() as db:
        second_claim = claim_next_workflow_action(db, ("workflow",), "workflow-worker-3")
        assert second_claim is not None
        assert second_claim.id == second_action.id
        second_claim.state = "succeeded"
        second_claim.lease_expires_at = None
        db.commit()


def test_worker_process_plan_is_split_by_pool() -> None:
    assert worker_specs({}) == [
        ("python", "python-1"),
        ("python", "python-2"),
        ("http", "http-1"),
        ("http", "http-2"),
        ("workflow", "workflow-1"),
        ("workflow", "workflow-2"),
    ]
    assert worker_specs({"FINANCIAL_WORKER_COUNTS": "python:3,rpa:1"}) == [
        ("python", "python-1"),
        ("python", "python-2"),
        ("python", "python-3"),
        ("rpa", "rpa-1"),
    ]


def test_stale_runtime_pid_is_rejected_by_command_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        serve_control,
        "process_command_line",
        lambda _pid: "C:\\Windows\\System32\\svchost.exe -k netsvcs",
    )
    assert not serve_control.process_matches(3468, "-m app.worker", "--worker-id", "python-1")
    monkeypatch.setattr(
        serve_control,
        "process_command_line",
        lambda _pid: (
            "D:\\BESTEASY\\financial_pj\\.venv\\Scripts\\python.exe "
            "-m app.worker --pools python --worker-id python-1"
        ),
    )
    assert serve_control.process_matches(3468, "-m app.worker", "--worker-id", "python-1")
