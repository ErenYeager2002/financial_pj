from __future__ import annotations

import hashlib
import fcntl
from contextlib import contextmanager
import httpx
import json
import io
import zipfile
import os
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from uuid import uuid4

import yaml
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from . import skill_source_service as source
from .auth import UserContext
from .audit_service import record_audit
from .contracts import NativeSkillRead, NativeSkillContext, NativeSkillContextRequest, SkillInstallCatalog, SkillInstallCandidate, SkillInstallRequest
from .models import FileRecord, RunRecord
from .settings import settings
from .skill_install_service import _check_tree_sizes, _package_files, _read_blob
from .storage import sha256_file, run_root, register_output
from .events import emit_event
from .native_skill_policy import require_native_skill

NAME = re.compile(r"^[a-z][a-z0-9-]{0,71}$")


def native_root() -> Path:
    return settings.data_dir / "native-skills"


def checked_name(name: str) -> str:
    if not NAME.fullmatch(name): raise HTTPException(422, "Skill 名称格式无效。")
    return name


def parse_instructions(raw: bytes, name: str) -> tuple[str, str, str]:
    if not 0 < len(raw) <= 131072: raise ValueError("SKILL.md 必须非空且不超过 128 KiB")
    text = raw.decode("utf-8-sig")
    if not text.strip(): raise ValueError("SKILL.md 不能为空")
    metadata = {}
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            parsed = yaml.safe_load(parts[1])
            if isinstance(parsed, dict): metadata = parsed
    title = str(metadata.get("name") or name)[:120]
    description = str(metadata.get("description") or next((line.strip('# ').strip() for line in text.splitlines() if line.strip()), name))[:1000]
    return title, description, text


def installed_skill(name: str) -> NativeSkillRead:
    checked_name(name)
    p = native_root() / "installed" / (name + ".json")
    if not p.is_file(): raise HTTPException(404, "该原生 Skill 尚未安装。")
    return NativeSkillRead.model_validate_json(p.read_text())


def list_native_skills() -> list[NativeSkillRead]:
    root = native_root() / "installed"
    return [NativeSkillRead.model_validate_json(p.read_text()) for p in sorted(root.glob("*.json"))]


def installation_catalog() -> SkillInstallCatalog:
    installed = {item.id: item for item in list_native_skills()}
    candidates = []
    with source._source_guard():
        repo, commit = source._cache_repository(source.FINANCE_SKILLS_REPOSITORY, "main")
        names = source._git_command(repo, "ls-tree", "-d", "--name-only", f"{commit}:skills").decode().splitlines()
        for name in names:
            path = "skills/" + name
            try:
                checked_name(name)
                raw = _read_blob(repo, commit, path + "/SKILL.md", 131072)
                parse_instructions(raw, name)
                current = installed.get(name)
                state = "installed" if current and current.commit == commit else "ready"
                reason = "已安装当前版本" if state == "installed" else "发现新版本，可更新" if current else "原生 Skill，可直接安装"
            except (ValueError, UnicodeError, yaml.YAMLError, HTTPException) as exc:
                state, reason = "needs_adaptation", "无法读取有效的 SKILL.md"
            candidates.append(SkillInstallCandidate(skill_id=name, source_path=path, version=commit[:12], state=state, reason=reason))
    return SkillInstallCatalog(repository_url=source.FINANCE_SKILLS_REPOSITORY, commit=commit, candidates=candidates)


