"""Private Unix-socket runner for native Skill commands in disposable containers."""
from __future__ import annotations
import json
import fcntl
import os
import re
import selectors
import shutil
import tarfile
import signal
import socketserver
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path, PurePosixPath
from uuid import uuid4

ROOT = Path(os.environ["FINANCIAL_NATIVE_ROOT"]).resolve()
IMAGE = os.environ["FINANCIAL_NATIVE_IMAGE"]
SOCKET = ROOT / "executor.sock"
LIMIT = threading.BoundedSemaphore(2)


def checked_path(relative, expression):
    if not isinstance(relative, str) or not re.fullmatch(expression, relative): raise ValueError("Invalid sandbox path")
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT) or not path.is_dir(): raise ValueError("Sandbox directory unavailable")
    return path


def execute_unlocked(body):
    package = checked_path(body.get("package"), r"packages/[a-z][a-z0-9-]{0,71}/[a-f0-9]{40}")
    workspace = checked_path(body.get("workspace"), r"sessions/[a-f0-9]{64}/workspace")
    inputs = checked_path(body.get("inputs"), r"sessions/[a-f0-9]{64}/materials/[a-f0-9]{64}")
    if inputs.parent.parent != workspace.parent: raise ValueError("Inputs must belong to the same session")
    if shutil.disk_usage(ROOT).free < 4 * 1024**3: raise ValueError("Insufficient sandbox storage")
    command = body.get("command")
    if not isinstance(command, str) or not 0 < len(command) <= 12000: raise ValueError("Invalid command")
    name = "financial-native-" + uuid4().hex
    args = ["docker", "run", "-d", "--init", "--pull", "never", "--name", name, "--label", "financial.platform.native-sandbox=true",
            "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "128",
            "--memory", "768m", "--cpus", "1", "--user", "10001:10001",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m", "--workdir", "/workspace",
            "--mount", f"type=bind,src={package},dst=/skill,readonly",
            "--tmpfs", "/workspace:rw,nosuid,nodev,size=512m,uid=10001,gid=10001",
            "--mount", f"type=bind,src={workspace},dst=/state,readonly",
            "--mount", f"type=bind,src={inputs},dst=/workspace/inputs,readonly",
            "--env", "HOME=/tmp", "--env", "PYTHONUTF8=1", "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--entrypoint", "/bin/sh", IMAGE, "-c",
            'exec sleep 3600']
    try:
        subprocess.run(args, check=True, capture_output=True, timeout=30)
    except Exception:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
        raise
    process = subprocess.Popen(["docker", "exec", name, "/bin/sh", "-c", 'mkdir -p /workspace/outputs; cp -a /state/outputs/. /workspace/outputs/; exec /bin/sh -lc "$1"', "native-skill", command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    output = bytearray(); deadline = time.monotonic() + 120; failure = ""
    selector = selectors.DefaultSelector(); selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while True:
            if time.monotonic() > deadline:
                failure = "命令超过 120 秒，已停止本次隔离执行。"; break
            events = selector.select(0.2)
            if events:
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk: break
                output.extend(chunk)
                if len(output) > 1024 * 1024:
                    failure = "命令输出超过 1 MiB，已停止本次隔离执行。"; break
            elif process.poll() is not None: break
        if failure:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
        code = process.wait(timeout=20)
        if not failure:
            export_outputs(name, workspace)
        return {"exit_code": code if not failure else 124, "output": output[:1024*1024].decode("utf-8", "replace"), "error": failure}
    finally:
        selector.close()
        if process.poll() is None:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
            process.kill(); process.wait(timeout=10)
        process.stdout.close()
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)


def export_outputs(container: str, workspace: Path):
    staging = workspace / (".output-sync-" + uuid4().hex)
    staging.mkdir(mode=0o755)
    process = subprocess.Popen(["docker", "exec", container, "tar", "-C", "/workspace/outputs", "-cf", "-", "."], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    total = 0; count = 0
    deadline = threading.Timer(30, process.kill); deadline.start()
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                    raise ValueError("Invalid output archive member")
                count += 1; total += member.size
                if count > 2000 or total > 512 * 1024**2: raise ValueError("Output limit exceeded")
                target = staging / path
                if member.isdir(): target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as src, target.open("wb") as dest:
                        shutil.copyfileobj(src, dest, length=1024*1024)
                os.chown(target, 10001, 10001)
        if process.wait(timeout=15): raise ValueError("Output export failed")
        outputs = workspace / "outputs"
        if outputs.is_symlink() or outputs.resolve() != outputs: raise ValueError("Invalid output path")
        previous = workspace / (".previous-output-" + uuid4().hex)
        os.replace(outputs, previous)
        try: os.replace(staging, outputs)
        except Exception:
            os.replace(previous, outputs); raise
        shutil.rmtree(previous)
        os.chown(outputs, 10001, 10001)
    finally:
        deadline.cancel()
        if process.poll() is None: process.kill(); process.wait(timeout=10)
        process.stdout.close()
        if staging.exists(): shutil.rmtree(staging)


def execute(body):
    workspace = checked_path(body.get("workspace"), r"sessions/[a-f0-9]{64}/workspace")
    with (workspace.parent / ".sandbox.lock").open("a+b") as lock:
        try: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc: raise ValueError("Session sandbox busy") from exc
        try: return execute_unlocked(body)
        finally: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        if self.path != "/execute": self.send_error(404); return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 20000: raise ValueError("Invalid request size")
            body = json.loads(self.rfile.read(size))
            if not LIMIT.acquire(blocking=False):
                self.send_error(429, "Sandbox busy"); return
            try: result = execute(body)
            finally: LIMIT.release()
            data = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        except (ValueError, KeyError, OSError, subprocess.SubprocessError, tarfile.TarError) as exc:
            self.send_error(422, "Sandbox execution failed")


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def cleanup_orphans():
    result = subprocess.run(["docker", "ps", "-a", "--filter", "label=financial.platform.native-sandbox=true", "--format", "{{.Names}}"], check=True, capture_output=True, text=True, timeout=20)
    for name in result.stdout.splitlines():
        if re.fullmatch(r"financial-native-[a-f0-9]{32}", name):
            subprocess.run(["docker", "rm", "-f", name], check=True, capture_output=True, timeout=20)


if __name__ == "__main__":
    cleanup_orphans()
    ROOT.mkdir(parents=True, exist_ok=True)
    SOCKET.unlink(missing_ok=True)
    with Server(str(SOCKET), Handler) as server:
        os.chown(SOCKET, 10001, 10001); os.chmod(SOCKET, 0o600)
        server.serve_forever()
