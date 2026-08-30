from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from helpers import TEST_PASSWORD, auth_client

from app.auth_service import create_user
from app.database import SessionLocal, init_db
from app.scheduler import recover_expired_jobs
from app.task_discovery import (
    TaskDiscoveryDayResult,
    execute_task_discovery,
    next_automatic_retry_at,
)
from app.task_discovery_schedule import (
    automatic_retry_times,
    scheduled_business_dates,
)
from app.task_discovery_worker import run_discovery_tick
from app.task_reminder_workflow_service import (
    associate_reminder_with_workflow,
    sync_reminder_from_workflow,
)
from app.workflow_service import (
    _assert_single_flight_available,
    _fail_batch,
    claim_next_workflow_action,
)


def _create_employee(username: str) -> str:
    init_db()
    with SessionLocal() as db:
        user = create_user(
            db,
            username=username,
            password=TEST_PASSWORD,
            display_name="应收核销负责人",
            role="finance_user",
            department_id="finance",
        )
        db.commit()
        return user.id


def test_admin_assigns_task_reminder_owner() -> None:
    suffix = uuid.uuid4().hex[:8]
    owner_id = _create_employee(f"reminder-owner-{suffix}")

    with auth_client(role="skill_admin", username=f"reminder-admin-{suffix}") as client:
        saved = client.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily",
            json={"owner_id": owner_id, "enabled": True},
        )

        assert saved.status_code == 200, saved.text
        assert saved.json() == {
            "skill_id": "ar-hexiao-daily",
            "skill_name": "应收核销日清",
            "owner_id": owner_id,
            "owner_name": "应收核销负责人",
            "enabled": True,
            "timezone": "Asia/Shanghai",
            "schedule_time": "09:10",
            "last_successful_business_date": None,
            "last_check_status": "never",
            "last_checked_at": None,
        }

        loaded = client.get(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily"
        )
        assert loaded.status_code == 200, loaded.text
        assert loaded.json() == saved.json()


def test_discovery_creates_one_owner_scoped_reminder_per_business_date() -> None:
    suffix = uuid.uuid4().hex[:8]
    username = f"discovery-owner-{suffix}"
    owner_id = _create_employee(username)
    with auth_client(role="skill_admin", username=f"discovery-admin-{suffix}") as admin:
        saved = admin.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily",
            json={"owner_id": owner_id, "enabled": True},
        )
        assert saved.status_code == 200, saved.text

    calls: list[tuple[str, ...]] = []

    def synthetic_probe(
        _account: str,
        _password: str,
        dates: tuple[str, ...],
    ) -> list[TaskDiscoveryDayResult]:
        calls.append(dates)
        return [
            TaskDiscoveryDayResult(
                business_date=dates[0],
                record_count=2,
                fingerprint="synthetic-fingerprint",
            )
        ]

    with auth_client(username=username) as employee:
        credential = employee.put(
            "/api/service-credentials/zhiyun",
            json={"account": "synthetic-account", "password": "synthetic-password"},
        )
        assert credential.status_code == 200, credential.text

        with SessionLocal() as db:
            execute_task_discovery(
                db,
                skill_id="ar-hexiao-daily",
                department_id="finance",
                business_dates=("2026-08-24",),
                trigger="scheduled",
                probe=synthetic_probe,
                now=datetime(2026, 8, 25, 1, 10, tzinfo=UTC),
            )
            execute_task_discovery(
                db,
                skill_id="ar-hexiao-daily",
                department_id="finance",
                business_dates=("2026-08-24",),
                trigger="manual",
                probe=synthetic_probe,
                now=datetime(2026, 8, 25, 2, 0, tzinfo=UTC),
            )

        board = employee.get("/api/task-reminders")
        assert board.status_code == 200, board.text
        assert board.json()["reminders"] == [
            {
                "id": board.json()["reminders"][0]["id"],
                "skill_id": "ar-hexiao-daily",
                "skill_name": "应收核销日清",
                "owner_id": owner_id,
                "owner_name": "应收核销负责人",
                "business_date": "2026-08-24",
                "record_count": 2,
                "state": "pending",
                "last_checked_at": "2026-08-25T02:00:00Z",
                "reopened": False,
                "workflow_id": None,
                "batch_id": None,
            }
        ]
        assert board.json()["check_failures"] == []
        workbench = employee.get("/api/workbench")
        assert workbench.status_code == 200, workbench.text
        assert workbench.json()["task_reminders"] == {
            "pending_dates": 1,
            "active_skills": 1,
            "failed_checks": 0,
        }
        assert calls == [("2026-08-24",), ("2026-08-24",)]


