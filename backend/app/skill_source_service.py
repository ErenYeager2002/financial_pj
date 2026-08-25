from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit_service import record_audit
from .auth import UserContext
from .contracts import (
    SkillSourceBindingConfirmRequest,
    SkillSourceBindingRead,
    SkillSourceCandidateRead,
    SkillSourceDiscoveryRead,
    SkillSourceUpdateCheckRead,
)
from .models import SkillSourceBinding
from .registry import registry
from .settings import settings

FINANCE_SKILLS_REPOSITORY = "https://gitee.com/Lee157/finance-skills.git"
EXCLUDED_SOURCE_SKILLS = {"update-finance-skills"}
REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
IGNORED_TREE_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules", "output"}
_SOURCE_LOCK = threading.Lock()


@dataclass(frozen=True)
class RemoteSkill:
    name: str
    path: str


@dataclass(frozen=True)
class RemoteSkillCatalog:
    repository_url: str
    tracking_ref: str
    commit: str
    skills: tuple[RemoteSkill, ...]


@dataclass(frozen=True)
class SkillSourceRevision:
    commit: str
    tree_hash: str
    source_name: str
    source_path: str


class SourceBindingBroken(RuntimeError):
    pass


def _normalized_repository_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if normalized == FINANCE_SKILLS_REPOSITORY.removesuffix(".git"):
        normalized = FINANCE_SKILLS_REPOSITORY
    if normalized != FINANCE_SKILLS_REPOSITORY:
        raise HTTPException(status_code=422, detail="只允许已配置的财务 Skill Gitee 仓库。")
    return normalized


def _validated_ref(value: str) -> str:
    ref = value.strip()
    if not REF_PATTERN.fullmatch(ref) or ".." in ref or ref.endswith("/"):
        raise HTTPException(status_code=422, detail="Git 跟踪引用格式无效。")
    return ref


def _validated_source_path(value: str) -> str:
    raw = value.strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or ".." in path.parts
        or len(path.parts) != 2
        or path.parts[0] != "skills"
        or not path.parts[1]
    ):
        raise HTTPException(status_code=422, detail="源码目录必须是 skills/<skill-id>。")
    return path.as_posix()


def _front_matter_name(content: str, path: str) -> str:
    normalized = content.replace("\r\n", "\n")
    parts = normalized.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise HTTPException(status_code=502, detail=f"Gitee Skill front matter 无效：{path}")
    payload = yaml.safe_load(parts[1])
    name = str((payload or {}).get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=502, detail=f"Gitee Skill 缺少 name：{path}")
    return name


def _git_command(repository: Path | None, *args: str, timeout: int = 120) -> bytes:
    command = [
        "git",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        "credential.helper=",
        "-c",
        "protocol.file.allow=never",
    ]
    if repository is not None:
        # The cache can be restored from a volume created by another container
        # user. Keep Git's ownership check enabled for every other path, but
        # explicitly allow this application-owned cache repository.
        command.extend(["-c", f"safe.directory={repository}"])
        command.extend(["-C", str(repository)])
    command.extend(args)
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    try:
        return subprocess.check_output(
            command,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=502, detail="无法获取固定的 Git Skill 源码版本。") from exc


@contextmanager
def _source_guard() -> Iterator[None]:
    with _SOURCE_LOCK:
        lock_path = settings.data_dir / ".skill-source.fetch.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
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
                                detail="另一个 Skill 源码检查仍在进行，请稍后重试。",
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


