from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from helpers import auth_client

from app.auth_service import get_user_by_username
from app.database import SessionLocal
from app.models import RunEvent, RunRecord, StepRun, WorkflowDefinition
from app.run_service import cancel_run
from app.scheduler import recover_expired_jobs
from app.step_runtime_service import (
    finish_run_execution_step,
    initialize_run_steps,
    start_run_execution_step,
)


def test_standard_run_step_projection_tracks_worker_lifecycle() -> None:
    username = f"step-runtime-{uuid.uuid4().hex[:8]}"
    run_id = str(uuid.uuid4())

    with auth_client(username=username):
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            run = RunRecord(
                id=run_id,
                owner_id=user.id,
                owner_name=user.display_name,
                department_id=user.department_id,
                skill_id="reconcile-bank",
                skill_name="银行流水核对",
                skill_version="1.0.0",
                skill_hash="a" * 64,
                manifest_path="skills/reconcile-bank/tool.yaml",
                manifest_snapshot="{}",
                adapter="python",
                worker_pool="python",
                state="queued",
                files_json='{"bank_file":{"file_id":"f1","name":"bank.xlsx"}}',
            )
            db.add(run)
            db.flush()

            initialize_run_steps(db, run)
            steps = sorted(run_steps(db, run.id), key=lambda item: item[0])
            assert [(position, step.state) for position, step in steps] == [
                (10, "succeeded"),
                (20, "succeeded"),
                (30, "queued"),
                (40, "pending"),
                (50, "pending"),
            ]

            start_run_execution_step(db, run, "worker-1")
            execution = steps[2][1]
            db.refresh(execution)
            assert execution.state == "running"
            assert execution.worker_id == "worker-1"
            assert execution.attempt_count == 1

            finish_run_execution_step(
                db,
                run,
                state="succeeded",
                result={"summary": {"rows": 2}},
            )
            db.flush()
            steps = sorted(run_steps(db, run.id), key=lambda item: item[0])
            assert [(position, step.state) for position, step in steps] == [
                (10, "succeeded"),
                (20, "succeeded"),
                (30, "succeeded"),
                (40, "succeeded"),
                (50, "succeeded"),
            ]
            assert steps[2][1].output_summary_json == '{"rows":2}'


def test_failed_read_only_execution_step_is_marked_safely_retryable() -> None:
    username = f"step-runtime-fail-{uuid.uuid4().hex[:8]}"

    with auth_client(username=username):
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            run = RunRecord(
                id=str(uuid.uuid4()),
                owner_id=user.id,
                owner_name=user.display_name,
                department_id=user.department_id,
                skill_id="reconcile-bank",
                skill_name="银行流水核对",
                skill_version="1.0.0",
                skill_hash="b" * 64,
                manifest_path="skills/reconcile-bank/tool.yaml",
                manifest_snapshot="{}",
                adapter="python",
                worker_pool="python",
                state="queued",
            )
            db.add(run)
            db.flush()
            initialize_run_steps(db, run)
            start_run_execution_step(db, run, "worker-2")
            finish_run_execution_step(
                db,
                run,
                state="failed",
                error_code="adapter_failure",
                error_message="private technical details",
            )
            execution = sorted(run_steps(db, run.id), key=lambda item: item[0])[2][1]
            assert execution.state == "failed"
            assert execution.can_retry is True
            assert execution.retry_block_reason == ""
            assert execution.error_code == "adapter_failure"


def test_standard_runs_reuse_one_workflow_definition() -> None:
    username = f"step-runtime-reuse-{uuid.uuid4().hex[:8]}"

    with auth_client(username=username):
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            runs = [
                RunRecord(
                    id=str(uuid.uuid4()),
                    owner_id=user.id,
                    owner_name=user.display_name,
                    department_id=user.department_id,
                    skill_id="reconcile-bank",
                    skill_name="银行流水核对",
                    skill_version="1.0.0",
                    skill_hash="c" * 64,
                    manifest_path="skills/reconcile-bank/tool.yaml",
                    manifest_snapshot="{}",
                    adapter="python",
                    worker_pool="python",
                    state="queued",
                )
                for _ in range(2)
            ]
            db.add_all(runs)
            db.flush()

            for run in runs:
                initialize_run_steps(db, run)
            definitions = db.query(WorkflowDefinition).filter(
                WorkflowDefinition.department_id == user.department_id,
                WorkflowDefinition.workflow_key == "standard-run:reconcile-bank",
                WorkflowDefinition.version == f"1.0.0+{'c' * 12}",
            )
            assert definitions.count() == 1
            assert len(definitions.one().steps) == 5