def test_task_discovery_schedule_uses_weekdays_and_catches_up_after_gaps() -> None:
    monday_before = datetime(2026, 8, 24, 9, 9)
    monday_due = datetime(2026, 8, 24, 9, 10)
    tuesday_due = datetime(2026, 8, 25, 9, 10)
    saturday = datetime(2026, 8, 29, 12, 0)

    assert scheduled_business_dates(None, monday_before) == ()
    assert scheduled_business_dates(None, monday_due) == (
        "2026-08-21",
        "2026-08-22",
        "2026-08-23",
    )
    assert scheduled_business_dates(None, tuesday_due) == ("2026-08-24",)
    assert scheduled_business_dates(None, saturday) == ()

    assert scheduled_business_dates(
        "2026-08-21",
        datetime(2026, 8, 26, 11, 0),
        holidays={date(2026, 8, 25)},
    ) == (
        "2026-08-22",
        "2026-08-23",
        "2026-08-24",
        "2026-08-25",
    )
    assert scheduled_business_dates(
        "2026-08-21",
        datetime(2026, 8, 25, 11, 0),
        holidays={date(2026, 8, 25)},
    ) == ()

    assert automatic_retry_times(date(2026, 8, 25)) == (
        datetime(2026, 8, 25, 9, 40),
        datetime(2026, 8, 25, 10, 40),
        datetime(2026, 8, 25, 14, 10),
    )
    assert next_automatic_retry_at(
        datetime(2026, 8, 25, 1, 10, tzinfo=UTC), "scheduled"
    ) == datetime(2026, 8, 25, 1, 40, tzinfo=UTC)
    assert next_automatic_retry_at(
        datetime(2026, 8, 25, 1, 41, tzinfo=UTC), "retry"
    ) == datetime(2026, 8, 25, 2, 40, tzinfo=UTC)
    assert next_automatic_retry_at(
        datetime(2026, 8, 25, 2, 41, tzinfo=UTC), "retry"
    ) == datetime(2026, 8, 25, 6, 10, tzinfo=UTC)
    assert next_automatic_retry_at(
        datetime(2026, 8, 25, 6, 11, tzinfo=UTC), "retry"
    ) is None


def test_discovery_worker_runs_due_check_once() -> None:
    suffix = uuid.uuid4().hex[:8]
    username = f"scheduled-owner-{suffix}"
    owner_id = _create_employee(username)
    with auth_client(role="skill_admin", username=f"scheduled-admin-{suffix}") as admin:
        saved = admin.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily",
            json={"owner_id": owner_id, "enabled": True},
        )
        assert saved.status_code == 200, saved.text
    with auth_client(username=username) as employee:
        credential = employee.put(
            "/api/service-credentials/zhiyun",
            json={"account": "synthetic-account", "password": "synthetic-password"},
        )
        assert credential.status_code == 200, credential.text

    with SessionLocal() as db:
        from app.models import TaskReminderSubscription

        subscription = db.query(TaskReminderSubscription).filter_by(
            department_id="finance",
            skill_id="ar-hexiao-daily",
        ).one()
        subscription.last_successful_business_date = "2026-08-24"
        db.commit()

        def synthetic_probe(_account, _password, dates):
            return [
                TaskDiscoveryDayResult(item, 1, f"fingerprint-{item}")
                for item in dates
            ]

        now = datetime(2026, 8, 26, 1, 10, tzinfo=UTC)
        assert run_discovery_tick(db, probe=synthetic_probe, now=now) is True
        assert run_discovery_tick(db, probe=synthetic_probe, now=now) is False