def install_native_skill(db: Session, actor: UserContext, body: SkillInstallRequest) -> NativeSkillRead:
    path = source._validated_source_path(body.source_path)
    name = checked_name(PurePosixPath(path).name)
    with source._source_guard():
        repo, commit = source._cache_repository(source.FINANCE_SKILLS_REPOSITORY, "main")
        if body.expected_commit != commit: raise HTTPException(409, "仓库已有新提交，请刷新目录后安装。")
        try:
            _check_tree_sizes(repo, commit, path)
            raw = source._git_command(repo, "archive", "--format=zip", f"{commit}:{path}")
            files = _package_files(raw)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                executable = {info.filename for info in archive.infolist() if (info.external_attr >> 16) & 0o111}
            title, description, _ = parse_instructions(files.get("SKILL.md", b""), name)
        except (ValueError, UnicodeError, yaml.YAMLError) as exc:
            raise HTTPException(422, "Skill 目录无效：" + str(exc)[:180]) from exc
        package = native_root() / "packages" / name / commit
        package.parent.mkdir(parents=True, exist_ok=True)
        if not package.exists():
            staging = package.parent / (".install-" + uuid4().hex)
            staging.mkdir()
            try:
                for filename, content in files.items():
                    target = staging / filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                    target.chmod(0o755 if filename in executable else 0o644)
                os.replace(staging, package)
            finally:
                if staging.exists(): shutil.rmtree(staging)
        result = NativeSkillRead(id=name, name=title, description=description, commit=commit, source_path=path, installed_at=datetime.now(UTC).isoformat())
        index = native_root() / "installed" / (name + ".json")
        index.parent.mkdir(parents=True, exist_ok=True)
        temp = index.with_suffix(".tmp")
        temp.write_text(result.model_dump_json())
        os.replace(temp, index)
    record_audit(db, actor=actor, action="native_skill.install", resource_type="native_skill", resource_id=name, details={"commit": commit})
    db.commit()
    return result