def test_cancel_and_expired_lease_keep_execution_step_in_sync() -> None:
    username = f"step-runtime-terminal-{uuid.uuid4().hex[:8]}"

    with auth_client(username=username):
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            cancelled = _runtime_run(user.id, user.display_name, user.department_id, "d" * 64)
            expired = _runtime_run(user.id, user.display_name, user.department_id, "e" * 64)
            db.add_all([cancelled, expired])
            db.flush()
            initialize_run_steps(db, cancelled)
            initialize_run_steps(db, expired)

            cancel_run(db, cancelled)
            start_run_execution_step(db, expired, "expired-worker")
            expired.state = "running"
            expired.attempt_count = 1
            expired.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
            recover_expired_jobs(db)
            db.flush()

            cancelled_execution = sorted(
                run_steps(db, cancelled.id), key=lambda item: item[0]
            )[2][1]
            expired_execution = sorted(run_steps(db, expired.id), key=lambda item: item[0])[2][1]
            assert cancelled.state == "cancelled"
            assert cancelled_execution.state == "cancelled"
            assert expired.state == "queued"
            assert expired_execution.state == "queued"
            assert expired_execution.worker_id == ""
            assert expired_execution.started_at is None


def test_run_detail_and_event_stream_redact_worker_error_values() -> None:
    username = f"step-runtime-redact-{uuid.uuid4().hex[:8]}"

    with auth_client(username=username) as client:
        with SessionLocal() as db:
            user = get_user_by_username(db, username)
            assert user is not None
            run = _runtime_run(user.id, user.display_name, user.department_id, "f" * 64)
            run.state = "failed"
            run.progress_message = "token=must-not-leak D:\\private\\worker.py"
            run.error_message = (
                'Traceback (most recent call last):\n  File "D:\\private\\worker.py", line 9\n'
                "RuntimeError: token=must-not-leak"
            )
            db.add(run)
            db.flush()
            db.add(
                RunEvent(
                    run_id=run.id,
                    event_type="state",
                    state="failed",
                    message=run.error_message,
                    data_json=(
                        '{"token":"must-not-leak","detail":"password=also-secret '
                        'D:\\\\private\\\\worker.py"}'
                    ),
                )
            )
            db.commit()

        detail = client.get(f"/api/runs/{run.id}")
        assert detail.status_code == 200
        serialized = detail.text
        assert "must-not-leak" not in serialized
        assert "private" not in serialized
        assert "技术详情已隐藏" in serialized

        events = client.get(f"/api/runs/{run.id}/events")
        assert events.status_code == 200
        assert "must-not-leak" not in events.text
        assert "also-secret" not in events.text
        assert "private" not in events.text


def _runtime_run(owner_id: str, owner_name: str, department_id: str, skill_hash: str) -> RunRecord:
    return RunRecord(
        id=str(uuid.uuid4()),
        owner_id=owner_id,
        owner_name=owner_name,
        department_id=department_id,
        skill_id=f"runtime-{skill_hash[:8]}",
        skill_name="运行时测试",
        skill_version="1.0.0",
        skill_hash=skill_hash,
        manifest_path="skills/runtime/tool.yaml",
        manifest_snapshot=(
            '{"schema_version":1,"id":"runtime","name":"运行时测试",'
            '"version":"1.0.0","status":"published","description":"test",'
            '"handler":{"adapter":"python","entrypoint":"scripts/run.py",'
            '"worker_pool":"python"},"risk":{"level":"read_only"}}'
        ),
        adapter="python",
        worker_pool="python",
        state="queued",
        queued_at=datetime.now(UTC),
    )


def run_steps(db, run_id: str) -> list[tuple[int, StepRun]]:
    rows = db.query(StepRun).filter(StepRun.run_id == run_id).all()
    return [(item.step_definition.position, item) for item in rows]
