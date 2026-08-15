from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "migrate_user_storage.py"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _legacy_data(tmp_path: Path, *, busy: bool = False) -> tuple[Path, str]:
    data = tmp_path / "data"
    data.mkdir(parents=True)
    db_path = data / "financial.db"
    target_user = "11111111-1111-1111-1111-111111111111"
    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE users (id TEXT PRIMARY KEY, display_name TEXT NOT NULL);
            CREATE TABLE files (
              id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, kind TEXT NOT NULL,
              stored_path TEXT NOT NULL
            );
            CREATE TABLE runs (
              id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, owner_name TEXT NOT NULL,
              state TEXT NOT NULL
            );
            CREATE TABLE workflow_sessions (
              id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, owner_name TEXT NOT NULL,
              stage TEXT NOT NULL
            );
            CREATE TABLE workflow_batches (
              id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, owner_name TEXT NOT NULL
            );
            CREATE TABLE model_connections (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL);
            CREATE TABLE service_credentials (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL);
            CREATE TABLE workflow_actions (id TEXT PRIMARY KEY, state TEXT NOT NULL);
            """
        )
        db.execute("INSERT INTO users VALUES (?, ?)", (target_user, "迁移目标员工"))
        db.execute(
            "INSERT INTO runs VALUES ('run-1','demo-user','旧用户',?)",
            ("running" if busy else "succeeded",),
        )
        db.execute(
            "INSERT INTO workflow_sessions VALUES ('workflow-1','demo-user','旧用户','succeeded')"
        )
        db.execute("INSERT INTO workflow_batches VALUES ('batch-1','demo-user','旧用户')")
        db.execute("INSERT INTO model_connections VALUES ('model-1','demo-user')")
        db.execute("INSERT INTO service_credentials VALUES ('credential-1','demo-user')")
        db.execute("INSERT INTO workflow_actions VALUES ('action-1','succeeded')")

        upload = data / "uploads" / "file-1" / "input.xlsx"
        run_output = data / "runs" / "run-1" / "outputs" / "result.xlsx"
        workflow_output = data / "workflows" / "workflow-1" / "delivery" / "daily.xlsx"
        for path, payload in (
            (upload, b"synthetic-upload"),
            (run_output, b"synthetic-run-output"),
            (workflow_output, b"synthetic-workflow-output"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        db.executemany(
            "INSERT INTO files VALUES (?,?,?,?)",
            [
                ("file-1", "demo-user", "input", str(upload.resolve())),
                ("file-2", "demo-user", "output", str(run_output.resolve())),
                ("file-3", "demo-user", "output", str(workflow_output.resolve())),
            ],
        )
        db.commit()
    return data, target_user


def _run(data: Path, target_user: str, *extra: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    command = [
            sys.executable,
            str(SCRIPT),
            "--data-dir",
            str(data),
            "--owner-map",
            f"demo-user={target_user}",
            *extra,
        ]
    if "--apply" in extra:
        backup = data / "backups" / "test"
        backup.mkdir(parents=True, exist_ok=True)
        hashes: dict[str, str] = {}
        source_files = [
            data / "financial.db",
            *data.glob("uploads/**/*"),
            *data.glob("runs/**/*"),
            *data.glob("workflows/**/*"),
        ]
        for path in source_files:
            if not path.is_file():
                continue
            relative = path.relative_to(data)
            target = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
            hashes[relative.as_posix()] = _hash(target)
        manifest = backup / "manifest.json"
        manifest.write_text(
            json.dumps(
                {"source_data_dir": str(data.resolve()), "files": hashes},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        command.extend(["--backup-manifest", str(manifest)])
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )


def test_user_storage_migration_moves_and_verifies_legacy_layout(tmp_path: Path) -> None:
    data, target_user = _legacy_data(tmp_path)
    before = {
        "upload": _hash(data / "uploads" / "file-1" / "input.xlsx"),
        "run": _hash(data / "runs" / "run-1" / "outputs" / "result.xlsx"),
        "workflow": _hash(data / "workflows" / "workflow-1" / "delivery" / "daily.xlsx"),
    }
    result = _run(data, target_user, "--apply")
    assert result.returncode == 0, result.stderr or result.stdout

    migrated = {
        "upload": data / "uploads" / target_user / "file-1" / "input.xlsx",
        "run": data / "runs" / target_user / "run-1" / "outputs" / "result.xlsx",
        "workflow": data
        / "workflows"
        / target_user
        / "workflow-1"
        / "delivery"
        / "daily.xlsx",
    }
    assert {kind: _hash(path) for kind, path in migrated.items()} == before
    assert not (data / "uploads" / "file-1").exists()
    assert not (data / "runs" / "run-1").exists()
    assert not (data / "workflows" / "workflow-1").exists()

    with sqlite3.connect(data / "financial.db") as db:
        assert {row[0] for row in db.execute("SELECT DISTINCT owner_id FROM files")} == {
            target_user
        }
        assert db.execute("SELECT owner_name FROM runs").fetchone()[0] == "迁移目标员工"
        stored_paths = {row[0] for row in db.execute("SELECT stored_path FROM files")}
        assert stored_paths == {str(path.resolve()) for path in migrated.values()}

    report_path = next((data / "migrations").glob("*_applied.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "verified"
    assert report["resource_count"] == 3
    assert report["file_count"] == 3
    assert report["rewritten_file_paths"] == 3


def test_user_storage_migration_requires_mapping_and_idle_platform(tmp_path: Path) -> None:
    data, target_user = _legacy_data(tmp_path / "missing-map")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    missing = subprocess.run(
        [sys.executable, str(SCRIPT), "--data-dir", str(data)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    assert missing.returncode != 0
    assert "必须显式映射" in missing.stderr

    busy_data, busy_target = _legacy_data(tmp_path / "busy", busy=True)
    busy = _run(busy_data, busy_target, "--apply")
    assert busy.returncode != 0
    assert "拒绝迁移" in busy.stderr
    assert (busy_data / "runs" / "run-1").is_dir()
    assert not (busy_data / "runs" / busy_target / "run-1").exists()
