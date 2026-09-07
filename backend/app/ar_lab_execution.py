"""Opt-in optimization support for the separately published AR lab Skill."""
from pathlib import Path

from .ar_skill_identity import AR_LAB_SKILL_ID

CACHED_SCRIPTS = {"classify_hexiao.py", "validate_plan.py", "build_execution_evidence.py", "build_flow_plan.py"}


def build_cache(execution, workspace: Path, ledgers: dict[int, Path]) -> dict:
    # Later batch dates use the first date's verified storage root.
    root = execution.service._workflow_storage_root(execution.db, execution.workflow).resolve()
    path = root / "read-cache" / f"{execution.action.id}.json.gz"
    arguments = ["--root", str(root), "--output", str(path)]
    for ledger in ledgers.values():
        arguments.extend(["--ledger", str(ledger)])
    for export in sorted((workspace / "01_智云导出").glob("*.xlsx")):
        arguments.extend(["--export", str(export)])
    execution.script("workbook_read_cache.py", arguments)
    return {"path": str(path), "fingerprint": execution.service.sha256_file(path)}


def cached_command(execution, name: str, arguments: list[str]) -> tuple[str, list[str]]:
    cache = execution.context.get("ar_read_cache")
    if execution.workflow.skill_id != AR_LAB_SKILL_ID or name not in CACHED_SCRIPTS or not cache:
        return name, arguments
    root = execution.service._workflow_storage_root(execution.db, execution.workflow).resolve()
    path = Path(cache["path"])
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("只读索引不属于当前核销任务")
    return "run_read_cached.py", ["--root", str(root), "--cache", str(path),
        "--fingerprint", cache["fingerprint"], "--script", name, "--", *arguments]
