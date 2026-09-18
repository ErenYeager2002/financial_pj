"""Host-side lifecycle for owner-scoped official Pi containers.

Only the authenticated API may reach this Unix socket. Docker and host paths are
never exposed to the user container. Reconnecting does not restart a live task.
"""
from __future__ import annotations

import fcntl
import hashlib
import pi_files
import http.client
import json
import os
import re
import socket
import stat
import socketserver
import struct
import subprocess
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from uuid import UUID


class RuntimeErrorWithStatus(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path, timeout=25):
        super().__init__('localhost', timeout=timeout)
        self.path = str(path)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        # Pin the socket inode before connecting. An untrusted user owns the
        # container's control directory and must not redirect host root via a
        # symlink (or swap the path after an lstat check).
        descriptor = os.open(self.path, os.O_PATH | os.O_NOFOLLOW)
        try:
            endpoint = os.fstat(descriptor)
            if not stat.S_ISSOCK(endpoint.st_mode) or endpoint.st_uid != 10001:
                raise RuntimeErrorWithStatus(409, 'Invalid Pi control endpoint')
            self.sock.connect('/proc/self/fd/' + str(descriptor))
        finally:
            os.close(descriptor)


class RuntimeManager:
    def __init__(self, root, control, image):
        self.root = Path(root).resolve()
        self.control = Path(control).resolve()
        self.image = image
        for directory in (self.root, self.control):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.root / 'locks').mkdir(exist_ok=True, mode=0o700)

    def identity(self, owner, session):
        if not isinstance(owner, str) or not re.fullmatch(r'[a-f0-9]{64}', owner):
            raise RuntimeErrorWithStatus(422, 'Invalid owner scope')
        try:
            session = str(UUID(session))
        except (ValueError, TypeError, AttributeError):
            raise RuntimeErrorWithStatus(422, 'Invalid session ID') from None
        key = hashlib.sha256((owner + ':' + session).encode()).hexdigest()
        return owner, session, key

    @contextmanager
    def lock(self, key):
        with (self.root / 'locks' / key).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def docker(self, *args):
        result = subprocess.run(['docker', *args], capture_output=True, timeout=40)
        if result.returncode:
            # Do not put Docker diagnostics (paths/configuration) in HTTP replies.
            raise RuntimeErrorWithStatus(503, 'Pi container operation failed')
        return result.stdout

    def inspect(self, name):
        # A failed daemon query is not proof that a container is absent.
        listing = self.docker('ps', '-a', '--filter', 'name=^/' + name + '$', '--format', '{{.ID}}').strip()
        if not listing:
            return None
        return json.loads(self.docker('inspect', name))[0]

    def directory(self, path):
        if path.is_symlink():
            raise RuntimeErrorWithStatus(409, 'Unsafe runtime directory')
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.resolve().is_relative_to(self.root) and not path.resolve().is_relative_to(self.control):
            raise RuntimeErrorWithStatus(409, 'Unsafe runtime path')
        os.chown(path, 10001, 10001)
        path.chmod(0o700)
        return path

    def ensure_network(self, owner):
        name = 'financial-pi-user-' + owner[:24]
        proxy = 'financial-pi-egress'
        with self.lock('network-' + owner):
            proxy_info = self.inspect(proxy)
            if not proxy_info or not proxy_info['State']['Running'] or (proxy_info['Config'].get('Labels') or {}).get('financial.pi.egress') != '1':
                raise RuntimeErrorWithStatus(503, 'Pi outbound proxy is unavailable')
            networks = self.docker('network', 'ls', '--filter', 'name=^' + name + '$', '--format', '{{.ID}}').strip()
            if not networks:
                self.docker('network', 'create', '--internal', '--opt', 'com.docker.network.bridge.gateway_mode_ipv4=isolated', '--label', 'financial.pi.owner=' + owner, name)
            info = json.loads(self.docker('network', 'inspect', name))[0]
            if not info['Internal'] or (info.get('Labels') or {}).get('financial.pi.owner') != owner or info.get('Options', {}).get('com.docker.network.bridge.gateway_mode_ipv4') != 'isolated':
                raise RuntimeErrorWithStatus(409, 'Pi network ownership mismatch')
            if name not in proxy_info['NetworkSettings']['Networks']:
                self.docker('network', 'connect', '--alias', 'pi-egress', name, proxy)
        return name

    def check_capacity(self, owner, current_name):
        rows = self.docker('ps', '--filter', 'label=financial.pi.runtime=1', '--format', '{{.Names}} {{.Label "financial.pi.owner"}}').decode().splitlines()
        peers = [row.split() for row in rows if row.split() and row.split()[0] != current_name]
        if len(peers) >= int(os.environ.get('PI_MAX_ENVIRONMENTS', '12')):
            raise RuntimeErrorWithStatus(429, 'Pi runtime capacity is currently full')
        if sum(len(row) > 1 and row[1] == owner for row in peers) >= int(os.environ.get('PI_MAX_OWNER_ENVIRONMENTS', '4')):
            raise RuntimeErrorWithStatus(429, 'Stop an unused Pi environment before starting another')

    def skill_mounts(self, bindings):
        if not isinstance(bindings, list) or len(bindings) > 200:
            raise RuntimeErrorWithStatus(422, 'Invalid Skill bindings')
        base = self.root.parent / 'data/native-skills/packages'
        resolved = []
        seen = set()
        for item in bindings:
            if not isinstance(item, dict): raise RuntimeErrorWithStatus(422, 'Invalid Skill binding')
            name, commit = item.get('id'), item.get('commit')
            if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,71}', name) or not isinstance(commit, str) or not re.fullmatch(r'[a-f0-9]{40}', commit) or name in seen:
                raise RuntimeErrorWithStatus(422, 'Invalid Skill version')
            package = base / name / commit
            if not package.is_dir() or package.resolve() != package or not (package / 'SKILL.md').is_file():
                raise RuntimeErrorWithStatus(409, 'Pinned Skill package unavailable')
            if any(p.is_symlink() for p in package.rglob('*')):
                raise RuntimeErrorWithStatus(409, 'Unsafe Skill package')
            seen.add(name)
            resolved.append((name, commit, package))
        return sorted(resolved)

    def ensure(self, owner, session, key, bindings=None):
        skills = self.skill_mounts(bindings or [])
        skill_hash = hashlib.sha256(json.dumps([(n,c) for n,c,p in skills]).encode()).hexdigest()
        network = self.ensure_network(owner)
        self.directory(self.control / key[:32])
        name = 'financial-pi-' + key[:32]
        info = self.inspect(name)
        if info is not None:
            labels = info['Config'].get('Labels') or {}
            if labels.get('financial.pi.key') != key or labels.get('financial.pi.owner') != owner:
                raise RuntimeErrorWithStatus(409, 'Runtime ownership mismatch')
            desired_image = self.docker('image', 'inspect', self.image, '--format', '{{.Id}}').decode().strip()
            connected = info['NetworkSettings']['Networks']
            input_mount = any(m.get('Destination') == '/inputs' and not m.get('RW') for m in info.get('Mounts', []))
            needs_upgrade = info['Image'] != desired_image or set(connected) != {network} or not input_mount or not any(m.get('Destination') == '/context' for m in info.get('Mounts', [])) or labels.get('financial.pi.skills') != skill_hash
            if needs_upgrade:
                if info['State']['Running']:
                    state = self.call(self.control / key[:32] / 'pi.sock', '/poll', {'after': 0})
                    processes = self.docker('top', name, '-eo', 'pid,ppid,stat,comm').decode().splitlines()[1:]
                    live_processes = [row for row in processes if len(row.split()) >= 4 and not row.split()[2].startswith('Z')]
                    if state.get('running') or len(live_processes) > 2:
                        raise RuntimeErrorWithStatus(409, 'Stop active Pi tasks before upgrading this environment')
                # Only the container is replaced. User HOME and workspace mounts
                # are durable and stay in place throughout this explicit start.
                self.docker('rm', '-f', name)
                info = None
            elif not info['State']['Running']:
                self.check_capacity(owner, name)
                self.docker('start', name)
        if info is None:
            self.check_capacity(owner, name)
            owner_root = self.root / 'owners' / owner
            owner_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            home = self.directory(owner_root / 'home')
            workspace = self.directory(owner_root / 'sessions' / session / 'workspace')
            shared = self.directory(owner_root / 'context')
            control = self.directory(self.control / key[:32])
            originals = pi_files.inputs(owner_root / 'sessions' / session)
            # Networking is explicitly connected by the isolated egress manager.
            # Never fall back to the platform database network or host networking.
            args = ['create', '--name', name, '--init', '--network', network,
                    '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                    '--pids-limit', '512', '--cgroup-parent', 'financial-pi.slice', '--cpu-shares', '256', '--user', '10001:10001',
                    '--log-driver', 'json-file', '--log-opt', 'max-size=10m', '--log-opt', 'max-file=2',
                    '--tmpfs', '/tmp:rw,nosuid,nodev,size=512m,mode=1777',
                    '--label', 'financial.pi.runtime=1', '--label', 'financial.pi.key=' + key,
                    '--label', 'financial.pi.owner=' + owner,
                    '--label', 'financial.pi.skills=' + skill_hash,
                    '--mount', f'type=bind,src={home},dst=/home/agent',
                    '--mount', f'type=bind,src={workspace},dst=/workspace',
                    '--mount', f'type=bind,src={shared},dst=/context',
                    '--mount', f'type=bind,src={originals},dst=/inputs,readonly',
                    '--mount', f'type=bind,src={control},dst=/control',
                    '-e', 'HOME=/home/agent', '-e', 'PI_PLATFORM_SESSION_ID=' + session,
                    '-e', 'PI_SKILL_REVISIONS=' + json.dumps({n:c for n,c,p in skills}),
                    '-e', 'PI_TELEMETRY=0', '-e', 'PI_SKIP_VERSION_CHECK=1',
                    '-e', 'HTTP_PROXY=http://pi-egress:8080', '-e', 'HTTPS_PROXY=http://pi-egress:8080',
                    '-e', 'http_proxy=http://pi-egress:8080', '-e', 'https_proxy=http://pi-egress:8080',
                    '-e', 'NO_PROXY=localhost,127.0.0.1,::1',
                    '-e', 'NODE_OPTIONS=--use-env-proxy',
                    '-e', 'PIP_USER=1', '-e', 'NPM_CONFIG_PREFIX=/home/agent/.local',
                    '-e', 'PATH=/home/agent/.local/bin:/usr/local/bin:/usr/bin:/bin',
                    self.image, 'python', '/opt/platform/pi_runtime_server.py']
            mounts = [value for skill_name, _, package in skills for value in ['--mount', f'type=bind,src={package},dst=/skills/{skill_name},readonly']]
            args[-3:-3] = mounts
            self.docker(*args)
            self.docker('start', name)
        sock = self.control / key[:32] / 'pi.sock'
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                self.call(sock, '/poll', {'after': 0})
                return sock
            except (OSError, http.client.HTTPException):
                time.sleep(0.1)
        raise RuntimeErrorWithStatus(503, 'Pi runtime did not become ready')

    def call(self, sock, path, payload):
        connection = UnixHTTP(sock)
        try:
            connection.request('POST', path, json.dumps(payload).encode(), {'Content-Type': 'application/json'})
            response = connection.getresponse()
            content = response.read(32 * 1024 * 1024)
            if response.status != 200:
                raise RuntimeErrorWithStatus(response.status, 'Pi rejected the operation')
            return json.loads(content)
        finally:
            connection.close()

    def dispatch(self, body):
        owner, session, key = self.identity(body.get('owner'), body.get('session_id'))
        operation = body.get('operation')
        if operation not in {'start', 'send', 'resize', 'poll', 'stop', 'files', 'jobs'}:
            raise RuntimeErrorWithStatus(422, 'Invalid operation')
        payload = body.get('payload', {})
        if not isinstance(payload, dict):
            raise RuntimeErrorWithStatus(422, 'Invalid operation payload')
        if operation == 'jobs' and payload.get('operation') not in {'list', 'poll', 'cancel'}:
            raise RuntimeErrorWithStatus(422, 'Invalid job control operation')
        with self.lock(key):
            if operation == 'files':
                try:
                    return pi_files.operate(self.root / 'owners' / owner / 'sessions' / session, payload)
                except FileNotFoundError:
                    raise RuntimeErrorWithStatus(404, 'Pi file not found') from None
                except (ValueError, TypeError, OSError) as exc:
                    raise RuntimeErrorWithStatus(507 if getattr(exc, 'errno', None) == 28 else 422, 'Pi file operation rejected') from None
            # Only an explicit start creates/restarts an environment. Polling a
            # missing/stopped runtime must not silently restart an interrupted job.
            if operation == 'start':
                with self.lock('admission'):
                    sock = self.ensure(owner, session, key, body.get('skill_bindings', []))
            else:
                name = 'financial-pi-' + key[:32]
                info = self.inspect(name)
                if info is None or not info['State']['Running']:
                    if operation == 'jobs' and payload.get('operation') == 'list':
                        return {'jobs': [], 'environment_running': False}
                    if operation in {'poll', 'stop'}:
                        return {'running': False, 'events': [], 'next': 0, 'environment_running': False}
                    raise RuntimeErrorWithStatus(409, 'Start the Pi environment first')
                labels = info['Config'].get('Labels') or {}
                if labels.get('financial.pi.key') != key or labels.get('financial.pi.owner') != owner:
                    raise RuntimeErrorWithStatus(409, 'Runtime ownership mismatch')
                sock = self.control / key[:32] / 'pi.sock'
            if operation == 'stop':
                # Explicit stop remains available when the user's bridge is
                # broken. Ownership was checked above; never stop by raw input.
                try:
                    self.call(sock, '/browser', {'action': 'close'})
                except (RuntimeErrorWithStatus, OSError, ValueError, http.client.HTTPException):
                    pass
                try:
                    self.call(sock, '/stop', payload)
                except (RuntimeErrorWithStatus, OSError, ValueError, http.client.HTTPException):
                    pass
                name = 'financial-pi-' + key[:32]
                self.docker('stop', '--time', '10', name)
                observed = self.inspect(name)
                if observed and observed['State']['Running']:
                    raise RuntimeErrorWithStatus(503, 'Pi environment did not stop')
                return {'running': False, 'environment_running': False}
            if operation == 'start' and isinstance(body.get('business_config'), dict):
                self.call(sock, '/configure-business', body['business_config'])
            if operation == 'start' and isinstance(body.get('model_config'), dict):
                self.call(sock, '/configure-model', body['model_config'])
            return self.call(sock, '/' + operation, payload)


