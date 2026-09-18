"""Durable jobs inside one user's Pi container; never executes on the host."""
from __future__ import annotations
import base64
import codecs
import ctypes
import fcntl
import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path('/workspace/.pi/jobs')
GUARD = threading.Lock()
MAX_OUTPUT = 64 * 1024 * 1024


def _atomic(path, value):
    temporary = path.with_name(path.name + '.' + uuid4().hex)
    temporary.write_text(json.dumps(value), encoding='utf-8')
    temporary.chmod(0o600)
    os.replace(temporary, path)


def atomic(path, value):
    with (path.parent / 'state.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _atomic(path, value)


def identity(pid):
    try:
        raw = Path('/proc/' + str(int(pid)) + '/stat').read_text()
        fields = raw[raw.rindex(')') + 2:].split()
        if fields[0] == 'Z':
            return None
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip() + ':' + fields[19]
    except (OSError, ValueError, IndexError):
        return None


def directory(job_id):
    return ROOT / str(UUID(job_id))


def _state(path):
    value = json.loads((path / 'state.json').read_text())
    if value['status'] in {'starting', 'running', 'cancelling'}:
        live = value.get('supervisor_pid') and identity(value['supervisor_pid']) == value.get('supervisor_identity')
        # A launch can be observed before the child supervisor stores its PID.
        pending_launch = value['status'] == 'starting' and time.time() - value['created_at'] < 15
        if not live and not pending_launch:
            value = {**value, 'status': 'interrupted', 'finished_at': time.time(),
                     'error': 'Execution environment stopped; this job was not restarted.'}
            _atomic(path / 'state.json', value)
    return value


def state(path):
    with (path / 'state.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _state(path)


def descendants():
    parents = {}
    for item in Path('/proc').iterdir():
        if item.name.isdigit():
            try:
                raw = (item / 'stat').read_text(); fields = raw[raw.rindex(')') + 2:].split()
                if fields[0] != 'Z': parents[int(item.name)] = int(fields[1])
            except (OSError, ValueError, IndexError): pass
    found = {os.getpid()}
    while True:
        added = {pid for pid, parent in parents.items() if parent in found} - found
        if not added: return found - {os.getpid()}
        found.update(added)


def stop_descendants():
    # Linux subreaping retains daemonized/setsid descendants under this
    # supervisor. PID file descriptors avoid signaling a reused process ID.
    deadline = time.monotonic() + 5
    while True:
        children = descendants()
        if not children: return True
        for pid in children:
            try:
                descriptor = os.pidfd_open(pid)
                try:
                    if pid in descendants():
                        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                finally: os.close(descriptor)
            except ProcessLookupError: pass
        if time.monotonic() >= deadline: return False
        time.sleep(.02)


def operate(body):
    operation = body.get('operation')
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    if operation == 'start':
        command = body.get('command')
        if not isinstance(command, str) or not command.strip() or len(command) > 65536:
            raise ValueError('A command of at most 65536 characters is required')
        cwd = Path(body.get('cwd') or '/workspace').resolve()
        if not cwd.is_dir() or not (cwd.is_relative_to('/workspace') or cwd.is_relative_to('/home/agent')):
            raise ValueError('Working directory must be in your workspace or home')
        with GUARD:
            active = sum(state(p)['status'] in {'starting', 'running', 'cancelling'} for p in ROOT.iterdir() if p.is_dir() and (p / 'state.json').is_file())
            if active >= 16:
                raise ValueError('Stop an unused job before starting another')
            job_id = str(uuid4()); path = ROOT / job_id; path.mkdir(mode=0o700)
            value = {'job_id': job_id, 'status': 'starting', 'created_at': time.time(),
                     'command': command, 'cwd': str(cwd), 'output_truncated': False}
            atomic(path / 'state.json', value)
            process = subprocess.Popen([sys.executable, '-B', __file__, 'run', job_id],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
            # Reap the supervisor while the bridge remains alive; the independent
            # supervisor continues if only Pi's own agent process is restarted.
            threading.Thread(target=process.wait, daemon=True).start()
            return {'job_id': job_id, 'status': 'starting', 'next': 0}
    if operation == 'list':
        paths = sorted(ROOT.glob('*/state.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:200]
        return {'jobs': [state(p.parent) for p in paths]}
    if operation not in {'poll', 'cancel'} or not isinstance(body.get('job_id'), str):
        raise ValueError('A valid job operation and job_id are required')
    path = directory(body['job_id'])
    value = state(path)
    if operation == 'cancel':
        if value['status'] in {'starting', 'running', 'cancelling'}:
            # A marker also handles cancel racing with initial supervisor startup.
            (path / 'cancel').touch(mode=0o600, exist_ok=True)
            pid = value.get('supervisor_pid')
            if pid:
                try:
                    descriptor = os.pidfd_open(pid)
                    try:
                        if identity(pid) == value.get('supervisor_identity'):
                            signal.pidfd_send_signal(descriptor, signal.SIGTERM)
                    finally:
                        os.close(descriptor)
                except ProcessLookupError:
                    pass
            return {'job_id': value['job_id'], 'status': 'cancelling'}
        return value
    if operation != 'poll':
        raise ValueError('Invalid job operation')
    offset = max(0, int(body.get('after', 0)))
    wait = min(10, max(0, float(body.get('wait_seconds', 0))))
    deadline = time.monotonic() + wait
    output = path / 'output.bin'
    while value['status'] in {'starting', 'running', 'cancelling'} and time.monotonic() < deadline and (not output.exists() or output.stat().st_size <= offset):
        time.sleep(.1); value = state(path)
    data = b''
    if output.exists():
        with output.open('rb') as stream:
            stream.seek(offset); data = stream.read(65536)
    decoder = codecs.getincrementaldecoder('utf-8')('replace')
    final = value['status'] not in {'starting', 'running', 'cancelling'} and (not output.exists() or offset + len(data) >= output.stat().st_size)
    decoded = decoder.decode(data, final=final)
    pending = decoder.getstate()[0]
    if pending: data = data[:-len(pending)]
    return {**value, 'output': decoded,
            'output_base64': base64.b64encode(data).decode(), 'next': offset + len(data),
            'observation_timed_out': value['status'] in {'starting', 'running', 'cancelling'} and not data}


def run(job_id):
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeError('Cannot establish job subreaper')
    path = directory(job_id)
    value = json.loads((path / 'state.json').read_text())
    cancelled = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: cancelled.set())
    if (path / 'cancel').exists():
        atomic(path / 'state.json', {**value, 'status': 'cancelled', 'finished_at': time.time()})
        return
    value.update(status='running', supervisor_pid=os.getpid(),
                 supervisor_identity=identity(os.getpid()), started_at=time.time())
    atomic(path / 'state.json', value)
    process = subprocess.Popen(['bash', '-lc', value['command']], cwd=value['cwd'],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True)
    truncated = threading.Event()
    def drain():
        count = 0
        with (path / 'output.bin').open('wb', buffering=0) as output:
            while chunk := process.stdout.read1(65536):
                kept = chunk[:max(0, MAX_OUTPUT - count)]
                if kept: output.write(kept); count += len(kept)
                if len(kept) < len(chunk) and not truncated.is_set():
                    truncated.set()
                    value['output_truncated'] = True
                    atomic(path / 'state.json', value)
    reader = threading.Thread(target=drain, daemon=True); reader.start()
    while process.poll() is None:
        if cancelled.is_set() or (path / 'cancel').exists():
            cancelled.set()
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait()
            break
        time.sleep(.1)
    cleaned = stop_descendants()
    process.wait()
    while True:
        try:
            if os.waitpid(-1, os.WNOHANG)[0] == 0: break
        except ChildProcessError: break
    reader.join(timeout=5)
    value.update(status='cancelled' if cancelled.is_set() else ('succeeded' if process.returncode == 0 else 'failed'),
                 exit_code=process.returncode, finished_at=time.time(), output_truncated=truncated.is_set())
    if not cleaned:
        value.update(status='failed', error='A descendant did not stop; stop the execution environment.')
    atomic(path / 'state.json', value)


class Connection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout if isinstance(self.timeout, (int, float)) else 20)
        self.sock.connect('/control/pi.sock')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'run':
        try:
            run(sys.argv[2])
        except Exception as exc:
            path = directory(sys.argv[2]); value = json.loads((path / 'state.json').read_text())
            stop_descendants()
            atomic(path / 'state.json', {**value, 'status': 'failed', 'finished_at': time.time(), 'error': type(exc).__name__})
    else:
        connection = Connection('pi')
        body = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise ValueError('Job request too large')
        connection.request('POST', '/jobs', body, {'Content-Type': 'application/json'})
        response = connection.getresponse(); data = response.read(); connection.close()
        if response.status != 200:
            print(json.dumps({'error': 'Job operation failed', 'status': response.status}));sys.exit(1)
        print(data.decode())
