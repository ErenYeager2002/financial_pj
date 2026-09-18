"""Disposable PostgreSQL baseline; no production network, mounts, or ports."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
LABEL = "financial.refactor.synthetic"

def command(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, **kwargs)

def cleanup(name, identity):
    value = command(["docker", "inspect", name, "--format", '{{json .Config.Labels}}'], timeout=10)
    if value.returncode:
        if "No such object" in value.stderr or "No such container" in value.stderr: return
        raise RuntimeError("TEST_CONTAINER_INSPECTION_FAILED")
    labels = json.loads(value.stdout)
    if labels.get(LABEL) != identity: raise RuntimeError("TEST_CONTAINER_CLEANUP_OWNERSHIP_MISMATCH")
    result = command(["docker", "rm", "-f", name], timeout=30)
    if result.returncode: raise RuntimeError("TEST_CONTAINER_CLEANUP_FAILED")


def main():
    identity = uuid.uuid4().hex
    name = "financial-refactor-pg-" + identity[:12]
    test_name = "financial-refactor-client-" + identity[:12]
    try:
        result = command(["docker", "run", "-d", "--name", name, "--label", LABEL+"="+identity,
            "--network", "none", "--tmpfs", "/var/lib/postgresql/data:rw,size=512m", "--tmpfs", "/var/run/postgresql",
            "-e", "POSTGRES_DB=financial_refactor_test_retention", "-e", "POSTGRES_USER=synthetic",
            "-e", "POSTGRES_PASSWORD=synthetic-only",
            os.environ.get("REFACTOR_POSTGRES_IMAGE", "docker.m.daocloud.io/library/postgres:16-alpine")], timeout=60)
        if result.returncode: raise RuntimeError("TEST_DATABASE_CONTAINER_START_FAILED")
        for _ in range(30):
            ready = command(["docker", "exec", name, "pg_isready", "-U", "synthetic", "-d", "financial_refactor_test_retention"], timeout=5)
            if ready.returncode == 0: break
            time.sleep(1)
        else: raise RuntimeError("TEST_DATABASE_NOT_READY")
        result = command(["docker", "run", "--rm", "--name", test_name, "--label", LABEL+"="+identity, "--read-only", "--network", "container:"+name,
            "--tmpfs", "/tmp:rw,size=512m", "-v", str(ROOT)+":/workspace:ro", "-w", "/workspace",
            "-e", "REFACTOR_POSTGRES_URL=postgresql+psycopg://synthetic:synthetic-only@127.0.0.1:5432/financial_refactor_test_retention",
            "--entrypoint", "python", os.environ.get("REFACTOR_BACKEND_TEST_IMAGE", "financial-refactor-test:baseline-20260918"), "-B",
            "scripts/refactor/check.py", "--suite", "postgres-integration", "--timeout", "180"], timeout=210)
        print(result.stdout)
        if result.stderr: print(result.stderr, file=sys.stderr)
        return result.returncode
    finally:
        errors = []
        for target in [test_name, name]:
            try: cleanup(target, identity)
            except Exception as error: errors.append(error)
        if errors: raise RuntimeError("TEST_CONTAINER_CLEANUP_INCOMPLETE") from errors[0]

if __name__ == '__main__': raise SystemExit(main())
