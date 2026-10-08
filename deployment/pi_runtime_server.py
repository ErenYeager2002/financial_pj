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
import re
import socket
import signal
import socketserver
import struct
import subprocess
import sys
import termios
import threading
import time
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


class BridgeLifecycleError(Exception):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status


class Admission:
    # Durable gate for every platform-controlled work entry.

    def __init__(self, process):
        self.process = process
        self.lock = threading.RLock()
        self.path = SOCKET.parent / "lifecycle.json"
        self.state = "open"
        self.revision = 0
        self.token = None
        self.binding = None
        try:
            saved = json.loads(self.path.read_text())
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError):
            self.state = "stop_unknown"
            return
        if not isinstance(saved, dict) or type(saved.get("revision")) is not int:
            self.state = "stop_unknown"
            return
        self.revision = max(0, saved["revision"])
        # A bridge restart invalidates the old instance's token. It must not
        # silently reopen a gate while the host may still be stopping Docker.
        if saved.get("state") != "open":
            self.state = "stop_unknown"

    def _persist(self, state, token, binding):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name("lifecycle." + uuid4().hex + ".tmp")
        next_revision = self.revision + 1
        value = {"schema_version": "pi-lifecycle-v1", "state": state,
                 "revision": next_revision, "token": token, "binding": binding}
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            parent = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        finally:
            temporary.unlink(missing_ok=True)
        self.state, self.token, self.binding, self.revision = state, token, binding, next_revision

    def require_open(self):
        if self.state != "open":
            raise BridgeLifecycleError(409, "Pi admission is closed")

    def _verify_ticket(self, body):
        if (self.state != "quiescing" or not self.token or
                body.get("token") != self.token or
                body.get("container_id") != (self.binding or {}).get("container_id") or
                (self.binding or {}).get("instance_id") != self.process.instance_id):
            raise BridgeLifecycleError(409, "Pi quiesce ticket changed")

    def begin(self, body):
        with self.lock:
            self.require_open()
            with self.process.lock:
                revision = self.revision + self.process.sequence
                generation = self.process.generation
            container_id = body.get("container_id")
            if (body.get("session_id") != SESSION or
                    body.get("instance_id") != self.process.instance_id or
                    body.get("generation") != generation or
                    body.get("activity_revision") != revision or
                    not isinstance(container_id, str) or
                    not re.fullmatch(r"[a-f0-9]{64}", container_id) or
                    body.get("requester") != "pi-manager"):
                raise BridgeLifecycleError(409, "Pi activity identity changed")
            token = uuid4().hex
            binding = {"session_id": SESSION, "instance_id": self.process.instance_id,
                       "generation": generation, "container_id": container_id,
                       "requester": "pi-manager", "expected_revision": revision}
            self._persist("quiescing", token, binding)
            return {"token": token, "state": self.state,
                    "snapshot": self.process.activity_snapshot()}

    def inspect(self, body):
        with self.lock:
            self._verify_ticket(body)
            return {"token": self.token, "state": self.state,
                    "snapshot": self.process.activity_snapshot()}

    @staticmethod
    def _stop_eligible(snapshot):
        jobs = snapshot.get("jobs")
        return (snapshot.get("schema_version") == "pi-activity-snapshot-v1" and
                snapshot.get("admission") == "quiescing" and
                snapshot.get("inventory_complete") is True and
                snapshot.get("stop_eligible") is True and
                snapshot.get("agent_busy") is False and
                snapshot.get("pending_messages") == 0 and
                snapshot.get("pending_dialogs") == 0 and
                snapshot.get("browser_busy") is False and
                snapshot.get("untracked_execution") is False and
                snapshot.get("unpersisted_outputs") is False and
                isinstance(jobs, dict) and jobs.get("scan_complete") is True and
                jobs.get("active_count") == 0 and jobs.get("unknown_count") == 0)

    def commit(self, body):
        with self.lock:
            self._verify_ticket(body)
            snapshot = self.process.activity_snapshot()
            if (body.get("activity_revision") != snapshot.get("activity_revision") or
                    snapshot.get("instance_id") != self.process.instance_id or
                    snapshot.get("generation") != self.process.generation or
                    not self._stop_eligible(snapshot)):
                raise BridgeLifecycleError(409, "Pi is not proven idle")
            self._persist("stopping", self.token, self.binding)
            return {"state": self.state, "activity_revision": self.revision + self.process.sequence}

    def release(self, body):
        with self.lock:
            self._verify_ticket(body)
            self._persist("open", None, None)
            return {"state": self.state, "activity_revision": self.revision + self.process.sequence}


