from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from helpers import auth_client
from sqlalchemy import delete, select

from app import skill_source_service
from app.database import SessionLocal, init_db
from app.models import AuditEvent, SkillSourceBinding

REPOSITORY = "https://gitee.com/Lee157/finance-skills.git"
COMMIT = "7f4f2d8622a3c50a8159c1ff4fc1c3a9e818be16"


@pytest.fixture(autouse=True)
def isolate_source_bindings():
    init_db()
    with SessionLocal() as db:
        db.execute(delete(SkillSourceBinding))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(SkillSourceBinding))
        db.commit()


def _catalog() -> skill_source_service.RemoteSkillCatalog:
    return skill_source_service.RemoteSkillCatalog(
        repository_url=REPOSITORY,
        tracking_ref="main",
        commit=COMMIT,
        skills=(
            skill_source_service.RemoteSkill(name="ar-hexiao-daily", path="skills/ar-hexiao-daily"),
            skill_source_service.RemoteSkill(
                name="compliance-spot-check", path="skills/compliance-spot-check"
            ),
            skill_source_service.RemoteSkill(
                name="qige-invoice-to-kingdee", path="skills/qige-invoice-to-kingdee"
            ),
            skill_source_service.RemoteSkill(
                name="update-finance-skills", path="skills/update-finance-skills"
            ),
        ),
    )


def test_employee_cannot_manage_skill_source_bindings(monkeypatch) -> None:
    monkeypatch.setattr(skill_source_service, "load_remote_catalog", lambda *_: _catalog())
    with auth_client() as employee:
        assert employee.get("/api/admin/skill-sources/bindings").status_code == 403
        assert (
            employee.post(
                "/api/admin/skill-sources/discover",
                json={"repository_url": REPOSITORY, "tracking_ref": "main"},
            ).status_code
            == 403
        )


def test_discovery_matches_platform_names_and_marks_exclusions(monkeypatch) -> None:
    monkeypatch.setattr(skill_source_service, "load_remote_catalog", lambda *_: _catalog())
    with auth_client(role="skill_admin") as admin:
        response = admin.post(
            "/api/admin/skill-sources/discover",
            json={"repository_url": REPOSITORY, "tracking_ref": "main"},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["commit"] == COMMIT
    candidates = {item["source_name"]: item for item in payload["candidates"]}
    assert candidates["ar-hexiao-daily"]["match_state"] == "candidate"
    assert candidates["ar-hexiao-daily"]["platform_skill_id"] == "ar-hexiao-daily"
    assert candidates["qige-invoice-to-kingdee"]["match_state"] == "unmatched"
    assert candidates["update-finance-skills"]["match_state"] == "excluded"


def test_admin_confirms_unique_candidate_and_repeat_is_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(skill_source_service, "load_remote_catalog", lambda *_: _catalog())
    body = {
        "skill_id": "compliance-spot-check",
        "repository_url": REPOSITORY,
        "tracking_ref": "main",
        "source_path": "skills/compliance-spot-check",
        "expected_commit": COMMIT,
    }
    with auth_client(role="skill_admin") as admin:
        first = admin.post("/api/admin/skill-sources/bindings", json=body)
        second = admin.post("/api/admin/skill-sources/bindings", json=body)
        listed = admin.get("/api/admin/skill-sources/bindings")
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    matching = [item for item in listed.json() if item["skill_id"] == body["skill_id"]]
    assert len(matching) == 1
    assert matching[0]["binding_status"] == "bound"
    assert matching[0]["source_path"] == body["source_path"]
    assert matching[0]["last_seen_commit"] == COMMIT

    with SessionLocal() as db:
        event = db.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "admin.skill_source_binding.confirm")
            .order_by(AuditEvent.id.desc())
        )
        assert event is not None
        details = json.loads(event.details_json)
        assert "content" not in details
        assert "credential" not in details
        binding = db.scalar(
            select(SkillSourceBinding).where(
                SkillSourceBinding.skill_id == "compliance-spot-check"
            )
        )
        assert binding is not None