def _tree_sha256_directory(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or any(part in IGNORED_TREE_PARTS for part in path.parts):
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root.resolve()):
            raise SourceBindingBroken("源码目录包含越界文件。")
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _tree_sha256_at_revision(repository: Path, commit: str, source_path: str) -> str:
    prefix = f"{source_path.rstrip('/')}/"
    listing = _git_command(repository, "ls-tree", "-r", "-z", commit, "--", source_path)
    entries: list[tuple[str, str]] = []
    for raw in listing.split(b"\0"):
        if not raw:
            continue
        try:
            metadata, raw_path = raw.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
            full_path = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise SourceBindingBroken("Git Skill 目录结构无效。") from exc
        if object_type != "blob" or mode == "120000" or not full_path.startswith(prefix):
            raise SourceBindingBroken("Git Skill 目录包含不允许的对象。")
        relative = full_path.removeprefix(prefix)
        if any(part in IGNORED_TREE_PARTS for part in PurePosixPath(relative).parts):
            continue
        entries.append((relative, object_id))
    if not entries:
        raise SourceBindingBroken("Git Skill 源码目录不存在或为空。")
    digest = hashlib.sha256()
    for relative, object_id in sorted(entries):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_git_command(repository, "cat-file", "blob", object_id))
        digest.update(b"\0")
    return digest.hexdigest()


def _cache_repository(repository_url: str, tracking_ref: str) -> tuple[Path, str]:
    cache_root = (settings.data_dir / "skill-source-cache").resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_name = f"{hashlib.sha256(repository_url.encode('utf-8')).hexdigest()[:24]}.git"
    repository = (cache_root / cache_name).resolve()
    if not repository.is_relative_to(cache_root):
        raise HTTPException(status_code=500, detail="Skill 源码缓存目录无效。")
    if repository.exists() and not (
        os.access(repository, os.W_OK) and os.access(repository / "config", os.W_OK)
    ):
        # A previous container may have created the cache as root. Do not let
        # that stale cache prevent the application user from fetching a fresh
        # revision; use a user-scoped cache alongside it.
        owner = getattr(os, "getuid", lambda: 0)()
        repository = (cache_root / f"{cache_name.removesuffix('.git')}.{owner}.git").resolve()
        if not repository.is_relative_to(cache_root):
            raise HTTPException(status_code=500, detail="Skill 源码缓存目录无效。")
    if not repository.exists():
        _git_command(None, "init", "--bare", str(repository))
        _git_command(repository, "remote", "add", "origin", repository_url)
    elif not (repository / "HEAD").is_file():
        raise HTTPException(status_code=409, detail="Skill 源码缓存目录已损坏。")
    _git_command(repository, "remote", "set-url", "origin", repository_url)
    _git_command(
        repository,
        "fetch",
        "--force",
        "--prune",
        "--no-tags",
        "--depth=1",
        "origin",
        tracking_ref,
    )
    commit = _git_command(repository, "rev-parse", "FETCH_HEAD^{commit}").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise HTTPException(status_code=502, detail="Git 未返回有效 commit。")
    _git_command(repository, "config", "core.autocrlf", "false")
    return repository, commit


def _source_worktree_root() -> Path:
    """Return a writable temporary-worktree directory for the API user.

    Development data volumes can retain directories created by an earlier
    root-running container. Keep those directories intact and use a
    user-scoped sibling when the shared directory is not writable.
    """

    data_root = settings.data_dir.resolve()
    shared_root = (data_root / "skill-source-worktrees").resolve()
    if not shared_root.exists():
        try:
            shared_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(
                status_code=503,
                detail="Skill 源码临时工作区不可写，请检查数据目录权限。",
            ) from exc
    if os.access(shared_root, os.W_OK | os.X_OK):
        return shared_root

    owner = getattr(os, "getuid", lambda: 0)()
    scoped_root = (data_root / f"skill-source-worktrees.{owner}").resolve()
    if not scoped_root.is_relative_to(data_root):
        raise HTTPException(status_code=500, detail="Skill 源码工作区目录无效。")
    try:
        scoped_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail="Skill 源码临时工作区不可写，请检查数据目录权限。",
        ) from exc
    if not os.access(scoped_root, os.W_OK | os.X_OK):
        raise HTTPException(
            status_code=503,
            detail="Skill 源码临时工作区不可写，请检查数据目录权限。",
        )
    return scoped_root