def test_owner_can_queue_manual_check_and_retry_terminal_failure() -> None:
    suffix = uuid.uuid4().hex[:8]
    username = f"retry-owner-{suffix}"
    owner_id = _create_employee(username)
    with auth_client(role="skill_admin", username=f"retry-admin-{suffix}") as admin:
        saved = admin.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily",
            json={"owner_id": owner_id, "enabled": True},
        )
        assert saved.status_code == 200, saved.text
    with auth_client(username=username) as employee:
        credential = employee.put(
            "/api/service-credentials/zhiyun",
            json={"account": "synthetic-account", "password": "synthetic-password"},
        )
        assert credential.status_code == 200, credential.text
        with SessionLocal() as db:
            def initial_probe(_account, _password, dates):
                return [TaskDiscoveryDayResult(item, 0, "0" * 64) for item in dates]

            assert run_discovery_tick(
                db,
                probe=initial_probe,
                now=datetime(2026, 8, 25, 1, 0, tzinfo=UTC),
            ) is True
        queued = employee.post(
            "/api/task-reminders/checks",
            json={
                "skill_id": "ar-hexiao-daily",
                "business_dates": ["2026-08-23"],
            },
        )
        assert queued.status_code == 202, queued.text
        duplicate = employee.post(
            "/api/task-reminders/checks",
            json={
                "skill_id": "ar-hexiao-daily",
                "business_dates": ["2026-08-23"],
            },
        )
        assert duplicate.status_code == 202, duplicate.text
        assert duplicate.json()["id"] == queued.json()["id"]

        with SessionLocal() as db:
            def failed_probe(_account, _password, _dates):
                raise RuntimeError("synthetic discovery failure")

            assert run_discovery_tick(
                db,
                probe=failed_probe,
                now=datetime(2026, 8, 25, 6, 11, tzinfo=UTC),
            ) is True

        board = employee.get("/api/task-reminders")
        assert board.status_code == 200, board.text
        failures = board.json()["check_failures"]
        assert failures and failures[0]["id"] == queued.json()["id"]
        retried = employee.post(
            f"/api/task-reminders/checks/{queued.json()['id']}/retry"
        )
        assert retried.status_code == 202, retried.text
        assert retried.json()["state"] == "queued"


def test_workflow_success_resolves_only_its_reminder_date() -> None:
    suffix = uuid.uuid4().hex[:8]
    username = f"workflow-reminder-owner-{suffix}"
    owner_id = _create_employee(username)
    with auth_client(role="skill_admin", username=f"workflow-reminder-admin-{suffix}") as admin:
        saved = admin.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily",
            json={"owner_id": owner_id, "enabled": True},
        )
        assert saved.status_code == 200, saved.text
    with auth_client(username=username) as employee:
        credential = employee.put(
            "/api/service-credentials/zhiyun",
            json={"account": "synthetic-account", "password": "synthetic-password"},
        )
        assert credential.status_code == 200, credential.text

    with SessionLocal() as db:
        from app.models import TaskReminder, WorkflowSession

        execute_task_discovery(
            db,
            skill_id="ar-hexiao-daily",
            department_id="finance",
            business_dates=("2026-08-22", "2026-08-23"),
            trigger="manual",
            probe=lambda _account, _password, dates: [
                TaskDiscoveryDayResult(item, 1, f"fingerprint-{item}") for item in dates
            ],
            now=datetime(2026, 8, 25, 2, 0, tzinfo=UTC),
        )
        workflow = WorkflowSession(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            owner_name="应收核销负责人",
            department_id="finance",
            skill_id="ar-hexiao-daily",
            skill_name="应收核销日清",
            skill_version="test",
            skill_hash="test",
            model_connection_id="background",
            model_provider="platform",
            model_name="background",
            reconciliation_date="2026-08-22",
            state="running",
        )
        db.add(workflow)
        db.flush()
        associate_reminder_with_workflow(db, workflow)
        workflow.state = "succeeded"
        sync_reminder_from_workflow(db, workflow)
        db.commit()

        states = {
            item.business_date: item.state
            for item in db.query(TaskReminder).filter_by(owner_id=owner_id).all()
        }
        assert states["2026-08-22"] == "resolved"
        assert states["2026-08-23"] == "pending"


