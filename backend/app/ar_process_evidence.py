"""Private, append-only facts about deterministic AR script processes.

These receipts prove direct-child lifecycle facts, never workbook correctness or
the termination of external applications a script may have contacted.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .network_policy import subprocess_base_environment, skill_subprocess_environment
from .approval_service import load_workflow_manifest
from .resource_policy import workflow_root
from .ar_process_identity import capture_identity
from .ar_process_supervisor import DOMAIN_VERSION, validate_receipt

SCHEMA_VERSION = "ar-process-evidence-v1"


def _stamp() -> str:
    return datetime.now(UTC).isoformat()


def _write_fact(path: Path, fact: dict) -> str:
    encoded = json.dumps(fact, ensure_ascii=False, sort_keys=True).encode("utf-8")
    # Each event has its own filename and is never replaced by a later state.
    with path.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return hashlib.sha256(encoded).hexdigest()


def _terminate_process_group(process: subprocess.Popen) -> None:
    """Stop the script and descendants, then wait for an unambiguous exit."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        try:
            process.terminate()
        except (ProcessLookupError, OSError):
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            try:
                process.kill()
            except (ProcessLookupError, OSError):
                pass
        process.wait(timeout=10)


def script_environment(script_name: str, arguments: list[str], workflow) -> dict[str, str]:
    """Pass declared BOC access only to AR classification, including its cache wrapper."""
    actual_name = script_name
    if script_name == "run_read_cached.py" and "--script" in arguments:
        index = arguments.index("--script") + 1
        actual_name = arguments[index] if index < len(arguments) else ""
    if actual_name == "classify_hexiao.py":
        runtime = load_workflow_manifest(workflow).runtime
        if "https://www.boc.cn" in runtime.network_targets or "https://www.boc.cn:443" in runtime.network_targets:
            return skill_subprocess_environment(runtime)
    return subprocess_base_environment()


def run_recorded_script(
    script_dir: Path, script_name: str, arguments: list[str], *,
    action, workflow, timeout: int = 900, accepted_returncodes: tuple[int, ...] = (0,),
) -> str:
    action._ar_process_exit_confirmed = False
    action._ar_lease_lost = False
    root = workflow_root(workflow.owner_id, workflow.id).resolve()
    script = script_dir / script_name
    if (Path(script_name).name != script_name or script.is_symlink()
            or not script.resolve().is_relative_to(root / "skill") or not script.is_file()):
        raise ValueError("执行脚本不属于本任务固定 Skill 快照。")
    journal = root / "execution-processes" / action.id
    if journal.is_symlink() or not journal.resolve().is_relative_to(root):
        raise ValueError("任务进程证据目录无效。")
    journal.mkdir(parents=True, exist_ok=True)
    record_id = uuid.uuid4().hex
    record = journal / record_id
    record.mkdir()
    context = json.loads(workflow.context_json or "{}")
    execution = context.get("ar_execution") or {}
    binding = {
        "schema_version": SCHEMA_VERSION, "record_id": record_id,
        "workflow_id": workflow.id, "action_id": action.id, "action_name": action.name,
        "attempt": action.attempt_count, "worker_id": action.worker_id,
        "reconciliation_date": workflow.reconciliation_date, "skill_hash": workflow.skill_hash,
        "material_set_id": execution.get("material_set_id"), "material_version": execution.get("material_version"),
        "plan_fingerprint": context.get("plan_fingerprint"),
        "host": socket.gethostname(), "worker_pid": os.getpid(),
        "script": script_name, "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "arguments_sha256": hashlib.sha256(json.dumps(arguments, ensure_ascii=False).encode("utf-8")).hexdigest(),
    }
    domain = sys.platform.startswith("linux")
    if domain:
        binding.update(execution_domain_schema=DOMAIN_VERSION, domain_token=uuid.uuid4().hex)
    reference = {"record_id": record_id, "script": script_name, "state": "prepared",
                 "direct_process_exit_confirmed": False}
    records = getattr(action, "_ar_process_records", None)
    if records is None:
        records = []
        action._ar_process_records = records
    records.append(reference)
    reference["prepared_sha256"] = _write_fact(record / "prepared.json", {**binding, "at": _stamp()})
    process = None
    domain_confirmed = not domain
    completed = False
    stdout, stderr = "", ""

    def stop_for_lease_loss() -> None:
        action._ar_lease_lost = True
        if process is not None:
            _terminate_process_group(process)

    action._ar_terminate_process = stop_for_lease_loss
    try:
        command = [sys.executable, str(script), *arguments]
        if domain:
            command = [sys.executable, str(Path(__file__).with_name("ar_process_supervisor.py")),
                       str(record / "domain-exited.json"), binding["domain_token"], str(script), *arguments]
        process = subprocess.Popen(
            command, cwd=script_dir,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", env=script_environment(script_name, arguments, workflow),
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        reference["started_sha256"] = _write_fact(record / "started.json", {
            **binding, "at": _stamp(), "pid": process.pid, "identity": capture_identity(process.pid),
        })
        reference["state"] = "running"
        stdout, stderr = process.communicate(timeout=timeout)
        completed = not getattr(action, "_ar_lease_lost", False)
    finally:
        # Never abandon a launched child because a journal write, lease loss, or
        # timeout failed. Waiting for the process group establishes direct
        # child exit; external applications remain outside this evidence.
        if process is not None:
            try:
                if process.poll() is None:
                    _terminate_process_group(process)
                process.wait()
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()
                if domain and (record / "domain-exited.json").is_file():
                    domain_path = record / "domain-exited.json"
                    if domain_path.is_symlink() or domain_path.stat().st_size > 16384:
                        raise ValueError("脚本后代进程退出证明路径或大小无效。")
                    raw = domain_path.read_bytes()
                    fact = validate_receipt(json.loads(raw), token=binding["domain_token"],
                                            supervisor_pid=process.pid)
                    expected_code = fact["script_returncode"]
                    expected_code = expected_code if expected_code >= 0 else 128 - expected_code
                    if process.returncode != expected_code:
                        raise ValueError("脚本与监督进程退出状态不一致。")
                    reference["domain_exit_sha256"] = hashlib.sha256(raw).hexdigest()
                    domain_confirmed = True
                reference["exit_sha256"] = _write_fact(record / "exited.json", {
                    **binding, "at": _stamp(), "pid": process.pid, "returncode": process.returncode,
                    "communication_completed": completed, "direct_process_exit_confirmed": process.returncode is not None,
                    "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest() if completed else None,
                    "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest() if completed else None,
                })
                reference.update(state="exited", direct_process_exit_confirmed=process.returncode is not None)
                action._ar_process_exit_confirmed = process.returncode is not None and domain_confirmed
            except BaseException:
                reference["state"] = "exit_unconfirmed"
                action._ar_process_exit_confirmed = False
                raise
        else:
            reference["state"] = "launch_unconfirmed"
        if hasattr(action, "_ar_terminate_process"):
            delattr(action, "_ar_terminate_process")
    if process is None:
        raise RuntimeError(f"{script_name} 启动未确认。")
    if not domain_confirmed:
        raise RuntimeError("脚本后代进程退出未核清，不能登记阶段完成。")
    if process.returncode not in accepted_returncodes:
        details = (stderr or stdout).strip()
        suffix = f"：{details[-1200:]}" if details else ""
        raise RuntimeError(f"{script_name} 执行失败，退出码 {process.returncode}。{suffix}")
    return stdout
