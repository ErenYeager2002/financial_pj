from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import skill_source_service
from .audit_service import record_audit
from .auth import UserContext
from .contracts import SkillReleaseRead
from .models import SkillRelease, SkillSourceBinding
from .registry import registry
from .settings import settings
from .skill_availability_service import get_availability, transition_availability
from .skill_release_service import activate_release_without_review, import_release

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$")


def _run(command: list[str], *, cwd: Path) -> None:
    environment = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "GIT_TERMINAL_PROMPT": "0",
    }
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=422, detail="单 Skill 制包命令无法完成。") from exc
    if result.returncode != 0:
        raise HTTPException(status_code=422, detail="单 Skill 转换或测试失败。")


def _test_command(worktree: Path, source_path: str) -> list[str]:
    relative = Path(source_path)
    tests = worktree / relative / "tests"
    if tests.is_dir() and any(tests.glob("test_*.py")):
        return [sys.executable, "-m", "pytest", relative.joinpath("tests").as_posix(), "-q"]
    return [sys.executable, "-m", "compileall", "-q", relative.as_posix()]


def _verify_package_source(
    package: Path, binding: SkillSourceBinding, revision: skill_source_service.SkillSourceRevision
) -> None:
    try:
        with zipfile.ZipFile(package) as archive:
            metadata = json.loads(archive.read(".release.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="生成的 Skill 发布包元数据无效。") from exc
    if (
        metadata.get("source_repository") != binding.repository_url
        or metadata.get("source_commit") != revision.commit
        or metadata.get("source_tree_hash") != revision.tree_hash
    ):
        package.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="发布包来源证据与源码绑定不一致。")


def prepare_bound_release(
    db: Session,
    actor: UserContext,
    skill_id: str,
    version: str,
) -> SkillReleaseRead:
    binding = db.scalar(
        select(SkillSourceBinding).where(SkillSourceBinding.skill_id == skill_id)
    )
    if binding is None:
        raise HTTPException(status_code=404, detail="Skill 尚未建立源码绑定。")
    if binding.binding_status != "bound":
        raise HTTPException(status_code=409, detail="Skill 源码绑定当前不可用于发布。")
    if len(binding.last_seen_commit) != 40 or len(binding.last_seen_tree_hash) != 64:
        raise HTTPException(status_code=409, detail="请先检查 Skill 源码更新。")
    revision = skill_source_service.SkillSourceRevision(
        commit=binding.last_seen_commit,
        tree_hash=binding.last_seen_tree_hash,
        source_name=binding.skill_id,
        source_path=binding.source_path,
    )
    with skill_source_service.materialize_revision(binding, revision) as worktree:
        source_skill = (worktree / binding.source_path).resolve()
        if not source_skill.is_relative_to(worktree.resolve()) or not source_skill.is_dir():
            raise HTTPException(status_code=409, detail="固定源码版本缺少绑定 Skill。")
        with tempfile.TemporaryDirectory(prefix="skill-package-") as temp_value:
            staging_root = Path(temp_value) / "skills"
            sync_command = [
                sys.executable,
                str(settings.project_root / "scripts" / "sync_finance_skills.py"),
                "--source",
                str(worktree / "skills"),
                "--target",
                str(staging_root),
                "--skill-id",
                binding.skill_id,
                "--repository-url",
                binding.repository_url,
                "--source-path",
                binding.source_path,
                "--source-commit",
                revision.commit,
                "--version",
                version,
            ]
            _run(sync_command, cwd=settings.project_root)
            package_name = f"{binding.skill_id}-{version}-{revision.commit[:12]}.zip"
            package = settings.skill_release_inbox_dir / package_name
            stage_command = [
                sys.executable,
                str(settings.project_root / "scripts" / "stage_skill_release.py"),
                "--skill-dir",
                str(staging_root / binding.skill_id),
                "--source-repo",
                str(worktree),
                "--source-skill",
                str(source_skill),
                "--inbox",
                str(settings.skill_release_inbox_dir),
                "--test-command",
                *_test_command(worktree, binding.source_path),
            ]
            _run(stage_command, cwd=settings.project_root)
            if not package.is_file():
                raise HTTPException(status_code=422, detail="单 Skill 发布包没有生成。")
            _verify_package_source(package, binding, revision)
            return import_release(db, actor, package.name)


def _next_version(db: Session, skill_id: str, current_version: str) -> str:
    match = SEMVER.fullmatch(current_version.strip())
    if match:
        major, minor, patch = (int(match.group(index)) for index in range(1, 4))
    else:
        major, minor, patch = 1, 0, 0
    while True:
        patch += 1
        candidate = f"{major}.{minor}.{patch}"
        exists = db.scalar(
            select(SkillRelease.id).where(
                SkillRelease.skill_id == skill_id,
                SkillRelease.version == candidate,
            )
        )
        if exists is None:
            return candidate


def update_bound_skill(db: Session, actor: UserContext, skill_id: str) -> SkillReleaseRead:
    """Pull, package, activate and re-enable one already-disabled Skill."""
    availability = get_availability(db, skill_id)
    if availability.state != "disabled":
        raise HTTPException(status_code=409, detail="请先完成该 Skill 的禁用，再执行更新。")
    if availability.active_work_count:
        raise HTTPException(
            status_code=409,
            detail=f"该 Skill 仍有 {availability.active_work_count} 个活动任务，暂时不能更新。",
        )

    binding = db.scalar(
        select(SkillSourceBinding).where(SkillSourceBinding.skill_id == skill_id)
    )
    if binding is None or binding.binding_status != "bound":
        raise HTTPException(status_code=409, detail="该 Skill 尚未建立可用的 Gitee 源码绑定。")

    try:
        check = skill_source_service.check_update(db, actor, skill_id)
        if not check.update_available:
            raise HTTPException(status_code=409, detail="Gitee 中没有新的 Skill 代码。")
        current = registry.get(skill_id, include_unpublished=True)
        if current is None:
            raise HTTPException(status_code=404, detail="平台不存在该 Skill。")
        version = _next_version(db, skill_id, current.manifest.version)
        prepared = prepare_bound_release(db, actor, skill_id, version)
        record = db.get(SkillRelease, prepared.id)
        if record is None:
            raise HTTPException(status_code=409, detail="Skill 更新发布记录没有保存成功。")
        result = activate_release_without_review(db, actor, record)

        binding = db.scalar(
            select(SkillSourceBinding).where(SkillSourceBinding.skill_id == skill_id)
        )
        if binding is not None:
            binding.published_commit = result.source_commit
            binding.published_tree_hash = result.source_tree_hash
            binding.updated_by = actor.user_id
            db.commit()
        transition_availability(db, actor, skill_id, "enabled", "Skill 代码更新完成")
        record_audit(
            db,
            actor=actor,
            action="admin.skill.update",
            resource_type="skill",
            resource_id=skill_id,
            details={
                "skill_id": skill_id,
                "version": result.version,
                "source_commit": result.source_commit,
                "source_tree_hash": result.source_tree_hash,
            },
        )
        db.commit()
        return result
    except HTTPException as exc:
        db.rollback()
        try:
            record_audit(
                db,
                actor=actor,
                action="admin.skill.update",
                resource_type="skill",
                resource_id=skill_id,
                outcome="failure",
                details={"skill_id": skill_id, "reason": str(exc.detail)[:500]},
            )
            db.commit()
        except Exception:
            db.rollback()
        raise
