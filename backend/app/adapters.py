from __future__ import annotations

import json
import os
import signal
import shutil
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .auth import UserContext
from .events import emit_event
from .run_fencing import assert_run_fence
from .models import FileRecord, RunRecord
from .network_policy import assert_url_allowed, skill_subprocess_environment
from .registry import SkillManifest
from .storage import copy_input_to_workspace, register_output, sha256_file


@dataclass
class ExecutionContext:
    db: Session
    run: RunRecord
    manifest: SkillManifest
    skill_dir: Path
    workspace: Path
    owner: UserContext

    def emit(
        self,
        message: str,
        *,
        progress: int | None = None,
        state: str | None = None,
        event_type: str = "progress",
        data: dict[str, Any] | None = None,
    ) -> None:
        emit_event(
            self.db,
            self.run,
            event_type=event_type,
            state=state,
            progress=progress,
            message=message,
            data=data,
        )


def _json_load(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


def build_execution_request(ctx: ExecutionContext) -> tuple[dict[str, Any], Path]:
    inputs_dir = ctx.workspace / "inputs"
    outputs_dir = ctx.workspace / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    bindings = _json_load(ctx.run.files_json)
    request_files: dict[str, Any] = {}
    for role, binding in bindings.items():
        items = binding if isinstance(binding, list) else ([binding] if binding else [])
        copied: list[dict[str, Any]] = []
        for item in items:
            record = ctx.db.get(FileRecord, item["file_id"])
            if not record:
                raise RuntimeError(f"输入文件记录不存在：{item['file_id']}")
            if record.owner_id != ctx.run.owner_id or record.kind != "input":
                raise RuntimeError(f"输入文件所有者校验失败：{record.id}")
            source = Path(record.stored_path).resolve()
            if not source.is_file() or record.sha256 != sha256_file(source):
                raise RuntimeError(f"输入文件完整性校验失败：{record.id}")
            local_path = copy_input_to_workspace(
                source,
                inputs_dir,
                f"{role}_{len(copied) + 1}__{Path(record.original_name).stem}",
            )
            copied.append(
                {
                    "file_id": record.id,
                    "name": record.original_name,
                    "sha256": record.sha256,
                    "size_bytes": record.size_bytes,
                    "local_path": str(local_path),
                }
            )
        request_files[role] = (
            copied if isinstance(binding, list) else (copied[0] if copied else None)
        )
    payload = {
        "protocol_version": 1,
        "run": {
            "id": ctx.run.id,
            "skill_id": ctx.run.skill_id,
            "skill_version": ctx.run.skill_version,
            "skill_hash": ctx.run.skill_hash,
            "created_at": ctx.run.created_at.isoformat(),
        },
        "user": {
            "id": ctx.owner.user_id,
            "name": ctx.owner.display_name,
            "department_id": ctx.owner.department_id,
        },
        "message": ctx.run.message,
        "parameters": _json_load(ctx.run.parameters_json),
        "files": request_files,
        "output_dir": str(outputs_dir.resolve()),
    }
    if ctx.run.skill_id == "consolidated-statements":
        from .consolidation_store import inherited_metadata
        payload["source_metadata"] = inherited_metadata(ctx)
    request_path = ctx.workspace / "request.json"
    request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload, request_path


def _handle_skill_event(ctx: ExecutionContext, raw_line: str) -> None:
    line = raw_line.strip()
    if not line:
        return
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        ctx.emit(line, event_type="log")
        return
    event_type = str(event.get("type", "progress"))
    message = str(event.get("message", ""))
    progress = event.get("progress")
    state = event.get("state")
    if state not in {None, "running", "waiting_user_action"}:
        state = None
    ctx.emit(
        message,
        progress=int(progress) if isinstance(progress, (int, float)) else None,
        state=state,
        event_type=event_type,
        data=event.get("data") if isinstance(event.get("data"), dict) else {},
    )


def _pump_stream(stream: Any, label: str, output: queue.Queue[tuple[str, str | None]]) -> None:
    try:
        for line in iter(stream.readline, ""):
            output.put((label, line))
    finally:
        output.put((label, None))


class SubprocessAdapter:
    def execute(self, ctx: ExecutionContext) -> dict[str, Any]:
        isolated = ctx.run.skill_id == "consolidated-statements" and os.name == "posix"
        self._browser_process = None
        try:
            return self._execute(ctx)
        finally:
            if isolated:
                process = self._browser_process
                if process is not None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
                shutil.rmtree(ctx.workspace / "browser_tmp", ignore_errors=True)

    def _execute(self, ctx: ExecutionContext) -> dict[str, Any]:
        _, request_path = build_execution_request(ctx)
        result_path = ctx.workspace / "result.json"
        entrypoint = (ctx.skill_dir / (ctx.manifest.handler.entrypoint or "")).resolve()
        if not entrypoint.is_file() or not entrypoint.is_relative_to(ctx.skill_dir.resolve()):
            raise RuntimeError("Skill 入口不存在或超出 Skill 目录。")
        command = self.command(entrypoint, request_path, result_path)
        env = skill_subprocess_environment(ctx.manifest.runtime)
        env.update(
            {
                "FINANCIAL_RUN_ID": ctx.run.id,
                "FINANCIAL_RUN_WORKSPACE": str(ctx.workspace.resolve()),
                "PYTHONUTF8": "1",
            }
        )
        login = None
        if ctx.run.skill_id == "consolidated-statements" and _json_load(ctx.run.parameters_json).get("fetch_kingdee"):
            from .service_credential_service import has_service_credential, resolve_service_credential
            login = {}
            if has_service_credential(ctx.db, ctx.run.owner_id, ctx.run.department_id, "kingdee"):
                account, password = resolve_service_credential(ctx.db, ctx.run.owner_id, ctx.run.department_id, "kingdee")
                login = {"account": account, "password": password}
                del account, password
        isolated_browser = ctx.run.skill_id == "consolidated-statements" and os.name == "posix"
        browser_tmp = ctx.workspace / "browser_tmp"
        if isolated_browser:
            browser_tmp.mkdir(mode=0o700, exist_ok=True)
            env["TMPDIR"] = str(browser_tmp.resolve())
        ctx.emit("执行器已启动", progress=5, state="running", event_type="state")
        process = subprocess.Popen(
            command,
            start_new_session=isolated_browser,
            cwd=str(ctx.skill_dir),
            stdin=subprocess.PIPE if login is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        if isolated_browser:
            self._browser_process = process

        def stop_child():
            if isolated_browser:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if isolated_browser:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                process.wait(timeout=5)
            if isolated_browser:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                shutil.rmtree(browser_tmp, ignore_errors=True)

        if login is not None:
            try:
                process.stdin.write(json.dumps(login) + "\n")
                process.stdin.close()
            except (BrokenPipeError, OSError):
                stop_child()
                raise RuntimeError("采集进程启动失败") from None
            finally:
                login.clear()
        output: queue.Queue[tuple[str, str | None]] = queue.Queue()
        streams = {"stdout": process.stdout, "stderr": process.stderr}
        for label, stream in streams.items():
            threading.Thread(
                target=_pump_stream,
                args=(stream, label, output),
                daemon=True,
            ).start()
        open_streams = set(streams)
        started = time.monotonic()
        stderr_lines: list[str] = []
        timeout = ctx.manifest.runtime.timeout_seconds
        while open_streams or process.poll() is None:
            try:
                assert_run_fence(ctx.db)
            except Exception:
                stop_child()
                raise
            ctx.db.refresh(ctx.run)
            if ctx.run.cancel_requested:
                stop_child()
                raise InterruptedError("任务已被员工取消。")
            if time.monotonic() - started > timeout:
                stop_child()
                raise TimeoutError(f"Skill 执行超过 {timeout} 秒。")
            try:
                label, line = output.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                open_streams.discard(label)
            elif label == "stdout":
                _handle_skill_event(ctx, line)
            else:
                stderr_lines.append(line.rstrip())
                if len(stderr_lines) > 100:
                    stderr_lines.pop(0)
        return_code = process.wait()
        if isolated_browser:
            shutil.rmtree(browser_tmp, ignore_errors=True)
        if return_code != 0:
            detail = "\n".join(stderr_lines[-20:]) or f"退出码 {return_code}"
            raise RuntimeError(f"Skill 执行失败：{detail}")
        if not result_path.is_file():
            raise RuntimeError("Skill 未生成 result.json。")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        return self.register_artifacts(ctx, result)

    def command(self, entrypoint: Path, request_path: Path, result_path: Path) -> list[str]:
        if entrypoint.suffix.lower() == ".py":
            return [
                sys.executable,
                str(entrypoint),
                "--request",
                str(request_path),
                "--result",
                str(result_path),
            ]
        return [str(entrypoint), "--request", str(request_path), "--result", str(result_path)]

    def register_artifacts(self, ctx: ExecutionContext, result: dict[str, Any]) -> dict[str, Any]:
        consolidation = ctx.run.skill_id == "consolidated-statements"
        if consolidation:
            result["output_files"].sort(key=lambda item: item.get("name") == "报表来源与核验记录.json")
        artifacts: list[dict[str, Any]] = []
        for item in result.get("output_files", []):
            if not isinstance(item, dict) or not item.get("path"):
                continue
            path = Path(item["path"])
            if consolidation and path.name == "报表来源与核验记录.json":
                from .consolidation_store import link_sources
                link_sources(ctx)
            record = register_output(
                ctx.db,
                path,
                ctx.run.id,
                ctx.owner,
                display_name=item.get("name"),
                skill_id=ctx.run.skill_id,
                skill_name=ctx.run.skill_name,
                skill_version=ctx.run.skill_version,
            )
            artifacts.append(
                {
                    "name": record.original_name,
                    "file_id": record.id,
                    "size_bytes": record.size_bytes,
                    "sha256": record.sha256,
                    "download_url": f"/api/files/{record.id}/download",
                }
            )
        result["output_files"] = artifacts
        if consolidation:
            from .consolidation_store import persist
            persist(ctx, result)
        ctx.db.commit()
        return result


class PythonAdapter(SubprocessAdapter):
    pass


class RpaAdapter(SubprocessAdapter):
    pass


class HttpAdapter:
    def execute(self, ctx: ExecutionContext) -> dict[str, Any]:
        payload, _ = build_execution_request(ctx)
        endpoint = ctx.manifest.handler.endpoint or ""
        assert_url_allowed(endpoint, ctx.manifest.runtime)
        ctx.emit("正在调用内部接口", progress=10, state="running", event_type="state")
        response = httpx.post(endpoint, json=payload, timeout=ctx.manifest.runtime.timeout_seconds)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError("HTTP Skill 必须返回 JSON 对象。")
        return result


ADAPTERS: dict[str, Callable[[], Any]] = {
    "python": PythonAdapter,
    "rpa": RpaAdapter,
    "http": HttpAdapter,
}


def get_adapter(name: str) -> Any:
    factory = ADAPTERS.get(name)
    if not factory:
        raise RuntimeError(f"不支持的执行适配器：{name}")
    return factory()
