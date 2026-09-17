from __future__ import annotations

import io
import re
import json
import stat
import zipfile
from pathlib import PurePosixPath

import yaml
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .auth import UserContext
from .contracts import SkillInstallCatalog, SkillInstallCandidate, SkillInstallRequest, SkillReleaseRead
from .registry import SkillManifest, registry, validate_declared_operational_profile
from .settings import settings
from . import skill_source_service as source
from .skill_release_service import import_release, MAX_PACKAGE_BYTES, MAX_EXTRACTED_BYTES, MAX_PACKAGE_FILES


def inspect_standard_package(files: dict[str, bytes], source_name: str) -> SkillManifest:
    if "tool.yaml" not in files:
        raise ValueError("缺少 tool.yaml：当前是源码 Skill，需要补充平台运行清单")
    payload = yaml.safe_load(files["tool.yaml"].decode("utf-8-sig"))
    validate_declared_operational_profile(payload)
    manifest = SkillManifest.model_validate(payload)
    if manifest.schema_version != 1 or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", manifest.version):
        raise ValueError("标准包必须使用 schema_version: 1 和三段式版本号")
    if manifest.id != source_name:
        raise ValueError("tool.yaml 的 id 必须与源码目录一致")
    if manifest.conversation.mode != "chat":
        raise ValueError("新安装入口仅接收已声明 conversation.mode: chat 的标准包")
    if manifest.ui is None:
        raise ValueError("缺少员工展示 ui 配置")
    instructions = files.get("SKILL.md", b"")
    if not 0 < len(instructions) <= 131072 or not instructions.decode("utf-8-sig").strip():
        raise ValueError("缺少非空 UTF-8 SKILL.md，或说明超过 128 KiB")
    entry = manifest.handler.entrypoint or ""
    path = PurePosixPath(entry)
    if path.is_absolute() or ".." in path.parts or entry not in files:
        raise ValueError("Python 执行入口缺失或越界")
    return manifest


def _check_tree_sizes(repository, commit: str, path: str) -> None:
    listing = source._git_command(repository, "ls-tree", "-r", "-l", "-z", commit, "--", path)
    entries = [entry for entry in listing.split(b"\0") if entry]
    if len(entries) > MAX_PACKAGE_FILES:
        raise ValueError("包内文件过多")
    total = 0
    for entry in entries:
        metadata, _ = entry.split(b"\t", 1)
        mode, kind, oid, size = metadata.split()
        if kind != b"blob" or mode == b"120000":
            raise ValueError("包包含不允许的 Git 对象或符号链接")
        total += int(size)
        if total > MAX_PACKAGE_BYTES - 1024 * 1024:
            raise ValueError("源码总量超过安装包限制")


def _read_blob(repository, commit: str, path: str, limit: int) -> bytes:
    size = int(source._git_command(repository, "cat-file", "-s", f"{commit}:{path}"))
    if size > limit:
        raise ValueError("说明或入口文件超过大小限制")
    return source._git_command(repository, "show", f"{commit}:{path}")


def _read_candidate(repository, commit: str, path: str) -> dict[str, bytes]:
    listing = source._git_command(repository, "ls-tree", "-r", "--name-only", commit, "--", path).decode("utf-8").splitlines()
    manifest_path = path + "/tool.yaml"
    if manifest_path not in listing:
        return {}
    manifest_bytes = _read_blob(repository, commit, manifest_path, 131072)
    if len(manifest_bytes) > 131072:
        raise ValueError("tool.yaml 超过 128 KiB")
    payload = yaml.safe_load(manifest_bytes.decode("utf-8-sig"))
    entry = SkillManifest.model_validate(payload).handler.entrypoint or ""
    result = {"tool.yaml": manifest_bytes}
    for name in ["SKILL.md", entry]:
        if not isinstance(name, str) or not name or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
            continue
        if path + "/" + name in listing:
            result[name] = _read_blob(repository, commit, path + "/" + name, 131072 if name == "SKILL.md" else MAX_PACKAGE_BYTES)
    return result


