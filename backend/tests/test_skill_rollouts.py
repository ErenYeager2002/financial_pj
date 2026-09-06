from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from helpers import auth_client
from sqlalchemy import delete, select, update
from test_skill_releases import _import_and_review, _preserve_skill

from app import skill_rollout_service
from app.database import SessionLocal, init_db
from app.models import (
    RunRecord,
    SkillAvailability,
    SkillRollout,
    SkillSourceBinding,
    WorkflowAction,
    WorkflowSession,
)
from app.registry import registry
from app.skill_rollout_service import run_rollout_once

ROLLOUT_SKILLS = {
    "compliance-spot-check",
    "dept-expense-alloc",
    "labor-invoice-check",
    "receivables-merge-and-split",
}


@pytest.fixture(autouse=True)
def isolate_rollouts():
    init_db()
    with SessionLocal() as db:
        db.execute(delete(SkillRollout))
        db.execute(delete(SkillAvailability))
        db.execute(delete(SkillSourceBinding))
        db.execute(
            update(RunRecord)
            .where(
                RunRecord.skill_id.in_(ROLLOUT_SKILLS),
                RunRecord.state.not_in(("succeeded", "failed", "timed_out", "cancelled")),
            )
            .values(state="cancelled")
        )
        workflow_ids = select(WorkflowSession.id).where(
            WorkflowSession.skill_id.in_(ROLLOUT_SKILLS)
        )
        db.execute(
            update(WorkflowAction)
            .where(
                WorkflowAction.workflow_id.in_(workflow_ids),
                WorkflowAction.state.in_(("queued", "running")),
            )
            .values(state="cancelled")
        )
        db.execute(
            update(WorkflowSession)
            .where(
                WorkflowSession.skill_id.in_(ROLLOUT_SKILLS),
                WorkflowSession.state.not_in(("succeeded", "failed", "cancelled")),
            )
            .values(state="cancelled", stage="cancelled")
        )
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(SkillRollout))
        db.execute(delete(SkillAvailability))
        db.execute(delete(SkillSourceBinding))
        db.commit()


def _start_rollout(admin, release: dict[str, object]):
    return admin.post(
        f"/api/admin/skill-releases/{release['id']}/rollout",
        json={
            "confirmation": f"停用并发布 {release['skill_id']} {release['version']}"
        },
    )


def test_rollout_disables_activates_verifies_and_enables() -> None:
    skill_id = "compliance-spot-check"
    registry.refresh()
    with _preserve_skill(skill_id):
        with auth_client(role="skill_admin") as admin:
            release = _import_and_review(admin, skill_id, "9.7.1")
            with SessionLocal() as db:
                binding = db.scalar(
                    select(SkillSourceBinding).where(SkillSourceBinding.skill_id == skill_id)
                )
                if binding is None:
                    binding = SkillSourceBinding(
                        id=str(uuid.uuid4()),
                        skill_id=skill_id,
                        repository_url=str(release["source_repository"]),
                        source_path=f"skills/{skill_id}",
                        tracking_ref="main",
                        binding_status="bound",
                        last_seen_commit=str(release["source_commit"]),
                        last_seen_tree_hash=str(release["source_tree_hash"]),
                        created_by=str(release["imported_by"]),
                        updated_by=str(release["imported_by"]),
                    )
                    db.add(binding)
                db.commit()
            started = _start_rollout(admin, release)
            assert started.status_code == 202, started.text
            rollout = started.json()
            assert rollout["state"] == "queued"
            assert run_rollout_once(force=True) is True
            finished = admin.get(f"/api/admin/skill-rollouts/{rollout['id']}")
            assert finished.status_code == 200
            assert finished.json()["state"] == "succeeded", finished.text
            active = registry.get(skill_id, include_unpublished=True)
            assert active is not None
            assert active.manifest.version == "9.7.1"
            with SessionLocal() as db:
                availability = db.get(SkillAvailability, skill_id)
                assert availability is not None
                assert availability.state == "enabled"
                binding = db.scalar(
                    select(SkillSourceBinding).where(SkillSourceBinding.skill_id == skill_id)
                )
                assert binding is not None
                assert binding.published_commit == release["source_commit"]
                assert binding.published_tree_hash == release["source_tree_hash"]


