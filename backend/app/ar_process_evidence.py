"""Private, append-only facts about deterministic AR script processes.

These receipts prove direct-child lifecycle facts, never workbook correctness or
the termination of external applications a script may have contacted.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .network_policy import subprocess_base_environment
from .resource_policy import workflow_root
from .ar_process_identity import capture_identity

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


def run_recorded_script(
    script_dir: Path, script_name: str, arguments: list[str], *,
    action, workflow, timeout: int = 900, accepted_returncodes: tuple[int, ...] = (0,),
) -> str:
    action._ar_process_exit_confirmed = False
    root = workflow_root(workflow.owner_id, workflow.id).resolve()
    script = script_dir / script_name
    if (Path(script_name).name != script_name or script.is_symlink()
            or not script.resolve().is_relative_to(root / "skill") or not script.is_file()):
        raise ValueError("执行脚本不属于任务固定 Skill 快照。")
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
    reference = {"record_id": record_id, "script": script_name, "state": "prepared",
                 "direct_process_exit_confirmed": False}
    records = getattr(action, "_ar_process_records", None)
    if records is None:
        records = []
        action._ar_process_records = records
    records.append(reference)
    reference["prepared_sha256"] = _write_fact(record / "prepared.json", {**binding, "at": _stamp()})
    process = None
    completed = False
    stdout, stderr = "", ""
    try:
        process = subprocess.Popen(
            [sys.executable, str(script), *arguments], cwd=script_dir,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", env=subprocess_base_environment(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        reference["started_sha256"] = _write_fact(record / "started.json", {
            **binding, "at": _stamp(), "pid": process.pid, "identity": capture_identity(process.pid),
        })
        reference["state"] = "running"
        stdout, stderr = process.communicate(timeout=timeout)
        completed = True
    finally:
        # Never abandon a launched child because a journal write or timeout failed.
        # Waiting for this child does not establish that an external Excel process
        # is stopped; interrupted scripts remain unavailable for automatic recovery.
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
                process.wait()
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()
                reference["exit_sha256"] = _write_fact(record / "exited.json", {
                    **binding, "at": _stamp(), "pid": process.pid, "returncode": process.returncode,
                    "communication_completed": completed, "direct_process_exit_confirmed": True,
                    "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest() if completed else None,
                    "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest() if completed else None,
                })
                reference.update(state="exited", direct_process_exit_confirmed=True)
                action._ar_process_exit_confirmed = completed
            except BaseException:
                reference["state"] = "exit_unconfirmed"
                action._ar_process_exit_confirmed = False
                raise
        else:
            reference["state"] = "launch_unconfirmed"
    if process.returncode not in accepted_returncodes:
        details = (stderr or stdout).strip()
        suffix = f"：{details[-1200:]}" if details else ""
        raise RuntimeError(f"{script_name} 执行失败（退出码 {process.returncode}）{suffix}")
    return stdout
