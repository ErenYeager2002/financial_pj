"""Private per-user Pi process bridge, running inside the isolated user container.

Exposes the official interactive terminal and RPC without reimplementing Pi's
agent loop. The platform authenticates/authorizes each Unix-socket request.
"""
from __future__ import annotations

import base64
import collections
import fcntl
import json
import os
import pty
import signal
import socketserver
import struct
import subprocess
import sys
import termios
import threading
import pi_jobs
import pi_browser
from pi_extension_ui import PendingDialogs
from pi_activity import Activity
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from uuid import UUID, uuid4

SOCKET = Path(os.environ.get("PI_CONTROL_SOCKET", "/control/pi.sock"))
SESSION = str(UUID(os.environ["PI_PLATFORM_SESSION_ID"]))
HOME = Path(os.environ.get("HOME", "/home/agent"))


class PiProcess:
    def __init__(self):
        self.lock = threading.RLock()
        self.process = None
        self.mode = None
        self.master = None
        self.events = collections.deque(maxlen=4000)
        self.sequence = 0
        self.generation = 0
        self.instance_id = uuid4().hex
        self.dialogs = PendingDialogs()
        self.activity = Activity()

    def append(self, event):
        with self.lock:
            self.sequence += 1
            self.events.append({"sequence": self.sequence, "generation": self.generation, **event})

    def append_for(self, process, event):
        with self.lock:
            if self.process is process:
                self.append(event)

    def live(self):
        return self.process is not None and self.process.poll() is None

    def start(self, mode):
        if mode not in {"terminal", "rpc"}:
            raise ValueError("Invalid Pi mode")
        with self.lock:
            if self.live():
                if self.mode != mode:
                    raise ValueError("Pi is already running in another mode; stop it before switching")
                return {"mode": self.mode, "running": True, "generation": self.generation}
            self.mode = mode
            self.generation += 1
            self.dialogs.clear()
            self.activity.reset()
            # Each platform conversation has its own official session tree set.
            # --continue preserves /new and /fork instead of resetting to the
            # initial UUID after a process restart.
            session_dir = HOME / ".pi/agent/sessions/platform" / SESSION
            session_dir.mkdir(parents=True, exist_ok=True)
            args = ["pi", "--append-system-prompt", "Platform files: uploaded originals are read-only in /inputs/<upload-id>/<filename>. Inspect /inputs when the user refers to uploaded files. Copy originals to /workspace before editing; save deliverables under /workspace/outputs so the user can download them. Never claim a file was created without verifying it.", "--session-dir", str(session_dir), "--extension", "/opt/platform/pi_session_tracking.ts", "--extension", "/opt/platform/pi_jobs_extension.ts", "--extension", "/opt/platform/pi_browser_extension.ts", "--extension", "/opt/platform/pi_business_extension.ts", "--extension", "/opt/platform/pi_shared_context.ts"]
            skill_root = Path('/skills')
            if skill_root.is_dir():
                for skill_path in sorted(skill_root.iterdir()):
                    if (skill_path / 'SKILL.md').is_file():
                        args += ['--skill', str(skill_path)]
                args += ['--append-system-prompt', 'Platform-installed Skills are available read-only under /skills. Read the relevant SKILL.md and follow its steps before acting. Preserve business write-before-validation, work-copy, readback and chronological-date rules. Never infer permission to run real financial writes from an environment test. Uploaded originals live in /inputs, not the legacy /workspace/inputs location.']
            pointer = session_dir / "active.json"
            active = {}
            try:
                active = json.loads(pointer.read_text())
                active["id"] = str(UUID(active["id"]))
            except (OSError, ValueError, KeyError, TypeError):
                active = {}
            if active and Path(active.get("file", "")).is_file():
                args += ["--session", active["file"]]
            elif active:
                args += ["--session-id", active["id"]]
            else:
                args += ["--continue"] if any(session_dir.glob("*.jsonl")) else ["--session-id", SESSION]
            if not active and not any(session_dir.glob('*.jsonl')) and getattr(self, 'platform_default', None):
                # Respect the user's saved provider; default only a fresh setup.
                settings_file = HOME / '.pi/agent/settings.json'
                saved = json.loads(settings_file.read_text()) if settings_file.exists() else {}
                if not saved.get('defaultProvider'):
                    args += ['--provider', 'financial-platform', '--model', self.platform_default]
            env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor", "PI_TELEMETRY": "0", "PI_SKIP_VERSION_CHECK": "1"}
            if mode == "rpc":
                args += ["--mode", "rpc"]
                self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                stderr=subprocess.PIPE, cwd="/workspace", env=env,
                                                start_new_session=True)
                process = self.process
                threading.Thread(target=self._rpc_reader, args=(process,), daemon=True).start()
                threading.Thread(target=self._error_reader, args=(process,), daemon=True).start()
            else:
                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
                # Never use preexec_fn in this threaded HTTP server. Set the
                # controlling terminal in a fresh interpreter before exec Pi.
                wrapper = [sys.executable, "-c",
                           "import fcntl,termios,os,sys; fcntl.ioctl(0,termios.TIOCSCTTY,0); os.execvp(sys.argv[1],sys.argv[1:])"]
                try:
                    self.process = subprocess.Popen(wrapper + args, stdin=slave, stdout=slave, stderr=slave,
                                                    cwd="/workspace", env=env, start_new_session=True)
                finally:
                    os.close(slave)
                self.master = master
                threading.Thread(target=self._terminal_reader, args=(self.process, master), daemon=True).start()
            self.append({"kind": "started", "mode": mode, "generation": self.generation})
            return {"mode": mode, "running": True, "generation": self.generation}


    def configure_business(self, body):
        token = body.get('token')
        if body.get('session_id') != SESSION or not isinstance(token,str) or not 32 <= len(token) <= 128:
            raise ValueError('Invalid platform business configuration')
        path = SOCKET.parent / 'business.json'
        temporary = path.with_name('business.' + uuid4().hex + '.json')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd,'w') as handle:
            json.dump({'token':token,'session_id':SESSION},handle)
        os.replace(temporary,path)
        return {'configured':True}

    def configure_model(self, body):
        token = body.get('token')
        models = body.get('models')
        if not isinstance(token, str) or not 32 <= len(token) <= 128 or not isinstance(models, list):
            raise ValueError('Invalid platform model configuration')
        prepared = []
        data_root = Path('/opt/pi/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai/dist/providers/data')
        fields = ('reasoning', 'input', 'cost', 'contextWindow', 'maxTokens', 'thinkingLevelMap', 'compat')
        provider_names = {'opencode_go': 'opencode-go', 'qwen': 'qwen-token-plan', 'moonshot': 'moonshotai'}
        for descriptor in models:
            model = {'id': descriptor['id'], 'name': descriptor['name']}
            provider = provider_names.get(descriptor.get('source_provider'), descriptor.get('source_provider', ''))
            if provider and all(c.isalnum() or c == '-' for c in provider):
                preferred = data_root / (provider + '.json')
                candidates = [preferred, *sorted(data_root.glob('*.json'))]
                for catalog_path in dict.fromkeys(candidates):
                    try:
                        catalog = json.loads(catalog_path.read_text())
                        found = next(((api, group[descriptor.get('source_model')])
                                      for api, group in catalog.items()
                                      if isinstance(group, dict) and descriptor.get('source_model') in group), None)
                    except (OSError, ValueError):
                        continue
                    if found:
                        api, upstream = found
                        # General model capabilities carry across the platform's
                        # chat-completions transport. Protocol-specific flags do not.
                        keys = [key for key in fields if key != 'compat']
                        if api == 'openai-completions':
                            keys.append('compat')
                        if catalog_path != preferred:
                            keys = [key for key in keys if key != 'cost']
                        model.update({key: upstream[key] for key in keys if key in upstream})
                        break
            prepared.append(model)
        directory = HOME / '.pi/agent'
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / 'platform-model.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = directory / 'models.json'
            current = json.loads(path.read_text()) if path.exists() else {}
            current.setdefault('providers', {})['financial-platform'] = {
                'baseUrl': 'http://platform-model.internal/v1', 'api': 'openai-completions',
                'apiKey': token, 'models': prepared,
                'compat': {'supportsStore': False, 'supportsDeveloperRole': False, 'maxTokensField': 'max_tokens'},
            }
            temporary = path.with_name('models.' + uuid4().hex + '.json')
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as handle:
                json.dump(current, handle)
            os.replace(temporary, path)
        self.platform_default = body.get('default_model')
        return {'configured': True}

    def _terminal_reader(self, process, master):
        try:
            while True:
                chunk = os.read(master, 16384)
                if not chunk:
                    break
                self.append_for(process, {"kind": "terminal", "data": base64.b64encode(chunk).decode()})
        except OSError:
            pass
        finally:
            process.wait()
            with self.lock:
                if self.master == master:
                    self.master = None
            os.close(master)
            self.append_for(process, {"kind": "exit", "exit_code": process.returncode})

    def _rpc_reader(self, process):
        # Only LF delimits RPC records. Do not split Unicode line separators.
        buffer = b""
        while True:
            chunk = os.read(process.stdout.fileno(), 16384)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                raw, buffer = buffer.split(b"\n", 1)
                try:
                    event = json.loads(raw.rstrip(b"\r"))
                    if not isinstance(event, dict):
                        raise ValueError("Expected RPC event object")
                    with self.lock:
                        if self.process is process:
                            self.dialogs.observe(event)
                            self.activity.observe(event)
                            self.append({"kind": "rpc", "event": event})
                except (ValueError, UnicodeError):
                    self.append_for(process, {"kind": "protocol_error", "message": "Pi emitted a non-JSON event"})
            if len(buffer) > 16 * 1024 * 1024:
                with self.lock:
                    if self.process is process:
                        self.append({"kind": "protocol_error", "message": "Pi event exceeds bridge limit"})
                        self.stop()
                break
        process.wait()
        self.append_for(process, {"kind": "exit", "exit_code": process.returncode})

    def _error_reader(self, process):
        # Stderr is terminal diagnostic output from this user's Pi only.
        while chunk := os.read(process.stderr.fileno(), 8192):
            self.append_for(process, {"kind": "stderr", "text": chunk.decode("utf-8", "replace")})

    def send(self, body):
        with self.lock:
            if not self.live():
                raise ValueError("Pi is not running")
            if self.mode == "rpc":
                value = body.get("command")
                if not isinstance(value, dict) or not isinstance(value.get("type"), str):
                    raise ValueError("Invalid RPC command")
                if value["type"] == "extension_ui_response":
                    value = self.dialogs.validate(value)
                data = json.dumps(value, ensure_ascii=False).encode() + b"\n"
                if len(data) > 8 * 1024 * 1024:
                    raise ValueError("RPC request too large")
                self.process.stdin.write(data)
                self.process.stdin.flush()
                if value["type"] == "extension_ui_response":
                    self.dialogs.complete(value["id"])
            else:
                data = base64.b64decode(body.get("data", ""), validate=True)
                if len(data) > 65536:
                    raise ValueError("Terminal input too large")
                os.write(self.master, data)
            return {"accepted": True}

    def resize(self, body):
        with self.lock:
            rows, cols = int(body.get("rows", 32)), int(body.get("cols", 120))
            if not 2 <= rows <= 500 or not 10 <= cols <= 1000:
                raise ValueError("Invalid terminal dimensions")
            if self.master is not None:
                fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            return {"rows": rows, "cols": cols}

    def poll(self, body):
        after = max(0, int(body.get("after", 0)))
        with self.lock:
            records = [x for x in self.events if x["sequence"] > after][:200]
            earliest = self.events[0]["sequence"] if self.events else self.sequence + 1
            return {"running": self.live(), "mode": self.mode, "generation": self.generation,
                    "events": records, "next": records[-1]["sequence"] if records else after,
                    "gap": after < earliest - 1, "first_available": earliest,
                    "session_id": SESSION, "instance_id": self.instance_id,
                    "activity": self.activity.snapshot(self.live()) if self.mode == "rpc" else None,
                    "pending_dialogs": self.dialogs.snapshot() if self.live() else []}

    def stop(self):
        with self.lock:
            process = self.process
            if process and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
            return {"running": False}


PI = PiProcess()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 9 * 1024 * 1024:
                raise ValueError("Invalid request length")
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError("Expected object")
            if self.path == "/configure-business": result = PI.configure_business(body)
            elif self.path == "/configure-model": result = PI.configure_model(body)
            elif self.path == "/start": result = PI.start(body.get("mode", "terminal"))
            elif self.path == "/send": result = PI.send(body)
            elif self.path == "/resize": result = PI.resize(body)
            elif self.path == "/poll": result = PI.poll(body)
            elif self.path == "/jobs": result = pi_jobs.operate(body)
            elif self.path == "/browser": result = pi_browser.operate(body)
            elif self.path == "/stop": result = PI.stop()
            else:
                self.send_error(404)
                return
            data = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (ValueError, OSError, subprocess.SubprocessError):
            self.send_error(422, "Pi operation failed")


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


if __name__ == "__main__":
    SOCKET.parent.mkdir(parents=True, exist_ok=True)
    SOCKET.unlink(missing_ok=True)
    with Server(str(SOCKET), Handler) as server:
        SOCKET.chmod(0o600)
        server.serve_forever()