def installation_catalog() -> SkillInstallCatalog:
    candidates = []
    with source._source_guard():
        repository, commit = source._cache_repository(source.FINANCE_SKILLS_REPOSITORY, "main")
        directories = source._git_command(repository, "ls-tree", "-d", "--name-only", f"{commit}:skills").decode("utf-8").splitlines()
        for name in directories:
            path = source._validated_source_path("skills/" + name)
            installed = name in source._platform_skill_ids()
            state, reason, version = "needs_adaptation", "", ""
            if name in source.EXCLUDED_SOURCE_SKILLS:
                state, reason = "excluded", "此辅助 Skill 不进入 Skill 中心"
            else:
                try:
                    manifest = inspect_standard_package(_read_candidate(repository, commit, path), name)
                    version = manifest.version
                    state, reason = ("installed", "已安装，更新请使用现有版本管理") if installed else ("ready", "结构兼容，可生成待审核安装包；业务结果和依赖仍需验收")
                except (ValueError, TypeError, UnicodeError, yaml.YAMLError) as exc:
                    reason = str(exc).split("\n")[0][:240]
                    if installed: reason = "平台已有适配版本；仓库标准包：" + reason
            candidates.append(SkillInstallCandidate(skill_id=name, source_path=path, version=version, state=state, reason=reason))
    return SkillInstallCatalog(repository_url=source.FINANCE_SKILLS_REPOSITORY, commit=commit, candidates=candidates)


def _package_files(raw: bytes) -> dict[str, bytes]:
    if len(raw) > MAX_PACKAGE_BYTES:
        raise ValueError("仓库包超过 50 MB")
    files = {}; total = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.infolist()) > MAX_PACKAGE_FILES:
            raise ValueError("包内文件过多")
        for item in archive.infolist():
            path = PurePosixPath(item.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or any(":" in p for p in path.parts) or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("包包含越界路径或符号链接")
            if item.is_dir(): continue
            total += item.file_size
            if total > MAX_EXTRACTED_BYTES: raise ValueError("解压大小超过限制")
            if path.name == ".release.json": continue
            key = path.as_posix()
            if key.casefold() in {k.casefold() for k in files}: raise ValueError("包内路径重复")
            files[key] = archive.read(item)
    return files


def prepare_install(db: Session, actor: UserContext, body: SkillInstallRequest) -> SkillReleaseRead:
    path = source._validated_source_path(body.source_path)
    name = PurePosixPath(path).name
    if name in source.EXCLUDED_SOURCE_SKILLS or name in source._platform_skill_ids():
        raise HTTPException(status_code=409, detail="该 Skill 已存在或不允许安装，请使用现有版本管理。")
    with source._source_guard():
        repository, commit = source._cache_repository(source.FINANCE_SKILLS_REPOSITORY, "main")
        if commit != body.expected_commit:
            raise HTTPException(status_code=409, detail="仓库提交已变化，请重新读取安装目录。")
        try:
            _check_tree_sizes(repository, commit, path)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        raw = source._git_command(repository, "archive", "--format=zip", f"{commit}:{path}")
        tree_hash = source._tree_sha256_at_revision(repository, commit, path)
    try:
        files = _package_files(raw)
        manifest = inspect_standard_package(files, name)
        manifest.catalog_module = "installed_skills"
        compile(files[manifest.handler.entrypoint], manifest.handler.entrypoint, "exec")
        files["tool.yaml"] = yaml.safe_dump(manifest.model_dump(exclude_none=True), allow_unicode=True, sort_keys=False).encode("utf-8")
        for filename, content in files.items():
            if filename.endswith(".py"): compile(content, filename, "exec")
    except (ValueError, TypeError, SyntaxError, UnicodeError, yaml.YAMLError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=422, detail="标准包结构或 Python 语法校验未通过：" + str(exc).split("\n")[0][:240]) from exc
    metadata = {"source_repository": source.FINANCE_SKILLS_REPOSITORY, "source_commit": commit, "source_tree_hash": tree_hash,
                "tests": {"passed": True, "scope": "manifest-and-python-syntax-only", "business_acceptance": False, "command": "standard package structure and Python compile (no source execution)"}}
    target = settings.skill_release_inbox_dir / f"{manifest.id}-{commit[:12]}-standard.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Only the request that creates this file owns cleanup, including partial ZIP writes.
    try:
        handle = target.open("xb")
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="同一安装包正在准备，请稍后查看发布记录。") from exc
    try:
        with handle:
            with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for filename, content in sorted(files.items()): archive.writestr(filename, content)
                archive.writestr(".release.json", json.dumps(metadata, ensure_ascii=False))
        return import_release(db, actor, target.name)
    finally:
        target.unlink(missing_ok=True)