def test_owner_can_clear_successful_reminders_without_rediscovery() -> None:
    suffix = uuid.uuid4().hex[:8]
    business_date = f"r{suffix}x"
    username = f"clear-reminder-owner-{suffix}"
    owner_id = _create_employee(username)
    with auth_client(role="skill_admin", username=f"clear-reminder-admin-{suffix}") as admin:
        assert admin.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily",
            json={"owner_id": owner_id, "enabled": True},
        ).status_code == 200
    with auth_client(username=username) as employee:
        assert employee.put(
            "/api/service-credentials/zhiyun",
            json={"account": "synthetic-account", "password": "synthetic-password"},
        ).status_code == 200

    with SessionLocal() as db:
        from app.models import TaskReminder, WorkflowSession

        execute_task_discovery(
            db,
            skill_id="ar-hexiao-daily",
            department_id="finance",
            business_dates=(business_date,),
            trigger="manual",
            probe=lambda _account, _password, dates: [
                TaskDiscoveryDayResult(dates[0], 1, "before-clear")
            ],
            now=datetime(2026, 8, 25, 2, 0, tzinfo=UTC),
        )
        workflow = WorkflowSession(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            owner_name="应收核销负责人",
            department_id="finance",
            skill_id="ar-hexiao-daily",
            skill_name="应收核销日清",
            skill_version="test",
            skill_hash="test",
            model_connection_id="background",
            model_provider="platform",
            model_name="background",
            reconciliation_date=business_date,
            state="running",
        )
        db.add(workflow)
        db.flush()
        associate_reminder_with_workflow(db, workflow)
        workflow.state = "succeeded"
        db.commit()

    with auth_client(username=username) as employee:
        completed = employee.get("/api/task-reminders")
        assert completed.status_code == 200, completed.text
        assert business_date not in {
            item["business_date"] for item in completed.json()["reminders"]
        }
        assert completed.json()["resolved_count"] >= 1

        cleared = employee.delete("/api/task-reminders/resolved")
        assert cleared.status_code == 200, cleared.text
        assert cleared.json() == {"dismissed_count": completed.json()["resolved_count"]}
        cleared_again = employee.delete("/api/task-reminders/resolved")
        assert cleared_again.status_code == 200, cleared_again.text
        assert cleared_again.json() == {"dismissed_count": 0}

    with SessionLocal() as db:
        reminder = db.query(TaskReminder).filter_by(
            owner_id=owner_id,
            business_date=business_date,
        ).one()
        assert reminder.state == "dismissed"

        execute_task_discovery(
            db,
            skill_id="ar-hexiao-daily",
            department_id="finance",
            business_dates=(business_date,),
            trigger="manual",
            probe=lambda _account, _password, dates: [
                TaskDiscoveryDayResult(dates[0], 2, "changed-after-clear")
            ],
            now=datetime(2026, 8, 25, 3, 0, tzinfo=UTC),
        )

    with auth_client(username=username) as employee:
        after_rediscovery = employee.get("/api/task-reminders")
        assert after_rediscovery.status_code == 200, after_rediscovery.text
        assert business_date not in {
            item["business_date"] for item in after_rediscovery.json()["reminders"]
        }
        assert after_rediscovery.json()["resolved_count"] == 0


def test_zero_result_does_not_turn_an_unfinished_reminder_into_success() -> None:
    suffix = uuid.uuid4().hex[:8]
    business_date = f"z{suffix}x"
    username = f"zero-result-owner-{suffix}"
    owner_id = _create_employee(username)
    with auth_client(role="skill_admin", username=f"zero-result-admin-{suffix}") as admin:
        assert admin.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily",
            json={"owner_id": owner_id, "enabled": True},
        ).status_code == 200
    with auth_client(username=username) as employee:
        assert employee.put(
            "/api/service-credentials/zhiyun",
            json={"account": "zero-result", "password": "zero-result-password"},
        ).status_code == 200

    with SessionLocal() as db:
        from app.models import TaskReminder

        for checked_at, count, fingerprint in (
            (datetime(2026, 8, 25, 1, 0, tzinfo=UTC), 1, "present-before"),
            (datetime(2026, 8, 25, 2, 0, tzinfo=UTC), 0, "empty-now"),
        ):
            execute_task_discovery(
                db,
                skill_id="ar-hexiao-daily",
                department_id="finance",
                business_dates=(business_date,),
                trigger="manual",
                probe=lambda _account, _password, dates, count=count, fingerprint=fingerprint: [
                    TaskDiscoveryDayResult(dates[0], count, fingerprint)
                ],
                now=checked_at,
            )
        reminder = db.query(TaskReminder).filter_by(
            owner_id=owner_id,
            business_date=business_date,
        ).one()
        assert reminder.state == "no_records"
        assert reminder.completed_at is None

    with auth_client(username=username) as employee:
        board = employee.get("/api/task-reminders")
        assert board.status_code == 200, board.text
        assert business_date not in {
            item["business_date"] for item in board.json()["reminders"]
        }
        assert board.json()["resolved_count"] == 0
        cleared = employee.delete("/api/task-reminders/resolved")
        assert cleared.status_code == 200, cleared.text
        assert cleared.json() == {"dismissed_count": 0}

    with SessionLocal() as db:
        execute_task_discovery(
            db,
            skill_id="ar-hexiao-daily",
            department_id="finance",
            business_dates=(business_date,),
            trigger="manual",
            probe=lambda _account, _password, dates: [
                TaskDiscoveryDayResult(dates[0], 2, "present-again")
            ],
            now=datetime(2026, 8, 25, 3, 0, tzinfo=UTC),
        )

    with auth_client(username=username) as employee:
        board = employee.get("/api/task-reminders")
        assert board.status_code == 200, board.text
        restored = next(
            item for item in board.json()["reminders"] if item["business_date"] == business_date
        )
        assert restored["state"] == "pending"
        assert restored["record_count"] == 2