def resolve_bound_revision(binding: SkillSourceBinding) -> SkillSourceRevision:
    repository_url = _normalized_repository_url(binding.repository_url)
    tracking_ref = _validated_ref(binding.tracking_ref)
    source_path = _validated_source_path(binding.source_path)
    with _source_guard():
        repository, commit = _cache_repository(repository_url, tracking_ref)
        try:
            raw_manifest = _git_command(
                repository, "show", f"{commit}:{source_path}/SKILL.md"
            ).decode("utf-8")
        except HTTPException as exc:
            raise SourceBindingBroken("Git Skill 源码目录或 SKILL.md 已不存在。") from exc
        except UnicodeDecodeError as exc:
            raise SourceBindingBroken("Git Skill 的 SKILL.md 不是 UTF-8。") from exc
        try:
            source_name = _front_matter_name(raw_manifest, source_path)
        except HTTPException as exc:
            raise SourceBindingBroken("Git Skill 的 SKILL.md 元数据无效。") from exc
        if source_name != binding.skill_id:
            raise SourceBindingBroken("Git Skill 名称与正式绑定不一致。")
        tree_hash = _tree_sha256_at_revision(repository, commit, source_path)
    return SkillSourceRevision(commit, tree_hash, source_name, source_path)


@contextmanager
def materialize_revision(
    binding: SkillSourceBinding, revision: SkillSourceRevision
) -> Iterator[Path]:
    worktree_root = _source_worktree_root()
    try:
        worktree = Path(
            tempfile.mkdtemp(prefix=f"{binding.skill_id}-", dir=worktree_root)
        ).resolve()
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail="Skill 源码临时工作区不可写，请检查数据目录权限。",
        ) from exc
    if not worktree.is_relative_to(worktree_root):
        raise HTTPException(status_code=500, detail="Skill 源码工作区目录无效。")
    repository: Path | None = None
    added = False
    try:
        with _source_guard():
            repository, _ = _cache_repository(binding.repository_url, binding.tracking_ref)
            try:
                _git_command(repository, "cat-file", "-e", f"{revision.commit}^{{commit}}")
            except HTTPException:
                _git_command(repository, "fetch", "--depth=1", "origin", revision.commit)
            _git_command(
                repository,
                "worktree",
                "add",
                "--force",
                "--detach",
                str(worktree),
                revision.commit,
            )
            added = True
        source = (worktree / revision.source_path).resolve()
        if not source.is_relative_to(worktree) or not source.is_dir():
            raise SourceBindingBroken("固定源码版本中不存在绑定目录。")
        if _tree_sha256_directory(source) != revision.tree_hash:
            raise SourceBindingBroken("固定源码版本的目录哈希与检查结果不一致。")
        source_name = _front_matter_name(
            (source / "SKILL.md").read_text(encoding="utf-8"), str(source)
        )
        if source_name != binding.skill_id:
            raise SourceBindingBroken("固定源码版本的 Skill 名称与绑定不一致。")
        yield worktree
    finally:
        if repository is not None and added:
            with _source_guard():
                try:
                    _git_command(repository, "worktree", "remove", "--force", str(worktree))
                except HTTPException:
                    pass
                try:
                    _git_command(repository, "worktree", "prune")
                except HTTPException:
                    pass
        if worktree.exists() and worktree.is_relative_to(worktree_root):
            shutil.rmtree(worktree)


def load_remote_catalog(repository_url: str, tracking_ref: str) -> RemoteSkillCatalog:
    normalized_url = _normalized_repository_url(repository_url)
    ref = _validated_ref(tracking_ref)
    skills: list[RemoteSkill] = []
    with _source_guard():
        repository, commit = _cache_repository(normalized_url, ref)
        directory_names = (
            _git_command(repository, "ls-tree", "-d", "--name-only", f"{commit}:skills")
            .decode("utf-8")
            .splitlines()
        )
        for directory_name in directory_names:
            source_path = _validated_source_path(f"skills/{directory_name.strip()}")
            try:
                content = _git_command(
                    repository, "show", f"{commit}:{source_path}/SKILL.md"
                ).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HTTPException(
                    status_code=502, detail=f"Gitee Skill 内容编码无效：{source_path}"
                ) from exc
            skills.append(RemoteSkill(_front_matter_name(content, source_path), source_path))
    return RemoteSkillCatalog(normalized_url, ref, commit, tuple(skills))


