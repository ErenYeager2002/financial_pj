"""Host-side lifecycle for owner-scoped official Pi containers.

Only the authenticated API may reach this Unix socket. Docker and host paths are
never exposed to the user container. Reconnecting does not restart a live task.
"""
from __future__ import annotations

import fcntl
import hashlib
import pi_files
import pi_history
import http.client
import json
import logging
import os
import re
import socket
import stat
import socketserver
import struct
import subprocess
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from uuid import UUID, uuid4


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
        self.activity = self.root / 'activity'
        self.activity.mkdir(exist_ok=True, mode=0o700)
        self.reap_root = self.root / 'reap'
        self.reap_root.mkdir(exist_ok=True, mode=0o700)
        self.idle_seconds = max(300, int(os.environ.get('PI_IDLE_SECONDS', str(8 * 60 * 60))))

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

    def inspect_id(self, container_id):
        if not isinstance(container_id, str) or not re.fullmatch(r'[a-f0-9]{64}', container_id):
            raise RuntimeErrorWithStatus(409, 'Invalid Pi container identity')
        rows = json.loads(self.docker('inspect', container_id))
        if len(rows) != 1 or rows[0].get('Id') != container_id:
            raise RuntimeErrorWithStatus(409, 'Pi container identity changed')
        return rows[0]

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

    def _activity_path(self, key):
        if not re.fullmatch(r'[a-f0-9]{64}', key):
            raise RuntimeErrorWithStatus(422, 'Invalid runtime key')
        return self.activity / (key + '.stamp')

    def _boot_id(self):
        try:
            return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        except OSError:
            return None

    def _write_activity_fact(self, key, state):
        path = self._activity_path(key)
        temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
        value = {'schema_version': 'pi-user-activity-v1', 'state': state,
                 'last_user_activity_at': time.time() if state == 'accepted' else None,
                 'boot_id': self._boot_id()}
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, 'w') as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def _mark_activity_pending(self, key):
        # Written before a request can be accepted. An uncertain result must
        # never leave an older timestamp that permits automatic reclaim.
        self._write_activity_fact(key, 'pending')

    def touch_activity(self, key):
        self._write_activity_fact(key, 'accepted')

    def _accepted_activity(self, key):
        try:
            self.touch_activity(key)
        except OSError:
            # Work was already accepted; preserve that answer. The pending
            # marker prevents reclaim until the activity fact is repaired.
            logging.exception('Pi user activity fact could not be finalized')

    def _last_activity(self, key, info):
        try:
            value = json.loads(self._activity_path(key).read_text())
            stamp = value.get('last_user_activity_at')
            boot_id = self._boot_id()
            now = time.time()
            if (value.get('schema_version') == 'pi-user-activity-v1' and
                    value.get('state') == 'accepted' and boot_id and
                    value.get('boot_id') == boot_id and
                    isinstance(stamp, (int, float)) and 0 <= stamp <= now + 60):
                return stamp
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return None

    @staticmethod
    def _activity_policy(operation, payload):
        if operation == 'start':
            return True, True
        if operation == 'send':
            command = payload.get('command')
            if isinstance(command, dict):
                kind = command.get('type')
                if not isinstance(kind, str):
                    return True, False
                if kind in {'get_state', 'get_messages', 'get_available_models', 'get_commands'}:
                    return False, False
                return True, kind in {'prompt', 'steer', 'follow_up', 'extension_ui_response'}
            return True, bool(payload.get('data'))
        if operation == 'files':
            action = payload.get('action')
            if not isinstance(action, str):
                return False, False
            return (action in {'upload_begin', 'upload_chunk', 'upload_commit', 'upload_abort'},
                    action in {'upload_begin', 'upload_commit'})
        if operation == 'jobs' and payload.get('operation') == 'cancel':
            return True, False
        return False, False

    def _reap_path(self, key):
        if not re.fullmatch(r'[a-f0-9]{64}', key):
            raise RuntimeErrorWithStatus(422, 'Invalid runtime key')
        return self.reap_root / (key + '.json')

    def _read_reap_record(self, key):
        path = self._reap_path(key)
        if path.is_symlink():
            return {'state': 'stop_unknown'}
        try:
            value = json.loads(path.read_text())
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError):
            return {'state': 'stop_unknown'}
        if (not isinstance(value, dict) or value.get('schema_version') != 'pi-reap-v1' or
                value.get('state') not in {'stopping', 'stop_unknown', 'released', 'stopped'}):
            return {'state': 'stop_unknown'}
        return value

    def _write_reap_record(self, key, state, container_id, reason):
        if state not in {'stopping', 'stop_unknown', 'released', 'stopped'}:
            raise ValueError('Invalid reap state')
        path = self._reap_path(key)
        temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
        value = {'schema_version': 'pi-reap-v1', 'state': state,
                 'container_id': container_id, 'reason': reason,
                 'recorded_at': time.time(), 'boot_id': self._boot_id()}
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, 'w') as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def _runtime_candidate(self, info):
        if info.get('State', {}).get('Running') is not True:
            return None
        labels = info.get('Config', {}).get('Labels') or {}
        owner, key = labels.get('financial.pi.owner'), labels.get('financial.pi.key')
        if labels.get('financial.pi.runtime') != '1' or not isinstance(owner, str):
            return None
        values = [item.partition('=')[2] for item in info['Config'].get('Env') or []
                  if isinstance(item, str) and item.startswith('PI_PLATFORM_SESSION_ID=')]
        if len(values) != 1:
            return None
        try:
            _, session, computed = self.identity(owner, values[0])
        except RuntimeErrorWithStatus:
            return None
        if (key != computed or info.get('Name') != '/financial-pi-' + key[:32] or
                info.get('HostConfig', {}).get('ReadonlyRootfs') is not True):
            return None
        mounts = info.get('Mounts') or []
        if not all(any(m.get('Destination') == target and m.get('Type') == 'bind'
                       for m in mounts) for target in ('/home/agent', '/workspace', '/control')):
            return None
        return owner, session, key

    @staticmethod
    def _same_runtime(before, after):
        return (before.get('Id') == after.get('Id') and before.get('Name') == after.get('Name') and
                before.get('Image') == after.get('Image') and
                before.get('Config', {}).get('Labels') == after.get('Config', {}).get('Labels'))

    @staticmethod
    def _idle_snapshot(value, session, admission):
        if not isinstance(value, dict) or not isinstance(value.get('jobs'), dict):
            return False
        jobs = value['jobs']
        instance = value.get('instance_id')
        return (value.get('schema_version') == 'pi-activity-snapshot-v1' and
                value.get('session_id') == session and
                isinstance(instance, str) and re.fullmatch(r'[a-f0-9]{32}', instance) is not None and
                type(value.get('generation')) is int and value['generation'] >= 0 and
                type(value.get('activity_revision')) is int and value['activity_revision'] >= 0 and
                value.get('admission') == admission and value.get('inventory_complete') is True and
                value.get('stop_eligible') is True and value.get('agent_busy') is False and
                type(value.get('pending_messages')) is int and value['pending_messages'] == 0 and
                type(value.get('pending_dialogs')) is int and value['pending_dialogs'] == 0 and
                value.get('browser_busy') is False and value.get('untracked_execution') is False and
                value.get('unpersisted_outputs') is False and value.get('reasons') == [] and
                jobs.get('scan_complete') is True and
                type(jobs.get('active_count')) is int and jobs['active_count'] == 0 and
                type(jobs.get('unknown_count')) is int and jobs['unknown_count'] == 0)

    def _host_process_clear(self, container_id):
        lines = self.docker('top', container_id, '-eo', 'pid,ppid,stat,comm').decode().splitlines()
        if not lines or not lines[0].split()[:2] == ['PID', 'PPID']:
            return False
        rows = [line.split(maxsplit=3) for line in lines[1:]]
        if len(rows) not in {2, 3} or any(len(row) != 4 for row in rows):
            return False
        if any(not row[0].isdigit() or not row[1].isdigit() or 'Z' in row[2] for row in rows):
            return False
        init = [row for row in rows if row[3] == 'docker-init']
        bridge = [row for row in rows if row[3] == 'python']
        if len(init) != 1 or len(bridge) != 1 or bridge[0][1] != init[0][0]:
            return False
        others = [row for row in rows if row is not init[0] and row is not bridge[0]]
        return not others or (len(others) == 1 and others[0][3] == 'pi' and
                              others[0][1] == bridge[0][0])

    def _release_reap_ticket(self, key, container_id, sock, ticket):
        try:
            current = self.inspect_id(container_id)
            if not current['State']['Running']:
                raise RuntimeErrorWithStatus(409, 'Pi container changed before release')
            result = self.call(sock, '/lifecycle/release', ticket)
            if result.get('state') != 'open':
                raise RuntimeErrorWithStatus(409, 'Pi admission release unconfirmed')
            return True
        except (RuntimeErrorWithStatus, OSError, ValueError, http.client.HTTPException):
            self._write_reap_record(key, 'stop_unknown', container_id, 'release_unconfirmed')
            return False

    def _prune_one(self, container_id):
        before = self.inspect_id(container_id)
        candidate = self._runtime_candidate(before)
        if candidate is None:
            return
        owner, session, key = candidate
        with self.lock(key):
            current = self.inspect_id(container_id)
            if not self._same_runtime(before, current) or not current['State']['Running']:
                return
            record = self._read_reap_record(key)
            if record and record['state'] in {'stopping', 'stop_unknown'}:
                return
            last = self._last_activity(key, current)
            if last is None or time.time() - last < self.idle_seconds:
                return
            if not self._host_process_clear(container_id):
                return
            sock = self.control / key[:32] / 'pi.sock'
            try:
                initial = self.call(sock, '/activity-snapshot', {})
            except (RuntimeErrorWithStatus, OSError, ValueError, http.client.HTTPException):
                return  # Old bridge or unavailable socket; never stop it.
            if not self._idle_snapshot(initial, session, 'open'):
                return
            expected = {'session_id': session, 'instance_id': initial['instance_id'],
                        'generation': initial['generation'],
                        'activity_revision': initial['activity_revision'],
                        'container_id': container_id, 'requester': 'pi-manager'}
            try:
                begun = self.call(sock, '/lifecycle/begin', expected)
            except (RuntimeErrorWithStatus, OSError, ValueError, http.client.HTTPException):
                try:
                    observed = self.call(sock, '/activity-snapshot', {})
                except (RuntimeErrorWithStatus, OSError, ValueError, http.client.HTTPException):
                    observed = None
                if (not isinstance(observed, dict) or observed.get('admission') != 'open' or
                        observed.get('instance_id') != initial['instance_id']):
                    self._write_reap_record(key, 'stop_unknown', container_id, 'begin_unconfirmed')
                return
            token = begun.get('token') if isinstance(begun, dict) else None
            if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{32}', token):
                self._write_reap_record(key, 'stop_unknown', container_id, 'ticket_missing')
                return
            ticket = {'token': token, 'container_id': container_id}
            if not self._idle_snapshot(begun.get('snapshot'), session, 'quiescing'):
                self._release_reap_ticket(key, container_id, sock, ticket)
                return
            try:
                inspected = self.call(sock, '/lifecycle/inspect', ticket)
                latest = inspected.get('snapshot')
            except (RuntimeErrorWithStatus, OSError, ValueError, http.client.HTTPException):
                self._release_reap_ticket(key, container_id, sock, ticket)
                return
            if not self._idle_snapshot(latest, session, 'quiescing'):
                self._release_reap_ticket(key, container_id, sock, ticket)
                return
            checked = self.inspect_id(container_id)
            if (not self._same_runtime(current, checked) or not checked['State']['Running'] or
                    not self._host_process_clear(container_id)):
                self._write_reap_record(key, 'stop_unknown', container_id, 'container_changed')
                return
            try:
                self._write_reap_record(key, 'stopping', container_id, 'intent_recorded')
            except OSError:
                self._release_reap_ticket(key, container_id, sock, ticket)
                raise
            try:
                committed = self.call(sock, '/lifecycle/commit',
                                      {**ticket, 'activity_revision': latest['activity_revision']})
            except RuntimeErrorWithStatus as exc:
                if exc.status == 409 and self._release_reap_ticket(key, container_id, sock, ticket):
                    self._write_reap_record(key, 'released', container_id, 'commit_conflict')
                else:
                    self._write_reap_record(key, 'stop_unknown', container_id, 'commit_unconfirmed')
                return
            except (OSError, ValueError, http.client.HTTPException):
                self._write_reap_record(key, 'stop_unknown', container_id, 'commit_unconfirmed')
                return
            if not isinstance(committed, dict) or committed.get('state') != 'stopping':
                self._write_reap_record(key, 'stop_unknown', container_id, 'commit_unconfirmed')
                return
            checked = self.inspect_id(container_id)
            if (not self._same_runtime(current, checked) or not checked['State']['Running'] or
                    not self._host_process_clear(container_id)):
                self._write_reap_record(key, 'stop_unknown', container_id, 'container_changed')
                return
            try:
                self.docker('stop', '--time', '10', container_id)
                stopped = self.inspect_id(container_id)
                if not self._same_runtime(current, stopped) or stopped['State']['Running']:
                    raise RuntimeErrorWithStatus(503, 'Pi stop result unknown')
                self.docker('rm', container_id)
            except (RuntimeErrorWithStatus, OSError, ValueError, subprocess.SubprocessError):
                self._write_reap_record(key, 'stop_unknown', container_id, 'docker_stop_or_remove_unconfirmed')
                return
            self._write_reap_record(key, 'stopped', container_id, 'exact_container_removed')

    def prune_idle(self):
        try:
            raw = self.docker('ps', '--no-trunc', '--filter', 'label=financial.pi.runtime=1',
                              '--format', '{{.ID}}').decode()
            candidates = [item.strip() for item in raw.splitlines() if item.strip()]
            if len(candidates) > 128 or any(not re.fullmatch(r'[a-f0-9]{64}', item)
                                            for item in candidates):
                logging.error('Pi idle inventory is incomplete or malformed')
                return
        except (RuntimeErrorWithStatus, OSError, ValueError, subprocess.SubprocessError):
            logging.exception('Pi idle inventory unavailable')
            return
        for container_id in candidates:
            try:
                self._prune_one(container_id)
            except (RuntimeErrorWithStatus, OSError, ValueError, subprocess.SubprocessError):
                logging.exception('Pi idle candidate check failed')

    def reaper_loop(self):
        while True:
            time.sleep(300)
            self.prune_idle()

    def check_capacity(self, owner, current_name):
        rows = self.docker('ps', '--filter', 'label=financial.pi.runtime=1', '--format', '{{.Names}} {{.Label "financial.pi.owner"}}').decode().splitlines()
        peers = [row.split() for row in rows if row.split() and row.split()[0] != current_name]
        if len(peers) >= int(os.environ.get('PI_MAX_ENVIRONMENTS', '4')):
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

    @staticmethod
    def _memory_bytes(value):
        match = re.fullmatch(r'([1-9][0-9]*)([kKmMgGtT]?)', str(value))
        if not match:
            raise RuntimeErrorWithStatus(503, 'Invalid Pi resource policy')
        return int(match.group(1)) * 1024 ** ('kmgt'.find(match.group(2).lower()) + 1 if match.group(2) else 0)

    def desired_runtime_policy(self, owner, session, key, network, skills, image_id):
        owner_root = self.root / 'owners' / owner
        mounts = {
            '/home/agent': [str(owner_root / 'home'), True],
            '/workspace': [str(owner_root / 'sessions' / session / 'workspace'), True],
            '/context': [str(owner_root / 'context'), True],
            '/inputs': [str(owner_root / 'sessions' / session / 'inputs'), False],
            '/control': [str(self.control / key[:32]), True],
        }
        mounts.update({'/skills/' + name: [str(package), False]
                       for name, _, package in skills})
        memory = self._memory_bytes(os.environ.get('PI_RUNTIME_MEMORY', '1536m'))
        swap = self._memory_bytes(os.environ.get('PI_RUNTIME_MEMORY_SWAP', '1536m'))
        if swap < memory:
            raise RuntimeErrorWithStatus(503, 'Invalid Pi resource policy')
        return {
            'image': image_id, 'network': network, 'memory': memory,
            'memory_swap': swap, 'pids_limit': 512, 'cpu_shares': 256,
            'cpu_quota': 0, 'cpu_period': 0, 'nano_cpus': 0,
            'cgroup_parent': 'financial-pi.slice', 'readonly_rootfs': True,
            'user': '10001:10001', 'cap_drop': ['ALL'], 'cap_add': [],
            'security_opt': ['no-new-privileges'], 'mounts': mounts,
            'tmpfs': {'/tmp': 'rw,nosuid,nodev,size=512m,mode=1777'},
            'log_driver': 'json-file', 'log_options': {'max-size': '10m', 'max-file': '2'},
        }

    @staticmethod
    def actual_runtime_policy(info):
        host = info.get('HostConfig') or {}
        config = info.get('Config') or {}
        log = host.get('LogConfig') or {}
        return {
            'image': info.get('Image'), 'network': host.get('NetworkMode'),
            'memory': host.get('Memory'), 'memory_swap': host.get('MemorySwap'),
            'pids_limit': host.get('PidsLimit'), 'cpu_shares': host.get('CpuShares'),
            'cpu_quota': host.get('CpuQuota'), 'cpu_period': host.get('CpuPeriod'),
            'nano_cpus': host.get('NanoCpus'), 'cgroup_parent': host.get('CgroupParent'),
            'readonly_rootfs': host.get('ReadonlyRootfs'), 'user': config.get('User'),
            'cap_drop': sorted(host.get('CapDrop') or []),
            'cap_add': sorted(host.get('CapAdd') or []),
            'security_opt': sorted(host.get('SecurityOpt') or []),
            'mounts': {item.get('Destination'): [item.get('Source'), item.get('RW')]
                       for item in info.get('Mounts') or []},
            'tmpfs': host.get('Tmpfs') or {}, 'log_driver': log.get('Type'),
            'log_options': {key: (log.get('Config') or {}).get(key)
                            for key in ('max-size', 'max-file')},
        }

    @staticmethod
    def runtime_policy_drift(desired, actual):
        # Image-only drift is intentionally compatible with an active legacy bridge.
        return sorted(key for key in desired if key != 'image' and desired[key] != actual.get(key))

    def ensure(self, owner, session, key, bindings=None):
        skills = self.skill_mounts(bindings or [])
        skill_hash = hashlib.sha256(json.dumps([(n,c) for n,c,p in skills]).encode()).hexdigest()
        network = self.ensure_network(owner)
        self.directory(self.control / key[:32])
        name = 'financial-pi-' + key[:32]
        desired_image = self.docker('image', 'inspect', self.image, '--format', '{{.Id}}').decode().strip()
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', desired_image):
            raise RuntimeErrorWithStatus(503, 'Pi runtime image identity unavailable')
        desired = self.desired_runtime_policy(owner, session, key, network, skills, desired_image)
        policy_hash = hashlib.sha256(json.dumps(desired, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        info = self.inspect(name)
        if info is not None:
            labels = info['Config'].get('Labels') or {}
            if labels.get('financial.pi.key') != key or labels.get('financial.pi.owner') != owner:
                raise RuntimeErrorWithStatus(409, 'Runtime ownership mismatch')
            actual = self.actual_runtime_policy(info)
            drift = self.runtime_policy_drift(desired, actual)
            if set((info.get('NetworkSettings') or {}).get('Networks') or {}) != {network}:
                drift.append('network_attachment')
            if labels.get('financial.pi.skills') != skill_hash:
                drift.append('skill_binding')
            image_drift = actual['image'] != desired_image
            if drift or image_drift:
                if info['State']['Running']:
                    if drift:
                        logging.warning('Pi runtime policy drift for %s: %s', name, ','.join(drift))
                        raise RuntimeErrorWithStatus(409, 'Pi environment policy drift: ' + ', '.join(drift))
                    # A running pinned bridge stays usable on its own image.
                    # Its activity protocol is treated as legacy until stopped.
                else:
                    # Never force-remove a running or identity-changed container.
                    current = self.inspect_id(info['Id'])
                    if current['State']['Running'] or current.get('Name') != info.get('Name'):
                        raise RuntimeErrorWithStatus(409, 'Pi container changed before policy replacement')
                    self.docker('rm', info['Id'])
                    info = None
            elif not info['State']['Running']:
                self.check_capacity(owner, name)
                self.docker('start', info['Id'])
                started = self.inspect_id(info['Id'])
                if (not started['State']['Running'] or
                        self.runtime_policy_drift(desired, self.actual_runtime_policy(started))):
                    raise RuntimeErrorWithStatus(503, 'Pi runtime policy verification failed')
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
                    '--pids-limit', '512', '--cgroup-parent', 'financial-pi.slice', '--cpu-shares', '256',
                    '--memory', os.environ.get('PI_RUNTIME_MEMORY', '1536m'),
                    '--memory-swap', os.environ.get('PI_RUNTIME_MEMORY_SWAP', '1536m'),
                    '--user', '10001:10001',
                    '--log-driver', 'json-file', '--log-opt', 'max-size=10m', '--log-opt', 'max-file=2',
                    '--tmpfs', '/tmp:rw,nosuid,nodev,size=512m,mode=1777',
                    '--label', 'financial.pi.runtime=1', '--label', 'financial.pi.key=' + key,
                    '--label', 'financial.pi.owner=' + owner,
                    '--label', 'financial.pi.skills=' + skill_hash,
                    '--label', 'financial.pi.policy=' + policy_hash,
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
                    '-e', 'NPM_CONFIG_PREFIX=/home/agent/.local',
                    '-e', 'PATH=/home/agent/.local/bin:/usr/local/bin:/usr/bin:/bin',
                    self.image, 'python', '/opt/platform/pi_runtime_server.py']
            mounts = [value for skill_name, _, package in skills for value in ['--mount', f'type=bind,src={package},dst=/skills/{skill_name},readonly']]
            args[-3:-3] = mounts
            self.docker(*args)
            created = self.inspect(name)
            if (created is None or created['State']['Running'] or
                    created.get('Image') != desired_image or
                    self.runtime_policy_drift(desired, self.actual_runtime_policy(created)) or
                    set((created.get('NetworkSettings') or {}).get('Networks') or {}) != {network}):
                raise RuntimeErrorWithStatus(503, 'Pi runtime policy verification failed')
            self.docker('start', created['Id'])
            started = self.inspect_id(created['Id'])
            if (not started['State']['Running'] or
                    self.runtime_policy_drift(desired, self.actual_runtime_policy(started))):
                raise RuntimeErrorWithStatus(503, 'Pi runtime policy verification failed')
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
        if operation not in {'start', 'send', 'resize', 'poll', 'stop', 'files', 'jobs', 'history'}:
            raise RuntimeErrorWithStatus(422, 'Invalid operation')
        payload = body.get('payload', {})
        if not isinstance(payload, dict):
            raise RuntimeErrorWithStatus(422, 'Invalid operation payload')
        if operation == 'jobs' and payload.get('operation') not in {'list', 'poll', 'cancel'}:
            raise RuntimeErrorWithStatus(422, 'Invalid job control operation')
        with self.lock(key):
            if operation == 'history':
                info = self.inspect('financial-pi-' + key[:32])
                if info is not None and info['State']['Running']:
                    raise RuntimeErrorWithStatus(409, 'Use live Pi messages while the environment is running')
                try:
                    return pi_history.read_history(self.root, owner, session)
                except pi_history.HistoryError as exc:
                    raise RuntimeErrorWithStatus(exc.status, str(exc)) from None
            activity_pending, user_action = self._activity_policy(operation, payload)
            if operation == 'files':
                try:
                    if activity_pending:
                        self._mark_activity_pending(key)
                    result = pi_files.operate(self.root / 'owners' / owner / 'sessions' / session, payload)
                    if user_action:
                        self._accepted_activity(key)
                    return result
                except FileNotFoundError:
                    raise RuntimeErrorWithStatus(404, 'Pi file not found') from None
                except (ValueError, TypeError, OSError) as exc:
                    raise RuntimeErrorWithStatus(507 if getattr(exc, 'errno', None) == 28 else 422, 'Pi file operation rejected') from None
            # Only an explicit start creates/restarts an environment. Polling a
            # missing/stopped runtime must not silently restart an interrupted job.
            if operation == 'start':
                record = self._read_reap_record(key)
                if record and record['state'] in {'stopping', 'stop_unknown'}:
                    raise RuntimeErrorWithStatus(409, 'Pi stop result requires investigation')
                with self.lock('admission'):
                    sock = self.ensure(owner, session, key, body.get('skill_bindings', []))
                self._mark_activity_pending(key)
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
                if activity_pending:
                    self._mark_activity_pending(key)
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
                container_id = info.get('Id')
                current = self.inspect_id(container_id)
                labels = current['Config'].get('Labels') or {}
                if (current.get('Name') != info.get('Name') or not current['State']['Running'] or
                        labels.get('financial.pi.key') != key or labels.get('financial.pi.owner') != owner):
                    raise RuntimeErrorWithStatus(409, 'Pi container identity changed before stop')
                self.docker('stop', '--time', '10', container_id)
                observed = self.inspect_id(container_id)
                if observed['State']['Running']:
                    raise RuntimeErrorWithStatus(503, 'Pi environment did not stop')
                return {'running': False, 'environment_running': False}
            if operation == 'start' and isinstance(body.get('business_config'), dict):
                self.call(sock, '/configure-business', body['business_config'])
            if operation == 'start' and isinstance(body.get('model_config'), dict):
                self.call(sock, '/configure-model', body['model_config'])
            result = self.call(sock, '/' + operation, payload)
            if user_action and ((operation == 'send' and result.get('accepted') is True) or
                                (operation == 'start' and result.get('running') is True)):
                self._accepted_activity(key)
            return result


def serve():
    manager = RuntimeManager(os.environ['PI_RUNTIME_ROOT'], os.environ.get('PI_CONTROL_ROOT', '/run/financial-pi'),
                             os.environ['PI_RUNTIME_IMAGE'])
    threading.Thread(target=manager.reaper_loop, daemon=True, name='pi-idle-reaper').start()
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
