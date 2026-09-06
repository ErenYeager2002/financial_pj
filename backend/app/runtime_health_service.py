from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import UserContext
from .contracts import RuntimeHealth, WorkerHealth
from .models import RunRecord, TaskDiscoveryCheck, WorkflowAction, WorkflowSession
from .reconciliation_runner import PI_HARNESS_ACTION
from .resource_policy import owner_list_filter
from .settings import settings


def runtime_health(db: Session, user: UserContext) -> RuntimeHealth:
    """Report measured local worker state without probing external services."""
    now = datetime.now(UTC)
    heartbeat_cutoff = now - timedelta(
        seconds=max(settings.worker_lease_seconds * 2, settings.worker_heartbeat_seconds * 3)
    )
    configured = dict(settings.worker_counts)
    queued: defaultdict[str, int] = defaultdict(int)
    running: defaultdict[str, int] = defaultdict(int)
    live_workers: defaultdict[str, set[str]] = defaultdict(set)
    last_heartbeat: dict[str, datetime] = {}

    run_filter = owner_list_filter(RunRecord, user)
    for pool, state, worker_id, heartbeat_at, lease_expires_at in db.execute(
        select(
            RunRecord.worker_pool,
            RunRecord.state,
            RunRecord.worker_id,
            RunRecord.heartbeat_at,
            RunRecord.lease_expires_at,
        ).where(run_filter, RunRecord.state.in_(("queued", "running")))
    ).all():
        pool_name = str(pool or "python")
        if state == "queued":
            queued[pool_name] += 1
        else:
            running[pool_name] += 1
            if worker_id and heartbeat_at:
                heartbeat = heartbeat_at if heartbeat_at.tzinfo else heartbeat_at.replace(tzinfo=UTC)
                last_heartbeat[pool_name] = max(last_heartbeat.get(pool_name, heartbeat), heartbeat)
                if heartbeat >= heartbeat_cutoff and (
                    lease_expires_at is None
                    or (lease_expires_at if lease_expires_at.tzinfo else lease_expires_at.replace(tzinfo=UTC))
                    >= now
                ):
                    live_workers[pool_name].add(str(worker_id))

    workflow_filter = owner_list_filter(WorkflowSession, user)
    for action_state, action_name, worker_id, heartbeat_at, lease_expires_at in db.execute(
        select(
            WorkflowAction.state,
            WorkflowAction.name,
            WorkflowAction.worker_id,
            WorkflowAction.heartbeat_at,
            WorkflowAction.lease_expires_at,
        )
        .join(WorkflowSession, WorkflowSession.id == WorkflowAction.workflow_id)
        .where(workflow_filter, WorkflowAction.state.in_(("queued", "running")))
    ).all():
        pool_name = "pi_harness" if action_name == PI_HARNESS_ACTION else "workflow"
        if action_state == "queued":
            queued[pool_name] += 1
        else:
            running[pool_name] += 1
            if worker_id and heartbeat_at:
                heartbeat = heartbeat_at if heartbeat_at.tzinfo else heartbeat_at.replace(tzinfo=UTC)
                last_heartbeat[pool_name] = max(last_heartbeat.get(pool_name, heartbeat), heartbeat)
                if heartbeat >= heartbeat_cutoff and (
                    lease_expires_at is None
                    or (lease_expires_at if lease_expires_at.tzinfo else lease_expires_at.replace(tzinfo=UTC))
                    >= now
                ):
                    live_workers[pool_name].add(str(worker_id))

    discovery_filter = [TaskDiscoveryCheck.department_id == user.department_id]
    if not user.is_admin:
        discovery_filter.append(TaskDiscoveryCheck.owner_id == user.user_id)
    for state, worker_id, lease_expires_at in db.execute(
        select(
            TaskDiscoveryCheck.state,
            TaskDiscoveryCheck.worker_id,
            TaskDiscoveryCheck.lease_expires_at,
        ).where(*discovery_filter, TaskDiscoveryCheck.state.in_(("queued", "running")))
    ).all():
        pool_name = "task_discovery"
        if state == "queued":
            queued[pool_name] += 1
        else:
            running[pool_name] += 1
            # Task discovery currently has no heartbeat column. Its worker
            # lease is useful for showing a running or expired task, but it is
            # not evidence of an online Worker.

    pools = sorted(set(configured) | set(queued) | set(running) | set(last_heartbeat))
    workers: list[WorkerHealth] = []
    for pool in pools:
        online = len(live_workers[pool])
        state = "online" if online else "expired" if running[pool] else "unknown"
        workers.append(
            WorkerHealth(
                pool=pool,
                state=state,
                configured_capacity=max(0, int(configured.get(pool, 0))),
                online_capacity=online,
                queued_count=queued[pool],
                running_count=running[pool],
                last_heartbeat_at=last_heartbeat.get(pool),
            )
        )
    configured_total = sum(max(0, int(value)) for value in configured.values())
    has_queue = any(queued.values())
    has_live_workers = any(live_workers.values())
    if configured_total == 0 or registry_errors():
        readiness = "not_ready"
    elif has_live_workers:
        readiness = "ready"
    else:
        readiness = "unknown"
    if has_queue and not has_live_workers:
        readiness = "unknown"
    return RuntimeHealth(
        liveness="alive",
        readiness=readiness,
        dependency_status="not_checked",
        checked_at=now,
        configured_workers=configured,
        online_workers={pool: len(values) for pool, values in live_workers.items() if values},
        queue_depth=dict(queued),
        workers=workers,
        scope="当前账号可见范围；仅检查数据库记录、Worker 心跳和队列，不连接智云或模型服务。",
    )


def registry_errors() -> bool:
    # Import lazily so the liveness probe never needs to initialize registry details.
    from .registry import registry

    return bool(registry.errors)
