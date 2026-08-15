from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKUP_SCRIPT = PROJECT_ROOT / "scripts" / "backup_database.py"


def test_backup_with_credential_recovery_package(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "credential.key").write_bytes(b"test-recovery-key")
    upload = data_dir / "uploads" / "file-1" / "sample.txt"
    upload.parent.mkdir(parents=True)
    upload.write_text("sample", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            str(BACKUP_SCRIPT),
            "--data-dir",
            str(data_dir),
            "--label",
            "include-keys-test",
            "--include-keys",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    backup_dir = next((data_dir / "backups").glob("*_include-keys-test"))
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    recovery = json.loads(
        (backup_dir / "credential-recovery" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["credential_key_included"] is True
    assert "credential-recovery/credential.key" not in manifest["files"]
    assert "credential-recovery/credential.key" in recovery["files"]
    assert (backup_dir / "credential-recovery" / "credential.key").read_bytes() == (
        b"test-recovery-key"
    )