def binding_read(record: SkillSourceBinding) -> SkillSourceBindingRead:
    return SkillSourceBindingRead.model_validate(record, from_attributes=True)


def list_bindings(db: Session) -> list[SkillSourceBindingRead]:
    records = db.scalars(
        select(SkillSourceBinding).order_by(SkillSourceBinding.skill_id)
    ).all()
    return [binding_read(item) for item in records]


def _platform_skill_ids() -> set[str]:
    skill_ids = {item.manifest.id for item in registry.list(include_disabled=True)}
    root = settings.skill_dir.resolve()
    if not root.is_dir():
        return skill_ids
    for directory in root.iterdir():
        manifest_path = directory / "tool.yaml"
        resolved_directory = directory.resolve()
        if (
            not directory.is_dir()
            or not resolved_directory.is_relative_to(root)
            or not manifest_path.is_file()
            or not manifest_path.resolve().is_relative_to(resolved_directory)
            or manifest_path.stat().st_size > 2 * 1024 * 1024
        ):
            continue
        try:
            payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        skill_id = payload.get("id") if isinstance(payload, dict) else None
        if isinstance(skill_id, str) and skill_id == directory.name:
            skill_ids.add(skill_id)
    return skill_ids


def discover_bindings(
    db: Session, repository_url: str, tracking_ref: str
) -> SkillSourceDiscoveryRead:
    catalog = load_remote_catalog(repository_url, tracking_ref)
    platform_ids = _platform_skill_ids()
    bindings = {
        item.skill_id: item for item in db.scalars(select(SkillSourceBinding)).all()
    }
    counts = Counter(item.name for item in catalog.skills)
    candidates: list[SkillSourceCandidateRead] = []
    for remote in sorted(catalog.skills, key=lambda item: (item.name, item.path)):
        platform_id = remote.name if remote.name in platform_ids else ""
        if remote.name in EXCLUDED_SOURCE_SKILLS:
            state, reason = "excluded", "仓库更新导航 Skill 不进入员工平台。"
        elif counts[remote.name] != 1:
            state, reason = "conflict", "仓库中存在多个同名 Skill。"
        elif not platform_id:
            state, reason = "unmatched", "平台尚无同名 Skill。"
        elif platform_id in bindings:
            bound = bindings[platform_id]
            if bound.repository_url == catalog.repository_url and bound.source_path == remote.path:
                state, reason = "bound", "已确认绑定。"
            else:
                state, reason = "conflict", "平台 Skill 已绑定其他源码目录。"
        else:
            state, reason = "candidate", "名称唯一一致，等待管理员确认。"
        candidates.append(
            SkillSourceCandidateRead(
                platform_skill_id=platform_id,
                source_name=remote.name,
                source_path=remote.path,
                match_state=state,
                reason=reason,
            )
        )
    return SkillSourceDiscoveryRead(
        repository_url=catalog.repository_url,
        tracking_ref=catalog.tracking_ref,
        commit=catalog.commit,
        candidates=candidates,
    )