def test_admin_cannot_dismiss_another_owners_successful_reminder() -> None:
    suffix = uuid.uuid4().hex[:8]
    business_date = f"a{suffix}x"
    username = f"cleanup-owner-{suffix}"
    owner_id = _create_employee(username)
    reminder_id = str(uuid.uuid4())
    with SessionLocal() as db:
        from app.models import TaskReminder

        db.add(
            TaskReminder(
                id=reminder_id,
                owner_id=owner_id,
                department_id="finance",
                skill_id="ar-hexiao-daily",
                business_date=business_date,
                record_count=1,
                fingerprint="cleanup-permission",
                state="resolved",
                completed_at=datetime.now(UTC),
            )
        )
        db.commit()

    with auth_client(role="skill_admin", username=f"cleanup-admin-{suffix}") as admin:
        cleared = admin.delete("/api/task-reminders/resolved")
        assert cleared.status_code == 200, cleared.text
        assert cleared.json() == {"dismissed_count": 0}

    with SessionLocal() as db:
        from app.models import TaskReminder

        reminder = db.get(TaskReminder, reminder_id)
        assert reminder is not None
        assert reminder.state == "resolved"

    with auth_client(username=username) as employee:
        cleared = employee.delete("/api/task-reminders/resolved")
        assert cleared.status_code == 200, cleared.text
        assert cleared.json() == {"dismissed_count": 1}

    with SessionLocal() as db:
        from app.models import AuditEvent

        event = (
            db.query(AuditEvent)
            .filter_by(
                actor_id=owner_id,
                action="task_reminder.resolved.dismissed",
            )
            .order_by(AuditEvent.id.desc())
            .first()
        )
        assert event is not None
        assert event.resource_type == "task_reminder_collection"
        assert json.loads(event.details_json)["dismissed_reminder_ids"] == [reminder_id]


def test_failed_and_cancelled_formal_tasks_keep_reminders_pending() -> None:
    suffix = uuid.uuid4().hex[:8]
    owner_id = _create_employee(f"terminal-reminder-owner-{suffix}")
    with SessionLocal() as db:
        from app.models import TaskReminder, WorkflowSession

        for prefix, state in (("f", "failed"), ("c", "cancelled")):
            business_date = f"{prefix}{suffix}x"
            workflow = WorkflowSession(
                id=str(uuid.uuid4()),
                owner_id=owner_id,
                owner_name="应收核销负责人",
                department_id="finance",
                skill_id="ar-hexiao-daily",
                skill_name="应收核销日清",
                skill_version="test",
                skill_hash="test",
                model_connection_id="background",
                model_provider="platform",
                model_name="background",
                reconciliation_date=business_date,
                state=state,
            )
            reminder = TaskReminder(
                id=str(uuid.uuid4()),
                owner_id=owner_id,
                department_id="finance",
                skill_id="ar-hexiao-daily",
                business_date=business_date,
                record_count=1,
                fingerprint=f"terminal-{state}",
                state="in_progress",
                workflow_id=workflow.id,
            )
            db.add_all((workflow, reminder))
            db.flush()
            sync_reminder_from_workflow(db, workflow)
            assert reminder.state == "pending"
            assert reminder.completed_at is None
        db.rollback()


def test_failed_batch_restores_all_unsuccessful_reminders_to_pending() -> None:
    suffix = uuid.uuid4().hex[:8]
    owner_id = _create_employee(f"failed-batch-reminder-{suffix}")
    batch_id = f"BAT-REMINDER-{suffix}"
    with SessionLocal() as db:
        from app.models import TaskReminder, WorkflowBatch, WorkflowSession

        batch = WorkflowBatch(
            id=batch_id,
            owner_id=owner_id,
            owner_name="应收核销负责人",
            department_id="finance",
            skill_id="ar-hexiao-daily",
            skill_name="应收核销日清",
            skill_version="test",
            model_connection_id="background",
            model_provider="platform",
            model_name="background",
            reconciliation_dates_json='["2026-08-10", "2026-08-11", "2026-08-12"]',
            state="running",
        )
        workflows = []
        reminders = []
        for sequence, (business_date, state, reminder_state) in enumerate(
            (
                ("2026-08-10", "succeeded", "resolved"),
                ("2026-08-11", "failed", "in_progress"),
                ("2026-08-12", "queued", "in_progress"),
            ),
            start=1,
        ):
            workflow = WorkflowSession(
                id=str(uuid.uuid4()),
                owner_id=owner_id,
                owner_name="应收核销负责人",
                department_id="finance",
                skill_id="ar-hexiao-daily",
                skill_name="应收核销日清",
                skill_version="test",
                skill_hash="test",
                model_connection_id="background",
                model_provider="platform",
                model_name="background",
                reconciliation_date=business_date,
                batch_id=batch_id,
                batch_sequence=sequence,
                state=state,
            )
            workflows.append(workflow)
            reminders.append(
                TaskReminder(
                    id=str(uuid.uuid4()),
                    owner_id=owner_id,
                    department_id="finance",
                    skill_id="ar-hexiao-daily",
                    business_date=business_date,
                    record_count=1,
                    fingerprint=f"batch-{business_date}",
                    state=reminder_state,
                    workflow_id=workflow.id,
                    batch_id=batch_id,
                )
            )
        db.add_all([batch, *workflows, *reminders])
        independently_succeeded = WorkflowSession(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            owner_name="应收核销负责人",
            department_id="finance",
            skill_id="ar-hexiao-daily",
            skill_name="应收核销日清",
            skill_version="test",
            skill_hash="test",
            model_connection_id="background",
            model_provider="platform",
            model_name="background",
            reconciliation_date="2026-08-11",
            state="succeeded",
        )
        db.add(independently_succeeded)
        db.flush()

        _fail_batch(db, workflows[1], "synthetic failure")
        assert [item.state for item in reminders] == ["resolved", "resolved", "pending"]
        assert reminders[1].workflow_id == independently_succeeded.id
        assert reminders[1].batch_id is None
        db.rollback()


