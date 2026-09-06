"""Observe the original local process; never signal, enumerate or trust a bare PID.

Process identity uses PID plus creation time as documented by psutil:
https://psutil.io/7.2/#psutil.Process.is_running
The hashed OS scope additionally prevents querying a different machine/container.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import socket
import sys
from pathlib import Path

IDENTITY_VERSION = "ar-process-identity-v1"


def _scope() -> str:
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            machine = str(winreg.QueryValueEx(key, "MachineGuid")[0])
        namespace = "windows"
        # Windows boot_time() may differ by a second across processes. The
        # machine scope stays stable; exact process creation time distinguishes
        # a PID reused after restart without that unstable boot-time estimate.
        boot = "process_creation_time_checked"
    elif sys.platform.startswith("linux"):
        machine = Path("/etc/machine-id").read_text(encoding="ascii").strip()
        boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        namespace = os.readlink("/proc/self/ns/pid")
    else:
        raise ValueError("unsupported_scope")
    if not machine or not boot or not namespace:
        raise ValueError("missing_scope")
    return hashlib.sha256(json.dumps(
        [sys.platform, socket.gethostname(), machine, boot, namespace],
    ).encode("utf-8")).hexdigest()


def capture_identity(pid: int) -> dict:
    """A fast-exiting child may have no identity; retain that uncertainty."""
    try:
        import psutil
    except ImportError:
        return {"schema_version": IDENTITY_VERSION, "available": False}
    try:
        process = psutil.Process(pid)
        created = process.create_time()
        if process.ppid() != os.getpid() or not process.is_running() or not math.isfinite(created):
            raise ValueError("unconfirmed_child")
        return {"schema_version": IDENTITY_VERSION, "available": True,
                "scope": _scope(), "pid": pid, "created": repr(created)}
    except (psutil.Error, OSError, ValueError):
        return {"schema_version": IDENTITY_VERSION, "available": False}


def _changed_or_missing(psutil, identity: dict) -> str:
    # Let NoSuchProcess reach observe_identity's not_running handler. A false
    # is_running result alone may instead mean the cached identity changed.
    current = psutil.Process(identity["pid"])
    return "identity_changed" if repr(current.create_time()) != identity["created"] else "unavailable"


def observe_identity(identity: object) -> str:
    """Return only a state; no host, PID, command, user or path is exposed."""
    if (not isinstance(identity, dict) or identity.get("schema_version") != IDENTITY_VERSION
            or identity.get("available") is not True or type(identity.get("pid")) is not int
            or identity["pid"] <= 0 or not isinstance(identity.get("created"), str)):
        return "not_recorded"
    try:
        import psutil
    except ImportError:
        return "unavailable"
    try:
        if identity.get("scope") != _scope():
            return "different_scope"
        process = psutil.Process(identity["pid"])
        if repr(process.create_time()) != identity["created"]:
            # Creation-time changes can also reflect clock adjustments. Do not
            # declare the original process stopped merely from an unequal value.
            return "identity_changed"
        if not process.is_running():
            return _changed_or_missing(psutil, identity)
        status = process.status()
        if not process.is_running():
            return _changed_or_missing(psutil, identity)
        if status in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
            return "exited_unreaped"
        return "running"
    except psutil.NoSuchProcess:
        return "not_running"
    except (psutil.Error, OSError, ValueError):
        return "unavailable"
