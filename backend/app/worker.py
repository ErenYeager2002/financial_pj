from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import time
from contextlib import contextmanager
from datetime import UTC, datetime

from jsonschema import Draft202012Validator
from sqlalchemy import case, func, or_, select, text
from sqlalchemy.orm import Session

from .adapters import ExecutionContext, get_adapter
from .ar_execution_contract import CONTRACT_VERSION
from .modules.execution.authorization import execution_owner, ExecutionPhase, ExecutionAuthorizationRevoked
from .modules.execution.preconditions import assert_run_confirmation, ExecutionPreconditionFailed
from .database import SessionLocal, check_runtime_database
from .events import append_run_event
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


@contextmanager
def _candidate_query_timeout(db: Session):
    """Bound candidate reads only; an aborted transaction is rolled back by the caller."""
    if db.get_bind().dialect.name != "postgresql":
        yield
        return
    previous = db.scalar(text("SHOW statement_timeout"))
    configured_ms = int(db.scalar(text(
        "SELECT setting FROM pg_settings WHERE name = 'statement_timeout'")))
    limit_ms = min(configured_ms, 2000) if configured_ms > 0 else 2000
    db.execute(text("SELECT set_config('statement_timeout', :value, true)"),
               {"value": str(limit_ms)})
    # Restore only on a successful read. A failed PostgreSQL transaction cannot
    # run SET; propagating the original error preserves the rollback contract.
    yield
    db.execute(text("SELECT set_config('statement_timeout', :value, true)"),
               {"value": previous})