def test_failed_batch_does_not_use_success_older_than_a_reopened_reminder() -> None:
    suffix = uuid.uuid4().hex[:8]
    owner_id = _create_employee(f"reopened-batch-owner-{suffix}")
    business_date = f"o{suffix}x"
    batch_id = f"BAT-REOPENED-{suffix}"
    old_success_at = datetime(2026, 8, 25, 1, 0, tzinfo=UTC)
    reopened_at = datetime(2026, 8, 25, 2, 0, tzinfo=UTC)
    with SessionLocal() as db:
        from app.models import TaskReminder, WorkflowBatch, WorkflowSession

        old_success = WorkflowSession(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            owner_name="应收核销负责人",
            department_id="finance",
            skill_id="ar-hexiao-daily",
            skill_name="应收核销日清",
            skill_version="test",
            skill_hash="test",
            model_connection_id="background",
            model_provider="platform",
            model_name="background",
            reconciliation_date=business_date,
            state="succeeded",
            created_at=old_success_at,
            updated_at=old_success_at,
        )
        failed = WorkflowSession(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            owner_name="应收核销负责人",
            department_id="finance",
            skill_id="ar-hexiao-daily",
            skill_name="应收核销日清",
            skill_version="test",
            skill_hash="test",
            model_connection_id="background",
            model_provider="platform",
            model_name="background",
            reconciliation_date=business_date,
            batch_id=batch_id,
            batch_sequence=1,
            state="failed",
            created_at=reopened_at,
            updated_at=reopened_at,
        )
        batch = WorkflowBatch(
            id=batch_id,
            owner_id=owner_id,
            owner_name="应收核销负责人",
            department_id="finance",
            skill_id="ar-hexiao-daily",
            skill_name="应收核销日清",
            skill_version="test",
            model_connection_id="background",
            model_provider="platform",
            model_name="background",
            reconciliation_dates_json=json.dumps([business_date]),
            state="running",
        )
        reminder = TaskReminder(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            department_id="finance",
            skill_id="ar-hexiao-daily",
            business_date=business_date,
            record_count=2,
            fingerprint="reopened-after-success",
            state="in_progress",
            workflow_id=failed.id,
            batch_id=batch_id,
            last_checked_at=reopened_at,
        )
        db.add_all((batch, old_success, failed, reminder))
        db.flush()

        _fail_batch(db, failed, "synthetic failure")

        assert reminder.state == "pending"
        assert reminder.workflow_id == failed.id
        assert reminder.batch_id == batch_id
        assert reminder.completed_at is None
        db.rollback()


def test_admin_manual_check_enforces_recent_31_day_boundary() -> None:
    suffix = uuid.uuid4().hex[:8]
    owner_id = _create_employee(f"range-reminder-owner-{suffix}")
    today = datetime.now().astimezone().date()
    valid_dates = [
        (today - timedelta(days=offset)).isoformat()
        for offset in range(31, 0, -1)
    ]
    with auth_client(role="skill_admin", username=f"range-reminder-admin-{suffix}") as admin:
        assert admin.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily",
            json={"owner_id": owner_id, "enabled": True},
        ).status_code == 200
        accepted = admin.post(
            "/api/task-reminders/checks",
            json={"skill_id": "ar-hexiao-daily", "business_dates": valid_dates},
        )
        assert accepted.status_code == 202, accepted.text
        rejected = admin.post(
            "/api/task-reminders/checks",
            json={
                "skill_id": "ar-hexiao-daily",
                "business_dates": [
                    (today - timedelta(days=32)).isoformat(),
                    *valid_dates,
                ],
            },
        )
        assert rejected.status_code == 422, rejected.text


