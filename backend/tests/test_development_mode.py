from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_development_mode_configuration_passes_repository_validator() -> None:
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "validate_development_mode.py")],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "development mode configuration: ok" in result.stdout


def test_frontend_stop_discards_reused_pid_without_stopping_process(tmp_path: Path) -> None:
    pwsh = shutil.which("pwsh")
    assert pwsh is not None
    script_dir = tmp_path / "scripts"
    state_path = tmp_path / "data" / "development" / "frontend-host.json"
    script_dir.mkdir(parents=True)
    state_path.parent.mkdir(parents=True)
    script = script_dir / "dev-frontend-host.ps1"
    shutil.copy2(PROJECT_ROOT / "scripts" / script.name, script)
    state_path.write_text(
        json.dumps({"process_id": os.getpid(), "project_root": str(tmp_path)}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Stop"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not state_path.exists()