def serve():
    manager = RuntimeManager(os.environ['PI_RUNTIME_ROOT'], os.environ.get('PI_CONTROL_ROOT', '/run/financial-pi'),
                             os.environ['PI_RUNTIME_IMAGE'])
    allowed_uid = int(os.environ.get('PI_API_UID', '10001'))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                _, uid, _ = struct.unpack('3i', self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid not in {0, allowed_uid}:
                    raise RuntimeErrorWithStatus(403, 'Forbidden')
                if self.path != '/operate':
                    raise RuntimeErrorWithStatus(404, 'Not found')
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 9 * 1024 * 1024:
                    raise RuntimeErrorWithStatus(413, 'Invalid request size')
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise RuntimeErrorWithStatus(422, 'Expected object')
                value, status = manager.dispatch(body), 200
            except RuntimeErrorWithStatus as exc:
                value, status = {'detail': str(exc)}, exc.status
            except (ValueError, OSError, subprocess.SubprocessError, http.client.HTTPException):
                value, status = {'detail': 'Pi runtime unavailable'}, 503
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    target = Path(os.environ['PI_MANAGER_SOCKET'])
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive service lock prevents unlinking a live manager's socket.
    with (manager.root / 'service.lock').open('a') as service_lock:
        fcntl.flock(service_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target.unlink(missing_ok=True)
        with Server(str(target), Handler) as server:
            os.chown(target, allowed_uid, allowed_uid)
            target.chmod(0o600)
            server.serve_forever()


if __name__ == '__main__':
    serve()
