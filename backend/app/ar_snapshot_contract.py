"""Validate the fixed post-fetch contract before accepting an AR task."""
from __future__ import annotations

from .ar_skill_identity import is_ar_skill

import json
from pathlib import Path
from typing import Any

import yaml

from .ar_execution_contract import (
    COMMON_AGENT_TOOLS, CONTRACT_VERSION, GUARDED_TOOLS, PHASES, WRITE_GUARD_FIELDS,
)


class SnapshotCompatibilityError(ValueError):
    """A bounded, non-sensitive explanation suitable for a task error."""


def snapshot_file(root: Path, relative: str, *, limit: int, label: str = "执行文件") -> Path:
    path = root / relative
    if (path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
            or not path.is_file() or path.stat().st_size > limit):
        raise SnapshotCompatibilityError(f"{label}缺失、路径无效或超过大小限制。")
    return path


def snapshot_execution_version(root: Path) -> str:
    if not root.is_dir() or root.is_symlink():
        raise SnapshotCompatibilityError("固定 Skill 快照目录缺失或不安全，不能按旧版流程处理。")
    marker = root / "config" / "execution-pipeline.json"
    if not marker.exists() and not marker.is_symlink():
        return ""
    path = snapshot_file(root, "config/execution-pipeline.json", limit=64 * 1024, label="执行契约清单")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SnapshotCompatibilityError("执行契约清单不是有效的 UTF-8 JSON。") from exc
    if (not isinstance(payload, dict) or payload.get("schema_version") != CONTRACT_VERSION
            or payload.get("phases") != [phase.name for phase in PHASES]):
        raise SnapshotCompatibilityError("任务 Skill 的执行契约与当前平台不兼容")
    return CONTRACT_VERSION


def declared_tools(payload: Any, contract: str) -> list[dict[str, Any]]:
    """One tool/argument contract for creation and Agent claims; no execution."""
    if not isinstance(payload, dict) or not isinstance(payload.get("tools"), list):
        raise SnapshotCompatibilityError("任务固定的 Pi Harness 工具清单无效。")
    tools = payload["tools"]
    if any(not isinstance(item, dict) for item in tools):
        raise SnapshotCompatibilityError("任务固定的 Pi Harness 工具清单无效。")
    if contract == CONTRACT_VERSION:
        additions = payload.get("execution_v2_tools")
        if not isinstance(additions, list):
            raise SnapshotCompatibilityError("新版核销缺少分阶段工具清单，不能退回旧版统一执行。")
        tools = [item for item in tools
                 if item.get("name") not in {"build_reconciliation_plan", "apply_reconciliation"}] + additions
    result, names = [], set()
    for item in tools:
        if not isinstance(item, dict):
            raise SnapshotCompatibilityError("任务固定的 Pi Harness 工具清单无效。")
        name, description = str(item.get("name") or ""), str(item.get("description") or "")
        required = item.get("required_arguments", [])
        if (not name or not description or name in names or not isinstance(required, list)
                or any(not isinstance(value, str) for value in required)):
            raise SnapshotCompatibilityError("任务固定的 Pi Harness 工具声明不完整。")
        names.add(name)
        if contract == CONTRACT_VERSION:
            expected = list(WRITE_GUARD_FIELDS) if name in GUARDED_TOOLS else ["path"] if name == "read_task_file" else []
            if required != expected:
                raise SnapshotCompatibilityError("新版核销工具的写入条件声明与平台执行契约不一致。")
        result.append({"name": name, "description": description, "required_arguments": required})
    if contract == CONTRACT_VERSION and names != {phase.tool for phase in PHASES} | COMMON_AGENT_TOOLS:
        raise SnapshotCompatibilityError("新版核销缺少必要的执行或证据工具，不能创建省略步骤的任务。")
    return result


def validate_snapshot(root: Path) -> str:
    contract = snapshot_execution_version(root)
    if not contract:
        return ""
    from .registry import SkillManifest

    manifest_path = snapshot_file(root, "tool.yaml", limit=256 * 1024, label="Skill 声明")
    manifest = SkillManifest.model_validate(yaml.safe_load(manifest_path.read_text(encoding="utf-8")))
    if not is_ar_skill(manifest.id) or manifest.execution is None:
        raise SnapshotCompatibilityError("分阶段核销契约只能用于声明双执行模式的应收核销 Skill。")
    if set(manifest.execution.modes) != {"workflow", "pi_harness"}:
        raise SnapshotCompatibilityError("新版应收核销必须保留 Workflow 与 Pi Harness 两种固定执行方式。")
    mode = manifest.execution.modes["pi_harness"]
    tools_path = snapshot_file(root, str(mode.tools), limit=96 * 1024, label="Agent 工具清单")
    declared_tools(yaml.safe_load(tools_path.read_text(encoding="utf-8")), contract)
    for relative in (str(mode.instructions), "SKILL.md", "config/execution-v2.md"):
        path = snapshot_file(root, relative, limit=50_000, label="执行说明")
        if not path.read_text(encoding="utf-8").strip():
            raise SnapshotCompatibilityError("新版核销缺少完整执行说明。")
    # These are the adapter's entry points and its new supporting modules.
    # Presence is a packaging check, not proof of script correctness or runtime readiness.
    for name in (
        "inspect_inputs.py", "verify_sources.py", "classify_hexiao.py", "build_flow_plan.py",
        "build_execution_evidence.py", "validate_plan.py", "build_worklist.py", "apply_all.py",
        "execution_flow_stage.py", "verify_execution_write.py", "investigate_failed_write.py", "rescan_execution_holds.py",
        "build_execution_report.py", "complete_execution.py", "execution_lineage.py",
        "build_task_reports.py", "common.py", "amount_policy.py", "settlement_status.py",
        "fallback_allocation_ledger.py", "writeoff_duplicate_audit.py", "flow_ledger.py",
        "batch_ledger.py", "apply_to_copy.py", "apply_flow.py", "rescan_holds.py",
        "workbook_finalize.py", "formula_compare.py", "xlsx_patch.py", "audit_shifted_details.py",
    ):
        snapshot_file(root, f"vendor/scripts/{name}", limit=4 * 1024 * 1024, label=f"必要脚本 {name}")
    from .ar_skill_identity import AR_LAB_SKILL_ID
    if manifest.id == AR_LAB_SKILL_ID:
        for name in ("workbook_read_cache.py", "run_read_cached.py"):
            snapshot_file(root, f"vendor/scripts/{name}", limit=256 * 1024, label="优化测试必要脚本")
    return contract
