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
from .auth import UserContext
from .database import SessionLocal, init_db
from .events import emit_event
from .leases import LeaseHeartbeat, lease_deadline
from .models import RunRecord
from .registry import SkillManifest
from .scheduler import acquire_claim_lock, active_run_count, recover_expired_jobs
from .settings import settings
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
    return selected


def execute_run(db: Session, run: RunRecord) -> None:
    manifest = SkillManifest.model_validate(json.loads(run.manifest_snapshot))
    owner = UserContext(
        user_id=run.owner_id,
        display_name=run.owner_name,
        role="finance_user",
        department_id=run.department_id,
    )
    workspace = settings.run_dir / run.id
    skill_dir = workspace / "skill"
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
        emit_event(
            db,
            run,
            event_type="state",
            state="succeeded",
            progress=100,
            message="任务执行完成",
            data={"summary": result.get("summary", {})},
        )
    except InterruptedError as exc:
        run.finished_at = datetime.now(UTC)
        emit_event(db, run, event_type="state", state="cancelled", message=str(exc))
    except TimeoutError as exc:
        run.error_message = str(exc)
        run.finished_at = datetime.now(UTC)
        emit_event(db, run, event_type="state", state="timed_out", message=str(exc))
    except Exception as exc:
        run.error_message = str(exc)
        run.finished_at = datetime.now(UTC)
        emit_event(db, run, event_type="state", state="failed", message=str(exc))


def run_once(
    pools: tuple[str, ...] | None = None,
    worker_id: str | None = None,
) -> bool:
    pools = pools or settings.worker_pools
    identity = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    with SessionLocal() as db:
        run = claim_next_run(db, pools, identity)
        if run:
            with LeaseHeartbeat("run", run.id, identity):
                execute_run(db, run)
            run.heartbeat_at = datetime.now(UTC)
            run.lease_expires_at = None
            db.commit()
            return True
        return run_workflow_action_once(db, pools, identity)


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
        if not run_once(pools, worker_id):
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