class PiProcess:
    def __init__(self):
        self.lock = threading.RLock()
        self.process = None
        self.process_identity = None
        self.mode = None
        self.master = None
        self.events = collections.deque(maxlen=4000)
        self.sequence = 0
        self.generation = 0
        self.instance_id = uuid4().hex
        self.admission = Admission(self)
        self.dialogs = PendingDialogs()
        self.activity = Activity()
        self.state_probes = {}

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
            self.process_identity = pi_jobs.identity(self.process.pid)
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
                            request_id = event.get('id')
                            internal = (event.get('type') == 'response' and
                                        isinstance(request_id, str) and
                                        request_id.startswith('__platform_activity__:'))
                            if internal:
                                probe = self.state_probes.get(request_id)
                                if probe and probe['process'] is process:
                                    probe['response'] = event
                                    probe['ready'].set()
                            else:
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
        with self.lock:
            for probe in self.state_probes.values():
                if probe["process"] is process:
                    probe["ready"].set()
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

    def query_rpc_state(self):
        """Request current queue state without exposing the response as a user event."""
        with self.lock:
            if self.mode != 'rpc' or not self.live():
                return None
            process = self.process
            generation = self.generation
            request_id = '__platform_activity__:' + uuid4().hex
            probe = {'process': process, 'ready': threading.Event(), 'response': None}
            self.state_probes[request_id] = probe
            packet = json.dumps({'type': 'get_state', 'id': request_id}).encode() + b'\n'
            descriptor = process.stdin.fileno()
            try:
                os.set_blocking(descriptor, False)
                if os.write(descriptor, packet) != len(packet):
                    raise BlockingIOError('Incomplete activity query')
            except (OSError, ValueError):
                self.state_probes.pop(request_id, None)
                return None
            finally:
                try: os.set_blocking(descriptor, True)
                except OSError: pass
        probe['ready'].wait(timeout=2)
        with self.lock:
            self.state_probes.pop(request_id, None)
            if self.process is not process or self.generation != generation:
                return None
        response = probe['response']
        if not isinstance(response, dict) or response.get('success') is not True or response.get('command') != 'get_state':
            return None
        data = response.get('data')
        if not isinstance(data, dict):
            return None
        pending = data.get('pendingMessageCount')
        streaming = data.get('isStreaming')
        compacting = data.get('isCompacting')
        if type(pending) is not int or pending < 0 or not isinstance(streaming, bool) or not isinstance(compacting, bool):
            return None
        return {'generation': generation, 'pending': pending,
                'streaming': streaming, 'compacting': compacting}

    def _process_inventory(self, process, generation, expected_identity):
        """Observe every PID in the container namespace; ambiguity blocks reap."""
        expected = {1, os.getpid()}
        if process is not None:
            expected.add(process.pid)
        try:
            namespace = os.stat('/proc/self/ns/pid').st_ino
            deadline = time.monotonic() + 0.5
            with os.scandir('/proc') as entries:
                pids = [int(entry.name) for entry in entries if entry.name.isdecimal()]
            if len(pids) > 1024 or time.monotonic() > deadline:
                return None
            rows = {}
            for pid in pids:
                if time.monotonic() > deadline:
                    return None
                path = Path('/proc') / str(pid)
                raw = (path / 'stat').read_text()
                fields = raw[raw.rindex(')') + 2:].split()
                if len(fields) < 20 or os.stat(path / 'ns/pid').st_ino != namespace:
                    return None
                rows[pid] = (fields[0], int(fields[1]), int(fields[19]))
        except (OSError, ValueError, IndexError):
            return None
        with self.lock:
            if (self.generation != generation or
                    (process is None and self.live()) or
                    (process is not None and
                     (self.process is not process or process.poll() is not None or
                      expected_identity is None or self.process_identity != expected_identity or
                      pi_jobs.identity(process.pid) != expected_identity))):
                return None
        if set(rows) != expected or any(state == 'Z' for state, _, _ in rows.values()):
            return True
        if rows[1][1] != 0 or rows[os.getpid()][1] != 1:
            return None
        if process is not None and rows[process.pid][1] != os.getpid():
            return None
        return False

    def activity_snapshot(self):
        """Expose observed facts; missing sources still prevent automatic reap."""
        rpc_state = self.query_rpc_state()
        with self.lock:
            live = self.live()
            mode = self.mode
            if rpc_state and rpc_state['generation'] != self.generation:
                rpc_state = None
            activity = self.activity.snapshot(live) if mode == 'rpc' else None
            dialogs = self.dialogs.snapshot() if live else []
            process = self.process if live else None
            generation = self.generation
            process_identity = self.process_identity if live else None
            if not live:
                agent_busy, pending = False, 0
            elif mode == 'rpc':
                agent_busy = True if activity and activity.get('busy') else (
                    bool(rpc_state['streaming'] or rpc_state['compacting']) if rpc_state else None)
                pending = rpc_state['pending'] if rpc_state else None
            else:
                agent_busy, pending = None, None
            base = {'schema_version': 'pi-activity-snapshot-v1',
                    'session_id': SESSION, 'instance_id': self.instance_id,
                    'generation': self.generation,
                    'activity_revision': self.sequence + self.admission.revision,
                    'admission': self.admission.state, 'agent_busy': agent_busy,
                    'pending_messages': pending, 'pending_dialogs': len(dialogs)}
        untracked = self._process_inventory(process, generation, process_identity)
        jobs = pi_jobs.activity_snapshot()
        browser = pi_browser.activity_snapshot()
        reasons = ['unpersisted_outputs_unobserved']
        if untracked is None:
            reasons.append('untracked_execution_unobserved')
        elif untracked:
            reasons.append('untracked_execution_present')
        if self.admission.state != 'open':
            reasons.append('admission_closed')
        if pending is None:
            reasons.append('pending_messages_unobserved')
        if mode == 'terminal' and live:
            reasons.append('terminal_activity_unobserved')
        if browser['busy'] is None:
            reasons.append('browser_cleanup_unknown')
        elif browser['busy']:
            reasons.append('browser_open_or_active')
        if not jobs['scan_complete']:
            reasons.append('job_inventory_incomplete')
        elif jobs['unknown_count']:
            reasons.append('job_execution_unknown')
        return {**base, 'browser_busy': browser['busy'],
                'untracked_execution': untracked, 'unpersisted_outputs': None,
                'inventory_complete': False, 'jobs': jobs,
                'stop_eligible': False, 'reasons': reasons}

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
            with PI.admission.lock:
                if self.path.startswith("/lifecycle/"):
                    peer = self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                    _, uid, _ = struct.unpack("3i", peer)
                    if uid != 0:
                        raise BridgeLifecycleError(403, "Host lifecycle access required")
                    if self.path == "/lifecycle/begin": result = PI.admission.begin(body)
                    elif self.path == "/lifecycle/inspect": result = PI.admission.inspect(body)
                    elif self.path == "/lifecycle/commit": result = PI.admission.commit(body)
                    elif self.path == "/lifecycle/release": result = PI.admission.release(body)
                    else: raise BridgeLifecycleError(404, "Unknown lifecycle operation")
                else:
                    command = body.get("command")
                    kind = command.get("type") if isinstance(command, dict) else None
                    new_work = (self.path in {"/configure-business", "/configure-model", "/start"} or
                                (self.path == "/send" and kind not in {
                                    "get_state", "get_messages", "get_available_models", "get_commands", "abort"}) or
                                (self.path == "/jobs" and body.get("operation") == "start") or
                                (self.path == "/browser" and body.get("action") != "close"))
                    if new_work:
                        PI.admission.require_open()
                    if self.path == "/configure-business": result = PI.configure_business(body)
                    elif self.path == "/configure-model": result = PI.configure_model(body)
                    elif self.path == "/start": result = PI.start(body.get("mode", "terminal"))
                    elif self.path == "/send": result = PI.send(body)
                    elif self.path == "/resize": result = PI.resize(body)
                    elif self.path == "/poll": result = PI.poll(body)
                    elif self.path == "/jobs": result = pi_jobs.operate(body)
                    elif self.path == "/activity-snapshot": result = PI.activity_snapshot()
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
        except BridgeLifecycleError as exc:
            self.send_error(exc.status, "Pi lifecycle conflict")
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
