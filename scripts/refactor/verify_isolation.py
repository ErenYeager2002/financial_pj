"""Fail closed before importing any application module; no secrets in diagnostics."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
from urllib.parse import urlsplit, unquote

def contained_path(raw: str, root: Path) -> Path:
    path = Path(raw).absolute()
    if any(part.is_symlink() for part in [path, *path.parents]):
        raise ValueError("TEST_PATH_SYMLINK")
    resolved = path.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError("TEST_PATH_OUTSIDE_ROOT")
    return resolved

def verify(env=None):
    env = os.environ if env is None else env
    raw = env.get("REFACTOR_TEST_ROOT", "")
    if not raw:
        raise ValueError("TEST_ROOT_REQUIRED")
    root = Path(raw).absolute()
    if any(p.is_symlink() for p in [root, *root.parents]):
        raise ValueError("TEST_ROOT_SYMLINK")
    root = root.resolve()
    if not root.name.startswith("financial-refactor-"):
        raise ValueError("TEST_ROOT_NAME_REQUIRED")
    marker = root / ".refactor-isolated"
    if marker.is_symlink() or not marker.is_file() or marker.read_text() != "synthetic-only-v1":
        raise ValueError("TEST_MARKER_REQUIRED")
    if env.get("FINANCIAL_ENV") not in {"test", "development"}:
        raise ValueError("TEST_ENV_REQUIRED")
    contained_path(env.get("FINANCIAL_DATA_DIR", ""), root)
    url = urlsplit(env.get("FINANCIAL_DATABASE_URL", ""))
    if url.scheme == "sqlite":
        if url.netloc or url.query or url.fragment:
            raise ValueError("SQLITE_TEST_URL_INVALID")
        contained_path(unquote(url.path), root)
    elif url.scheme in {"postgresql", "postgresql+psycopg"}:
        if url.hostname not in {"localhost", "127.0.0.1", "::1", "postgres-test"} or not re.fullmatch(r"financial_refactor_test_[a-z0-9_]+", url.path.lstrip("/")) or url.query or url.fragment:
            raise ValueError("POSTGRES_TEST_TARGET_REQUIRED")
    else:
        raise ValueError("TEST_DATABASE_REQUIRED")
    for key in ("FINANCIAL_AR_HEXIAO_EXECUTION_ENABLED", "FINANCIAL_TASK_DISCOVERY_ENABLED"):
        if env.get(key) != "false":
            raise ValueError("REAL_EXECUTION_MUST_BE_DISABLED")
    if env.get("REFACTOR_REAL_CONNECTORS") != "disabled":
        raise ValueError("REAL_CONNECTORS_MUST_BE_DISABLED")
    for key in ("FINANCIAL_LLM_API_KEY", "FINANCIAL_LLM_BASE_URL", "FINANCIAL_ZHIYUN_BASE_URL", "FINANCIAL_PI_HARNESS_TOKEN", "FINANCIAL_EXTERNAL_SKILL_DIR"):
        if env.get(key):
            raise ValueError("PRODUCTION_CONNECTOR_CONFIG_REJECTED")
    return {"profile": "isolated-tests", "database_kind": url.scheme, "verified": True}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["isolated-tests"], default="isolated-tests")
    parser.parse_args()
    try:
        print(verify())
    except ValueError as error:
        parser.exit(2, str(error) + "\n")