def session_snapshot(name: str, user: UserContext, session_id: str) -> tuple[NativeSkillRead, Path, Path]:
    checked_name(name)
    prefix = "skill-native--" + name + "__"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id) or not session_id.startswith(prefix):
        raise HTTPException(422, "原生 Skill 会话标识不匹配。")
    key = hashlib.sha256((user.user_id + "\0" + user.department_id + "\0" + session_id).encode()).hexdigest()
    root = native_root() / "sessions" / key
    root.mkdir(parents=True, exist_ok=True)
    pin = root / "snapshot.json"
    with (root / ".snapshot.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            if not pin.exists():
                current = installed_skill(name)
                temporary = root / (".snapshot-" + uuid4().hex)
                temporary.write_text(current.model_dump_json())
                os.replace(temporary, pin)
            pinned = NativeSkillRead.model_validate_json(pin.read_text())
        finally: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    if pinned.id != name or not re.fullmatch(r"[a-f0-9]{40}", pinned.commit): raise HTTPException(409, "Skill 会话快照无效。")
    package = native_root() / "packages" / name / pinned.commit
    if not package.is_dir(): raise HTTPException(409, "会话固定的 Skill 版本不可用。")
    workspace = root / "workspace"
    workspace.mkdir(exist_ok=True)
    for directory in [workspace / "outputs", workspace / "inputs"]:
        if directory.is_symlink() or directory.resolve() != directory: raise HTTPException(409, "会话目录无效。")
        directory.mkdir(exist_ok=True)
    return pinned, package, workspace


def prepare_context(db: Session, user: UserContext, name: str, body: NativeSkillContextRequest) -> NativeSkillContext:
    user = require_native_skill(db, user, name)
    if body.file_ids:
        require_native_skill(db, user, name, "can_upload")
    pinned, package, workspace = session_snapshot(name, user, body.session_id)
    inputs = []
    material_key = hashlib.sha256(json.dumps(sorted(set(body.file_ids))).encode()).hexdigest()
    target_dir = workspace.parent / "materials" / material_key
    target_dir.mkdir(parents=True, exist_ok=True)
    for file_id in dict.fromkeys(body.file_ids):
        item = db.get(FileRecord, file_id)
        if not item or item.owner_id != user.user_id or item.department_id != user.department_id or item.kind != "input":
            raise HTTPException(404, "当前账号没有所选输入文件。")
        src = Path(item.stored_path).resolve()
        if not src.is_file() or sha256_file(src) != item.sha256: raise HTTPException(409, "输入文件已变化，请重新选择。")
        filename = file_id + Path(item.original_name).suffix.lower()
        target = target_dir / filename
        if not target.exists():
            temporary = target.with_name(".copy-" + uuid4().hex)
            try:
                shutil.copy2(src, temporary); os.replace(temporary, target)
            finally: temporary.unlink(missing_ok=True)
        if sha256_file(target) != item.sha256: raise HTTPException(409, "会话材料副本完整性校验失败。")
        inputs.append({"file_id": item.id, "sha256": item.sha256, "name": item.original_name, "path": "/workspace/inputs/" + filename})
    _, _, instructions = parse_instructions((package / "SKILL.md").read_bytes(), name)
    files = [p.relative_to(package).as_posix() for p in sorted(package.rglob("*")) if p.is_file()]
    return NativeSkillContext(skill=pinned, instructions=instructions, files=files, inputs=inputs)


def read_package_file(db: Session, user: UserContext, name: str, session_id: str, path: str, offset: int = 0):
    user = require_native_skill(db, user, name)
    _, package, _ = session_snapshot(name, user, session_id)
    target = (package / path).resolve()
    if not target.is_relative_to(package.resolve()) or not target.is_file(): raise HTTPException(404, "Skill 文件不存在。")
    if target.stat().st_size > 2 * 1024 * 1024: raise HTTPException(422, "文本文件过大，请通过隔离命令读取所需部分。")
    try: text = target.read_text(encoding="utf-8-sig")
    except UnicodeError as exc: raise HTTPException(422, "此文件不是 UTF-8 文本。") from exc
    offset = max(0, offset); end = min(len(text), offset + 40000)
    return {"path": path, "content": text[offset:end], "offset": offset, "next_offset": end if end < len(text) else None, "total_chars": len(text)}


@contextmanager
def command_guard(workspace: Path):
    with (workspace.parent / ".command.lock").open("a+b") as handle:
        try: fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc: raise HTTPException(409, "本会话已有命令正在执行。") from exc
        try: yield
        finally: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def execute_command(db: Session, user: UserContext, name: str, body):
    from .run_service import serialize_run
    context = prepare_context(db, user, name, body)
    pinned, package, workspace = session_snapshot(name, user, body.session_id)
    with command_guard(workspace):
        user = require_native_skill(db, user, name)
        from .assistant_turn_service import require_turn_command
        require_turn_command(db, user, body.session_id, body.turn_id)
        before = {p.relative_to(workspace / "outputs").as_posix(): sha256_file(p) for p in (workspace / "outputs").rglob("*") if p.is_file() and not p.is_symlink()}
        now = datetime.now(UTC)
        run = RunRecord(id=str(uuid4()), owner_id=user.user_id, owner_name=user.display_name, department_id=user.department_id,
            skill_id="native--" + name, skill_name=pinned.name, skill_version=pinned.commit[:12], skill_commit=pinned.commit,
            skill_hash=hashlib.sha256((pinned.id + pinned.commit).encode()).hexdigest(), manifest_path=str(package / "SKILL.md"),
            manifest_snapshot=json.dumps({"risk": {"level": "read_only", "modifies_uploaded_files": False}}),
            adapter="native", worker_pool="native", state="running", progress=10, progress_message="正在隔离环境执行 Skill 命令",
            files_json=json.dumps({"materials": [{"file_id": item["file_id"], "name": item["name"], "sha256": item["sha256"]} for item in context.inputs]}),
            message=body.command, idempotency_key=workspace.parent.name, started_at=now, heartbeat_at=now, attempt_count=1)
        db.add(run); db.commit()
        emit_event(db, run, event_type="state", state="running", progress=10, message="原生 Skill 命令已开始")
        artifacts = []
        try:
            transport = httpx.HTTPTransport(uds=str(native_root() / "executor.sock"))
            with httpx.Client(transport=transport, timeout=240) as client:
                response = client.post("http://native/execute", json={"package": package.relative_to(native_root()).as_posix(),
                    "workspace": workspace.relative_to(native_root()).as_posix(), "inputs": (workspace.parent / "materials" / hashlib.sha256(json.dumps(sorted(set(body.file_ids))).encode()).hexdigest()).relative_to(native_root()).as_posix(), "command": body.command})
                response.raise_for_status(); result = response.json()
            output_root = run_root(user.user_id, run.id) / "outputs"
            output_root.mkdir(parents=True, exist_ok=True)
            for path in sorted((workspace / "outputs").rglob("*")):
                if not path.is_file(): continue
                if path.is_symlink() or not path.resolve().is_relative_to((workspace / "outputs").resolve()): raise ValueError("输出文件越界")
                relative = path.relative_to(workspace / "outputs").as_posix()
                if before.get(relative) == sha256_file(path): continue
                target = output_root / relative; target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, target)
                record = register_output(db, target, run.id, user, display_name=path.name, skill_id=run.skill_id, skill_name=run.skill_name, skill_version=run.skill_version)
                artifacts.append({"id": record.id, "name": record.original_name, "sha256": record.sha256, "size_bytes": record.size_bytes, "url": f"/api/platform/files/{record.id}/download"})
            run.state = "succeeded" if result.get("exit_code") == 0 else "failed"
            run.error_message = result.get("error") or ("隔离命令返回非零退出码" if run.state == "failed" else "")
            run.result_json = json.dumps({"output": result.get("output", "")[:40000], "exit_code": result.get("exit_code"), "artifacts": artifacts, "output_files": [{"file_id": item["id"], "name": item["name"], "sha256": item["sha256"], "size_bytes": item["size_bytes"]} for item in artifacts]}, ensure_ascii=False)
        except Exception as exc:
            db.rollback()
            run = db.get(RunRecord, run.id)
            artifacts = []
            run.state = "failed"; run.error_message = "隔离执行或结果归档失败，请查看本次记录；不会自动重试。"
            run.result_json = json.dumps({"error": type(exc).__name__})
        run.progress = 100; run.finished_at = datetime.now(UTC)
        run.progress_message = "原生 Skill 命令已完成" if run.state == "succeeded" else run.error_message
        emit_event(db, run, event_type="state", state=run.state, progress=100, message=run.progress_message)
        record_audit(db, actor=user, action="native_skill.command", resource_type="run", resource_id=run.id, details={"skill_id": name, "commit": pinned.commit, "state": run.state})
        db.commit()
        return {"run": serialize_run(run).model_dump(mode="json"), "output": json.loads(run.result_json), "artifacts": artifacts}


