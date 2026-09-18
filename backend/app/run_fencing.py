"""Database fencing for ordinary Run workers; never used by AR actions."""
from datetime import UTC, datetime
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from .models import RunRecord

class RunLeaseLost(RuntimeError):
    pass

def bind_run_fence(db, run):
    if not run.worker_id or not run.attempt_count:
        raise RunLeaseLost("Task has no execution owner")
    db.info["ordinary_run_fence"] = (run.id, run.worker_id, run.attempt_count)

def assert_run_fence(db, *, lock=False):
    fence = db.info.get("ordinary_run_fence")
    if fence is None:
        return
    rid, worker, attempt = fence
    query = select(RunRecord.worker_id, RunRecord.attempt_count, RunRecord.state, RunRecord.lease_expires_at).where(RunRecord.id == rid)
    if lock:
        query = query.with_for_update()
    with db.no_autoflush:
        row = db.execute(query).first()
    deadline = row[3] if row else None
    if deadline is not None and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if not row or row[0] != worker or row[1] != attempt or row[2] not in {"running", "waiting_user_action"} or deadline is None or deadline <= datetime.now(UTC):
        raise RunLeaseLost("Execution lease lost; stale worker cannot publish")

@event.listens_for(Session, "before_flush")
def _fence_worker_writes(db, flush_context, instances):
    # Hold the row lock through the same transaction as event/file/state writes.
    # Scheduler recovery locks the same Run row before changing ownership.
    assert_run_fence(db, lock=True)
