"""Linux child-subreaper for one controlled script invocation.

A successful receipt means this supervisor reaped its entire descendant tree.
It does not certify external services, unrelated processes, or business effects.
No receipt is emitted on supervisor termination or incomplete observation.
"""
from __future__ import annotations
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys

DOMAIN_VERSION = "ar-linux-subreaper-v1"


def validate_receipt(fact, *, token, supervisor_pid):
    if (not isinstance(token, str) or len(token) != 32
            or any(c not in "0123456789abcdef" for c in token)
            or type(supervisor_pid) is not int or supervisor_pid <= 0
            or not isinstance(fact, dict) or fact.get("schema_version") != DOMAIN_VERSION
            or fact.get("token") != token
            or type(fact.get("supervisor_pid")) is not int
            or fact["supervisor_pid"] != supervisor_pid
            or fact.get("all_descendants_reaped") is not True
            or type(fact.get("reaped_count")) is not int or fact["reaped_count"] < 1
            or type(fact.get("script_returncode")) is not int):
        raise ValueError("脚本后代进程退出证明不完整。")
    return fact


def supervise(script, arguments, receipt, token):
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Linux subreaper is required")
    # PR_SET_CHILD_SUBREAPER: orphaned descendants reparent here, including
    # descendants that created another process group/session via setsid().
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Cannot establish script subreaper")
    child = subprocess.Popen([sys.executable, script, *arguments])
    count = 0
    script_code = None
    while True:
        try:
            pid, status = os.waitpid(-1, 0)
        except InterruptedError:
            continue
        except ChildProcessError:
            break
        count += 1
        if pid == child.pid:
            script_code = os.waitstatus_to_exitcode(status)
            child.returncode = script_code
    if script_code is None:
        raise RuntimeError("Script exit was not observed")
    fact = {"schema_version": DOMAIN_VERSION, "token": token,
            "supervisor_pid": os.getpid(), "all_descendants_reaped": True,
            "reaped_count": count, "script_returncode": script_code}
    encoded = json.dumps(fact, sort_keys=True).encode()
    with Path(receipt).open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return script_code if script_code >= 0 else 128 - script_code


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit("receipt, token and script required")
    raise SystemExit(supervise(sys.argv[3], sys.argv[4:], sys.argv[1], sys.argv[2]))
