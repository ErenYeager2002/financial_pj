from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime

from app.auth_models import User
from app.database import SessionLocal, engine, init_db
from app.models import (
    RunEvent,
    RunRecord,
    StepDefinition,
    StepRun,
    WorkflowAction,
    WorkflowDefinition,
    WorkflowSession,
)
from app.worker import claim_next_run
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError


def _manifest(skill_id: str) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "id": skill_id,
            "name": "PostgreSQL 并发探针",
            "version": "1.0.0",
            "status": "published",
            "description": "只读并发验证",
            "handler": {
                "adapter": "python",
                "entrypoint": "scripts/probe.py",
                "worker_pool": "stage10-probe",
            },
            "runtime": {"concurrency_limit": 1},
            "risk": {"level": "read_only"},
        },
        ensure_ascii=False,
    )


def main() -> int:
    if engine.dialect.name != "postgresql":
        raise RuntimeError("阶段十并发验证必须连接 PostgreSQL。")
    init_db()
    probe = f"stage10-probe-{uuid.uuid4()}"
    owner_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    with SessionLocal() as db:
        active_runs = int(
            db.scalar(
                select(func.count()).select_from(RunRecord).where(
                    RunRecord.state.in_(("queued", "running", "waiting_confirmation"))
                )
            )
            or 0
        )
        active_actions = int(
            db.scalar(
                select(func.count()).select_from(WorkflowAction).where(
                    WorkflowAction.state.in_(("queued", "running"))
                )
            )
            or 0
        )
        active_workflows = int(
            db.scalar(
                select(func.count()).select_from(WorkflowSession).where(
                    WorkflowSession.state.in_(("running", "waiting_confirmation", "waiting_approval"))
                )
            )
            or 0
        )
        if active_runs or active_actions or active_workflows:
            raise RuntimeError("存在活动任务，不能运行并发探针。")
        db.add(
            User(
                id=owner_id,
                username=f"{probe}@invalid.local",
                display_name="阶段十探针",
                password_hash="disabled-runtime-probe",
                role="finance_user",
                department_id="finance",
            )
        )
        for index in range(6):
            run_id = str(uuid.uuid4())
            db.add(
                RunRecord(
                    id=run_id,
                    owner_id=owner_id,
                    owner_name="阶段十探针",
                    department_id="finance",
                    skill_id=probe,
                    skill_name="PostgreSQL 并发探针",
                    skill_version="1.0.0",
                    skill_hash=uuid.uuid4().hex,
                    manifest_path=f"/probe/{run_id}/tool.yaml",
                    manifest_snapshot=_manifest(probe),
                    adapter="python",
                    worker_pool="stage10-probe",
                    concurrency_limit=1,
                    state="queued",
                    queued_at=now,
                    created_at=now,
                )
            )
        db.commit()

    barrier = threading.Barrier(6)
    claimed: list[str] = []
    errors: list[str] = []

    def worker(index: int) -> None:
        try:
            barrier.wait(timeout=10)
            with SessionLocal() as db:
                run = claim_next_run(db, ("stage10-probe",), f"probe-{index}")
                if run:
                    claimed.append(run.id)
        except (SQLAlchemyError, RuntimeError, ValueError, threading.BrokenBarrierError) as exc:
            errors.append(type(exc).__name__)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    try:
        if errors or len(claimed) != 1:
            raise RuntimeError(
                f"PostgreSQL 并发领取验证失败：claimed={len(claimed)}, errors={errors}"
            )
        with SessionLocal() as db:
            states = dict(
                db.execute(
                    select(RunRecord.state, func.count())
                    .where(RunRecord.skill_id == probe)
                    .group_by(RunRecord.state)
                ).all()
            )
            revision = db.scalar(text("SELECT version_num FROM alembic_version"))
            if states != {"queued": 5, "running": 1}:
                raise RuntimeError(f"并发领取状态不符合预期：{states}")
            print(
                json.dumps(
                    {
                        "dialect": engine.dialect.name,
                        "revision": revision,
                        "concurrent_workers": 6,
                        "claimed": 1,
                        "states": states,
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        with SessionLocal() as db:
            ids = list(db.scalars(select(RunRecord.id).where(RunRecord.skill_id == probe)).all())
            if ids:
                db.execute(delete(RunEvent).where(RunEvent.run_id.in_(ids)))
                db.execute(delete(StepRun).where(StepRun.run_id.in_(ids)))
                db.execute(delete(RunRecord).where(RunRecord.id.in_(ids)))
            definition_ids = list(
                db.scalars(
                    select(WorkflowDefinition.id).where(
                        WorkflowDefinition.skill_id == probe
                    )
                ).all()
            )
            if definition_ids:
                db.execute(
                    delete(StepDefinition).where(
                        StepDefinition.workflow_definition_id.in_(definition_ids)
                    )
                )
                db.execute(
                    delete(WorkflowDefinition).where(
                        WorkflowDefinition.id.in_(definition_ids)
                    )
                )
            db.execute(delete(User).where(User.id == owner_id))
            db.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