def test_rollout_waits_for_active_work_then_continues() -> None:
    skill_id = "receivables-merge-and-split"
    run_id = str(uuid.uuid4())
    with _preserve_skill(skill_id):
        with auth_client(role="skill_admin") as admin:
            release = _import_and_review(admin, skill_id, "9.7.2")
            with SessionLocal() as db:
                db.add(
                    RunRecord(
                        id=run_id,
                        owner_id=str(release["imported_by"]),
                        skill_id=skill_id,
                        skill_name="销售拆分",
                        skill_version="1.0.0",
                        skill_hash="a" * 64,
                        manifest_path="tool.yaml",
                        manifest_snapshot="{}",
                        adapter="python",
                        worker_pool="python",
                        state="queued",
                    )
                )
                db.commit()
            started = _start_rollout(admin, release)
            assert started.status_code == 202, started.text
            rollout_id = started.json()["id"]
            assert run_rollout_once(force=True) is True
            waiting = admin.get(f"/api/admin/skill-rollouts/{rollout_id}")
            assert waiting.json()["state"] == "draining"
            with SessionLocal() as db:
                availability = db.get(SkillAvailability, skill_id)
                assert availability is not None and availability.state == "draining"
                run = db.get(RunRecord, run_id)
                assert run is not None
                run.state = "succeeded"
                db.commit()
            assert run_rollout_once(force=True) is True
            finished = admin.get(f"/api/admin/skill-rollouts/{rollout_id}")
            assert finished.json()["state"] == "succeeded"


def test_rollout_failure_reenables_verified_previous_version(monkeypatch) -> None:
    skill_id = "labor-invoice-check"
    with _preserve_skill(skill_id):
        with auth_client(role="skill_admin") as admin:
            release = _import_and_review(admin, skill_id, "9.7.3")
            started = _start_rollout(admin, release)
            assert started.status_code == 202, started.text

            def fail_activation(*_args, **_kwargs):
                raise RuntimeError("synthetic activation failure")

            monkeypatch.setattr(
                skill_rollout_service, "activate_reviewed_release", fail_activation
            )
            assert run_rollout_once(force=True) is True
            finished = admin.get(
                f"/api/admin/skill-rollouts/{started.json()['id']}"
            ).json()
            assert finished["state"] == "failed"
            with SessionLocal() as db:
                availability = db.get(SkillAvailability, skill_id)
                assert availability is not None
                assert availability.state == "enabled"


def test_rollout_keeps_skill_disabled_when_restore_verification_fails(monkeypatch) -> None:
    skill_id = "dept-expense-alloc"
    with _preserve_skill(skill_id):
        with auth_client(role="skill_admin") as admin:
            release = _import_and_review(admin, skill_id, "9.7.4")
            started = _start_rollout(admin, release)
            assert started.status_code == 202, started.text

            def corrupt_then_fail(*_args, **_kwargs):
                manifest = registry.get(skill_id, include_unpublished=True)
                assert manifest is not None
                path = manifest.directory / "SKILL.md"
                path.write_text(path.read_text(encoding="utf-8") + "\n变更", encoding="utf-8")
                registry.refresh()
                raise RuntimeError("synthetic restore verification failure")

            monkeypatch.setattr(
                skill_rollout_service, "activate_reviewed_release", corrupt_then_fail
            )
            assert run_rollout_once(force=True) is True
            finished = admin.get(
                f"/api/admin/skill-rollouts/{started.json()['id']}"
            ).json()
            assert finished["state"] == "failed_disabled"
            with SessionLocal() as db:
                availability = db.get(SkillAvailability, skill_id)
                assert availability is not None
                assert availability.state == "failed_disabled"


def test_interrupted_verification_recovers_confirmed_target_version() -> None:
    skill_id = "compliance-spot-check"
    with _preserve_skill(skill_id):
        with auth_client(role="skill_admin") as admin:
            release = _import_and_review(admin, skill_id, "9.7.5")
            started = _start_rollout(admin, release)
            assert started.status_code == 202, started.text
            rollout_id = started.json()["id"]
            assert run_rollout_once(force=True) is True
            with SessionLocal() as db:
                rollout = db.get(SkillRollout, rollout_id)
                assert rollout is not None
                rollout.state = "verifying"
                rollout.finished_at = None
                rollout.updated_at = datetime.now(UTC) - timedelta(minutes=20)
                availability = db.get(SkillAvailability, skill_id)
                assert availability is not None
                availability.state = "disabled"
                db.commit()
            assert run_rollout_once() is True
            recovered = admin.get(f"/api/admin/skill-rollouts/{rollout_id}").json()
            assert recovered["state"] == "succeeded"
            with SessionLocal() as db:
                availability = db.get(SkillAvailability, skill_id)
                assert availability is not None
                assert availability.state == "enabled"