def test_confirmation_rejects_name_mismatch_and_stale_discovery(monkeypatch) -> None:
    monkeypatch.setattr(skill_source_service, "load_remote_catalog", lambda *_: _catalog())
    base = {
        "skill_id": "ar-hexiao-daily",
        "repository_url": REPOSITORY,
        "tracking_ref": "main",
        "expected_commit": COMMIT,
    }
    with auth_client(role="skill_admin") as admin:
        mismatch = admin.post(
            "/api/admin/skill-sources/bindings",
            json={**base, "source_path": "skills/compliance-spot-check"},
        )
        stale = admin.post(
            "/api/admin/skill-sources/bindings",
            json={
                **base,
                "source_path": "skills/ar-hexiao-daily",
                "expected_commit": "a" * 40,
            },
        )
    assert mismatch.status_code == 422
    assert "名称" in mismatch.json()["detail"]
    assert stale.status_code == 409
    assert "重新发现" in stale.json()["detail"]


def test_confirmation_rejects_unsafe_source_path(monkeypatch) -> None:
    unsafe = skill_source_service.RemoteSkillCatalog(
        repository_url=REPOSITORY,
        tracking_ref="main",
        commit=COMMIT,
        skills=(skill_source_service.RemoteSkill(name="ar-hexiao-daily", path="../outside"),),
    )
    monkeypatch.setattr(skill_source_service, "load_remote_catalog", lambda *_: unsafe)
    with auth_client(role="skill_admin") as admin:
        response = admin.post(
            "/api/admin/skill-sources/bindings",
            json={
                "skill_id": "ar-hexiao-daily",
                "repository_url": REPOSITORY,
                "tracking_ref": "main",
                "source_path": "../outside",
                "expected_commit": COMMIT,
            },
        )
    assert response.status_code == 422
    assert "源码目录" in response.json()["detail"]


def test_check_update_uses_binding_and_is_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(skill_source_service, "load_remote_catalog", lambda *_: _catalog())
    binding_body = {
        "skill_id": "ar-hexiao-daily",
        "repository_url": REPOSITORY,
        "tracking_ref": "main",
        "source_path": "skills/ar-hexiao-daily",
        "expected_commit": COMMIT,
    }
    revision = skill_source_service.SkillSourceRevision(
        commit=COMMIT,
        tree_hash="c" * 64,
        source_name="ar-hexiao-daily",
        source_path="skills/ar-hexiao-daily",
    )
    monkeypatch.setattr(skill_source_service, "resolve_bound_revision", lambda _: revision)
    with auth_client(role="skill_admin") as admin:
        confirmed = admin.post("/api/admin/skill-sources/bindings", json=binding_body)
        assert confirmed.status_code in {200, 201}, confirmed.text
        first = admin.post("/api/admin/skill-sources/bindings/ar-hexiao-daily/check-update")
        second = admin.post("/api/admin/skill-sources/bindings/ar-hexiao-daily/check-update")
    assert first.status_code == 200, first.text
    assert first.json()["update_available"] is True
    assert first.json()["commit"] == COMMIT
    assert first.json()["tree_hash"] == "c" * 64
    assert second.json() == first.json()

    with SessionLocal() as db:
        binding = db.scalar(
            select(SkillSourceBinding).where(SkillSourceBinding.skill_id == "ar-hexiao-daily")
        )
        assert binding is not None
        assert binding.last_seen_tree_hash == "c" * 64
        binding.published_commit = COMMIT
        binding.published_tree_hash = "c" * 64
        db.commit()
    with auth_client(role="skill_admin") as admin:
        unchanged = admin.post(
            "/api/admin/skill-sources/bindings/ar-hexiao-daily/check-update"
        )
    assert unchanged.status_code == 200
    assert unchanged.json()["update_available"] is False


def test_check_update_marks_missing_or_renamed_source_broken(monkeypatch) -> None:
    monkeypatch.setattr(skill_source_service, "load_remote_catalog", lambda *_: _catalog())

    def broken(_):
        raise skill_source_service.SourceBindingBroken("源码目录已经不存在。")

    with auth_client(role="skill_admin") as admin:
        confirmed = admin.post(
            "/api/admin/skill-sources/bindings",
            json={
                "skill_id": "ar-hexiao-daily",
                "repository_url": REPOSITORY,
                "tracking_ref": "main",
                "source_path": "skills/ar-hexiao-daily",
                "expected_commit": COMMIT,
            },
        )
        assert confirmed.status_code == 201, confirmed.text
        monkeypatch.setattr(skill_source_service, "resolve_bound_revision", broken)
        response = admin.post(
            "/api/admin/skill-sources/bindings/ar-hexiao-daily/check-update"
        )
    assert response.status_code == 409
    with SessionLocal() as db:
        binding = db.scalar(
            select(SkillSourceBinding).where(SkillSourceBinding.skill_id == "ar-hexiao-daily")
        )
        assert binding is not None
        assert binding.binding_status == "broken"


