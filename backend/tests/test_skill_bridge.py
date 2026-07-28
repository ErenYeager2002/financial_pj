from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_legacy_bridge_executes_cli_and_collects_output(tmp_path: Path) -> None:
    skill_dir = tmp_path / "sample-skill"
    scripts_dir = skill_dir / "scripts"
    vendor_dir = skill_dir / "vendor" / "scripts"
    scripts_dir.mkdir(parents=True)
    vendor_dir.mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "scripts" / "legacy_skill_bridge.py", scripts_dir / "entry.py")
    (vendor_dir / "fake.py").write_text(
        """
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--source", required=True)
parser.add_argument("--note", required=True)
parser.add_argument("--out", required=True)
args = parser.parse_args()
Path(args.out).write_text(f"{Path(args.source).name}|{args.note}", encoding="utf-8")
""".strip(),
        encoding="utf-8",
    )
    (skill_dir / "bridge.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "桥接测试",
                "command": "vendor/scripts/fake.py",
                "arguments": [
                    {"kind": "file", "role": "source", "flag": "--source"},
                    {"kind": "parameter", "name": "note", "flag": "--note"},
                ],
                "output": {"type": "file", "flag": "--out", "path": "结果.txt"},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    input_path = tmp_path / "原始输入.xlsx"
    input_path.write_bytes(b"test")
    output_dir = tmp_path / "run" / "outputs"
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    request_path.write_text(
        json.dumps(
            {
                "parameters": {"note": "已处理"},
                "files": {"source": {"local_path": str(input_path)}},
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(scripts_dir / "entry.py"),
            "--request",
            str(request_path),
            "--result",
            str(result_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "success"
    assert result["summary"]["output_count"] == 1
    assert result["output_files"][0]["name"] == "结果.txt"
    assert (output_dir / "结果.txt").read_text(encoding="utf-8") == "原始输入.xlsx|已处理"
