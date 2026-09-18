from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import time
from datetime import UTC, datetime

from jsonschema import Draft202012Validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .adapters import ExecutionContext, get_adapter
from .ar_execution_contract import CONTRACT_VERSION
from .auth import UserContext
from .database import SessionLocal, init_db
from .events import emit_event
from .fetched_bundle_service import purge_expired_bundles
from .leases import LeaseHeartbeat, lease_deadline
from .run_fencing import RunLeaseLost, bind_run_fence, assert_run_fence
from .models import RunRecord
from .redaction import sanitize_text
from .registry import SkillManifest
from .resource_policy import run_root
from .scheduler import acquire_claim_lock, active_run_count, recover_expired_jobs
from .settings import settings
from .step_runtime_service import finish_run_execution_step, start_run_execution_step
from .task_errors import build_task_error
from .workflow_service import run_workflow_action_once

STOP = False


def _stop(*_: object) -> None:
    global STOP
    STOP = True


def claim_next_run(
    db: Session,
    pools: tuple[str, ...],
    worker_id: str = "worker",
) -> RunRecord | None:
    acquire_claim_lock(db)
    now = datetime.now(UTC)
    recover_expired_jobs(db, now)
    candidates = list(
        db.scalars(
            select(RunRecord.id)
            .where(RunRecord.state == "queued", RunRecord.worker_pool.in_(pools))
            .order_by(RunRecord.queued_at.asc(), RunRecord.created_at.asc())
            .limit(100)
        ).all()
    )
    selected: RunRecord | None = None
    for run_id in candidates:
        run = db.get(RunRecord, run_id)
        if not run:
            continue
        try:
            SkillManifest.model_validate(json.loads(run.manifest_snapshot))
        except (TypeError, ValueError, json.JSONDecodeError):
            detail = build_task_error(
                employee=run.owner_name or run.owner_id,
                skill_id=run.skill_id,
                skill_name=run.skill_name,
                step_key="validate-snapshot",
                step="校验 Skill 执行快照",
                reason="任务中的 Skill 执行快照无效。",
            )
            run.error_message = detail.message()
            run.finished_at = now
            finish_run_execution_step(
                db,
                run,
                state="failed",
                error_code="invalid_skill_snapshot",
                error_message=run.error_message,
            )
            emit_event(
                db,
                run,
                event_type="state",
                state="failed",
                message=run.error_message,
                data={"error": detail.as_dict()},
                commit=False,
            )
            continue
        if active_run_count(db, run.skill_id, now) >= max(1, run.concurrency_limit):
            continue
        run.state = "running"
        run.started_at = now
        run.progress = 1
        run.progress_message = "Worker 已领取任务"
        run.worker_id = worker_id
        run.attempt_count += 1
        run.heartbeat_at = now
        run.lease_expires_at = lease_deadline(now)
        selected = run
        break
    db.commit()
    if not selected:
        return None
    emit_event(
        db,
        selected,
        event_type="state",
        state="running",
        progress=1,
        message="Worker 已领取任务",
        data={"worker_id": worker_id, "attempt": selected.attempt_count},
    )
    start_run_execution_step(db, selected, worker_id)
    db.commit()
    return selected


def execute_run(db: Session, run: RunRecord) -> None:
    bind_run_fence(db, run)
    try:
        assert_run_fence(db)
        _execute_claimed_run(db, run)
    except RunLeaseLost:
        db.rollback()
    finally:
        db.info.pop("ordinary_run_fence", None)


