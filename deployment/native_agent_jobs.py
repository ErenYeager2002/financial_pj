"""Durable native Agent jobs; invoked only by the platform Unix socket service.

Docker owns process liveness. A request timeout or service restart never starts
an existing job again. All user identity is supplied by the authenticated API.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

HEX64 = re.compile(r"[a-f0-9]{64}")
HEX32 = re.compile(r"[a-f0-9]{32}")
LABEL = "financial.platform.agent-job"


class AgentJobError(ValueError):
    pass


class AgentJobs:
    def __init__(self, root: Path, image: str, network: str = "none"):
        self.root = root.resolve()
        self.image = image
        self.network = network
        self.state = self.root / "agent-jobs"
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _docker(self, *args, timeout=30, check=True):
        result = subprocess.run(["docker", *args], capture_output=True, text=True,
                                timeout=timeout, check=False)
        if check and result.returncode:
            raise AgentJobError("Container operation failed")
        return result

    @contextmanager
    def _lock(self):
        with (self.state / ".lock").open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _path(self, value, pattern):
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise AgentJobError("Invalid runtime path")
        original = self.root / value
        if original.resolve() != original or not original.is_dir():
            raise AgentJobError("Runtime path is unavailable")
        return original

    def _scope(self, owner, workspace):
        if not isinstance(owner, str) or not HEX64.fullmatch(owner):
            raise AgentJobError("Invalid runtime owner")
        path = self._path(workspace, r"sessions/[a-f0-9]{64}/workspace")
        return owner, path

    def _record_path(self, job_id):
        if not isinstance(job_id, str) or not HEX32.fullmatch(job_id):
            raise AgentJobError("Invalid job identifier")
        return self.state / (job_id + ".json")

    def _save(self, record):
        target = self._record_path(record["job_id"])
        temporary = self.state / (".save-" + uuid4().hex)
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def _load(self, owner, workspace, job_id):
        self._scope(owner, workspace)
        path = self._record_path(job_id)
        if not path.is_file():
            raise AgentJobError("Job does not exist")
        record = json.loads(path.read_text())
        if record.get("owner") != owner or record.get("workspace") != workspace:
            raise AgentJobError("Job does not belong to this session")
        return record

    def _inspect(self, record):
        result = self._docker("inspect", record["container"], check=False)
        if result.returncode:
            return None
        data = json.loads(result.stdout)[0]
        if data["Config"].get("Labels", {}).get(LABEL) != record["job_id"]:
            raise AgentJobError("Job container identity mismatch")
        return data["State"]

    def _refresh(self, record):
        if record["state"] in {"succeeded", "failed", "cancelled", "lost"}:
            return record
        actual = self._inspect(record)
        if actual is None:
            # Includes an interrupted create: never re-execute an ambiguous job.
            record.update(state="lost", error="执行容器不可用；未自动重新运行。", finished_at=time.time())
        elif actual.get("Running"):
            record.update(state="running")
        elif actual.get("Status") == "created":
            record.update(state="starting")
        else:
            code = int(actual.get("ExitCode", 1))
            record.update(state="succeeded" if code == 0 else "failed", exit_code=code,
                          finished_at=time.time(), error="运行内存不足。" if actual.get("OOMKilled") else "")
        self._save(record)
        return record

    def _snapshot(self, record, offset=0):
        result = self._docker("logs", "--tail", "20000", record["container"], check=False)
        # Container logging rotates independently, so the cursor is a byte
        # position within this bounded snapshot, accompanied by a content hash.
        raw = (result.stdout + result.stderr).encode("utf-8") if result.returncode == 0 else b""
        truncated = len(raw) > 1024 * 1024
        raw = raw[-1024 * 1024:]
        offset = max(0, min(int(offset), len(raw)))
        end = min(offset + 64000, len(raw))
        return {"job_id": record["job_id"], "state": record["state"],
                "exit_code": record.get("exit_code"), "error": record.get("error", ""),
                "output": raw[offset:end].decode("utf-8", "replace"),
                "offset": offset, "next_offset": end, "output_bytes": len(raw),
                "output_truncated": truncated, "snapshot_hash": hashlib.sha256(raw).hexdigest(),
                "started_at": record["started_at"], "finished_at": record.get("finished_at")}

    def start(self, body):
        owner, workspace = self._scope(body.get("owner"), body.get("workspace"))
        package = self._path(body.get("package"), r"packages/[a-z][a-z0-9-]{0,71}/[a-f0-9]{40}")
        inputs = self._path(body.get("inputs"), r"sessions/[a-f0-9]{64}/materials/[a-f0-9]{64}")
        if inputs.parent.parent != workspace.parent:
            raise AgentJobError("Inputs do not belong to this session")
        command = body.get("command")
        if not isinstance(command, str) or not 0 < len(command) <= 12000 or "\0" in command:
            raise AgentJobError("Invalid command")
        job_id = body.get("job_id")
        target = self._record_path(job_id)
        fingerprint = hashlib.sha256(json.dumps({k: body.get(k) for k in
            ["owner", "workspace", "package", "inputs", "command"]}, sort_keys=True).encode()).hexdigest()
        with self._lock():
            if target.exists():
                previous = self._load(owner, body["workspace"], job_id)
                if previous["fingerprint"] != fingerprint:
                    raise AgentJobError("Job identifier reused with different request")
                return self._snapshot(self._refresh(previous))
            active = []
            for path in self.state.glob("*.json"):
                record = self._refresh(json.loads(path.read_text()))
                if record["state"] in {"starting", "running"}:
                    active.append(record)
            if any(item["workspace"] == body["workspace"] for item in active):
                raise AgentJobError("本会话已有运行中的命令，请查询或停止该任务。")
            if len(active) >= int(os.environ.get("FINANCIAL_AGENT_MAX_JOBS", "4")):
                raise AgentJobError("Agent执行槽已满，请稍后查询。")
            if shutil.disk_usage(self.root).free < 4 * 1024**3:
                raise AgentJobError("Insufficient runtime storage")
            home = self.root / "agent-homes" / owner
            home.mkdir(parents=True, exist_ok=True)
            if home.resolve() != home:
                raise AgentJobError("Invalid user home")
            os.chown(home, 10001, 10001)
            os.chown(workspace, 10001, 10001)
            for sub in ["outputs", "inputs"]:
                path = workspace / sub
                if path.is_symlink():
                    raise AgentJobError("Invalid workspace directory")
                path.mkdir(exist_ok=True)
                os.chown(path, 10001, 10001)
            container = "financial-agent-job-" + job_id
            record = dict(job_id=job_id, owner=owner, workspace=body["workspace"],
                          fingerprint=fingerprint, container=container, state="starting", started_at=time.time())
            # Persist the operation identity before starting Docker.
            self._save(record)
            args = ["run", "-d", "--init", "--pull", "never", "--name", container,
                    "--label", LABEL + "=" + job_id, "--network", self.network,
                    "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                    "--pids-limit", "512", "--memory", os.environ.get("FINANCIAL_AGENT_MEMORY", "2g"),
                    "--cpus", os.environ.get("FINANCIAL_AGENT_CPUS", "2"), "--user", "10001:10001",
                    "--log-driver", "json-file", "--log-opt", "max-size=10m", "--log-opt", "max-file=2",
                    "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m", "--workdir", "/workspace",
                    "--mount", f"type=bind,src={package},dst=/skill,readonly",
                    "--mount", f"type=bind,src={workspace},dst=/workspace",
                    "--mount", f"type=bind,src={inputs},dst=/workspace/inputs,readonly",
                    "--mount", f"type=bind,src={home},dst=/home/agent",
                    "--env", "HOME=/home/agent", "--env", "PYTHONUTF8=1",
                    "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PIP_USER=1",
                    "--env", "NPM_CONFIG_PREFIX=/home/agent/.npm-global",
                    "--env", "PATH=/home/agent/.local/bin:/home/agent/.npm-global/bin:/usr/local/bin:/usr/bin:/bin"]
            proxy = os.environ.get("FINANCIAL_AGENT_PROXY", "")
            if proxy:
                for key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
                    args += ["--env", key + "=" + proxy]
            args += ["--entrypoint", "/bin/sh", self.image, "-c", command]
            try:
                self._docker(*args)
            except (AgentJobError, subprocess.SubprocessError):
                # Docker may have started despite a client observation timeout.
                # Leave the saved identity for status reconciliation.
                raise AgentJobError("启动结果尚未确认，请查询原job_id，不要重复创建任务。") from None
            return self._snapshot(self._refresh(record))

    def status(self, body):
        with self._lock():
            record = self._load(body.get("owner"), body.get("workspace"), body.get("job_id"))
            return self._snapshot(self._refresh(record), body.get("offset", 0))

    def cancel(self, body):
        with self._lock():
            record = self._refresh(self._load(body.get("owner"), body.get("workspace"), body.get("job_id")))
            if record["state"] in {"starting", "running"}:
                self._docker("stop", "--time", "10", record["container"], timeout=20)
                record.update(state="cancelled", finished_at=time.time(), error="用户已停止此命令。")
                self._save(record)
            return self._snapshot(record)
