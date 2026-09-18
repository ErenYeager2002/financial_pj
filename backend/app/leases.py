from __future__ import annotations

import threading
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import update

from .database import SessionLocal
from .models import RunRecord, WorkflowAction
from .settings import settings

LeaseKind = Literal["run", "workflow_action"]


def lease_deadline(now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    return current + timedelta(seconds=settings.worker_lease_seconds)


class LeaseHeartbeat(AbstractContextManager["LeaseHeartbeat"]):
    def __init__(self, kind: LeaseKind, record_id: str, worker_id: str, *, attempt: int | None = None) -> None:
        self.attempt = attempt
        self.kind = kind
        self.record_id = record_id
        self.worker_id = worker_id
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def model(self):
        return RunRecord if self.kind == "run" else WorkflowAction

    def _touch(self) -> None:
        now = datetime.now(UTC)
        with SessionLocal() as db:
            query = update(self.model)
            if self.kind == "run":
                query = query.where(self.model.attempt_count == self.attempt, self.model.lease_expires_at >= now)
            db.execute(
                query
                .where(
                    self.model.id == self.record_id,
                    self.model.state == "running",
                    self.model.worker_id == self.worker_id,
                )
                .values(heartbeat_at=now, lease_expires_at=lease_deadline(now))
            )
            db.commit()

    def _loop(self) -> None:
        while not self._stop.wait(settings.worker_heartbeat_seconds):
            try:
                self._touch()
            except Exception:
                # A transient heartbeat failure must not terminate the financial action.
                # The next heartbeat gets another chance before the lease expires.
                continue

    def __enter__(self) -> LeaseHeartbeat:
        self._thread = threading.Thread(
            target=self._loop,
            name=f"lease-{self.kind}-{self.record_id[:8]}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