def _execute_claimed_run(db: Session, run: RunRecord) -> None:
    manifest = SkillManifest.model_validate(json.loads(run.manifest_snapshot))
    owner = UserContext(
        user_id=run.owner_id,
        display_name=run.owner_name,
        role="finance_user",
        department_id=run.department_id,
    )
    original_workspace = run_root(run.owner_id, run.id)
    workspace = original_workspace / "attempts" / str(run.attempt_count)
    workspace.mkdir(parents=True, exist_ok=True)
    skill_dir = original_workspace / "skill"
    ctx = ExecutionContext(
        db=db,
        run=run,
        manifest=manifest,
        skill_dir=skill_dir,
        workspace=workspace,
        owner=owner,
    )
    try:
        adapter = get_adapter(run.adapter)
        result = adapter.execute(ctx)
        errors = sorted(Draft202012Validator(manifest.output_schema).iter_errors(result), key=str)
        if errors:
            raise RuntimeError("输出协议校验失败：" + "; ".join(error.message for error in errors))
        run.result_json = json.dumps(result, ensure_ascii=False, sort_keys=True)
        run.finished_at = datetime.now(UTC)
        finish_run_execution_step(db, run, state="succeeded", result=result)
        emit_event(
            db,
            run,
            event_type="state",
            state="succeeded",
            progress=100,
            message="任务执行完成",
            data={"summary": result.get("summary", {})},
        )
    except RunLeaseLost:
        raise
    except InterruptedError as exc:
        safe_error = sanitize_text(str(exc), error=True)
        run.finished_at = datetime.now(UTC)
        finish_run_execution_step(
            db, run, state="cancelled", error_code="cancelled", error_message=safe_error
        )
        emit_event(db, run, event_type="state", state="cancelled", message=safe_error)
    except TimeoutError as exc:
        detail = build_task_error(
            employee=run.owner_name or run.owner_id,
            skill_id=run.skill_id,
            skill_name=run.skill_name,
            step_key="execute",
            step="执行 Skill",
            reason=exc,
        )
        safe_error = detail.message()
        run.error_message = safe_error
        run.finished_at = datetime.now(UTC)
        finish_run_execution_step(
            db, run, state="timed_out", error_code="timeout", error_message=safe_error
        )
        emit_event(
            db,
            run,
            event_type="state",
            state="timed_out",
            message=safe_error,
            data={"error": detail.as_dict()},
        )
    except Exception as exc:
        detail = build_task_error(
            employee=run.owner_name or run.owner_id,
            skill_id=run.skill_id,
            skill_name=run.skill_name,
            step_key="execute",
            step="执行 Skill",
            reason=exc,
        )
        safe_error = detail.message()
        run.error_message = safe_error
        run.finished_at = datetime.now(UTC)
        finish_run_execution_step(
            db,
            run,
            state="failed",
            error_code="adapter_failure",
            error_message=safe_error,
        )
        emit_event(
            db,
            run,
            event_type="state",
            state="failed",
            message=safe_error,
            data={"error": detail.as_dict()},
        )


def run_once(
    pools: tuple[str, ...] | None = None,
    worker_id: str | None = None,
) -> bool:
    pools = pools or settings.worker_pools
    identity = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    with SessionLocal() as db:
        run = claim_next_run(db, pools, identity)
        if run:
            with LeaseHeartbeat("run", run.id, identity, attempt=run.attempt_count):
                execute_run(db, run)
            return True
        if run_workflow_action_once(db, pools, identity, execution_contracts=(CONTRACT_VERSION,)):
            return True
        if "workflow" in pools and purge_expired_bundles(db, limit=1):
            return True
        if "workflow" in pools:
            from .ar_staging_retention import maintain_expired_staging

            if maintain_expired_staging(db):
                return True
    if "workflow" in pools:
        from .skill_rollout_service import run_rollout_once

        return run_rollout_once()
    return False


def run_loop(pools: tuple[str, ...], worker_id: str) -> None:
    init_db()
    settings.ensure_directories()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    print(
        f"Financial worker started; id={worker_id}; pools={','.join(pools)}",
        flush=True,
    )
    while not STOP:
        try:
            worked = run_once(pools, worker_id)
        except Exception as exc:
            safe_error = sanitize_text(str(exc), error=True)
            print(
                f"Financial worker iteration failed; type={type(exc).__name__}; "
                f"error={safe_error}",
                flush=True,
            )
            time.sleep(float(getattr(settings, "queue_poll_seconds", 1)))
            continue
        if not worked:
            time.sleep(settings.queue_poll_seconds)
    print("Financial worker stopped", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="财务 Skill 平台任务 Worker")
    parser.add_argument(
        "--pools",
        default=",".join(settings.worker_pools),
        help="逗号分隔的 Worker Pool，例如 python,http 或 rpa",
    )
    parser.add_argument(
        "--worker-id",
        default=f"{socket.gethostname()}:{os.getpid()}",
        help="当前 Worker 的稳定标识",
    )
    parser.add_argument("--once", action="store_true", help="最多处理一个任务后退出")
    args = parser.parse_args()
    pools = tuple(item.strip() for item in args.pools.split(",") if item.strip())
    if args.once:
        init_db()
        settings.ensure_directories()
        run_once(pools, args.worker_id)
    else:
        run_loop(pools, args.worker_id)


if __name__ == "__main__":
    main()
