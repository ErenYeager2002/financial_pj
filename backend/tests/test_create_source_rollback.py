from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_relative_output_is_resolved_from_invocation_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=repo, check=True)

    script = Path(__file__).resolve().parents[2] / "scripts" / "create_source_rollback.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--output",
            "rollback",
            "--repo",
            f"sample={repo}",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "rollback" / "sample" / "base.bundle").is_file()