def test_git_tree_hash_matches_release_tree_hash(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    skill = repository / "skills" / "demo-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo-skill\n---\n", encoding="utf-8")
    (skill / "script.py").write_text("print('demo')\n", encoding="utf-8")
    subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repository), "-c", "core.autocrlf=false", "add", "."],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Skill Test",
            "-c",
            "user.email=skill-test@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    commit = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()
    actual = skill_source_service._tree_sha256_at_revision(
        repository, commit, "skills/demo-skill"
    )
    expected = skill_source_service._tree_sha256_directory(skill)
    assert actual == expected


def test_source_worktree_uses_user_scoped_root_when_shared_root_is_not_writable(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = tmp_path / "data"
    shared_root = data_dir / "skill-source-worktrees"
    shared_root.mkdir(parents=True)
    real_access = skill_source_service.os.access
    monkeypatch.setattr(
        skill_source_service,
        "settings",
        SimpleNamespace(data_dir=data_dir),
    )
    monkeypatch.setattr(
        skill_source_service.os,
        "access",
        lambda path, mode: False
        if Path(path).resolve() == shared_root.resolve()
        else real_access(path, mode),
    )
    monkeypatch.setattr(skill_source_service.os, "getuid", lambda: 10001, raising=False)

    selected = skill_source_service._source_worktree_root()

    assert selected == data_dir / "skill-source-worktrees.10001"
    assert selected.is_dir()


def test_prepare_single_bound_skill_creates_validated_release(
    tmp_path: Path, monkeypatch
) -> None:
    repository = tmp_path / "source-repository"
    source_skill = repository / "skills" / "compliance-spot-check"
    source_skill.mkdir(parents=True)
    (source_skill / "SKILL.md").write_text(
        "---\nname: compliance-spot-check\n---\n\n# 合规抽查\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Skill Test"], check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "remote",
            "add",
            "origin",
            REPOSITORY,
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "-c", "core.autocrlf=false", "add", "."],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-m", "fixture"], check=True
    )
    commit = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()
    tree_hash = skill_source_service._tree_sha256_directory(source_skill)

    monkeypatch.setattr(skill_source_service, "load_remote_catalog", lambda *_: _catalog())
    with auth_client(role="skill_admin") as admin:
        confirmed = admin.post(
            "/api/admin/skill-sources/bindings",
            json={
                "skill_id": "compliance-spot-check",
                "repository_url": REPOSITORY,
                "tracking_ref": "main",
                "source_path": "skills/compliance-spot-check",
                "expected_commit": COMMIT,
            },
        )
        assert confirmed.status_code in {200, 201}, confirmed.text
    with SessionLocal() as db:
        binding = db.scalar(
            select(SkillSourceBinding).where(
                SkillSourceBinding.skill_id == "compliance-spot-check"
            )
        )
        assert binding is not None
        binding.last_seen_commit = commit
        binding.last_seen_tree_hash = tree_hash
        binding.binding_status = "bound"
        db.commit()

    @contextmanager
    def materialized(_binding, _revision):
        yield repository

    monkeypatch.setattr(skill_source_service, "materialize_revision", materialized)
    with auth_client(role="skill_admin") as admin:
        prepared = admin.post(
            "/api/admin/skill-sources/bindings/compliance-spot-check/prepare-release",
            json={"version": "9.8.7"},
        )
    assert prepared.status_code == 201, prepared.text
    release = prepared.json()
    assert release["skill_id"] == "compliance-spot-check"
    assert release["version"] == "9.8.7"
    assert release["state"] == "validated"
    assert release["source_repository"] == REPOSITORY
    assert release["source_commit"] == commit
    assert release["source_tree_hash"] == tree_hash
