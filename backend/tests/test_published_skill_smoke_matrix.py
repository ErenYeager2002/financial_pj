from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_generator() -> ModuleType:
    path = Path(__file__).parent / "fixtures" / "generate_published_skill_inputs.py"
    spec = importlib.util.spec_from_file_location("published_skill_fixture_generator", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATOR = load_generator()
CASES = {
    "compliance-spot-check": (GENERATOR.compliance_inputs, {}),
    "dept-expense-alloc": (GENERATOR.department_inputs, {}),
    "dreame-ar-progress-diff": (GENERATOR.dreame_inputs, {}),
    "labor-invoice-check": (GENERATOR.labor_inputs, {}),
    "order-daily-summary": (
        GENERATOR.order_inputs,
        {"today": "", "include_detail": True, "no_date_filter": True},
    ),
    "project-detail-to-ledger": (GENERATOR.project_inputs, {}),
    "receivables-merge": (GENERATOR.receivables_inputs, {"base_month": "202608"}),
    "reconcile-bank": (
        GENERATOR.reconciliation_inputs,
        {"amount_tolerance": 1, "date_tolerance_days": 2},
    ),
    "split-by-sales": (GENERATOR.split_inputs, {"date_label": "0827"}),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("skill_id", CASES)
def test_published_skill_entry_smoke_preserves_inputs(tmp_path: Path, skill_id: str) -> None:
    generator, parameters = CASES[skill_id]
    case_root = tmp_path / skill_id
    case_root.mkdir()
    files = generator(case_root)
    input_paths = [Path(path) for items in files.values() for path in items]
    before = {path: sha256(path) for path in input_paths}
    output_dir = case_root / "outputs"
    request_path = case_root / "request.json"
    result_path = case_root / "result.json"
    skill_dir = PROJECT_ROOT / "skills" / skill_id
    manifest = yaml.safe_load((skill_dir / "tool.yaml").read_text(encoding="utf-8"))
    file_payload: dict[str, object] = {}
    for role, paths in files.items():
        items = [{"local_path": path, "original_name": Path(path).name} for path in paths]
        file_payload[role] = items if len(items) > 1 else items[0]
    request_path.write_text(
        json.dumps(
            {
                "files": file_payload,
                "parameters": parameters,
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(skill_dir / manifest["handler"]["entrypoint"]),
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
        timeout=90,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "success"
    assert result["output_files"]
    assert all(Path(item["path"]).is_file() for item in result["output_files"])
    assert {path: sha256(path) for path in input_paths} == before