def reap_abandoned_runs(db: Session):
    cutoff = datetime.now(UTC) - timedelta(minutes=5)
    rows = db.scalars(select(RunRecord).where(RunRecord.adapter == "native", RunRecord.state == "running", RunRecord.started_at < cutoff)).all()
    for run in rows:
        key = run.idempotency_key or ""
        if not re.fullmatch(r"[a-f0-9]{64}", key): continue
        workspace = native_root() / "sessions" / key / "workspace"
        if not workspace.is_dir(): continue
        try:
            with command_guard(workspace):
                run.state = "failed"; run.progress = 100; run.finished_at = datetime.now(UTC)
                run.error_message = "执行服务异常中断，本次命令已结束；不会自动重试。"
                run.progress_message = run.error_message
                emit_event(db, run, event_type="state", state="failed", progress=100, message=run.error_message)
                db.commit()
        except HTTPException as exc:
            if exc.status_code != 409: raise


def session_runs(db: Session, user: UserContext, name: str, session_id: str):
    from .run_service import serialize_run
    _, _, workspace = session_snapshot(name, user, session_id)
    rows = db.scalars(select(RunRecord).where(RunRecord.owner_id == user.user_id, RunRecord.department_id == user.department_id,
        RunRecord.adapter == "native", RunRecord.idempotency_key == workspace.parent.name).order_by(RunRecord.created_at.desc()).limit(50)).all()
    return [serialize_run(row) for row in rows]