def claim_next_run(
    db: Session,
    pools: tuple[str, ...],
    worker_id: str = "worker",
) -> RunRecord | None:
    started = time.monotonic()
    scan = {"event": "run_claim_scan", "candidate_filter": "skill_capacity",
            "checked_count": 0, "invalid_snapshot_count": 0, "claim_denied_count": 0,
            "capacity_recheck_skip_count": 0, "query_elapsed_ms": 0,
            "outcome": "claim_error"}
    try:
        acquire_claim_lock(db)
        now = datetime.now(UTC)
        recover_expired_jobs(db, now)
        db.flush()
        # Unknown/expired execution still occupies capacity after recovery. Count
        # every pool and owner, matching active_run_count's existing Skill scope.
        active = (
            select(RunRecord.skill_id, func.count(RunRecord.id).label("count"))
            .where(RunRecord.state == "running",
                   or_(RunRecord.lease_expires_at.is_(None), RunRecord.lease_expires_at >= now))
            .group_by(RunRecord.skill_id)
            .subquery()
        )
        scan["outcome"] = "candidate_query"
        query_started = time.monotonic()
        with _candidate_query_timeout(db):
            candidates = list(
                db.scalars(
                    select(RunRecord.id)
                    .outerjoin(active, RunRecord.skill_id == active.c.skill_id)
                    .where(RunRecord.state == "queued", RunRecord.worker_pool.in_(pools),
                           func.coalesce(active.c.count, 0) < case(
                               (RunRecord.concurrency_limit < 1, 1), else_=RunRecord.concurrency_limit))
                    .order_by(RunRecord.queued_at.asc().nulls_last(), RunRecord.created_at.asc(), RunRecord.id.asc())
                    .limit(100)
                ).all()
            )
        scan["query_elapsed_ms"] = round((time.monotonic() - query_started) * 1000, 3)
        scan["outcome"] = "claim_error"

        selected: RunRecord | None = None
        for run_id in candidates:
            run = db.get(RunRecord, run_id, populate_existing=True)
            if not run or run.state != "queued" or run.worker_pool not in pools:
                continue
            scan["checked_count"] += 1
            try:
                manifest = SkillManifest.model_validate(json.loads(run.manifest_snapshot))
            except (TypeError, ValueError, json.JSONDecodeError):
                scan["invalid_snapshot_count"] += 1
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
                append_run_event(
                    db,
                    run,
                    event_type="state",
                    state="failed",
                    message=run.error_message,
                    data={"error": detail.as_dict()},
                )
                continue
            if active_run_count(db, run.skill_id, now) >= max(1, run.concurrency_limit):
                scan["capacity_recheck_skip_count"] += 1
                continue
            try:
                execution_owner(db, run, ExecutionPhase.CLAIM, observe=True)
                assert_run_confirmation(run, manifest, ExecutionPhase.CLAIM)
                from .modules.execution.run_snapshot import assert_execution_snapshot
                assert_execution_snapshot(db, run, ExecutionPhase.CLAIM)
            except (ExecutionAuthorizationRevoked, ExecutionPreconditionFailed) as error:
                scan["claim_denied_count"] += 1
                _deny_execution(db, run, error)
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
        if not selected:
            db.commit()
            scan["outcome"] = ("candidate_budget_reached" if len(candidates) == 100 else
                               "candidates_rejected" if candidates else "no_capacity_eligible_candidate")
            return None
        append_run_event(
            db,
            selected,
            event_type="state",
            state="running",
            progress=1,
            message="Worker 已领取任务",
            data={"worker_id": worker_id, "attempt": selected.attempt_count},
        )
        start_run_execution_step(db, selected, worker_id)
        if selected.queued_at:
            queued_at = selected.queued_at
            if queued_at.tzinfo is None:
                queued_at = queued_at.replace(tzinfo=UTC)
            scan["queued_wait_ms"] = round(max(0, (now - queued_at).total_seconds() * 1000), 3)
        db.commit()
        scan["outcome"] = "selected"
        return selected
    except Exception as error:
        if scan["outcome"] == "candidate_query":
            scan["query_elapsed_ms"] = round((time.monotonic() - query_started) * 1000, 3)
            code = getattr(getattr(error, "orig", None), "sqlstate", None)
            scan["outcome"] = ("candidate_query_timeout" if code == "57014" else
                               "candidate_query_error")
        else:
            scan["outcome"] = "claim_error"
        raise
    finally:
        # Idle/capacity-full polls stay quiet. Emit counts and timings only,
        # never task/owner/Skill identifiers, exception text, or SQL parameters.
        if scan["checked_count"] or scan["outcome"] in {
            "candidate_query_timeout", "candidate_query_error", "claim_error"
        }:
            scan["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
            try:
                print(json.dumps(scan, sort_keys=True), flush=True)
            except OSError:
                # An unavailable log sink must not strand a committed claim.
                pass


def _deny_execution(db, run, error):
    run.error_message = str(error)
    run.finished_at = datetime.now(UTC)
    finish_run_execution_step(db, run, state="failed", error_code=error.code,
                              error_message=run.error_message)
    append_run_event(db, run, event_type="state", state="failed",
                     message=run.error_message,
                     data={"code":error.code,"phase":error.phase.value})


def execute_run(db: Session, run: RunRecord) -> None:
    bind_run_fence(db, run)
    try:
        assert_run_fence(db)
        _execute_claimed_run(db, run)
    except RunLeaseLost:
        db.rollback()
    finally:
        db.info.pop("ordinary_run_fence", None)


def _reload_after_execution_failure(db: Session, run_id: str) -> RunRecord:
    """Discard unpublished work and revalidate ownership before recording failure."""
    db.rollback()
    run = db.get(RunRecord, run_id)
    if run is None:
        raise RunLeaseLost("Task disappeared before failure could be recorded")
    assert_run_fence(db, lock=True)
    return run


def _execute_claimed_run(db: Session, run: RunRecord) -> None:
    run_id = run.id
    try:
        # Same order as administrative permission mutations and queue claims:
        # global scheduler lock, then task fence, then current authorization.
        acquire_claim_lock(db)
        assert_run_fence(db, lock=True)
        db.refresh(run)
        manifest = SkillManifest.model_validate(json.loads(run.manifest_snapshot))
        if run.cancel_requested:
            raise InterruptedError("任务已被员工取消，未启动执行器。")
        owner = execution_owner(db, run, ExecutionPhase.START, observe=True)
        assert_run_confirmation(run, manifest, ExecutionPhase.START)
        from .modules.execution.run_snapshot import assert_execution_snapshot
        assert_execution_snapshot(db, run, ExecutionPhase.START)
        db.commit()
        original_workspace = run_root(run.owner_id, run.id)
        workspace = original_workspace / "attempts" / str(run.attempt_count)
        workspace.mkdir(parents=True, exist_ok=True)
        skill_dir = original_workspace / "skill"
        ctx = ExecutionContext(db=db, run=run, manifest=manifest, skill_dir=skill_dir,
                               workspace=workspace, owner=owner)
        adapter = get_adapter(run.adapter)
        result = adapter.execute(ctx)
        errors = sorted(Draft202012Validator(manifest.output_schema).iter_errors(result), key=str)
        if errors:
            raise RuntimeError("输出协议校验失败：" + "; ".join(error.message for error in errors))
        run.result_json = json.dumps(result, ensure_ascii=False, sort_keys=True)
        run.finished_at = datetime.now(UTC)
        finish_run_execution_step(db, run, state="succeeded", result=result)
        append_run_event(
            db,
            run,
            event_type="state",
            state="succeeded",
            progress=100,
            message="任务执行完成",
            data={"summary": result.get("summary", {})},
        )
        db.commit()
    except RunLeaseLost:
        raise
    except (ExecutionAuthorizationRevoked, ExecutionPreconditionFailed) as exc:
        run = _reload_after_execution_failure(db, run_id)
        _deny_execution(db, run, exc)
        db.commit()
    except InterruptedError as exc:
        run = _reload_after_execution_failure(db, run_id)
        safe_error = sanitize_text(str(exc), error=True)
        run.finished_at = datetime.now(UTC)
        finish_run_execution_step(
            db, run, state="cancelled", error_code="cancelled", error_message=safe_error
        )
        append_run_event(db, run, event_type="state", state="cancelled", message=safe_error)
        db.commit()
    except TimeoutError as exc:
        run = _reload_after_execution_failure(db, run_id)
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
        append_run_event(
            db,
            run,
            event_type="state",
            state="timed_out",
            message=safe_error,
            data={"error": detail.as_dict()},
        )
        db.commit()
    except Exception as exc:
        run = _reload_after_execution_failure(db, run_id)
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
        append_run_event(
            db,
            run,
            event_type="state",
            state="failed",
            message=safe_error,
            data={"error": detail.as_dict()},
        )
        db.commit()



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
            from .ar_material_lifecycle import maintain_materials
            if maintain_materials(db):
                return True
            from .ar_staging_retention import maintain_expired_staging

            if maintain_expired_staging(db):
                return True
    if "workflow" in pools:
        from .skill_rollout_service import run_rollout_once

        return run_rollout_once()
    return False


def run_loop(pools: tuple[str, ...], worker_id: str) -> None:
    check_runtime_database()
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
        check_runtime_database()
        settings.ensure_directories()
        run_once(pools, args.worker_id)
    else:
        run_loop(pools, args.worker_id)


if __name__ == "__main__":
    main()
