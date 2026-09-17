from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import threading
import time
import uuid
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit_service import record_audit
from .auth import UserContext
from .contracts import (
    AdminSkillDetail,
    SkillReleaseInboxItem,
    SkillReleaseMetadataUpdate,
    SkillReleaseRead,
    SkillReleaseReviewRequest,
)
from .models import (
    RunRecord,
    SkillAvailability,
    SkillRelease,
    SkillSourceBinding,
    WorkflowAction,
    WorkflowSession,
)
from .registry import SkillManifest, registry, validate_declared_operational_profile, validate_conversation_files
from .settings import settings
from .skill_availability_service import disable_after_drain, transition_availability
from .skill_execution_experiences import validate_published_execution_experience

PACKAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.zip$")
COMMIT = re.compile(r"^[0-9a-fA-F]{7,64}$")
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
MAX_PACKAGE_BYTES = 50 * 1024 * 1024
MAX_EXTRACTED_BYTES = 200 * 1024 * 1024
MAX_PACKAGE_FILES = 2000
ACTIVE_RUN_STATES = {
    "created",
    "parsing",
    "waiting_confirmation",
    "queued",
    "running",
    "cancelling",
}
ACTIVE_WORKFLOW_STATES = {"active", "running", "preparing", "applying"}
_PUBLISH_LOCK = threading.Lock()


def _json(value: str) -> dict[str, Any]:
    payload = json.loads(value)
    return payload if isinstance(payload, dict) else {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_tree_hash(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            metadata = archive.getinfo(".release.json")
            if metadata.file_size > 64 * 1024:
                return ""
            payload = json.loads(archive.read(metadata).decode("utf-8"))
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile):
        return ""
    source_tree_hash = payload.get("source_tree_hash") if isinstance(payload, dict) else ""
    return source_tree_hash.lower() if isinstance(source_tree_hash, str) else ""


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root.resolve()):
            raise HTTPException(status_code=409, detail="Skill 发布包内容超出受控目录。")
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _publish_lock_path() -> Path:
    """Choose a publish lock the API user can open.

    A development data volume may contain a lock file created by a previous
    root-running container. Keep that file for compatibility and use a
    user-scoped lock when the shared file is not writable.
    """

    data_dir = settings.data_dir.resolve()
    shared = (data_dir / ".skill-release.publish.lock").resolve()
    if not shared.is_relative_to(data_dir):
        raise HTTPException(status_code=500, detail="Skill 发布锁目录无效。")
    if not shared.exists() or os.access(shared, os.W_OK):
        return shared

    owner = getattr(os, "getuid", lambda: 0)()
    scoped = (data_dir / f".skill-release.publish.{owner}.lock").resolve()
    if not scoped.is_relative_to(data_dir):
        raise HTTPException(status_code=500, detail="Skill 发布锁目录无效。")
    if scoped.exists() and not os.access(scoped, os.W_OK):
        raise HTTPException(
            status_code=503,
            detail="Skill 发布锁不可写，请检查数据目录权限。",
        )
    return scoped