def test_admin_manages_assigned_owner_credential_without_plaintext_readback() -> None:
    suffix = uuid.uuid4().hex[:8]
    username = f"credential-owner-{suffix}"
    owner_id = _create_employee(username)
    with auth_client(role="skill_admin", username=f"credential-admin-{suffix}") as admin:
        saved = admin.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily",
            json={"owner_id": owner_id, "enabled": True},
        )
        assert saved.status_code == 200, saved.text
        credential = admin.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily/credential",
            json={"account": "synthetic-owner-account", "password": "synthetic-password"},
        )
        assert credential.status_code == 200, credential.text
        assert credential.json()["configured"] is True
        assert "synthetic-owner-account" not in credential.text
        assert "synthetic-password" not in credential.text

        status = admin.get(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily/credential"
        )
        assert status.status_code == 200, status.text
        assert status.json() == credential.json()

        removed = admin.delete(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily/credential"
        )
        assert removed.status_code == 204, removed.text

    with auth_client(username=username) as employee:
        own_status = employee.get("/api/service-credentials/zhiyun")
        assert own_status.status_code == 200, own_status.text
        assert own_status.json()["configured"] is False


def test_owner_change_preserves_formal_task_and_reopens_changed_completed_date() -> None:
    suffix = uuid.uuid4().hex[:8]
    old_username = f"old-reminder-owner-{suffix}"
    new_username = f"new-reminder-owner-{suffix}"
    old_owner_id = _create_employee(old_username)
    new_owner_id = _create_employee(new_username)
    with auth_client(role="skill_admin", username=f"owner-change-admin-{suffix}") as admin:
        assert admin.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily",
            json={"owner_id": old_owner_id, "enabled": True},
        ).status_code == 200
        assert admin.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily/credential",
            json={"account": "old-account", "password": "old-password"},
        ).status_code == 200

        with SessionLocal() as db:
            from app.models import TaskReminder, WorkflowSession

            execute_task_discovery(
                db,
                skill_id="ar-hexiao-daily",
                department_id="finance",
                business_dates=("2026-08-22", "2026-08-23"),
                trigger="manual",
                probe=lambda _account, _password, dates: [
                    TaskDiscoveryDayResult(item, 1, f"before-{item}") for item in dates
                ],
                now=datetime(2026, 8, 25, 2, 0, tzinfo=UTC),
            )
            workflow_ids: list[str] = []
            for business_date, state in (
                ("2026-08-22", "running"),
                ("2026-08-23", "succeeded"),
            ):
                workflow = WorkflowSession(
                    id=str(uuid.uuid4()),
                    owner_id=old_owner_id,
                    owner_name="应收核销负责人",
                    department_id="finance",
                    skill_id="ar-hexiao-daily",
                    skill_name="应收核销日清",
                    skill_version="test",
                    skill_hash="test",
                    model_connection_id="background",
                    model_provider="platform",
                    model_name="background",
                    reconciliation_date=business_date,
                    state="running",
                )
                db.add(workflow)
                db.flush()
                associate_reminder_with_workflow(db, workflow)
                workflow.state = state
                sync_reminder_from_workflow(db, workflow)
                workflow_ids.append(workflow.id)
            db.commit()

        changed = admin.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily",
            json={"owner_id": new_owner_id, "enabled": True},
        )
        assert changed.status_code == 200, changed.text
        assert admin.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily/credential",
            json={"account": "new-account", "password": "new-password"},
        ).status_code == 200

        with SessionLocal() as db:
            from app.models import TaskReminder

            execute_task_discovery(
                db,
                skill_id="ar-hexiao-daily",
                department_id="finance",
                business_dates=("2026-08-22", "2026-08-23"),
                trigger="manual",
                probe=lambda _account, _password, dates: [
                    TaskDiscoveryDayResult(item, 2, f"after-{item}") for item in dates
                ],
                now=datetime(2026, 8, 25, 3, 0, tzinfo=UTC),
            )
            reminders = {
                item.business_date: item
                for item in db.query(TaskReminder)
                .filter(TaskReminder.business_date.in_(("2026-08-22", "2026-08-23")))
                .all()
            }
            active = reminders["2026-08-22"]
            reopened = reminders["2026-08-23"]
            assert active.owner_id == old_owner_id
            assert active.state == "in_progress"
            assert active.workflow_id == workflow_ids[0]
            assert reopened.owner_id == new_owner_id
            assert reopened.state == "reopened"
            assert reopened.workflow_id is None
            assert reopened.batch_id is None