def confirm_binding(
    db: Session, actor: UserContext, body: SkillSourceBindingConfirmRequest
) -> tuple[SkillSourceBindingRead, bool]:
    repository = _normalized_repository_url(body.repository_url)
    ref = _validated_ref(body.tracking_ref)
    source_path = _validated_source_path(body.source_path)
    catalog = load_remote_catalog(repository, ref)
    if catalog.commit != body.expected_commit:
        raise HTTPException(status_code=409, detail="Gitee commit 已变化，请重新发现后确认。")
    remote = next((item for item in catalog.skills if item.path == source_path), None)
    if remote is None:
        raise HTTPException(status_code=422, detail="源码目录不在本次发现结果中。")
    if remote.name != body.skill_id:
        raise HTTPException(status_code=422, detail="源码 Skill 名称与平台 Skill ID 不一致。")
    if body.skill_id in EXCLUDED_SOURCE_SKILLS:
        raise HTTPException(status_code=422, detail="该 Skill 已标记为平台排除项。")
    if body.skill_id not in _platform_skill_ids():
        raise HTTPException(status_code=422, detail="平台不存在该 Skill。")

    existing = db.scalar(
        select(SkillSourceBinding).where(SkillSourceBinding.skill_id == body.skill_id)
    )
    if existing is not None:
        if (
            existing.repository_url == repository
            and existing.source_path == source_path
            and existing.tracking_ref == ref
        ):
            existing.last_seen_commit = catalog.commit
            existing.updated_by = actor.user_id
            db.commit()
            db.refresh(existing)
            return binding_read(existing), False
        raise HTTPException(status_code=409, detail="平台 Skill 已绑定其他源码目录。")
    path_owner = db.scalar(
        select(SkillSourceBinding).where(
            SkillSourceBinding.repository_url == repository,
            SkillSourceBinding.source_path == source_path,
        )
    )
    if path_owner is not None:
        raise HTTPException(status_code=409, detail="该源码目录已经绑定其他平台 Skill。")

    record = SkillSourceBinding(
        id=str(uuid.uuid4()),
        skill_id=body.skill_id,
        repository_url=repository,
        source_path=source_path,
        tracking_ref=ref,
        binding_status="bound",
        last_seen_commit=catalog.commit,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    db.add(record)
    record_audit(
        db,
        actor=actor,
        action="admin.skill_source_binding.confirm",
        resource_type="skill_source_binding",
        resource_id=record.id,
        details={
            "skill_id": record.skill_id,
            "repository_url": record.repository_url,
            "source_path": record.source_path,
            "tracking_ref": record.tracking_ref,
            "source_commit": record.last_seen_commit,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Skill 源码绑定发生并发冲突。") from exc
    db.refresh(record)
    return binding_read(record), True


def check_update(
    db: Session, actor: UserContext, skill_id: str
) -> SkillSourceUpdateCheckRead:
    binding = db.scalar(
        select(SkillSourceBinding).where(SkillSourceBinding.skill_id == skill_id)
    )
    if binding is None:
        raise HTTPException(status_code=404, detail="Skill 尚未建立源码绑定。")
    try:
        revision = resolve_bound_revision(binding)
    except SourceBindingBroken as exc:
        binding.binding_status = "broken"
        binding.updated_by = actor.user_id
        record_audit(
            db,
            actor=actor,
            action="admin.skill_source_binding.broken",
            resource_type="skill_source_binding",
            resource_id=binding.id,
            outcome="failure",
            details={"skill_id": binding.skill_id, "reason": str(exc)},
        )
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    binding.binding_status = "bound"
    binding.last_seen_commit = revision.commit
    binding.last_seen_tree_hash = revision.tree_hash
    binding.updated_by = actor.user_id
    changed = (
        binding.published_commit != revision.commit
        or binding.published_tree_hash != revision.tree_hash
    )
    record_audit(
        db,
        actor=actor,
        action="admin.skill_source_binding.check_update",
        resource_type="skill_source_binding",
        resource_id=binding.id,
        details={
            "skill_id": binding.skill_id,
            "source_commit": revision.commit,
            "source_tree_hash": revision.tree_hash,
            "update_available": changed,
        },
    )
    db.commit()
    return SkillSourceUpdateCheckRead(
        skill_id=binding.skill_id,
        repository_url=binding.repository_url,
        source_path=binding.source_path,
        tracking_ref=binding.tracking_ref,
        commit=revision.commit,
        tree_hash=revision.tree_hash,
        published_commit=binding.published_commit,
        published_tree_hash=binding.published_tree_hash,
        update_available=changed,
    )