@contextmanager
def _publish_guard() -> Iterator[None]:
    """Serialize filesystem activation across threads and server processes."""

    with _PUBLISH_LOCK:
        lock_path = _publish_lock_path()
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = lock_path.open("a+b")
        except OSError as exc:
            raise HTTPException(
                status_code=503,
                detail="Skill 发布锁不可写，请检查数据目录权限。",
            ) from exc
        with handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                deadline = time.monotonic() + 30
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError as exc:
                        if time.monotonic() >= deadline:
                            raise HTTPException(
                                status_code=409,
                                detail="另一个 Skill 发布操作仍在进行，请稍后重试。",
                            ) from exc
                        time.sleep(0.1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _release_dir(release_id: str) -> Path:
    path = (settings.skill_release_dir / release_id).resolve()
    if not path.is_relative_to(settings.skill_release_dir.resolve()):
        raise HTTPException(status_code=400, detail="Skill 发布记录目录无效。")
    return path


def _content_dir(record: SkillRelease) -> Path:
    path = _release_dir(record.id) / "content"
    if not path.is_dir():
        raise HTTPException(status_code=409, detail="Skill 发布包内容已经缺失。")
    return path


def _record_or_404(db: Session, release_id: str) -> SkillRelease:
    record = db.get(SkillRelease, release_id)
    if not record:
        raise HTTPException(status_code=404, detail="Skill 发布记录不存在。")
    return record


def _manifest_payload(record: SkillRelease) -> dict[str, Any]:
    payload = _json(record.manifest_json)
    payload.update(
        {
            "skill_hash": record.published_skill_hash or record.source_tree_hash,
            "commit_sha": record.source_commit,
            "source": "controlled-release",
        }
    )
    return payload


def release_read(record: SkillRelease) -> SkillReleaseRead:
    return SkillReleaseRead(
        id=record.id,
        skill_id=record.skill_id,
        version=record.version,
        state=record.state,
        package_sha256=record.package_sha256,
        source_repository=record.source_repository,
        source_commit=record.source_commit,
        source_tree_hash=record.source_tree_hash,
        manifest=AdminSkillDetail.model_validate(_manifest_payload(record)),
        validation=_json(record.validation_json),
        tests=_json(record.test_json),
        review_notes=record.review_notes,
        imported_by=record.imported_by,
        reviewed_by=record.reviewed_by,
        published_by=record.published_by,
        published_skill_hash=record.published_skill_hash,
        created_at=record.created_at,
        updated_at=record.updated_at,
        reviewed_at=record.reviewed_at,
        published_at=record.published_at,
    )


def list_inbox_packages(db: Session, actor: UserContext) -> list[SkillReleaseInboxItem]:
    items: list[SkillReleaseInboxItem] = []
    imported_hashes = set(db.scalars(select(SkillRelease.package_sha256)).all())
    imported_tree_hashes = set(db.scalars(select(SkillRelease.source_tree_hash)).all())
    imported_tree_hashes.discard("")
    for path in sorted(settings.skill_release_inbox_dir.glob("*.zip")):
        if not PACKAGE_NAME.fullmatch(path.name) or not path.is_file():
            continue
        size = path.stat().st_size
        if size > MAX_PACKAGE_BYTES:
            continue
        package_sha = _sha256(path)
        source_tree_hash = _release_tree_hash(path)
        if package_sha in imported_hashes or source_tree_hash in imported_tree_hashes:
            continue
        items.append(
            SkillReleaseInboxItem(package_name=path.name, size_bytes=size, sha256=package_sha)
        )
    record_audit(
        db,
        action="admin.skill_release_inbox.read",
        actor=actor,
        resource_type="skill_release_inbox",
        details={"count": len(items)},
    )
    db.commit()
    return items


def list_releases(db: Session, actor: UserContext, skill_id: str = "") -> list[SkillReleaseRead]:
    query = select(SkillRelease)
    if skill_id:
        query = query.where(SkillRelease.skill_id == skill_id)
    records = list(
        db.scalars(query.order_by(SkillRelease.created_at.desc(), SkillRelease.id.desc())).all()
    )
    result = [release_read(item) for item in records]
    record_audit(
        db,
        action="admin.skill_releases.read",
        actor=actor,
        resource_type="skill_release",
        details={"count": len(result), "skill_id": skill_id},
    )
    db.commit()
    return result


def _safe_extract(package: Path, target: Path) -> None:
    total = 0
    seen: set[str] = set()
    with zipfile.ZipFile(package) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_PACKAGE_FILES:
            raise HTTPException(status_code=422, detail="Skill 发布包文件数量超过限制。")
        for entry in entries:
            name = PurePosixPath(entry.filename.replace("\\", "/"))
            if name.is_absolute() or ".." in name.parts or not name.parts:
                raise HTTPException(status_code=422, detail="Skill 发布包包含越界路径。")
            normalized = name.as_posix().rstrip("/").casefold()
            if not normalized or normalized in seen or any(":" in part for part in name.parts):
                raise HTTPException(status_code=422, detail="Skill 发布包包含重复或无效路径。")
            seen.add(normalized)
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise HTTPException(status_code=422, detail="Skill 发布包不能包含符号链接。")
            total += entry.file_size
            if total > MAX_EXTRACTED_BYTES:
                raise HTTPException(status_code=422, detail="Skill 发布包解压后大小超过限制。")
            destination = (target / Path(*name.parts)).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise HTTPException(status_code=422, detail="Skill 发布包包含越界路径。")
            if entry.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)