def test_formal_workflow_is_blocked_while_read_only_discovery_is_running() -> None:
    suffix = uuid.uuid4().hex[:8]
    owner_id = _create_employee(f"discovery-lock-owner-{suffix}")
    with auth_client(role="skill_admin", username=f"discovery-lock-admin-{suffix}") as admin:
        assert admin.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily",
            json={"owner_id": owner_id, "enabled": True},
        ).status_code == 200

    with SessionLocal() as db:
        from app.models import TaskDiscoveryCheck

        check = db.query(TaskDiscoveryCheck).filter_by(
            skill_id="ar-hexiao-daily",
            owner_id=owner_id,
            state="queued",
        ).order_by(TaskDiscoveryCheck.created_at.desc()).first()
        assert check is not None
        check.state = "running"
        check.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        db.commit()

        with pytest.raises(Exception) as raised:
            _assert_single_flight_available(db, "ar-hexiao-daily")
        assert getattr(raised.value, "status_code", None) == 409
        assert "只读任务检查正在进行" in str(getattr(raised.value, "detail", ""))
        check.state = "failed"
        check.lease_expires_at = None
        db.commit()


def test_queued_conversational_workflow_waits_for_running_discovery() -> None:
    suffix = uuid.uuid4().hex[:8]
    owner_id = _create_employee(f"claim-lock-owner-{suffix}")
    with auth_client(role="skill_admin", username=f"claim-lock-admin-{suffix}") as admin:
        assert admin.put(
            "/api/admin/task-reminder-subscriptions/ar-hexiao-daily",
            json={"owner_id": owner_id, "enabled": True},
        ).status_code == 200

    with SessionLocal() as db:
        from app.models import TaskDiscoveryCheck, WorkflowAction, WorkflowSession

        check = (
            db.query(TaskDiscoveryCheck)
            .filter_by(
                skill_id="ar-hexiao-daily",
                owner_id=owner_id,
                state="queued",
            )
            .order_by(TaskDiscoveryCheck.created_at.desc())
            .first()
        )
        assert check is not None
        check.state = "running"
        check.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        workflow = WorkflowSession(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            owner_name="应收核销负责人",
            department_id="finance",
            skill_id="ar-hexiao-daily",
            skill_name="应收核销日清",
            skill_version="test",
            skill_hash="test",
            model_connection_id="background",
            model_provider="platform",
            model_name="background",
            reconciliation_date=f"q{suffix}x",
            state="active",
            stage="preparing",
        )
        action = WorkflowAction(
            id=str(uuid.uuid4()),
            workflow_id=workflow.id,
            name="prepare_worklist",
            state="queued",
        )
        db.add_all((workflow, action))
        db.commit()

        assert claim_next_workflow_action(db, ("workflow",)) is None
        db.refresh(action)
        assert action.state == "queued"
        check.state = "failed"
        check.lease_expires_at = None
        action.state = "cancelled"
        workflow.state = "cancelled"
        db.commit()

def test_expired_formal_worker_restores_linked_reminder() -> None:
    suffix = uuid.uuid4().hex[:8]
    owner_id = _create_employee(f"expired-reminder-owner-{suffix}")
    now = datetime(2026, 8, 25, 4, 0, tzinfo=UTC)
    with SessionLocal() as db:
        from app.models import TaskReminder, WorkflowAction, WorkflowSession

        workflow = WorkflowSession(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            owner_name="应收核销负责人",
            department_id="finance",
            skill_id="ar-hexiao-daily",
            skill_name="应收核销日清",
            skill_version="test",
            skill_hash="test",
            model_connection_id="background",
            model_provider="platform",
            model_name="background",
            reconciliation_date="2025-01-02",
            state="running",
        )
        reminder = TaskReminder(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            department_id="finance",
            skill_id="ar-hexiao-daily",
            business_date="2025-01-02",
            record_count=1,
            fingerprint="expired-worker",
            state="in_progress",
            workflow_id=workflow.id,
            first_discovered_at=now,
            last_checked_at=now,
        )
        action = WorkflowAction(
            id=str(uuid.uuid4()),
            workflow_id=workflow.id,
            name="fetch_zhiyun",
            state="running",
            lease_expires_at=now - timedelta(minutes=1),
        )
        db.add_all((workflow, reminder, action))
        db.commit()

        recover_expired_jobs(db, now)
        db.commit()
        db.refresh(reminder)
        assert workflow.state == "failed"
        assert reminder.state == "pending"
        assert reminder.completed_at is None
