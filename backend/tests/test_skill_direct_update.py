from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from helpers import auth_client
from sqlalchemy import select
from test_skill_releases import _stage_release

from app import skill_update_service
from app.auth import UserContext
from app.auth_service import get_user_by_username
from app.contracts import SkillSourceUpdateCheckRead
from app.database import SessionLocal
from app.models import SkillAvailability, SkillRelease, SkillSourceBinding
from app.registry import registry
from app.settings import settings


@contextmanager
def preserve_skill(skill_id: str) -> Iterator[None]:
    target = settings.skill_dir / skill_id
    backup = settings.data_dir / f"direct-update-skill-{skill_id}-{uuid.uuid4()}"
    shutil.copytree(target, backup)
    try:
        yield
    finally:
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(backup, target)
        shutil.rmtree(backup, ignore_errors=True)
        registry.refresh()


def test_direct_update_requires_disabled_skill() -> None:
    with auth_client(role="skill_admin") as admin:
        response = admin.post("/api/admin/skills/compliance-spot-check/update")
    assert response.status_code == 409
    assert "先完成" in response.json()["detail"]


def test_direct_update_pulls_package_replaces_skill_and_enables_it(monkeypatch) -> None:
    skill_id = "compliance-spot-check"
    with preserve_skill(skill_id):
        with auth_client(role="skill_admin", username="direct-update-admin") as admin:
            with SessionLocal() as db:
                actor_record = get_user_by_username(db, "direct-update-admin")
                assert actor_record is not None
                db.add(
                    SkillAvailability(
                        skill_id=skill_id,
                        state="disabled",
                        reason="测试前已禁用",
                        changed_by=actor_record.id,
                    )
                )
                binding_id = str(uuid.uuid4())
                db.add(
                    SkillSourceBinding(
                        id=binding_id,
                        skill_id=skill_id,
                        repository_url="https://gitee.com/Lee157/finance-skills.git",
                        source_path=f"skills/{skill_id}",
                        tracking_ref="main",
                        binding_status="bound",
                        last_seen_commit="a" * 40,
                        last_seen_tree_hash="b" * 64,
                        published_commit="c" * 40,
                        published_tree_hash="d" * 64,
                        created_by=actor_record.id,
                        updated_by=actor_record.id,
                    )
                )
                db.commit()

            def fake_check_update(db, actor, requested_skill_id):
                assert requested_skill_id == skill_id
                binding = db.scalar(
                    select(SkillSourceBinding).where(
                        SkillSourceBinding.skill_id == requested_skill_id
                    )
                )
                assert binding is not None
                binding.last_seen_commit = "e" * 40
                binding.last_seen_tree_hash = "f" * 64
                db.commit()
                return SkillSourceUpdateCheckRead(
                    skill_id=skill_id,
                    repository_url=binding.repository_url,
                    source_path=binding.source_path,
                    tracking_ref=binding.tracking_ref,
                    commit="e" * 40,
                    tree_hash="f" * 64,
                    published_commit=binding.published_commit,
                    published_tree_hash=binding.published_tree_hash,
                    update_available=True,
                )

            def fake_prepare(db, actor: UserContext, requested_skill_id: str, version: str):
                package_name = _stage_release(requested_skill_id, version)
                return skill_update_service.import_release(db, actor, package_name)

            monkeypatch.setattr(
                skill_update_service.skill_source_service,
                "check_update",
                fake_check_update,
            )
            monkeypatch.setattr(skill_update_service, "prepare_bound_release", fake_prepare)

            response = admin.post(f"/api/admin/skills/{skill_id}/update")

            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["skill_id"] == skill_id
            assert payload["state"] == "published"
            assert registry.get(skill_id, include_unpublished=True).manifest.version == payload[
                "version"
            ]

            with SessionLocal() as db:
                availability = db.get(SkillAvailability, skill_id)
                assert availability is not None
                assert availability.state == "enabled"
                binding = db.get(SkillSourceBinding, binding_id)
                assert binding is not None
                assert binding.published_commit == payload["source_commit"]
                assert binding.published_tree_hash == payload["source_tree_hash"]
                release = db.get(SkillRelease, payload["id"])
                assert release is not None
                assert release.state == "published"
                db.delete(availability)
                db.delete(binding)
                db.delete(release)
                db.commit()