def _validate_content(content: Path) -> tuple[SkillManifest, dict[str, Any], dict[str, Any]]:
    manifest_path = content / "tool.yaml"
    release_path = content / ".release.json"
    if not manifest_path.is_file() or not release_path.is_file():
        raise HTTPException(
            status_code=422,
            detail="Skill 发布包必须包含 tool.yaml 和 .release.json。",
        )
    try:
        raw_manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        validate_declared_operational_profile(raw_manifest)
        manifest = SkillManifest.model_validate(raw_manifest)
        release_meta = json.loads(release_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError, yaml.YAMLError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Skill 发布包结构无效：{exc}") from exc
    if not isinstance(release_meta, dict):
        raise HTTPException(status_code=422, detail=".release.json 格式无效。")
    source_commit = str(release_meta.get("source_commit", ""))
    source_tree_hash = str(release_meta.get("source_tree_hash", ""))
    source_repository = str(release_meta.get("source_repository", "")).strip()
    tests = release_meta.get("tests")
    if not source_repository or len(source_repository) > 512:
        raise HTTPException(status_code=422, detail="发布包缺少受控源码仓库信息。")
    if not COMMIT.fullmatch(source_commit):
        raise HTTPException(status_code=422, detail="发布包源码提交标识无效。")
    if not SHA256.fullmatch(source_tree_hash):
        raise HTTPException(status_code=422, detail="发布包源码树哈希无效。")
    if not isinstance(tests, dict) or tests.get("passed") is not True:
        raise HTTPException(status_code=422, detail="发布包缺少通过的测试证据。")
    if manifest.status == "published" and manifest.ui is None:
        raise HTTPException(status_code=422, detail="发布 Skill 必须配置员工展示信息。")
    try:
        validate_conversation_files(manifest, content)
        validate_published_execution_experience(manifest.id, manifest.status, manifest.conversation.mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if manifest.handler.entrypoint:
        entrypoint = (content / manifest.handler.entrypoint).resolve()
        if not entrypoint.is_relative_to(content.resolve()) or not entrypoint.is_file():
            raise HTTPException(status_code=422, detail="Skill 执行入口不存在或超出包目录。")
    validation = {
        "passed": True,
        "content_sha256": _tree_sha256(content),
        "checks": [
            "zip_paths",
            "zip_size",
            "manifest_schema",
            "source_commit",
            "source_tree_hash",
            "test_evidence",
            "entrypoint",
        ],
    }
    return manifest, release_meta, validation


def _assert_release_integrity(record: SkillRelease) -> None:
    expected_package = (_release_dir(record.id) / "package.zip").resolve()
    stored_package = Path(record.package_path).resolve()
    if stored_package != expected_package or not stored_package.is_file():
        raise HTTPException(status_code=409, detail="Skill 发布包已经缺失或存储位置无效。")
    if _sha256(stored_package) != record.package_sha256:
        raise HTTPException(status_code=409, detail="Skill 发布包哈希已经变化。")
    validation = _json(record.validation_json)
    expected_content = validation.get("content_sha256")
    if not isinstance(expected_content, str) or not SHA256.fullmatch(expected_content):
        raise HTTPException(status_code=409, detail="Skill 发布包缺少内容完整性证据。")
    if _tree_sha256(_content_dir(record)) != expected_content:
        raise HTTPException(status_code=409, detail="Skill 发布包内容已经变化。")
    if _json(record.test_json).get("passed") is not True:
        raise HTTPException(status_code=422, detail="发布前测试必须通过。")


def import_release(
    db: Session,
    actor: UserContext,
    package_name: str,
) -> SkillReleaseRead:
    if not PACKAGE_NAME.fullmatch(package_name):
        raise HTTPException(status_code=400, detail="Skill 发布包名称无效。")
    inbox = settings.skill_release_inbox_dir.resolve()
    package = (inbox / package_name).resolve()
    if not package.is_relative_to(inbox) or not package.is_file():
        raise HTTPException(status_code=404, detail="Skill 发布包不存在。")
    if package.stat().st_size > MAX_PACKAGE_BYTES:
        raise HTTPException(status_code=422, detail="Skill 发布包超过 50 MB。")
    package_sha = _sha256(package)
    existing = db.scalar(select(SkillRelease).where(SkillRelease.package_sha256 == package_sha))
    if existing:
        package.unlink(missing_ok=True)
        return release_read(existing)

    release_id = str(uuid.uuid4())
    release_dir = _release_dir(release_id)
    content = release_dir / "content"
    release_dir.mkdir(parents=True)
    try:
        _safe_extract(package, content)
        manifest, release_meta, validation = _validate_content(content)
        manifest.status = "draft"
        stored_package = release_dir / "package.zip"
        shutil.copy2(package, stored_package)
        record = SkillRelease(
            id=release_id,
            skill_id=manifest.id,
            version=manifest.version,
            state="validated",
            package_sha256=package_sha,
            package_path=str(stored_package),
            source_repository=str(release_meta["source_repository"]),
            source_commit=str(release_meta["source_commit"]),
            source_tree_hash=str(release_meta["source_tree_hash"]),
            manifest_json=json.dumps(manifest.model_dump(), ensure_ascii=False, sort_keys=True),
            validation_json=json.dumps(validation, ensure_ascii=False, sort_keys=True),
            test_json=json.dumps(release_meta["tests"], ensure_ascii=False, sort_keys=True),
            imported_by=actor.user_id,
        )
        db.add(record)
        record_audit(
            db,
            action="skill_release.import",
            actor=actor,
            resource_type="skill_release",
            resource_id=release_id,
            details={
                "skill_id": manifest.id,
                "version": manifest.version,
                "package_sha256": package_sha,
                "source_commit": record.source_commit,
            },
        )
        db.commit()
        db.refresh(record)
        package.unlink(missing_ok=True)
        return release_read(record)
    except IntegrityError as exc:
        db.rollback()
        shutil.rmtree(release_dir, ignore_errors=True)
        raise HTTPException(status_code=409, detail="该 Skill 发布包已经导入。") from exc
    except Exception:
        db.rollback()
        shutil.rmtree(release_dir, ignore_errors=True)
        raise


def update_release_metadata(
    db: Session,
    actor: UserContext,
    release_id: str,
    body: SkillReleaseMetadataUpdate,
) -> SkillReleaseRead:
    record = _record_or_404(db, release_id)
    if record.state not in {"validated", "rejected"}:
        raise HTTPException(status_code=409, detail="只有待审核或已退回版本可以修改元数据。")
    payload = _json(record.manifest_json)
    for key, value in body.model_dump(exclude_unset=True).items():
        payload[key] = value
    payload["status"] = "draft"
    try:
        manifest = SkillManifest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record.manifest_json = json.dumps(manifest.model_dump(), ensure_ascii=False, sort_keys=True)
    record.version = manifest.version
    record.state = "validated"
    record.review_notes = ""
    record.reviewed_by = ""
    record.reviewed_at = None
    record_audit(
        db,
        action="skill_release.metadata_update",
        actor=actor,
        resource_type="skill_release",
        resource_id=record.id,
        details={"skill_id": record.skill_id, "version": record.version},
    )
    db.commit()
    db.refresh(record)
    return release_read(record)


def review_release(
    db: Session,
    actor: UserContext,
    release_id: str,
    body: SkillReleaseReviewRequest,
) -> SkillReleaseRead:
    record = _record_or_404(db, release_id)
    if record.state not in {"validated", "rejected"}:
        raise HTTPException(status_code=409, detail="当前发布记录不能审核。")
    _assert_release_integrity(record)
    manifest = SkillManifest.model_validate(_json(record.manifest_json))
    if manifest.ui is None:
        raise HTTPException(status_code=422, detail="发布前必须配置员工展示信息。")
    tests = _json(record.test_json)
    if tests.get("passed") is not True:
        raise HTTPException(status_code=422, detail="发布前测试必须通过。")
    record.state = "reviewed" if body.decision == "approve" else "rejected"
    record.review_notes = body.notes
    record.reviewed_by = actor.user_id
    record.reviewed_at = datetime.now(UTC)
    record_audit(
        db,
        action="skill_release.review",
        actor=actor,
        resource_type="skill_release",
        resource_id=record.id,
        details={
            "skill_id": record.skill_id,
            "version": record.version,
            "decision": body.decision,
        },
    )
    db.commit()
    db.refresh(record)
    return release_read(record)


def _assert_no_active_work(record: SkillRelease, db: Session) -> None:
    run_id = db.scalar(
        select(RunRecord.id).where(
            RunRecord.skill_id == record.skill_id,
            RunRecord.state.in_(ACTIVE_RUN_STATES),
        )
    )
    workflow_id = db.scalar(
        select(WorkflowSession.id).where(
            WorkflowSession.skill_id == record.skill_id,
            WorkflowSession.state.in_(ACTIVE_WORKFLOW_STATES),
        )
    )
    action_id = db.scalar(
        select(WorkflowAction.id)
        .join(WorkflowSession, WorkflowSession.id == WorkflowAction.workflow_id)
        .where(
            WorkflowSession.skill_id == record.skill_id,
            WorkflowAction.state.in_(("queued", "running")),
        )
    )
    if run_id or workflow_id or action_id:
        raise HTTPException(status_code=409, detail="该 Skill 仍有活动任务，暂时不能发布。")


def _zip_directory(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())


def _capture_current_release(
    db: Session, actor: UserContext, skill_id: str
) -> tuple[SkillRelease | None, bool]:
    current = registry.get(skill_id, include_unpublished=True)
    if not current or current.source != "platform":
        return None, False
    existing = db.scalar(
        select(SkillRelease).where(
            SkillRelease.skill_id == skill_id,
            SkillRelease.published_skill_hash == current.skill_hash,
        )
    )
    if existing:
        return existing, False
    release_id = str(uuid.uuid4())
    release_dir = _release_dir(release_id)
    content = release_dir / "content"
    release_dir.mkdir(parents=True)
    shutil.copytree(current.directory, content)
    package = release_dir / "package.zip"
    _zip_directory(content, package)
    record = SkillRelease(
        id=release_id,
        skill_id=current.manifest.id,
        version=current.manifest.version,
        state="published",
        package_sha256=_sha256(package),
        package_path=str(package),
        source_repository=current.source,
        source_commit=current.commit_sha,
        source_tree_hash=current.skill_hash,
        manifest_json=json.dumps(
            current.manifest.model_dump(), ensure_ascii=False, sort_keys=True
        ),
        validation_json=json.dumps(
            {
                "passed": True,
                "content_sha256": _tree_sha256(content),
                "checks": ["existing_live_baseline"],
            },
            sort_keys=True,
        ),
        test_json=json.dumps(
            {"passed": True, "summary": "发布前现有线上版本基线"},
            ensure_ascii=False,
            sort_keys=True,
        ),
        imported_by=actor.user_id,
        reviewed_by=actor.user_id,
        published_by=actor.user_id,
        published_skill_hash=current.skill_hash,
        review_notes="自动保存的发布前线上版本归档",
        reviewed_at=datetime.now(UTC),
        published_at=datetime.now(UTC),
    )
    try:
        db.add(record)
        db.flush()
    except Exception:
        shutil.rmtree(release_dir, ignore_errors=True)
        raise
    return record, True


def _activate_release(
    db: Session,
    actor: UserContext,
    record: SkillRelease,
) -> SkillReleaseRead:
    _assert_release_integrity(record)
    _assert_no_active_work(record, db)
    content = _content_dir(record)
    target = (settings.skill_dir / record.skill_id).resolve()
    if not target.is_relative_to(settings.skill_dir.resolve()):
        raise HTTPException(status_code=400, detail="Skill 目标目录无效。")
    manifest = SkillManifest.model_validate(_json(record.manifest_json))
    manifest.status = "published"
    try:
        validate_conversation_files(manifest, content)
        validate_published_execution_experience(manifest.id, manifest.status, manifest.conversation.mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    temp = (settings.skill_dir / f".release-{record.id}").resolve()
    backup = (settings.skill_dir / f".release-backup-{record.id}").resolve()
    shutil.rmtree(temp, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    previous: SkillRelease | None = None
    previous_created = False
    target_moved = False
    temp_activated = False
    try:
        existing = registry.get(record.skill_id, include_unpublished=True)
        if existing is not None:
            manifest.catalog_module = existing.manifest.catalog_module
        shutil.copytree(content, temp)
        (temp / ".release.json").unlink(missing_ok=True)
        (temp / "tool.yaml").write_text(
            yaml.safe_dump(
                manifest.model_dump(exclude_none=True),
                allow_unicode=True,
                sort_keys=False,
                width=100,
            ),
            encoding="utf-8",
        )
        previous, previous_created = _capture_current_release(db, actor, record.skill_id)
        if target.exists():
            os.replace(target, backup)
            target_moved = True
        os.replace(temp, target)
        temp_activated = True
        registry.refresh()
        active = registry.get(record.skill_id, include_unpublished=True)
        if not active or active.manifest.version != record.version:
            raise RuntimeError("Registry 未加载刚发布的 Skill 版本。")
        target_errors = [
            item for item in registry.errors if str(target).lower() in item.get("path", "").lower()
        ]
        if target_errors:
            raise RuntimeError(target_errors[0]["error"])
        published_records = db.scalars(
            select(SkillRelease).where(
                SkillRelease.skill_id == record.skill_id,
                SkillRelease.state == "published",
                SkillRelease.id != record.id,
            )
        ).all()
        for published_record in published_records:
            published_record.state = "superseded"
        record.state = "published"
        record.published_by = actor.user_id
        record.published_at = datetime.now(UTC)
        record.published_skill_hash = active.skill_hash
        record.manifest_json = json.dumps(
            active.manifest.model_dump(), ensure_ascii=False, sort_keys=True
        )
        record_audit(
            db,
            action="skill_release.publish",
            actor=actor,
            resource_type="skill_release",
            resource_id=record.id,
            details={
                "skill_id": record.skill_id,
                "version": record.version,
                "package_sha256": record.package_sha256,
                "published_skill_hash": active.skill_hash,
            },
        )
        db.flush()
        db.refresh(record)
        result = release_read(record)
        db.commit()
        shutil.rmtree(backup, ignore_errors=True)
        return result
    except Exception as exc:
        db.rollback()
        if temp_activated and target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if target_moved and backup.exists():
            os.replace(backup, target)
        shutil.rmtree(temp, ignore_errors=True)
        if previous_created and previous:
            shutil.rmtree(_release_dir(previous.id), ignore_errors=True)
        registry.refresh()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=409, detail=f"Skill 激活失败，已恢复原版本：{exc}") from exc


def publish_release(
    db: Session,
    actor: UserContext,
    release_id: str,
    confirmation: str,
) -> SkillReleaseRead:
    record = _record_or_404(db, release_id)
    if record.state != "reviewed":
        raise HTTPException(status_code=409, detail="只有审核通过的版本可以发布。")
    _assert_release_integrity(record)
    expected = f"发布 {record.skill_id} {record.version}"
    if confirmation != expected:
        raise HTTPException(status_code=422, detail=f"发布确认文字必须为：{expected}")
    current = registry.get(record.skill_id, include_unpublished=True)
    if current and current.manifest.version == record.version:
        raise HTTPException(status_code=409, detail="新版本号必须与当前线上版本不同。")
    previous_hash = current.skill_hash if current else ""
    transition_availability(db, actor, record.skill_id, "draining", "兼容发布入口等待排空")
    count = disable_after_drain(db, actor, record.skill_id, "兼容发布入口开始激活")
    if count:
        transition_availability(db, actor, record.skill_id, "enabled", "活动任务尚未结束")
        raise HTTPException(status_code=409, detail="该 Skill 仍有活动任务，暂时不能发布。")
    try:
        with _publish_guard():
            result = _activate_release(db, actor, record)
        binding = db.scalar(
            select(SkillSourceBinding).where(SkillSourceBinding.skill_id == record.skill_id)
        )
        if binding is not None:
            binding.published_commit = record.source_commit
            binding.published_tree_hash = record.source_tree_hash
            binding.updated_by = actor.user_id
            db.commit()
        transition_availability(db, actor, record.skill_id, "enabled", "发布验证通过")
        return result
    except Exception:
        registry.refresh()
        active = registry.get(record.skill_id, include_unpublished=True)
        restored = bool(active and previous_hash and active.skill_hash == previous_hash)
        availability = db.get(SkillAvailability, record.skill_id)
        if restored and availability is not None and availability.state == "disabled":
            transition_availability(db, actor, record.skill_id, "enabled", "发布失败，原版本已恢复")
        elif availability is not None:
            availability.state = "failed_disabled"
            availability.generation += 1
            availability.reason = "发布失败且原版本恢复验证未通过"
            availability.changed_by = actor.user_id
            availability.changed_at = datetime.now(UTC)
            db.commit()
        raise


def activate_reviewed_release(
    db: Session, actor: UserContext, record: SkillRelease
) -> SkillReleaseRead:
    if record.state != "reviewed":
        raise HTTPException(status_code=409, detail="只有审核通过的版本可以激活。")
    with _publish_guard():
        return _activate_release(db, actor, record)


def activate_release_without_review(
    db: Session, actor: UserContext, record: SkillRelease
) -> SkillReleaseRead:
    """Activate a validated package for the single-admin direct update flow."""
    if record.state not in {"validated", "reviewed"}:
        raise HTTPException(status_code=409, detail="当前发布包不能直接更新 Skill。")
    with _publish_guard():
        return _activate_release(db, actor, record)
