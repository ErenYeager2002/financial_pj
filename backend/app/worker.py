from __future__ import annotations

import argparse
import json
import signal
import time
from datetime import UTC, datetime

from jsonschema import Draft202012Validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .adapters import ExecutionContext, get_adapter
from .auth import UserContext
from .database import SessionLocal, init_db
from .events import emit_event
from .models import RunRecord
from .registry import SkillManifest
from .settings import settings

STOP = False


def _stop(*_: object) -> None:
    global STOP
    STOP = True


def claim_next_run(db: Session, pools: tuple[str, ...]) -> RunRecord | None:
    run_id = db.scalar(
        select(RunRecord.id)
        .where(RunRecord.state == "queued", RunRecord.worker_pool.in_(pools))
        .order_by(RunRecord.queued_at.asc(), RunRecord.created_at.asc())
        .limit(1)
    )
    if not run_id:
        return None
    now = datetime.now(UTC)
    claimed = db.execute(
        update(RunRecord)
        .where(RunRecord.id == run_id, RunRecord.state == "queued")
        .values(state="running", started_at=now, progress=1, progress_message="Worker 已领取任务")
    )
    db.commit()
    if claimed.rowcount != 1:
        return None
    run = db.get(RunRecord, run_id)
    if run:
        emit_event(
            db,
            run,
            event_type="state",
            state="running",
            progress=1,
            message="Worker 已领取任务",
        )
    return run


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


def run_once(pools: tuple[str, ...] | None = None) -> bool:
    pools = pools or settings.worker_pools
    with SessionLocal() as db:
        run = claim_next_run(db, pools)
        if not run:
            return False
        execute_run(db, run)
        return True


def run_loop(pools: tuple[str, ...]) -> None:
    init_db()
    settings.ensure_directories()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    print(f"Financial worker started; pools={','.join(pools)}", flush=True)
    while not STOP:
        if not run_once(pools):
            time.sleep(settings.queue_poll_seconds)
    print("Financial worker stopped", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="财务 Skill 平台任务 Worker")
    parser.add_argument(
        "--pools",
        default=",".join(settings.worker_pools),
        help="逗号分隔的 Worker Pool，例如 python,http 或 rpa",
    )
    parser.add_argument("--once", action="store_true", help="最多处理一个任务后退出")
    args = parser.parse_args()
    pools = tuple(item.strip() for item in args.pools.split(",") if item.strip())
    if args.once:
        init_db()
        settings.ensure_directories()
        run_once(pools)
    else:
        run_loop(pools)


if __name__ == "__main__":
    main()
