"""Linux test-process groups: no descendants survive a check boundary."""
import os
import signal
import subprocess


def _signal_group(pid, value):
    try: os.killpg(pid, value)
    except ProcessLookupError: pass


def run_group(command, *, cwd=None, env=None, timeout, text=True, capture_output=True):
    if os.name != 'posix': raise RuntimeError('ISOLATED_PROCESS_GROUP_REQUIRES_POSIX')
    process = subprocess.Popen(command, cwd=cwd, env=env, text=text,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True)
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _signal_group(process.pid, signal.SIGTERM)
            try: stdout, stderr = process.communicate(timeout=0.5)
            except subprocess.TimeoutExpired:
                _signal_group(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
            raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        # Also remove descendants that detached their stdio and outlived a
        # successful parent. They belong to this dedicated test process group.
        _signal_group(process.pid, signal.SIGKILL)
        process.wait()
