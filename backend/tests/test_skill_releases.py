from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import yaml
from helpers import auth_client

from app import skill_release_service
from app.database import SessionLocal
from app.models import AuditEvent, RunRecord, SkillRelease
from app.registry import registry
from app.settings import settings


def _stage_release(skill_id: str, version: str) -> str:
    source = settings.skill_dir / skill_id
    staging = settings.data_dir / f"release-fixture-{version}"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(source, staging)
    manifest_path = staging / "tool.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = version
    manifest["status"] = "draft"
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (staging / ".release.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_repository": "https://example.invalid/finance-skills.git",
                "source_commit": "a" * 40,
                "source_tree_hash": "b" * 64,
                "tests": {
                    "passed": True,
                    "command": f"python -m pytest skills/{skill_id}/tests",
                    "summary": "12 passed",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    settings.skill_release_inbox_dir.mkdir(parents=True, exist_ok=True)
    package_name = f"{skill_id}-{version}.zip"
    package = settings.skill_release_inbox_dir / package_name
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file():
                archive.write(path, path.relative_to(staging).as_posix())
    shutil.rmtree(staging)
    return package_name


def _import_and_review(client, skill_id: str, version: str) -> dict[str, object]:
    package_name = _stage_release(skill_id, version)
    imported = client.post(
        "/api/admin/skill-releases/import",
        json={"package_name": package_name},
    )
    assert imported.status_code == 201, imported.text
    release = imported.json()
    reviewed = client.post(
        f"/api/admin/skill-releases/{release['id']}/review",
        json={"decision": "approve", "notes": "结构、来源和测试证据均已复核。"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["state"] == "reviewed"
    return reviewed.json()


@contextmanager
def _preserve_skill(skill_id: str) -> Iterator[None]:
    target = settings.skill_dir / skill_id
    backup = settings.data_dir / f"preserved-skill-{skill_id}-{uuid.uuid4()}"
    shutil.copytree(target, backup)
    try:
        yield
    finally:
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(backup, target)
        shutil.rmtree(backup, ignore_errors=True)
        registry.refresh()


def test_employee_cannot_manage_skill_releases() -> None:
    with auth_client() as employee:
        assert employee.get("/api/admin/skill-releases").status_code == 403
        assert employee.get("/api/admin/skill-releases/inbox").status_code == 403
        assert (
            employee.post(
                "/api/admin/skill-releases/import",
                json={"package_name": "release.zip"},
            ).status_code
            == 403
        )


def test_release_import_rejects_path_traversal() -> None:
    settings.skill_release_inbox_dir.mkdir(parents=True, exist_ok=True)
    package = settings.skill_release_inbox_dir / "unsafe-release.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("../outside.txt", "unsafe")
    with auth_client(role="skill_admin") as admin:
        response = admin.post(
            "/api/admin/skill-releases/import",
            json={"package_name": package.name},
        )
        assert response.status_code == 422
        assert "越界路径" in response.json()["detail"]
    assert not (settings.data_dir / "outside.txt").exists()


def test_inbox_hides_packages_that_have_already_been_imported() -> None:
    skill_id = "compliance-spot-check"
    package_name = _stage_release(skill_id, "9.9.6")

    with auth_client(role="skill_admin") as admin:
        imported = admin.post(
            "/api/admin/skill-releases/import",
            json={"package_name": package_name},
        )
        assert imported.status_code == 201, imported.text

        with SessionLocal() as db:
            record = db.get(SkillRelease, str(imported.json()["id"]))
            assert record is not None
            package = settings.skill_release_inbox_dir / package_name
            with (
                zipfile.ZipFile(record.package_path) as source,
                zipfile.ZipFile(package, "w", zipfile.ZIP_STORED) as duplicate,
            ):
                for name in reversed(source.namelist()):
                    duplicate.writestr(name, source.read(name))
            assert skill_release_service._sha256(package) != record.package_sha256

        inbox = admin.get("/api/admin/skill-releases/inbox")
        assert inbox.status_code == 200, inbox.text
        assert package_name not in {item["package_name"] for item in inbox.json()}


def test_release_lifecycle_publish_without_rollback() -> None:
    skill_id = "compliance-spot-check"
    registry.refresh()
    original = registry.get(skill_id, include_unpublished=True)
    assert original is not None
    original_version = original.manifest.version

    with _preserve_skill(skill_id):
        with auth_client(role="skill_admin") as admin:
            release = _import_and_review(admin, skill_id, "9.9.1")
            release_id = str(release["id"])

            updated = admin.patch(
                f"/api/admin/skill-releases/{release_id}",
                json={"description": "经过审核的银行流水与总账自动匹配版本。"},
            )
            assert updated.status_code == 409

            wrong = admin.post(
                f"/api/admin/skill-releases/{release_id}/publish",
                json={"confirmation": "发布"},
            )
            assert wrong.status_code == 422

            published = admin.post(
                f"/api/admin/skill-releases/{release_id}/publish",
                json={"confirmation": f"发布 {skill_id} 9.9.1"},
            )
            assert published.status_code == 200, published.text
            assert published.json()["state"] == "published"
            active = registry.get(skill_id, include_unpublished=True)
            assert active is not None
            assert active.manifest.version == "9.9.1"

            releases = admin.get(f"/api/admin/skill-releases?skill_id={skill_id}")
            assert releases.status_code == 200
            baseline = next(
                item
                for item in releases.json()
                if item["version"] == original_version and item["state"] == "superseded"
            )
            removed = admin.post(
                f"/api/admin/skill-releases/{baseline['id']}/rollback",
                json={"confirmation": f"回退 {skill_id} {original_version}"},
            )
            assert removed.status_code == 405

    with SessionLocal() as db:
        actions = {item.action for item in db.query(AuditEvent).all()}
        assert {
            "skill_release.import",
            "skill_release.review",
            "skill_release.publish",
        } <= actions


def test_release_publish_is_blocked_by_active_run() -> None:
    skill_id = "split-by-sales"
    with auth_client(role="skill_admin") as admin:
        release = _import_and_review(admin, skill_id, "9.9.2")
        run_id = str(uuid.uuid4())
        with SessionLocal() as db:
            db.add(
                RunRecord(
                    id=run_id,
                    owner_id=str(release["imported_by"]),
                    owner_name="管理员",
                    department_id="finance",
                    skill_id=skill_id,
                    skill_name="销售数据拆分",
                    skill_version="1.0.0",
                    skill_commit="",
                    skill_hash="c" * 64,
                    manifest_path="test/tool.yaml",
                    manifest_snapshot="{}",
                    adapter="python",
                    worker_pool="python",
                    state="queued",
                )
            )
            db.commit()
        blocked = admin.post(
            f"/api/admin/skill-releases/{release['id']}/publish",
            json={"confirmation": f"发布 {skill_id} 9.9.2"},
        )
        assert blocked.status_code == 409
        assert "活动任务" in blocked.json()["detail"]
        with SessionLocal() as db:
            record = db.get(RunRecord, run_id)
            if record:
                db.delete(record)
                db.commit()


def test_release_publish_rechecks_stored_content_hash() -> None:
    skill_id = "labor-invoice-check"
    with auth_client(role="skill_admin") as admin:
        release = _import_and_review(admin, skill_id, "9.9.3")
        with SessionLocal() as db:
            record = db.get(SkillRelease, str(release["id"]))
            assert record is not None
            content = settings.skill_release_dir / record.id / "content" / "tool.yaml"
            content.write_text(content.read_text(encoding="utf-8") + "\n", encoding="utf-8")

        blocked = admin.post(
            f"/api/admin/skill-releases/{release['id']}/publish",
            json={"confirmation": f"发布 {skill_id} 9.9.3"},
        )
        assert blocked.status_code == 409
        assert "内容已经变化" in blocked.json()["detail"]


def test_release_staging_failure_preserves_current_skill(monkeypatch) -> None:
    skill_id = "split-by-sales"
    target = settings.skill_dir / skill_id
    original_manifest = (target / "tool.yaml").read_bytes()

    with auth_client(role="skill_admin") as admin:
        release = _import_and_review(admin, skill_id, "9.9.4")
        content = settings.skill_release_dir / str(release["id"]) / "content"
        real_copytree = skill_release_service.shutil.copytree

        def fail_staging_copy(src: str | Path, dst: str | Path, *args, **kwargs):
            if Path(src).resolve() == content.resolve():
                raise OSError("synthetic staging failure")
            return real_copytree(src, dst, *args, **kwargs)

        monkeypatch.setattr(skill_release_service.shutil, "copytree", fail_staging_copy)
        blocked = admin.post(
            f"/api/admin/skill-releases/{release['id']}/publish",
            json={"confirmation": f"发布 {skill_id} 9.9.4"},
        )

    assert blocked.status_code == 409
    assert "已恢复原版本" in blocked.json()["detail"]
    assert target.is_dir()
    assert (target / "tool.yaml").read_bytes() == original_manifest


def test_release_backup_stays_on_skill_filesystem(monkeypatch) -> None:
    skill_id = "dept-expense-alloc"
    registry.refresh()
    original = registry.get(skill_id, include_unpublished=True)
    assert original is not None

    with _preserve_skill(skill_id):
        with auth_client(role="skill_admin") as admin:
            release = _import_and_review(admin, skill_id, "9.9.5")
            real_replace = skill_release_service.os.replace

            def require_same_skill_root(src: str | Path, dst: str | Path) -> None:
                source = Path(src).resolve()
                destination = Path(dst).resolve()
                if source == (settings.skill_dir / skill_id).resolve():
                    assert destination.parent == settings.skill_dir.resolve()
                real_replace(src, dst)

            monkeypatch.setattr(skill_release_service.os, "replace", require_same_skill_root)
            published = admin.post(
                f"/api/admin/skill-releases/{release['id']}/publish",
                json={"confirmation": f"发布 {skill_id} 9.9.5"},
            )
            assert published.status_code == 200, published.text
            active = registry.get(skill_id, include_unpublished=True)
            assert active is not None
            assert active.manifest.version == "9.9.5"
