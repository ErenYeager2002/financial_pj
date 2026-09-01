from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.orm import Session

from .approval_service import (
    load_workflow_manifest,
    revoke_workflow_approvals,
)
from .audit_service import record_audit
from .auth import UserContext
from .authorization import assert_skill_permission
from .fetched_data_preview import (
    CURRENT_AR_AMOUNT_SUMMARY_KEY,
    CURRENT_WRITEOFF_AMOUNT_SUMMARY_KEY,
    current_ar_amounts_by_currency,
    current_writeoff_amounts_by_currency,
    ensure_fetched_data_preview,
    fetched_data_group_search_text,
    fetched_data_revision,
    load_fetched_data_preview_page,
    load_persisted_fetched_data_preview_page,
)
from .leases import LeaseHeartbeat, lease_deadline
from .model_service import resolve_runtime_config
from .models import (
    FileRecord,
    TaskReminder,
    WorkflowAction,
    WorkflowBatch,
    WorkflowFetchedDataPreview,
    WorkflowFetchedDataPreviewArGroup,
    WorkflowMaterialSet,
    WorkflowMaterialSetFile,
    WorkflowMessage,
    WorkflowSession,
)
from .network_policy import (
    assert_url_allowed,
    skill_subprocess_environment,
    subprocess_base_environment,
)
from .redaction import sanitize_text
from .registry import RegisteredSkill, registry
from .resource_policy import assert_owner, owner_list_filter, workflow_root
from .scheduler import (
    acquire_claim_lock,
    active_task_discovery_count,
    active_workflow_count,
    recover_expired_jobs,
)
from .schemas import (
    WorkflowBatchRead,
    WorkflowBatchStart,
    WorkflowCreate,
    WorkflowFetchedDataArGroup,
    WorkflowFetchedDataOrderGroup,
    WorkflowFetchedDataRead,
    WorkflowFetchedDataSet,
    WorkflowFetchedDelivery,
    WorkflowFetchedOrderDetail,
    WorkflowFetchedPayment,
    WorkflowFetchedSnapshotRead,
    WorkflowFetchedWriteoff,
    WorkflowRead,
    WorkflowStart,
)
from .service_credential_service import (
    has_service_credential,
    resolve_service_credential,
)
from .settings import settings
from .skill_availability_service import assert_skill_accepting_new_work
from .storage import safe_filename, sha256_file
from .task_errors import TaskErrorDetail, build_task_error
from .task_reminder_workflow_service import (
    associate_reminder_with_workflow,
    restore_unfinished_batch_reminders,
    sync_reminder_from_workflow,
)
from .workflow_constants import (
    BACKGROUND_MODEL_CONNECTION_ID,
    BACKGROUND_MODEL_NAME,
    BACKGROUND_MODEL_PROVIDER,
    is_background_model_connection,
)
from .workflow_execution_policy import (
    assert_snapshot_replay_enabled,
    assert_workflow_agent_action_enabled,
    assert_workflow_execution_enabled,
    assert_workflow_skill_execution_enabled,
)
from .workflow_material_service import (
    MaterialVersionConflict,
    create_or_replace_current_set,
    current_material_set,
    material_binding_is_allowed_output,
    material_set_bindings,
    material_set_matches_bindings,
    publish_workflow_material_set,
    successful_reconciliation_workflows_for_material_lineage,
)
from .workflow_orchestrator import (
    WorkflowDecision,
    decide_workflow_turn,
    validate_workflow_agent_request,
)

WEEKDAYS = "一二三四五六日"
CONFIRM_STAGES = {
    "awaiting_date_confirmation",
    "awaiting_fetched_data_confirmation",
    "awaiting_apply_confirmation",
}
BUSY_STAGES = {"preparing", "supplementing_fetched_data", "applying", "finalizing"}
ANNUAL_LEDGER_ROLE = "profit_loss_ledgers"
RECEIPT_FLOW_ROLE = "receipt_flow_table"
LEGACY_FILE_ROLE = "finance_workbooks"
TERMINAL_WORKFLOW_STATES = {"succeeded", "failed", "cancelled"}
PLATFORM_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _platform_today() -> date:
    """Use the business calendar instead of the container's UTC calendar."""
    return datetime.now(PLATFORM_TIMEZONE).date()


FILE_ROLES = {
    ANNUAL_LEDGER_ROLE: "02_我的表副本",
    RECEIPT_FLOW_ROLE: "02_我的表副本",
}
FILE_ROLE_LABELS = {
    ANNUAL_LEDGER_ROLE: "年度盈亏核算表",
    RECEIPT_FLOW_ROLE: "到账流转表",
}
CONFIRM_REPLIES = {"确认", "可以", "可以写", "按这个写", "没问题写吧", "写吧", "对", "是"}
WRITE_STAGING_DIR = "03_写入暂存区"
BATCH_PUBLISH_TRANSACTION_DIR = ".批次发布事务"
FETCH_SNAPSHOT_DIR = "01_智云导出"
FETCH_SNAPSHOT_VERSION = "2026-08-31-total-received-v6"
FETCHED_DATASET_SPECS = (
    ("payments", "回款记录", "回款记录"),
    ("orders", "订单交付", "订单交付"),
    ("writeoffs", "核销明细", "核销明细"),
    ("order_details", "订单明细", "订单明细"),
)
FETCHED_DATASET_BY_KEY = {key: (label, prefix) for key, label, prefix in FETCHED_DATASET_SPECS}
FETCHED_DATASET_COUNT_KEYS = {
    "payments": "回款记录笔数",
    "orders": "下单行数",
    "writeoffs": "核销明细行数",
    "order_details": "订单明细SOD行数",
}
FETCHED_SUMMARY_KEYS = {
    "回款记录笔数",
    "回款记录_接口报总数",
    "下单行数",
    "结算回查行数",
    "从结算找回单号的AR数",
    "涉及SO数",
    "核销明细行数",
    "跨父回款历史核销补取行数",
    "订单明细SOD行数",
    "回款类型分布",
    "AR覆盖率",
    "AR/SO覆盖率",
    "AR覆盖",
    "AR/SO覆盖",
    CURRENT_AR_AMOUNT_SUMMARY_KEY,
    CURRENT_WRITEOFF_AMOUNT_SUMMARY_KEY,
}
FETCHED_SUMMARY_LIST_KEYS = (
    "无下单行的AR",
    "查不到SOD的SO",
    "缺项目交付日期的SO",
)
WORKLIST_SUMMARY_KEYS = {
    "今天要填",
    "已填过·跳过",
    "冲突·需你定",
    "挂账待办",
    "异常",
    "流转确认后自动写",
    "流转须手填",
}
FETCHED_PREVIEW_MAX_LIMIT = 200
AR_ID_PATTERN = re.compile(r"^AR[A-Z0-9_-]{3,30}$")
SO_ID_PATTERN = re.compile(r"^SO[A-Z0-9_-]{3,30}$")


class PostWriteVerificationError(RuntimeError):
    """The deterministic write completed, but its final baseline could not be verified."""


class StagedWriteError(RuntimeError):
    """A write attempt failed before staged files could be published."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _public_fetched_summary(value: object) -> dict[str, Any]:
    """Return only aggregate business counts; never return paths or internal metadata."""
    if not isinstance(value, dict):
        return {}
    summary: dict[str, Any] = {}
    for key in FETCHED_SUMMARY_KEYS:
        item = value.get(key)
        if isinstance(item, (str, int, float, bool)) or item is None:
            if item is not None:
                summary[key] = item
        elif isinstance(item, dict) and all(
            isinstance(child_key, str) and isinstance(child_value, (str, int, float, bool))
            for child_key, child_value in item.items()
        ):
            summary[key] = item
    for key in FETCHED_SUMMARY_LIST_KEYS:
        item = value.get(key)
        if isinstance(item, list):
            summary[f"{key}数量"] = len(item)
    return summary


def _fetched_summary_for_date(fetched_data: object, reconciliation_date: str) -> dict[str, Any]:
    if not isinstance(fetched_data, dict):
        return {}
    summary_by_date = fetched_data.get("summary_by_date")
    if isinstance(summary_by_date, dict):
        summary = summary_by_date.get(reconciliation_date)
        return summary if isinstance(summary, dict) else {}
    summary = fetched_data.get("summary")
    return summary if isinstance(summary, dict) else {}


def _is_confirmed_empty_reconciliation_date(
    fetched_data: object,
    reconciliation_date: str,
) -> bool:
    """Only treat a date as empty when the complete fetch summary says so."""
    summary = _fetched_summary_for_date(fetched_data, reconciliation_date)
    counts = [summary.get(key) for key in FETCHED_DATASET_COUNT_KEYS.values()]
    return bool(
        counts
        and all(isinstance(value, int) and not isinstance(value, bool) for value in counts)
        and all(value == 0 for value in counts)
    )


def _pass_through_batch_result(
    workflow: WorkflowSession,
    context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "workspace": str(context.get("workspace", "")),
        "next_files": _canonicalize_file_bindings(_load(workflow.files_json, {})),
        "material_set_id": workflow.material_set_id,
        "material_version": context.get("material_version"),
        "artifacts": [],
    }


def _complete_empty_reconciliation_date(
    db: Session,
    workflow: WorkflowSession,
    context: dict[str, Any],
    *,
    announce: bool = True,
) -> None:
    fetched_data = context.get("fetched_data", {})
    fetched_data = fetched_data if isinstance(fetched_data, dict) else {}
    fetched_data["empty_day_skipped"] = True
    fetched_data["empty_day_skip_reason"] = "取数结果确认无核销记录"
    context["fetched_data"] = fetched_data
    context["current_step"] = "completed"
    context["current_step_label"] = "当天无核销记录，已确认并跳过"
    context.pop("step_error", None)
    context.pop("error_detail", None)
    workflow.context_json = _json(context)
    workflow.stage = "completed"
    workflow.state = "succeeded"
    workflow.progress = 100
    workflow.progress_message = "当天无核销记录，已确认并跳过"
    workflow.error_message = ""
    if announce:
        _message(
            db,
            workflow,
            "assistant",
            f"核销日期 {_date_label(workflow.reconciliation_date)} 取数结果确认无核销记录，"
            "本日已跳过，不执行核销判定和写入。",
            {"kind": "empty_reconciliation_date_skipped"},
        )


def _public_worklist_summary(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        key: int(item)
        for key, item in value.items()
        if key in WORKLIST_SUMMARY_KEYS
        and isinstance(item, int)
        and not isinstance(item, bool)
        and item >= 0
    }


def _public_supplement_history(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value[-20:]:
        if not isinstance(item, dict):
            continue
        public: dict[str, Any] = {}
        for key in ("requested", "found", "added", "existing", "unresolved"):
            groups = item.get(key)
            if isinstance(groups, dict):
                public[key] = {
                    group: [str(identifier) for identifier in identifiers]
                    for group, identifiers in groups.items()
                    if group in {"ar_ids", "so_ids"} and isinstance(identifiers, list)
                }
        if isinstance(item.get("completed_at"), str):
            public["completed_at"] = item["completed_at"]
        result.append(public)
    return result


def _set_progress_step(
    db: Session,
    workflow: WorkflowSession,
    key: str,
    label: str,
    progress: int | None = None,
) -> None:
    # A few low-level synthetic tests use a minimal workflow namespace; the
    # persisted WorkflowSession always has context_json and commit().
    if not hasattr(workflow, "context_json") or not hasattr(db, "commit"):
        return
    # Worker scripts can run for several minutes.  A cancellation request may
    # update the same workflow while a script is running, so every subsequent
    # progress update must reload the authoritative row under the claim lock
    # before merging its own fields into context_json.
    if isinstance(workflow, WorkflowSession) and isinstance(db, Session):
        db.commit()
        acquire_claim_lock(db)
        db.refresh(workflow)
    context = _load(workflow.context_json, {})
    context["current_step"] = key
    context["current_step_label"] = label
    context.pop("step_error", None)
    context.pop("error_detail", None)
    workflow.context_json = _json(context)
    if progress is not None:
        workflow.progress = max(workflow.progress, progress)
    workflow.progress_message = label
    db.commit()


def _entry_file_id(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("file_id"), str):
        return value["file_id"]
    return ""


def _entry_name(value: object) -> str:
    if isinstance(value, dict) and isinstance(value.get("name"), str):
        return value["name"]
    return ""


def _file_role_for_name(name: str, *, strict: bool = False) -> str:
    lowered = name.lower()
    if any(marker in lowered for marker in ("到账", "流转", "receipt", "flow")):
        return RECEIPT_FLOW_ROLE
    if any(marker in lowered for marker in ("盈亏", "利润", "profit", "ledger")):
        return ANNUAL_LEDGER_ROLE
    if strict:
        raise HTTPException(
            status_code=422,
            detail=(
                f"无法从旧文件用途识别表类型：{name or '未命名文件'}；请按新的两类用途重新绑定。"
            ),
        )
    return ANNUAL_LEDGER_ROLE


def _canonicalize_file_bindings(bindings: object) -> dict[str, list[object]]:
    """Map legacy combined bindings to the two stable workflow roles."""
    if not isinstance(bindings, dict):
        return {}
    canonical: dict[str, list[object]] = {}
    for raw_role, raw_entries in bindings.items():
        if not isinstance(raw_role, str):
            continue
        entries = raw_entries if isinstance(raw_entries, list) else [raw_entries]
        if raw_role == LEGACY_FILE_ROLE:
            for entry in entries:
                target = _file_role_for_name(_entry_name(entry))
                canonical.setdefault(target, []).append(entry)
        elif raw_role in FILE_ROLES:
            canonical.setdefault(raw_role, []).extend(entries)
        else:
            canonical.setdefault(raw_role, []).extend(entries)
    return canonical


def _binding_ids(bindings: object) -> dict[str, list[str]]:
    ids: dict[str, list[str]] = {}
    for role, entries in _canonicalize_file_bindings(bindings).items():
        for entry in entries:
            file_id = _entry_file_id(entry)
            if file_id and file_id not in ids.setdefault(role, []):
                ids[role].append(file_id)
    return ids


def _ledger_year_from_entry(entry: object) -> str:
    match = re.search(
        r"(?<!\d)((?:19|20)\d{2})(?:年)?(?!\d)",
        _entry_name(entry),
    )
    return match.group(1) if match else str(_platform_today().year)


def _merge_file_bindings(
    existing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Append annual ledgers and replace the single flow table when supplied."""
    merged = {
        role: list(entries)
        for role, entries in _canonicalize_file_bindings(existing).items()
        if role in FILE_ROLES
    }
    for role, entries in incoming.items():
        if role == ANNUAL_LEDGER_ROLE:
            merged.setdefault(role, [])
            for entry in entries:
                year = _ledger_year_from_entry(entry)
                merged[role] = [
                    current for current in merged[role] if _ledger_year_from_entry(current) != year
                ]
                merged[role].append(entry)
        elif role == RECEIPT_FLOW_ROLE:
            merged[role] = list(entries)
    return merged


def _missing_required_files(skill: RegisteredSkill, files: object) -> list[str]:
    canonical = _canonicalize_file_bindings(files)
    return [
        spec.role
        for spec in skill.manifest.file_inputs
        if spec.required and len(canonical.get(spec.role, [])) < spec.min_files
    ]


def _assert_visible(workflow: WorkflowSession, user: UserContext) -> None:
    assert_owner(workflow.owner_id, user, "对话任务", workflow.department_id)


def get_workflow_or_404(
    db: Session,
    workflow_id: str,
    user: UserContext,
) -> WorkflowSession:
    workflow = db.get(WorkflowSession, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="对话任务不存在。")
    _assert_visible(workflow, user)
    return workflow


def _message(
    db: Session,
    workflow: WorkflowSession,
    role: str,
    content: str,
    data: dict[str, Any] | None = None,
) -> WorkflowMessage:
    item = WorkflowMessage(
        workflow_id=workflow.id,
        role=role,
        content=content,
        data_json=_json(data or {}),
    )
    db.add(item)
    workflow.updated_at = datetime.now(UTC)
    return item


def serialize_workflow(workflow: WorkflowSession) -> WorkflowRead:
    messages = sorted(workflow.messages, key=lambda item: item.id)
    actions = sorted(workflow.actions, key=lambda item: item.queued_at)
    context = _load(workflow.context_json, {})
    fetched_data = context.get("fetched_data", {})
    fetched_data = fetched_data if isinstance(fetched_data, dict) else {}
    fetched_data_source = (
        "snapshot" if fetched_data.get("source") == "snapshot" else "live"
    )
    stored_error_detail = context.get("error_detail", {})
    has_public_error = isinstance(stored_error_detail, dict) and bool(
        stored_error_detail.get("error_type")
    )
    public_error_message = (
        str(context.get("step_error") or workflow.error_message)
        if has_public_error
        else "任务未完成，请查看失败步骤并联系管理员。"
        if workflow.state == "failed" or workflow.stage == "failed"
        else workflow.error_message
    )
    return WorkflowRead(
        id=workflow.id,
        display_id=workflow.display_id or workflow.id,
        owner_id=workflow.owner_id,
        skill_id=workflow.skill_id,
        skill_name=workflow.skill_name,
        skill_version=workflow.skill_version,
        model_provider=workflow.model_provider,
        model_name=workflow.model_name,
        state=workflow.state,
        stage=workflow.stage,
        reconciliation_date=workflow.reconciliation_date,
        batch_id=workflow.batch_id,
        batch_sequence=workflow.batch_sequence,
        material_set_id=workflow.material_set_id,
        material_version=(
            int(context["material_version"])
            if isinstance(context.get("material_version"), int)
            else None
        ),
        material_source_workflow_id=str(context.get("material_source_workflow_id", "")),
        requires_confirmation=bool(context.get("requires_confirmation", True)),
        progress=workflow.progress,
        progress_message=workflow.progress_message,
        error_message=public_error_message,
        current_step=str(context.get("current_step", "")),
        current_step_label=str(context.get("current_step_label", "")),
        step_error=public_error_message if has_public_error else "",
        step_error_detail=(
            context.get("error_detail", {})
            if isinstance(context.get("error_detail", {}), dict)
            else {}
        ),
        fetched_data_available=bool(fetched_data.get("available")),
        fetched_data_source=fetched_data_source,
        fetched_data_summary=_public_fetched_summary(fetched_data.get("summary")),
        fetched_data_review_status=str(fetched_data.get("review_status", "")),
        fetched_data_supplement_history=_public_supplement_history(
            fetched_data.get("supplement_history")
        ),
        result_summary=_public_worklist_summary(context.get("summary")),
        files=_load(workflow.files_json, {}),
        artifacts=_load(workflow.artifacts_json, []),
        messages=[
            {
                "id": item.id,
                "role": item.role,
                "content": item.content,
                "data": _load(item.data_json, {}),
                "created_at": item.created_at,
            }
            for item in messages
        ],
        actions=[
            {
                "id": item.id,
                "name": item.name,
                "state": item.state,
                "error_message": (
                    item.error_message
                    if item.state != "failed"
                    else "该步骤未完成，请查看当前任务提示。"
                ),
                "created_at": item.queued_at,
                "finished_at": item.finished_at,
            }
            for item in actions
        ],
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def _batch_integrated_report_name(reconciliation_dates: list[str]) -> str | None:
    if not reconciliation_dates:
        return None
    start = reconciliation_dates[0].replace("-", "")
    end = reconciliation_dates[-1].replace("-", "")
    first = date.fromisoformat(reconciliation_dates[0])
    last = date.fromisoformat(reconciliation_dates[-1])
    if len(reconciliation_dates) == (last - first).days + 1:
        return f"核销日清_{start}_{end}.xlsx"
    return f"核销日清_已选{len(reconciliation_dates)}日_{start}_{end}.xlsx"


def _batch_final_output_artifacts(
    workflow: WorkflowSession,
    integrated_report_name: str,
) -> list[dict[str, Any]]:
    final_artifacts = _load(workflow.artifacts_json, [])
    final_artifacts = [item for item in final_artifacts if isinstance(item, dict)]
    context = _load(workflow.context_json, {})
    next_files = context.get("next_files", {}) if isinstance(context, dict) else {}
    material_artifacts: list[dict[str, Any]] = []
    if isinstance(next_files, dict):
        for role in (ANNUAL_LEDGER_ROLE, RECEIPT_FLOW_ROLE):
            entries = next_files.get(role, [])
            if isinstance(entries, list):
                material_artifacts.extend(
                    item
                    for item in entries
                    if isinstance(item, dict) and isinstance(item.get("file_id"), str)
                )
    integrated_artifacts = [
        artifact
        for artifact in final_artifacts
        if artifact.get("name") == integrated_report_name
    ]
    selected = material_artifacts + integrated_artifacts if material_artifacts else final_artifacts
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for artifact in selected:
        key = str(artifact.get("file_id") or artifact.get("name") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(artifact)
    return unique


def _fetched_export_directory(
    workflow: WorkflowSession,
    *,
    storage_root: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    context = _load(getattr(workflow, "context_json", "{}"), {})
    fetched_data = context.get("fetched_data", {})
    if not isinstance(fetched_data, dict) or not fetched_data.get("available"):
        raise HTTPException(status_code=409, detail="智云取数尚未完成，暂时没有可查看的数据。")
    raw_workspace = context.get("workspace", "")
    if not isinstance(raw_workspace, str) or not raw_workspace:
        raise HTTPException(status_code=409, detail="当前任务缺少取数工作区，无法查看数据。")
    root = (storage_root or workflow_root(workflow.owner_id, workflow.id)).resolve()
    workspace = Path(raw_workspace).resolve()
    if not workspace.is_dir() or not workspace.is_relative_to(root):
        raise HTTPException(status_code=409, detail="当前任务的取数工作区不可用，无法查看数据。")
    export_dir = workspace / "01_智云导出"
    if not export_dir.is_dir():
        raise HTTPException(status_code=409, detail="智云取数结果不完整，无法查看数据。")
    return export_dir, fetched_data


def _fetched_dataset_path(export_dir: Path, prefix: str, reconciliation_date: str) -> Path:
    tag = reconciliation_date.replace("-", "")
    matches = sorted(export_dir.glob(f"{prefix}_{tag}*.xlsx"), key=lambda item: item.name)
    if not matches:
        raise HTTPException(status_code=409, detail=f"智云取数结果缺少{prefix}数据文件。")
    return matches[-1]


def _fetched_summary_from_export(export_dir: Path, reconciliation_date: str) -> dict[str, Any]:
    tag = reconciliation_date.replace("-", "")
    summary_path = export_dir / f"取数摘要_{tag}.json"
    if not summary_path.is_file():
        return {}
    try:
        return _public_fetched_summary(_load(summary_path.read_text(encoding="utf-8"), {}))
    except OSError:
        return {}


def _snapshot_file_for_prefix(
    export_dir: Path,
    reconciliation_date: str,
    prefix: str,
    summary: dict[str, Any],
    *,
    resolve_path: bool = True,
) -> Path:
    """Resolve one file named by the fetch manifest, never by a client path."""
    tag = reconciliation_date.replace("-", "")
    names = summary.get("files")
    if isinstance(names, list):
        for raw_name in names:
            name = str(raw_name).strip()
            if name.startswith(f"{prefix}_{tag}") and name.lower().endswith(
                (".xlsx", ".xlsm", ".xls")
            ):
                candidate = export_dir / name
                if resolve_path:
                    candidate = candidate.resolve()
                # Listing only accepts direct children from the manifest. The
                # full replay path still resolves the candidate below before
                # copying it into a new task workspace.
                if (
                    Path(name).name == name
                    and candidate.is_relative_to(
                        export_dir if not resolve_path else export_dir.resolve()
                    )
                ):
                    return candidate
    return _fetched_dataset_path(export_dir, prefix, reconciliation_date)


def _snapshot_context_workspace(
    db: Session,
    source_workflow: WorkflowSession,
    *,
    storage_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], Path, Path] | None:
    """Load and boundary-check a snapshot workspace once per source workspace."""
    context = _load(source_workflow.context_json, {})
    context = context if isinstance(context, dict) else {}
    fetched_data = context.get("fetched_data", {})
    if not isinstance(fetched_data, dict) or not fetched_data.get("available"):
        return None
    raw_workspace = context.get("workspace", "")
    if not isinstance(raw_workspace, str) or not raw_workspace:
        return None
    storage_root = storage_root or _workflow_storage_root(db, source_workflow)
    workspace = Path(raw_workspace).resolve()
    if not workspace.is_dir() or not workspace.is_relative_to(storage_root):
        return None
    export_dir = (workspace / FETCH_SNAPSHOT_DIR).resolve()
    if not export_dir.is_dir() or not export_dir.is_relative_to(storage_root):
        return None
    return context, fetched_data, workspace, export_dir


def _validated_snapshot_for_date(
    db: Session,
    source_workflow: WorkflowSession,
    reconciliation_date: str,
    *,
    storage_root: Path | None = None,
    verify_hashes: bool = True,
    workspace_info: tuple[Path, Path] | None = None,
    resolve_file_paths: bool = True,
) -> dict[str, Any] | None:
    """Validate a stored four-file snapshot and return only controlled paths."""
    if workspace_info is None:
        prepared = _snapshot_context_workspace(
            db, source_workflow, storage_root=storage_root
        )
        if prepared is None:
            return None
        context, fetched_data, workspace, export_dir = prepared
    else:
        context = _load(source_workflow.context_json, {})
        context = context if isinstance(context, dict) else {}
        fetched_data = context.get("fetched_data", {})
        if not isinstance(fetched_data, dict) or not fetched_data.get("available"):
            return None
        workspace, export_dir = workspace_info
    tag = reconciliation_date.replace("-", "")
    summary_path = export_dir / f"取数摘要_{tag}.json"
    if summary_path.is_symlink():
        return None
    try:
        summary = _load(summary_path.read_text(encoding="utf-8"), {})
    except OSError:
        return None
    if not isinstance(summary, dict):
        return None
    if (
        summary.get("day") != reconciliation_date
        or summary.get("export_schema_version") != FETCH_SNAPSHOT_VERSION
        or summary.get("read_only") is not True
    ):
        return None
    hashes = summary.get("file_sha256")
    if not isinstance(hashes, dict):
        return None
    paths: list[Path] = []
    for _, _, prefix in FETCHED_DATASET_SPECS:
        try:
            path = _snapshot_file_for_prefix(
                export_dir,
                reconciliation_date,
                prefix,
                summary,
                resolve_path=resolve_file_paths,
            )
        except HTTPException:
            return None
        if (
            not path.is_file()
            or path.is_symlink()
            or not path.is_relative_to(
                export_dir if not resolve_file_paths else export_dir.resolve()
            )
            or not isinstance(hashes.get(path.name), str)
        ):
            return None
        if verify_hashes:
            try:
                if sha256_file(path).casefold() != str(hashes[path.name]).casefold():
                    return None
            except OSError:
                return None
        paths.append(path)
    return {
        "workspace": workspace,
        "export_dir": export_dir,
        "summary_path": summary_path,
        "summary": _public_fetched_summary(summary),
        "paths": paths,
    }


def _snapshot_source_workflow(
    db: Session,
    source_workflow_id: str,
    user: UserContext,
) -> WorkflowSession:
    source_id = str(source_workflow_id or "").strip()
    if not source_id:
        raise HTTPException(status_code=422, detail="取数快照标识不能为空。")
    source = db.get(WorkflowSession, source_id)
    if not source or source.skill_id != "ar-hexiao-daily":
        raise HTTPException(status_code=404, detail="取数快照不存在。")
    # A replay always stays within the requesting user's own snapshot set.
    # This keeps customer and payment data from crossing employee boundaries;
    # administrators can still use an account that owns the snapshot.
    if source.owner_id != user.user_id:
        raise HTTPException(status_code=404, detail="取数快照不存在。")
    assert_snapshot_replay_enabled(source.skill_id)
    return source


def _validated_snapshot_selection(
    db: Session,
    source_workflow_id: str,
    reconciliation_dates: list[str],
    user: UserContext,
) -> tuple[WorkflowSession, dict[str, dict[str, Any]]]:
    source = _snapshot_source_workflow(db, source_workflow_id, user)
    valid: dict[str, dict[str, Any]] = {}
    for item in reconciliation_dates:
        selected = _validated_snapshot_for_date(db, source, item)
        if selected is not None:
            valid[item] = selected
    missing = [item for item in reconciliation_dates if item not in valid]
    if missing:
        raise HTTPException(
            status_code=409,
            detail=f"所选日期没有可用的 v5 取数快照：{'、'.join(missing)}。",
        )
    return source, valid


def list_fetched_snapshot_options(
    db: Session,
    skill_id: str,
    user: UserContext,
) -> list[WorkflowFetchedSnapshotRead]:
    """List valid snapshots without exposing workspaces, customers or amounts."""
    assert_snapshot_replay_enabled(skill_id)
    assert_skill_permission(db, user, skill_id)
    filters = [WorkflowSession.skill_id == skill_id, WorkflowSession.owner_id == user.user_id]
    workflows = db.scalars(
        select(WorkflowSession)
        .where(*filters)
        .order_by(WorkflowSession.updated_at.desc(), WorkflowSession.id.desc())
    ).all()
    preview_rows = db.scalars(
        select(WorkflowFetchedDataPreview)
        .join(WorkflowSession, WorkflowSession.id == WorkflowFetchedDataPreview.workflow_id)
        .where(*filters)
    ).all()
    workflows_by_id = {source.id: source for source in workflows}
    preview_by_source_date = {
        (preview.workflow_id, preview.reconciliation_date): preview
        for preview in preview_rows
    }
    preview_by_source_key_date: dict[tuple[tuple[str, str], str], WorkflowFetchedDataPreview] = {}
    for preview in preview_rows:
        source = workflows_by_id.get(preview.workflow_id)
        if source is None:
            continue
        context = _load(source.context_json, {})
        workspace_hint = str(context.get("workspace", "")) if isinstance(context, dict) else ""
        if not workspace_hint:
            continue
        source_key = (str(getattr(source, "batch_id", "") or source.id), workspace_hint)
        preview_by_source_key_date[(source_key, preview.reconciliation_date)] = preview
    result: list[WorkflowFetchedSnapshotRead] = []
    storage_root_cache: dict[tuple[str, str], Path | None] = {}
    workspace_cache: dict[tuple[str, str], tuple[Path, Path] | None] = {}
    validation_cache: dict[tuple[tuple[str, str], str], dict[str, Any] | None] = {}
    emitted_snapshot_keys: set[tuple[str, tuple[str, ...]]] = set()
    for source in workflows:
        context = _load(source.context_json, {})
        fetched_data = context.get("fetched_data", {}) if isinstance(context, dict) else {}
        # Most historical workflows never produced a replayable snapshot. Skip
        # them before resolving storage roots or probing dates; otherwise the
        # selector pays the filesystem cost for every task in the history.
        if not isinstance(fetched_data, dict) or not fetched_data.get("available"):
            continue
        raw_dates = fetched_data.get("dates", []) if isinstance(fetched_data, dict) else []
        dates = [str(item) for item in raw_dates if isinstance(item, str) and item]
        if not dates and source.reconciliation_date:
            dates = [source.reconciliation_date]
        workspace_hint = str(context.get("workspace", "")) if isinstance(context, dict) else ""
        if not workspace_hint:
            continue
        source_key = (str(getattr(source, "batch_id", "") or source.id), workspace_hint)
        if source_key not in storage_root_cache:
            try:
                storage_root_cache[source_key] = _workflow_storage_root(db, source)
                prepared = _snapshot_context_workspace(
                    db, source, storage_root=storage_root_cache[source_key]
                )
                workspace_cache[source_key] = (
                    (prepared[2], prepared[3]) if prepared is not None else None
                )
            except RuntimeError:
                storage_root_cache[source_key] = None
                workspace_cache[source_key] = None
        if workspace_cache[source_key] is None:
            continue
        summaries: dict[str, dict[str, Any]] = {}
        valid_dates: list[str] = []
        for item in sorted(set(dates)):
            cache_key = (source_key, item)
            if cache_key not in validation_cache:
                preview = preview_by_source_date.get((source.id, item)) or (
                    preview_by_source_key_date.get((source_key, item))
                )
                if preview is not None:
                    # The preview is written only after the four source files
                    # have been found and parsed. Replay still performs the
                    # full manifest and hash validation when the user starts
                    # a task; the selector need not probe the same files again.
                    validation_cache[cache_key] = {
                        "summary": _public_fetched_summary(
                            _load(preview.summary_json, {})
                        )
                    }
                else:
                    # Listing must stay responsive on Windows bind mounts. The
                    # copy path below repeats the full content-hash validation.
                    validation_cache[cache_key] = _validated_snapshot_for_date(
                        db,
                        source,
                        item,
                        storage_root=storage_root_cache[source_key],
                        verify_hashes=False,
                        workspace_info=workspace_cache[source_key],
                        resolve_file_paths=False,
                    )
            validated = validation_cache[cache_key]
            if validated is None:
                continue
            valid_dates.append(item)
            summaries[item] = validated["summary"]
        if not valid_dates:
            continue
        snapshot_key = (workspace_hint, tuple(valid_dates))
        if snapshot_key in emitted_snapshot_keys:
            continue
        emitted_snapshot_keys.add(snapshot_key)
        result.append(
            WorkflowFetchedSnapshotRead(
                source_workflow_id=source.id,
                source_display_id=source.display_id or source.id,
                skill_version=source.skill_version,
                dates=valid_dates,
                summary_by_date=summaries,
                captured_at=source.updated_at or source.created_at,
            )
        )
    return result


def _copy_fetched_snapshot(
    db: Session,
    source_workflow_id: str,
    reconciliation_dates: list[str],
    target_workspace: Path,
    user: UserContext,
) -> dict[str, Any]:
    """Copy a validated snapshot into the new task workspace."""
    source, selected = _validated_snapshot_selection(
        db, source_workflow_id, reconciliation_dates, user
    )
    target_root = target_workspace.resolve()
    export_dir = (target_root / FETCH_SNAPSHOT_DIR).resolve()
    if not export_dir.is_relative_to(target_root):
        raise RuntimeError("目标取数工作区不安全，拒绝复制快照。")
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True, exist_ok=False)
    summaries: dict[str, dict[str, Any]] = {}
    for item in reconciliation_dates:
        validated = selected[item]
        for path in [*validated["paths"], validated["summary_path"]]:
            destination = export_dir / path.name
            shutil.copy2(path, destination)
        summaries[item] = validated["summary"]
    # A later worker invocation validates the source again.  The target only
    # records an opaque source id and public counts, never the original path.
    return {
        "source_workflow_id": source.id,
        "summary_by_date": summaries,
    }


def _preview_cell(value: object) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _preview_headers(values: tuple[object, ...]) -> tuple[list[str], list[int]]:
    headers: list[str] = []
    visible_indexes: list[int] = []
    for index, value in enumerate(values):
        label = str(value).strip() if value is not None else ""
        if label.casefold() in {"rowid", "_rowid", "__rowid"}:
            continue
        headers.append(label or f"列{index + 1}")
        visible_indexes.append(index)
    return headers, visible_indexes


def _preview_workbook_page(
    path: Path,
    offset: int,
    limit: int,
) -> tuple[list[str], list[list[Any]], int]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        raw_headers = next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
        headers, visible_indexes = _preview_headers(raw_headers)
        if not headers:
            raise HTTPException(status_code=409, detail=f"{path.name} 没有可展示的业务字段。")
        rows: list[list[Any]] = []
        total = 0
        for raw_row in worksheet.iter_rows(min_row=2, values_only=True):
            if not any(value not in (None, "") for value in raw_row):
                continue
            if offset <= total < offset + limit:
                rows.append(
                    [
                        _preview_cell(raw_row[index] if index < len(raw_row) else None)
                        for index in visible_indexes
                    ]
                )
            total += 1
        return headers, rows, total
    finally:
        workbook.close()


def _preview_workbook_records(path: Path) -> list[dict[str, Any]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        raw_headers = next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
        headers, visible_indexes = _preview_headers(raw_headers)
        records: list[dict[str, Any]] = []
        for raw_row in worksheet.iter_rows(min_row=2, values_only=True):
            if not any(value not in (None, "") for value in raw_row):
                continue
            records.append(
                {
                    header: _preview_cell(raw_row[index] if index < len(raw_row) else None)
                    for header, index in zip(headers, visible_indexes, strict=True)
                }
            )
        return records
    finally:
        workbook.close()


def _record_identifier(record: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _record_number(record: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, bool) or value in (None, ""):
            continue
        if isinstance(value, int | float):
            return float(value)
        try:
            return float(str(value).replace(",", "").strip())
        except ValueError:
            continue
    return None


def _record_flag(record: dict[str, Any], *keys: str) -> bool:
    value = _record_identifier(record, *keys).casefold()
    return value in {"1", "true", "yes", "是", "已撤销"}


def _fetched_ar_groups(
    export_dir: Path,
    reconciliation_date: str,
) -> list[WorkflowFetchedDataArGroup]:
    records = {
        key: _preview_workbook_records(
            _fetched_dataset_path(export_dir, prefix, reconciliation_date)
        )
        for key, _, prefix in FETCHED_DATASET_SPECS
    }
    groups: dict[str, dict[str, Any]] = {}

    def ensure_group(ar_id: str) -> dict[str, Any]:
        key = ar_id or "未识别 AR"
        return groups.setdefault(key, {"ar_id": key, "payments": [], "orders": {}})

    def ensure_order(ar_id: str, so_id: str) -> dict[str, Any]:
        group = ensure_group(ar_id)
        key = so_id or "未识别 SO"
        return group["orders"].setdefault(
            key,
            {
                "so_id": key,
                "deliveries": [],
                "writeoffs": [],
                "order_details": [],
            },
        )

    for payment in records["payments"]:
        ar_id = _record_identifier(payment, "回款记录ID", "回款记录NUM", "回款ID")
        ensure_group(ar_id)["payments"].append(
            WorkflowFetchedPayment(
                ar_id=ar_id or "未识别 AR",
                reconciliation_date=_record_identifier(payment, "核销日期"),
                arrival_date=_record_identifier(payment, "到账日期"),
                amount_original=_record_number(payment, "到账金额/原币", "到账金额"),
                amount_local=_record_number(payment, "到账金额/本币"),
                total_amount_original=_record_number(
                    payment, "总到账金额/原币", "总到账金额原币", "总到账金额"
                ),
                total_amount_local=_record_number(
                    payment, "总到账金额/本币", "总到账金额本币"
                ),
                fee_original=_record_number(payment, "手续费/原币"),
                tax_original=_record_number(payment, "税费/原币", "税费原币", "税费"),
                tax_local=_record_number(payment, "税费/本币", "税费本币"),
                currency=_record_identifier(payment, "原币币种", "币种"),
                payment_type=_record_identifier(payment, "回款类型"),
                writeoff_status=_record_identifier(payment, "核销状态"),
                customer=_record_identifier(payment, "开票客户", "客户名称"),
                salesperson=_record_identifier(payment, "销售名称"),
                historical_parent_only=_record_flag(payment, "仅历史累计父记录"),
            )
        )

    for delivery in records["orders"]:
        ar_id = _record_identifier(delivery, "回款记录ID", "回款记录NUM", "回款ID")
        so_id = _record_identifier(delivery, "SO", "订单号", "新智云单号")
        ensure_order(ar_id, so_id)["deliveries"].append(
            WorkflowFetchedDelivery(
                ar_id=ar_id or "未识别 AR",
                so_id=so_id or "未识别 SO",
                written_off_original=_record_number(delivery, "订单已核销金额"),
                written_off_local=_record_number(delivery, "订单已核销金额/本币"),
                delivery_amount_original=_record_number(delivery, "交付额/原币"),
                exchange_rate=_record_number(delivery, "汇率"),
                currency=_record_identifier(delivery, "结算币种", "币种"),
                order_name=_record_identifier(delivery, "订单名称"),
                delivery_date=_record_identifier(delivery, "项目交付日期"),
                delivery_date_status=_record_identifier(delivery, "交付日期取数状态"),
                source=_record_identifier(delivery, "单号来源"),
            )
        )

    for writeoff in records["writeoffs"]:
        ar_id = _record_identifier(writeoff, "回款记录NUM", "回款记录ID", "回款ID")
        so_id = _record_identifier(writeoff, "SO", "订单号", "新智云单号")
        ensure_order(ar_id, so_id)["writeoffs"].append(
            WorkflowFetchedWriteoff(
                writeoff_id=_record_identifier(writeoff, "核销记录NUM"),
                ar_id=ar_id or "未识别 AR",
                so_id=so_id or "未识别 SO",
                reconciliation_date=_record_identifier(writeoff, "核销日期"),
                amount_original=_record_number(writeoff, "本次核销金额"),
                amount_local=_record_number(writeoff, "本次核销金额/本币", "本次核销金额本币"),
                currency=_record_identifier(writeoff, "币种"),
                exchange_rate=_record_number(writeoff, "汇率"),
                order_name=_record_identifier(writeoff, "订单名称"),
                revoked=_record_flag(writeoff, "是否已撤销"),
            )
        )

    details_by_so: dict[str, list[WorkflowFetchedOrderDetail]] = {}
    for detail in records["order_details"]:
        so_id = _record_identifier(detail, "SO", "订单号", "新智云单号")
        details_by_so.setdefault(so_id or "未识别 SO", []).append(
            WorkflowFetchedOrderDetail(
                so_id=so_id or "未识别 SO",
                sod_id=_record_identifier(detail, "SOD"),
                delivery_amount_original=_record_number(detail, "交付额/原币"),
                currency=_record_identifier(detail, "币种"),
                project_status=_record_identifier(detail, "项目状态"),
            )
        )

    result: list[WorkflowFetchedDataArGroup] = []
    for raw_group in groups.values():
        group_issues: list[str] = []
        orders: list[WorkflowFetchedDataOrderGroup] = []
        for raw_order in raw_group["orders"].values():
            raw_order["order_details"] = details_by_so.get(raw_order["so_id"], [])
            issues: list[str] = []
            if not raw_order["deliveries"]:
                issues.append("未找到订单交付")
            elif not any(delivery.delivery_date for delivery in raw_order["deliveries"]):
                issues.append("缺少项目交付日期")
            if not raw_order["order_details"]:
                issues.append("未找到 SOD")
            raw_order["issues"] = issues
            orders.append(WorkflowFetchedDataOrderGroup(**raw_order))
            group_issues.extend(f"{raw_order['so_id']}：{issue}" for issue in issues)
        if not orders:
            group_issues.append("未找到关联 SO")
        result.append(
            WorkflowFetchedDataArGroup(
                ar_id=raw_group["ar_id"],
                payments=raw_group["payments"],
                orders=orders,
                issues=group_issues,
            )
        )
    return result


def _ar_group_matches_query(group: WorkflowFetchedDataArGroup, query: str) -> bool:
    return query in fetched_data_group_search_text(group)


def _fetched_data_preview_revision(
    workflow: WorkflowSession,
    fetched_data: dict[str, Any],
    reconciliation_date: str,
    source_paths: list[Path],
    *,
    refresh: bool = False,
) -> str:
    revisions = fetched_data.get("preview_revisions", {})
    revisions = revisions if isinstance(revisions, dict) else {}
    stored = revisions.get(reconciliation_date)
    if not refresh and isinstance(stored, str) and len(stored) == 64:
        return stored

    revision = fetched_data_revision(source_paths)
    revisions[reconciliation_date] = revision
    fetched_data["preview_revisions"] = revisions
    context = _load(workflow.context_json, {})
    context = context if isinstance(context, dict) else {}
    context["fetched_data"] = fetched_data
    workflow.context_json = _json(context)
    return revision


def read_workflow_fetched_data(
    workflow: WorkflowSession,
    dataset: str,
    offset: int = 0,
    limit: int = 100,
    reconciliation_date: str | None = None,
    query: str = "",
    issues_only: bool = False,
    storage_root: Path | None = None,
    db: Session | None = None,
) -> WorkflowFetchedDataRead:
    """Read only the task's completed Zhiyun exports, with bounded pagination."""
    if offset < 0 or limit < 1 or limit > FETCHED_PREVIEW_MAX_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=(
                f"分页参数无效：offset 不能小于 0，limit 取值为 1 至 {FETCHED_PREVIEW_MAX_LIMIT}。"
            ),
        )
    specification = FETCHED_DATASET_BY_KEY.get(dataset)
    if dataset == "ar_groups":
        if db is not None:
            db.execute(
                select(WorkflowSession.id)
                .where(WorkflowSession.id == workflow.id)
                .with_for_update()
            ).scalar_one()
            db.refresh(workflow)
        selected_date = reconciliation_date or workflow.reconciliation_date
        if db is not None and workflow.state in TERMINAL_WORKFLOW_STATES:
            persisted_page = load_persisted_fetched_data_preview_page(
                db,
                workflow_id=workflow.id,
                reconciliation_date=selected_date,
                offset=offset,
                limit=limit,
                query=query,
                issues_only=issues_only,
            )
            if persisted_page is not None:
                return WorkflowFetchedDataRead(
                    reconciliation_date=selected_date,
                    dataset=dataset,
                    dataset_label="按 AR 分组",
                    headers=[],
                    rows=[],
                    total=persisted_page.total,
                    offset=offset,
                    limit=limit,
                    datasets=[],
                    summary=persisted_page.summary,
                    ar_groups=persisted_page.groups,
                )
        export_dir, fetched_data = _fetched_export_directory(workflow, storage_root=storage_root)
        summary = _public_fetched_summary(
            (fetched_data.get("summary_by_date") or {}).get(selected_date)
            if isinstance(fetched_data.get("summary_by_date"), dict)
            else fetched_data.get("summary")
        ) or _fetched_summary_from_export(export_dir, selected_date)
        if db is not None:
            source_paths = [
                _fetched_dataset_path(export_dir, prefix, selected_date)
                for _, _, prefix in FETCHED_DATASET_SPECS
            ]
            revision = _fetched_data_preview_revision(
                workflow, fetched_data, selected_date, source_paths
            )
            preview_page = load_fetched_data_preview_page(
                db,
                workflow_id=workflow.id,
                reconciliation_date=selected_date,
                revision=revision,
                summary=summary,
                offset=offset,
                limit=limit,
                query=query,
                issues_only=issues_only,
                build_groups=lambda: _fetched_ar_groups(export_dir, selected_date),
            )
            return WorkflowFetchedDataRead(
                reconciliation_date=selected_date,
                dataset=dataset,
                dataset_label="按 AR 分组",
                headers=[],
                rows=[],
                total=preview_page.total,
                offset=offset,
                limit=limit,
                datasets=[],
                summary=preview_page.summary,
                ar_groups=preview_page.groups,
            )
        ar_groups = _fetched_ar_groups(export_dir, selected_date)
        ar_amount_summary = current_ar_amounts_by_currency(ar_groups)
        writeoff_amount_summary = current_writeoff_amounts_by_currency(ar_groups, selected_date)
        normalized_query = query.strip()[:100].casefold()
        if normalized_query:
            ar_groups = [
                group for group in ar_groups if _ar_group_matches_query(group, normalized_query)
            ]
        if issues_only:
            ar_groups = [group for group in ar_groups if group.issues]
        return WorkflowFetchedDataRead(
            reconciliation_date=selected_date,
            dataset=dataset,
            dataset_label="按 AR 分组",
            headers=[],
            rows=[],
            total=len(ar_groups),
            offset=offset,
            limit=limit,
            datasets=[],
            summary={
                **summary,
                CURRENT_AR_AMOUNT_SUMMARY_KEY: ar_amount_summary,
                CURRENT_WRITEOFF_AMOUNT_SUMMARY_KEY: writeoff_amount_summary,
            },
            ar_groups=ar_groups[offset : offset + limit],
        )
    if not specification:
        raise HTTPException(status_code=422, detail="未知的智云数据类型。")
    export_dir, fetched_data = _fetched_export_directory(workflow, storage_root=storage_root)
    selected_date = reconciliation_date or workflow.reconciliation_date
    summary = _public_fetched_summary(
        (fetched_data.get("summary_by_date") or {}).get(selected_date)
        if isinstance(fetched_data.get("summary_by_date"), dict)
        else fetched_data.get("summary")
    ) or _fetched_summary_from_export(export_dir, selected_date)
    label, prefix = specification
    selected_path = _fetched_dataset_path(export_dir, prefix, selected_date)
    headers, rows, total = _preview_workbook_page(selected_path, offset, limit)
    datasets = []
    for key, item_label, item_prefix in FETCHED_DATASET_SPECS:
        summary_total = summary.get(FETCHED_DATASET_COUNT_KEYS[key])
        if key == dataset:
            item_total = total
        elif (
            isinstance(summary_total, int)
            and not isinstance(summary_total, bool)
            and summary_total >= 0
        ):
            item_total = summary_total
        else:
            path = _fetched_dataset_path(export_dir, item_prefix, selected_date)
            _, _, item_total = _preview_workbook_page(path, 0, 1)
        datasets.append(WorkflowFetchedDataSet(key=key, label=item_label, total=item_total))
    return WorkflowFetchedDataRead(
        reconciliation_date=selected_date,
        dataset=dataset,
        dataset_label=label,
        headers=headers,
        rows=rows,
        total=total,
        offset=offset,
        limit=limit,
        datasets=datasets,
        summary=summary,
    )


def confirm_fetched_data_review(
    db: Session,
    workflow: WorkflowSession,
    actor: UserContext,
) -> WorkflowSession:
    if workflow.stage != "awaiting_fetched_data_confirmation":
        raise HTTPException(status_code=409, detail="当前任务不在取数检查阶段。")
    context = _load(workflow.context_json, {})
    fetched_data = context.get("fetched_data", {})
    if not isinstance(fetched_data, dict) or not fetched_data.get("available"):
        raise HTTPException(status_code=409, detail="智云取数尚未完成，不能确认继续。")
    fetched_data["review_status"] = "confirmed"
    fetched_data["reviewed_by"] = actor.user_id
    fetched_data["reviewed_at"] = datetime.now(UTC).isoformat()
    context["fetched_data"] = fetched_data
    if _is_confirmed_empty_reconciliation_date(fetched_data, workflow.reconciliation_date):
        _complete_empty_reconciliation_date(db, workflow, context)
        if workflow.batch_id:
            _advance_batch(db, workflow, _pass_through_batch_result(workflow, context))
        sync_reminder_from_workflow(db, workflow)
        db.commit()
        db.refresh(workflow)
        return workflow
    context["current_step"] = "inspect_inputs"
    context["current_step_label"] = "取数数据已确认，等待检查输入文件"
    workflow.context_json = _json(context)
    _queue_action(db, workflow, "prepare_worklist")
    workflow.stage = "preparing"
    workflow.state = "running"
    workflow.progress = 20
    workflow.progress_message = "取数数据已确认，等待继续生成核销日清"
    workflow.error_message = ""
    _message(
        db,
        workflow,
        "assistant",
        "工作人员已确认本次智云取数完整，后台将继续检查输入文件并生成核销日清。",
        {"kind": "fetched_data_review_confirmed"},
    )
    db.commit()
    db.refresh(workflow)
    return workflow


def _normalized_business_ids(values: list[str], pattern: re.Pattern[str], label: str) -> list[str]:
    normalized = sorted({str(value).strip().upper() for value in values if str(value).strip()})
    invalid = [value for value in normalized if not pattern.fullmatch(value)]
    if invalid:
        raise HTTPException(status_code=422, detail=f"{label}格式无效：{', '.join(invalid[:5])}")
    return normalized


def supplement_audit_summary(value: object) -> dict[str, Any]:
    """Return identifier counts for audit logs without storing business identifiers."""
    if not isinstance(value, dict):
        return {"ar_count": 0, "so_count": 0}
    return {
        "ar_count": len(value.get("ar_ids", [])) if isinstance(value.get("ar_ids"), list) else 0,
        "so_count": len(value.get("so_ids", [])) if isinstance(value.get("so_ids"), list) else 0,
    }


def supplement_result_audit_summary(value: object) -> dict[str, Any]:
    """Reduce each supplement result group to counts before audit persistence."""
    if not isinstance(value, dict):
        return {}
    summary: dict[str, Any] = {}
    for key in ("found", "added", "existing", "unresolved"):
        groups = value.get(key)
        if not isinstance(groups, dict):
            continue
        summary[key] = supplement_audit_summary(groups)
    return summary


def request_fetched_data_supplement(
    db: Session,
    workflow: WorkflowSession,
    ar_ids: list[str],
    so_ids: list[str],
    reconciliation_date: str | None = None,
) -> tuple[WorkflowSession, dict[str, Any]]:
    if workflow.stage != "awaiting_fetched_data_confirmation":
        raise HTTPException(status_code=409, detail="当前任务不在取数检查阶段。")
    checked_ar_ids = _normalized_business_ids(ar_ids, AR_ID_PATTERN, "AR 编号")
    checked_so_ids = _normalized_business_ids(so_ids, SO_ID_PATTERN, "SO 编号")
    if not checked_ar_ids and not checked_so_ids:
        raise HTTPException(status_code=422, detail="请至少填写一个缺失的 AR 或 SO 编号。")
    context = _load(workflow.context_json, {})
    fetched_data = context.get("fetched_data", {})
    if not isinstance(fetched_data, dict) or not fetched_data.get("available"):
        raise HTTPException(status_code=409, detail="智云取数尚未完成，不能补取。")
    if fetched_data.get("source") == "snapshot":
        raise HTTPException(status_code=409, detail="本地取数快照不能补取智云数据。")
    fetched_data["review_status"] = "supplementing"
    context["fetched_data"] = fetched_data
    context["current_step"] = "fetch_zhiyun"
    context["current_step_label"] = "正在按工作人员提供的 SO/AR 编号补取数据"
    workflow.context_json = _json(context)
    supplement: dict[str, Any] = {"ar_ids": checked_ar_ids, "so_ids": checked_so_ids}
    if reconciliation_date:
        supplement["reconciliation_date"] = reconciliation_date
    _queue_action(db, workflow, "supplement_fetched_data", {"supplement": supplement})
    workflow.stage = "supplementing_fetched_data"
    workflow.state = "running"
    workflow.progress = 15
    workflow.progress_message = "正在按 SO/AR 编号补取智云数据"
    workflow.error_message = ""
    _message(
        db,
        workflow,
        "assistant",
        "已收到缺失编号，正在按编号补取智云数据；完成后仍会暂停等待再次检查。",
        {"kind": "fetched_data_supplement_requested", **supplement},
    )
    db.commit()
    db.refresh(workflow)
    return workflow, supplement


def serialize_workflow_batch(
    batch: WorkflowBatch,
    *,
    retry_authorized: bool,
) -> WorkflowBatchRead:
    workflows = sorted(batch.workflows, key=lambda item: item.batch_sequence)
    fetched_context = (
        _load(_batch_fetched_data_workflow(batch).context_json, {}) if workflows else {}
    )
    fetched_data = fetched_context.get("fetched_data", {})
    fetched_data = fetched_data if isinstance(fetched_data, dict) else {}
    fetched_data_source = (
        "snapshot" if fetched_data.get("source") == "snapshot" else "live"
    )
    progress = (
        int(sum(item.progress for item in workflows) / len(workflows))
        if workflows
        else batch.progress
    )
    if batch.state == "finalizing":
        progress = batch.progress
    active = next((item for item in workflows if item.state == "running"), None)
    progress_message = batch.progress_message
    if active:
        active_progress_message = (
            f"第 {active.batch_sequence}/{len(workflows)} 天 · {active.progress_message}"
        )
        progress_message = (
            f"{batch.progress_message}；{active_progress_message}"
            if batch.progress_message.startswith("已排除已成功日期：")
            else active_progress_message
        )
    failed_workflow = next((item for item in workflows if item.state == "failed"), None)
    failed_action = (
        max(failed_workflow.actions, key=lambda item: item.queued_at, default=None)
        if failed_workflow
        else None
    )
    last_workflow = workflows[-1] if workflows else None
    failed_finalizer = (
        next(
            (
                item
                for item in reversed(
                    sorted(last_workflow.actions, key=lambda action: action.queued_at)
                )
                if item.name == "finalize_batch" and item.state == "failed"
            ),
            None,
        )
        if last_workflow
        else None
    )
    material_version_conflict = any(
        bool((_load(item.context_json, {}) or {}).get("material_version_conflict"))
        for item in workflows
    )
    retryable = bool(
        batch.state == "failed"
        and not material_version_conflict
        and (
            (failed_action and failed_action.name == "prepare_worklist")
            or failed_finalizer is not None
        )
    )
    retry_message = (
        "可从失败日期继续，之前成功的日期不会重复执行。"
        if retryable and failed_action and failed_action.name == "prepare_worklist"
        else "可重新生成范围报告。"
        if retryable
        else "当前失败发生在写入或校验阶段，不能自动重试；请联系平台管理员确认后续处理。"
        if batch.state == "failed"
        else ""
    )
    can_retry = retryable and retry_authorized
    retry_block_reason = (
        batch.error_message
        if material_version_conflict
        else "当前账号没有使用该财务工具的权限，请联系平台管理员。"
        if retryable and not retry_authorized
        else retry_message
        if batch.state == "failed" and not retryable
        else ""
    )
    batch_error_message = batch.error_message
    if batch.state == "failed" and failed_workflow and not material_version_conflict:
        child_context = _load(failed_workflow.context_json, {})
        child_detail = child_context.get("error_detail", {})
        if not isinstance(child_detail, dict) or not child_detail.get("error_type"):
            batch_error_message = "批次在某个日期未完成，请查看失败日期并联系管理员。"
    serialized_workflows = [serialize_workflow(item) for item in workflows]
    integrated_report_name = _batch_integrated_report_name(
        _load(batch.reconciliation_dates_json, [])
    )
    if integrated_report_name:
        for item in serialized_workflows:
            item.artifacts = []
        if serialized_workflows:
            serialized_workflows[-1].artifacts = _batch_final_output_artifacts(
                workflows[-1], integrated_report_name
            )
    return WorkflowBatchRead(
        id=batch.id,
        display_id=batch.display_id or batch.id,
        owner_id=batch.owner_id,
        skill_id=batch.skill_id,
        skill_name=batch.skill_name,
        skill_version=batch.skill_version,
        model_provider=batch.model_provider,
        model_name=batch.model_name,
        reconciliation_dates=_load(batch.reconciliation_dates_json, []),
        state=batch.state,
        progress=progress,
        progress_message=progress_message,
        error_message=batch_error_message,
        retryable=retryable,
        can_retry=can_retry,
        retry_message=retry_message,
        retry_block_reason=retry_block_reason,
        fetched_data_available=bool(fetched_data.get("available")),
        fetched_data_source=fetched_data_source,
        fetched_data_review_status=str(fetched_data.get("review_status") or ""),
        fetched_data_summary_by_date=(
            {
                str(item_date): _public_fetched_summary(item_summary)
                for item_date, item_summary in fetched_data.get("summary_by_date", {}).items()
            }
            if isinstance(fetched_data.get("summary_by_date"), dict)
            else {}
        ),
        fetched_data_supplement_history=_public_supplement_history(
            fetched_data.get("supplement_history")
        ),
        workflows=serialized_workflows,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


def _batch_primary_workflow(batch: WorkflowBatch) -> WorkflowSession:
    workflows = sorted(batch.workflows, key=lambda item: item.batch_sequence)
    if not workflows:
        raise RuntimeError("核销批次没有日期任务。")
    return workflows[0]


def _batch_fetched_data_workflow(batch: WorkflowBatch) -> WorkflowSession:
    """Use the surviving workflow that owns the current shared fetch snapshot."""
    workflows = sorted(batch.workflows, key=lambda item: item.batch_sequence)
    for workflow in workflows:
        context = _load(workflow.context_json, {})
        fetched_data = context.get("fetched_data", {})
        if isinstance(fetched_data, dict) and fetched_data.get("available"):
            return workflow
    return _batch_primary_workflow(batch)


def _workflow_storage_root(db: Session, workflow: WorkflowSession) -> Path:
    batch_id = str(getattr(workflow, "batch_id", "") or "")
    if batch_id:
        batch = db.get(WorkflowBatch, batch_id)
        if not batch:
            raise RuntimeError("所属核销批次不存在。")
        primary = _batch_primary_workflow(batch)
        return workflow_root(primary.owner_id, primary.id).resolve()
    return workflow_root(workflow.owner_id, workflow.id).resolve()


def _ensure_workflow_skill_snapshot(db: Session, workflow: WorkflowSession) -> Path:
    """Materialize a batch child's immutable Skill copy when its action starts."""
    root = workflow_root(workflow.owner_id, workflow.id).resolve()
    destination = root / "skill"
    if destination.is_dir():
        return destination

    batch_id = str(getattr(workflow, "batch_id", "") or "")
    batch = db.get(WorkflowBatch, batch_id) if batch_id else None
    if batch is None:
        raise RuntimeError("工作流 Skill 快照已经缺失。")
    primary = _batch_primary_workflow(batch)
    source = workflow_root(primary.owner_id, primary.id).resolve() / "skill"
    if not source.is_dir():
        raise RuntimeError("批次首日的 Skill 快照已经缺失。")

    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".skill-snapshot-{uuid.uuid4().hex}"
    try:
        shutil.copytree(source, staging)
        if destination.exists():
            if not destination.is_dir():
                raise RuntimeError("工作流 Skill 快照目录无效。")
            shutil.rmtree(staging, ignore_errors=True)
        else:
            os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def _prime_fetched_data_previews(
    db: Session,
    workflow: WorkflowSession,
    reconciliation_dates: list[str],
) -> None:
    """Build read-only AR previews while the Worker still owns the fetch action."""
    storage_root = _workflow_storage_root(db, workflow)
    try:
        export_dir, fetched_data = _fetched_export_directory(
            workflow, storage_root=storage_root
        )
        sources_by_date = {
            reconciliation_date: [
                _fetched_dataset_path(export_dir, prefix, reconciliation_date)
                for _, _, prefix in FETCHED_DATASET_SPECS
            ]
            for reconciliation_date in reconciliation_dates
        }
        if not all(
            path.is_file() for paths in sources_by_date.values() for path in paths
        ):
            return
    except HTTPException:
        # Legacy and test snapshots may not contain the four review workbooks.
        # The read endpoint keeps its on-demand fallback for those snapshots.
        return

    revisions = {
        reconciliation_date: _fetched_data_preview_revision(
            workflow,
            fetched_data,
            reconciliation_date,
            sources_by_date[reconciliation_date],
            refresh=True,
        )
        for reconciliation_date in reconciliation_dates
    }
    for reconciliation_date in reconciliation_dates:
        summary = _public_fetched_summary(
            (fetched_data.get("summary_by_date") or {}).get(reconciliation_date)
            if isinstance(fetched_data.get("summary_by_date"), dict)
            else fetched_data.get("summary")
        ) or _fetched_summary_from_export(export_dir, reconciliation_date)
        ensure_fetched_data_preview(
            db,
            workflow_id=workflow.id,
            reconciliation_date=reconciliation_date,
            revision=revisions[reconciliation_date],
            summary=summary,
            build_groups=lambda selected_date=reconciliation_date: _fetched_ar_groups(
                export_dir, selected_date
            ),
        )


def _discard_workspace_fetched_snapshot(storage_root: Path, workspace: Path) -> None:
    """Delete only the task-local Zhiyun snapshot inside a controlled workspace."""
    controlled_root = storage_root.resolve()
    controlled_workspace = workspace.resolve()
    if not controlled_workspace.is_relative_to(controlled_root):
        raise RuntimeError("任务工作区不在平台受控目录中，拒绝清理取数快照。")
    snapshot = (controlled_workspace / FETCH_SNAPSHOT_DIR).resolve()
    if not snapshot.is_relative_to(controlled_root):
        raise RuntimeError("取数快照不在平台受控目录中，拒绝清理。")
    if snapshot.is_dir():
        shutil.rmtree(snapshot)
    elif snapshot.exists():
        snapshot.unlink()


def _mark_fetched_snapshot_deleted(workflow: WorkflowSession) -> None:
    context = _load(workflow.context_json, {})
    context = context if isinstance(context, dict) else {}
    fetched_data = context.get("fetched_data", {})
    if not isinstance(fetched_data, dict) or not fetched_data:
        return
    retained = {
        key: fetched_data[key]
        for key in ("reconciliation_date", "date_from", "date_to", "dates")
        if key in fetched_data
    }
    retained.update(
        {
            "available": False,
            "review_status": "deleted",
            "deleted_at": datetime.now(UTC).isoformat(),
        }
    )
    context["fetched_data"] = retained
    context.pop("awaiting_fetched_data_confirmation", None)
    workflow.context_json = _json(context)


def _mark_fetched_snapshot_retained(workflow: WorkflowSession) -> None:
    context = _load(workflow.context_json, {})
    context = context if isinstance(context, dict) else {}
    fetched_data = context.get("fetched_data", {})
    if not isinstance(fetched_data, dict) or not fetched_data:
        return
    fetched_data["available"] = True
    fetched_data["review_status"] = "confirmed"
    fetched_data.pop("deleted_at", None)
    context["fetched_data"] = fetched_data
    context.pop("awaiting_fetched_data_confirmation", None)
    workflow.context_json = _json(context)


def _cleanup_terminal_fetched_snapshot(db: Session, workflow: WorkflowSession) -> None:
    """Remove raw fetch files while retaining completed previews for review."""
    if workflow.skill_id != "ar-hexiao-daily":
        return
    storage_root = _workflow_storage_root(db, workflow)
    batch = db.get(WorkflowBatch, workflow.batch_id) if workflow.batch_id else None
    if batch is not None:
        if batch.state not in TERMINAL_WORKFLOW_STATES:
            return
        members = list(batch.workflows)
        workspace = (storage_root / "batch" / str(batch.id) / "工作区").resolve()
    else:
        if workflow.state not in TERMINAL_WORKFLOW_STATES:
            return
        members = [workflow]
        context = _load(workflow.context_json, {})
        context = context if isinstance(context, dict) else {}
        raw_workspace = context.get("workspace", "")
        workspace = (
            Path(raw_workspace).resolve()
            if isinstance(raw_workspace, str) and raw_workspace
            else None
        )

    if workspace is not None and workspace.is_relative_to(storage_root):
        _discard_workspace_fetched_snapshot(storage_root, workspace)
    workflow_ids = [member.id for member in members]
    preview_ids = list(
        db.scalars(
            select(WorkflowFetchedDataPreview.id).where(
                WorkflowFetchedDataPreview.workflow_id.in_(workflow_ids)
            )
        )
    )
    preserve_completed_preview = bool(preview_ids) and (
        (batch is not None and batch.state == "succeeded")
        or (batch is None and workflow.state == "succeeded")
    )
    if preview_ids and not preserve_completed_preview:
        db.execute(
            delete(WorkflowFetchedDataPreviewArGroup).where(
                WorkflowFetchedDataPreviewArGroup.preview_id.in_(preview_ids)
            )
        )
        db.execute(
            delete(WorkflowFetchedDataPreview).where(WorkflowFetchedDataPreview.id.in_(preview_ids))
        )
    for member in members:
        if preserve_completed_preview:
            _mark_fetched_snapshot_retained(member)
        else:
            _mark_fetched_snapshot_deleted(member)


def read_batch_fetched_data(
    batch: WorkflowBatch,
    reconciliation_date: str,
    dataset: str,
    offset: int = 0,
    limit: int = 100,
    query: str = "",
    issues_only: bool = False,
    db: Session | None = None,
) -> WorkflowFetchedDataRead:
    dates = _load(batch.reconciliation_dates_json, [])
    if reconciliation_date not in dates:
        raise HTTPException(status_code=422, detail="核销日期不属于当前批次。")
    primary = _batch_primary_workflow(batch)
    return read_workflow_fetched_data(
        _batch_fetched_data_workflow(batch),
        dataset,
        offset,
        limit,
        reconciliation_date=reconciliation_date,
        query=query,
        issues_only=issues_only,
        storage_root=workflow_root(primary.owner_id, primary.id).resolve(),
        db=db,
    )


def confirm_batch_fetched_data_review(
    db: Session,
    batch: WorkflowBatch,
    actor: UserContext,
) -> WorkflowBatch:
    _reject_superseded_batch_material(db, batch)
    confirm_fetched_data_review(db, _batch_fetched_data_workflow(batch), actor)
    db.refresh(batch)
    return batch


def request_batch_fetched_data_supplement(
    db: Session,
    batch: WorkflowBatch,
    reconciliation_date: str,
    ar_ids: list[str],
    so_ids: list[str],
) -> tuple[WorkflowBatch, dict[str, Any]]:
    _reject_superseded_batch_material(db, batch)
    dates = _load(batch.reconciliation_dates_json, [])
    if reconciliation_date not in dates:
        raise HTTPException(status_code=422, detail="核销日期不属于当前批次。")
    workflow, supplement = request_fetched_data_supplement(
        db,
        _batch_fetched_data_workflow(batch),
        ar_ids,
        so_ids,
        reconciliation_date=reconciliation_date,
    )
    db.refresh(batch)
    return batch, supplement


def _assert_batch_visible(batch: WorkflowBatch, user: UserContext) -> None:
    assert_owner(batch.owner_id, user, "批次任务", batch.department_id)


def get_workflow_batch_or_404(
    db: Session,
    batch_id: str,
    user: UserContext,
) -> WorkflowBatch:
    batch = db.get(WorkflowBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="核销批次不存在。")
    _assert_batch_visible(batch, user)
    return batch


def _snapshot_skill(skill: RegisteredSkill, owner_id: str, workflow_id: str) -> Path:
    root = workflow_root(owner_id, workflow_id)
    destination = root / "skill"
    root.mkdir(parents=True, exist_ok=False)
    for path in skill.directory.rglob("*"):
        if path.is_symlink():
            raise HTTPException(status_code=422, detail="Skill 包不能包含符号链接。")
    shutil.copytree(
        skill.directory,
        destination,
        ignore=shutil.ignore_patterns(
            "__pycache__", ".pytest_cache", ".ruff_cache", "工作区", "output"
        ),
    )
    return destination


def _reusable_file_bindings(
    db: Session,
    skill: RegisteredSkill,
    user: UserContext,
) -> dict[str, list[dict[str, Any]]]:
    """Return the current immutable business version, or legacy uploads before migration."""
    current_set = current_material_set(
        db,
        user.user_id,
        user.department_id,
        skill.manifest.id,
    )
    if current_set:
        try:
            return material_set_bindings(db, current_set)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Existing installations may not have a version head yet. Only original
    # input records are candidates here; historical workflow outputs are never
    # guessed as authoritative. Starting a task with this selection establishes V1.
    annual_by_year: dict[str, FileRecord] = {}
    receipt_flow: FileRecord | None = None

    def consider(role: str, record: FileRecord) -> None:
        nonlocal receipt_flow
        if role == RECEIPT_FLOW_ROLE:
            if receipt_flow is None or (record.created_at, record.id) > (
                receipt_flow.created_at,
                receipt_flow.id,
            ):
                receipt_flow = record
            return
        if role != ANNUAL_LEDGER_ROLE:
            return
        year_match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", record.original_name)
        year_key = year_match.group(1) if year_match else f"file:{record.id}"
        current = annual_by_year.get(year_key)
        if current is None or (record.created_at, record.id) > (
            current.created_at,
            current.id,
        ):
            annual_by_year[year_key] = record

    uploaded_records = db.scalars(
        select(FileRecord).where(
            FileRecord.owner_id == user.user_id,
            FileRecord.department_id == user.department_id,
            FileRecord.skill_id == skill.manifest.id,
            FileRecord.kind == "input",
        )
    ).all()
    for record in uploaded_records:
        consider(_file_role_for_name(record.original_name), record)

    reusable_ids: dict[str, list[str]] = {}
    if annual_by_year:
        reusable_ids[ANNUAL_LEDGER_ROLE] = [
            record.id for _, record in sorted(annual_by_year.items(), key=lambda item: item[0])
        ]
    if receipt_flow:
        reusable_ids[RECEIPT_FLOW_ROLE] = [receipt_flow.id]
    return _validate_file_bindings(db, skill, reusable_ids, user) if reusable_ids else {}


def _attach_material_snapshot(
    db: Session,
    workflow: WorkflowSession,
    user: UserContext,
    bindings: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    try:
        material_set = create_or_replace_current_set(
            db,
            user,
            workflow.skill_id,
            bindings,
            expected_current_id=workflow.material_set_id,
        )
        normalized = material_set_bindings(db, material_set)
    except (ValueError, MaterialVersionConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    workflow.material_set_id = material_set.id
    context = _load(workflow.context_json, {})
    context.update(
        {
            "material_set_id": material_set.id,
            "material_version": material_set.version,
            "material_source_workflow_id": material_set.source_workflow_id,
        }
    )
    workflow.context_json = _json(context)
    return normalized


def _ensure_legacy_workflow_material_snapshot(
    db: Session,
    workflow: WorkflowSession,
):
    """Bind a pre-migration started task without allowing it to replace newer files."""
    if workflow.material_set_id:
        selected = db.get(WorkflowMaterialSet, workflow.material_set_id)
        if (
            selected is None
            or selected.owner_id != workflow.owner_id
            or selected.department_id != workflow.department_id
            or selected.skill_id != workflow.skill_id
        ):
            raise MaterialVersionConflict(
                "当前任务绑定的业务工作簿版本不存在，请基于最新版本重新创建任务。"
            )
        current = current_material_set(
            db,
            workflow.owner_id,
            workflow.department_id,
            workflow.skill_id,
        )
        if current is None or current.id != selected.id:
            raise MaterialVersionConflict(
                "业务工作簿已有更新版本；当前任务不能继续写入，请基于最新版本重新创建任务。"
            )
        return selected

    actor = UserContext(
        user_id=workflow.owner_id,
        display_name=workflow.owner_name,
        role="finance_user",
        department_id=workflow.department_id,
    )
    bindings = _canonicalize_file_bindings(_load(workflow.files_json, {}))
    current = current_material_set(
        db,
        workflow.owner_id,
        workflow.department_id,
        workflow.skill_id,
    )
    if current is None:
        selected = create_or_replace_current_set(
            db,
            actor,
            workflow.skill_id,
            bindings,
            require_no_current=True,
        )
    else:
        if not material_set_matches_bindings(
            db,
            actor,
            workflow.skill_id,
            current,
            bindings,
        ):
            raise MaterialVersionConflict(
                "业务工作簿已有更新版本；当前旧任务固定的文件与最新版不同，"
                "不能继续写入，请基于最新版本重新创建任务。"
            )
        selected = current

    normalized = material_set_bindings(db, selected)
    workflow.material_set_id = selected.id
    workflow.files_json = _json(normalized)
    context = _load(workflow.context_json, {})
    context.update(
        {
            "material_set_id": selected.id,
            "material_version": selected.version,
            "material_source_workflow_id": selected.source_workflow_id,
        }
    )
    workflow.context_json = _json(context)
    return selected


def _effective_file_bindings(
    db: Session,
    skill: RegisteredSkill,
    requested: dict[str, list[str]],
    user: UserContext,
    replace_roles: list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    reusable = _reusable_file_bindings(db, skill, user)
    replacement_roles = set(replace_roles or [])
    known_roles = {item.role for item in skill.manifest.file_inputs}
    unknown_replacement_roles = replacement_roles - known_roles
    if unknown_replacement_roles:
        raise HTTPException(
            status_code=422,
            detail=f"未知文件替换角色：{sorted(unknown_replacement_roles)}",
        )
    if not requested and not replacement_roles:
        return reusable
    incoming = _validate_file_bindings(db, skill, requested, user) if requested else {}
    normalized = _merge_file_bindings(reusable, incoming)
    for role in replacement_roles:
        normalized[role] = list(incoming.get(role, []))
    return {role: entries for role, entries in normalized.items() if entries}


def reusable_workflow_files(
    db: Session,
    skill_id: str,
    user: UserContext,
) -> tuple[dict[str, list[dict[str, Any]]], list[str], dict[str, Any]]:
    skill = registry.get(skill_id)
    if not skill or skill.manifest.handler.adapter != "workflow":
        raise HTTPException(status_code=404, detail="后台 Skill 不存在或尚未发布。")
    # Reading the current business material is also needed by the offline
    # snapshot launcher.  Keep the normal live-execution gate for other
    # workflow Skills, while allowing the explicitly development-gated AR
    # snapshot path to load its input copies.
    if skill_id == "ar-hexiao-daily":
        if not settings.ar_hexiao_execution_enabled:
            assert_snapshot_replay_enabled(skill_id)
    else:
        assert_workflow_skill_execution_enabled(skill_id)
    assert_skill_permission(db, user, skill_id)
    files = _reusable_file_bindings(db, skill, user)
    material_set = current_material_set(db, user.user_id, user.department_id, skill_id)
    metadata = {
        "material_set_id": material_set.id if material_set else None,
        "material_version": material_set.version if material_set else None,
        "source_workflow_id": material_set.source_workflow_id if material_set else "",
        "published_at": material_set.published_at if material_set else None,
    }
    return files, _missing_required_files(skill, files), metadata


def _workflow_model_snapshot(
    db: Session,
    user: UserContext,
    connection_id: str | None,
    requested_model: str | None,
) -> tuple[str, str, str]:
    """Return an audit snapshot without making background Skill runs depend on an LLM."""
    llm = resolve_runtime_config(db, user, connection_id, requested_model)
    if llm:
        return llm.connection_id, llm.provider, llm.model
    return (
        BACKGROUND_MODEL_CONNECTION_ID,
        BACKGROUND_MODEL_PROVIDER,
        BACKGROUND_MODEL_NAME,
    )


def _business_task_prefix(skill_id: str, now: datetime | None = None) -> str:
    created = (now or datetime.now(UTC)).astimezone(PLATFORM_TIMEZONE)
    return f"{skill_id}_{created.month}.{created.day}_"


def _next_business_task_id(
    db: Session,
    skill_id: str,
    now: datetime | None = None,
) -> str:
    """Allocate a user-facing identifier while the global claim lock is held."""
    prefix = _business_task_prefix(skill_id, now)
    values = [
        *db.scalars(
            select(WorkflowSession.display_id).where(WorkflowSession.display_id.like(f"{prefix}%"))
        ).all(),
        *db.scalars(
            select(WorkflowBatch.display_id).where(WorkflowBatch.display_id.like(f"{prefix}%"))
        ).all(),
    ]
    suffixes: list[int] = []
    for value in values:
        if not value:
            continue
        try:
            suffixes.append(int(value.removeprefix(prefix)))
        except ValueError:
            continue
    return f"{prefix}{max(suffixes, default=0) + 1}"


def _assert_single_flight_available(
    db: Session,
    skill_id: str,
    *,
    exclude_workflow_id: str = "",
    exclude_batch_id: str = "",
) -> None:
    if skill_id != "ar-hexiao-daily":
        return
    if active_task_discovery_count(db, skill_id, datetime.now(UTC)):
        raise HTTPException(
            status_code=409,
            detail="应收核销只读任务检查正在进行，请等待检查结束后再创建正式任务。",
        )
    batch_filters = [
        WorkflowBatch.skill_id == skill_id,
        WorkflowBatch.state.not_in(TERMINAL_WORKFLOW_STATES),
    ]
    if exclude_batch_id:
        batch_filters.append(WorkflowBatch.id != exclude_batch_id)
    active_batch = db.scalar(
        select(WorkflowBatch).where(*batch_filters).order_by(WorkflowBatch.created_at).limit(1)
    )
    if active_batch:
        task_id = active_batch.display_id or active_batch.id
        raise HTTPException(
            status_code=409,
            detail=f"应收核销任务 {task_id} 尚未结束，完成、失败或取消后才能创建下一任务。",
        )
    workflow_filters = [
        WorkflowSession.skill_id == skill_id,
        WorkflowSession.batch_id.is_(None),
        WorkflowSession.state.not_in(TERMINAL_WORKFLOW_STATES),
    ]
    if exclude_workflow_id:
        workflow_filters.append(WorkflowSession.id != exclude_workflow_id)
    active_workflow = db.scalar(
        select(WorkflowSession)
        .where(*workflow_filters)
        .order_by(WorkflowSession.created_at)
        .limit(1)
    )
    if active_workflow:
        task_id = active_workflow.display_id or active_workflow.id
        raise HTTPException(
            status_code=409,
            detail=f"应收核销任务 {task_id} 尚未结束，完成、失败或取消后才能创建下一任务。",
        )


def create_workflow(
    db: Session,
    request: WorkflowCreate,
    user: UserContext,
) -> WorkflowSession:
    skill = registry.get(request.skill_id)
    if not skill or skill.manifest.handler.adapter != "workflow":
        raise HTTPException(status_code=404, detail="对话式 Skill 不存在或尚未发布。")
    assert_workflow_skill_execution_enabled(request.skill_id)
    assert_skill_permission(db, user, request.skill_id)
    acquire_claim_lock(db)
    assert_skill_accepting_new_work(db, request.skill_id, acquire_lock=False)
    llm = resolve_runtime_config(db, user, request.model_connection_id, request.model)
    if not llm:
        raise HTTPException(status_code=422, detail="对话式 Skill 必须选择一个大模型连接。")
    _assert_single_flight_available(db, request.skill_id)
    display_id = _next_business_task_id(db, skill.manifest.id)
    reusable_files = _reusable_file_bindings(db, skill, user)
    reusable_ready = not _missing_required_files(skill, reusable_files)
    workflow_id = str(uuid.uuid4())
    _snapshot_skill(skill, user.user_id, workflow_id)
    workflow = WorkflowSession(
        id=workflow_id,
        display_id=display_id,
        owner_id=user.user_id,
        owner_name=user.display_name,
        department_id=user.department_id,
        skill_id=skill.manifest.id,
        skill_name=skill.manifest.name,
        skill_version=skill.manifest.version,
        skill_hash=skill.skill_hash,
        skill_commit=skill.commit_sha,
        concurrency_limit=skill.manifest.runtime.concurrency_limit,
        model_connection_id=llm.connection_id,
        model_provider=llm.provider,
        model_name=llm.model,
        state="active",
        stage="awaiting_date",
        files_json=_json(reusable_files),
        context_json=_json(
            {
                "reused_files": reusable_ready,
                "requires_confirmation": skill.manifest.risk.requires_confirmation,
                "requires_approval": skill.manifest.risk.requires_approval,
            }
        ),
        progress_message=(
            "等待确认核销日期（已复用上次保存的财务表）" if reusable_ready else "等待确认核销日期"
        ),
    )
    db.add(workflow)
    db.flush()
    existing_material_set = current_material_set(
        db,
        user.user_id,
        user.department_id,
        request.skill_id,
    )
    if reusable_ready and existing_material_set is not None:
        workflow.files_json = _json(_attach_material_snapshot(db, workflow, user, reusable_files))
    _message(
        db,
        workflow,
        "assistant",
        "先告诉我要跑的核销日期。可以说“昨天”或直接说“2026-07-24”。",
        {"kind": "date_request"},
    )
    db.commit()
    db.refresh(workflow)
    return workflow


def start_workflow(
    db: Session,
    request: WorkflowStart,
    user: UserContext,
) -> WorkflowSession:
    """Start a workflow from a completed prerequisite form.

    The web form supplies the date, model and uploaded file IDs in one request.
    The worker still performs the deterministic financial processing and keeps
    the existing human confirmation gate before any workbook write.
    """
    skill = registry.get(request.skill_id)
    if not skill or skill.manifest.handler.adapter != "workflow":
        raise HTTPException(status_code=404, detail="对话式 Skill 不存在或尚未发布。")
    snapshot_workflow_id = str(request.snapshot_workflow_id or "").strip()
    if snapshot_workflow_id:
        assert_snapshot_replay_enabled(request.skill_id)
    else:
        assert_workflow_skill_execution_enabled(request.skill_id)
    assert_skill_permission(db, user, request.skill_id)
    if request.files or request.replace_roles:
        assert_skill_permission(db, user, request.skill_id, "can_upload")
    acquire_claim_lock(db)
    assert_skill_accepting_new_work(db, request.skill_id, acquire_lock=False)
    parsed_date = _parse_date(request.reconciliation_date)
    if not parsed_date:
        raise HTTPException(status_code=422, detail="核销日期无效，不能晚于今天。")
    if snapshot_workflow_id:
        _validated_snapshot_selection(
            db,
            snapshot_workflow_id,
            [parsed_date.isoformat()],
            user,
        )
    model_connection_id, model_provider, model_name = _workflow_model_snapshot(
        db,
        user,
        request.model_connection_id,
        request.model,
    )
    if not snapshot_workflow_id and not has_service_credential(
        db, user.user_id, user.department_id, "zhiyun"
    ):
        raise HTTPException(status_code=422, detail="尚未配置智云登录凭据，请先安全保存账号密码。")

    _assert_single_flight_available(db, request.skill_id)
    workflow_id = str(uuid.uuid4())
    display_id = _next_business_task_id(db, skill.manifest.id)
    _snapshot_skill(skill, user.user_id, workflow_id)
    workflow = WorkflowSession(
        id=workflow_id,
        display_id=display_id,
        owner_id=user.user_id,
        owner_name=user.display_name,
        department_id=user.department_id,
        skill_id=skill.manifest.id,
        skill_name=skill.manifest.name,
        skill_version=skill.manifest.version,
        skill_hash=skill.skill_hash,
        skill_commit=skill.commit_sha,
        concurrency_limit=skill.manifest.runtime.concurrency_limit,
        model_connection_id=model_connection_id,
        model_provider=model_provider,
        model_name=model_name,
        state="active",
        stage="awaiting_files",
        reconciliation_date=parsed_date.isoformat(),
        context_json=_json(
            {
                "started_from_form": True,
                "requires_confirmation": skill.manifest.risk.requires_confirmation,
                "requires_approval": skill.manifest.risk.requires_approval,
                "current_step": "queued",
                "current_step_label": "已提交后台任务队列",
                "fetched_data_source": "snapshot" if snapshot_workflow_id else "live",
                "snapshot_workflow_id": snapshot_workflow_id,
            }
        ),
        progress_message="正在核验前置条件",
    )
    db.add(workflow)
    db.flush()
    normalized_files = _effective_file_bindings(
        db,
        skill,
        request.files,
        user,
        request.replace_roles,
    )
    workflow.files_json = _json(normalized_files)
    ready, missing = _has_required_files(workflow)
    if not ready:
        raise HTTPException(
            status_code=422,
            detail=f"前置文件未上传完整：{'、'.join(missing)}。",
        )
    normalized_files = _attach_material_snapshot(db, workflow, user, normalized_files)
    workflow.files_json = _json(normalized_files)
    workflow.state = "running"
    workflow.stage = "preparing"
    workflow.progress = 5
    workflow.progress_message = "已提交后台 Worker，等待开始"
    workflow.error_message = ""
    context = _load(workflow.context_json, {})
    context.update(
        {
            "current_step": "queued",
            "current_step_label": "已提交后台 Worker，等待开始",
            "step_error": "",
        }
    )
    if hasattr(workflow, "context_json"):
        workflow.context_json = _json(context)
    _queue_action(db, workflow, "prepare_worklist")
    associate_reminder_with_workflow(db, workflow)
    _message(
        db,
        workflow,
        "assistant",
        f"前置条件已核验，已提交后台 Worker 执行"
        f" {_date_label(workflow.reconciliation_date)} 的核销日清。",
        {"kind": "direct_start", "reconciliation_date": workflow.reconciliation_date},
    )
    db.commit()
    db.refresh(workflow)
    return workflow


def start_workflow_batch(
    db: Session,
    request: WorkflowBatchStart,
    user: UserContext,
) -> WorkflowBatch:
    """Create an ordered multi-date batch without widening a child's write scope."""
    skill = registry.get(request.skill_id)
    if not skill or skill.manifest.handler.adapter != "workflow":
        raise HTTPException(status_code=404, detail="对话式 Skill 不存在或尚未发布。")
    snapshot_workflow_id = str(request.snapshot_workflow_id or "").strip()
    if snapshot_workflow_id:
        assert_snapshot_replay_enabled(request.skill_id)
    else:
        assert_workflow_skill_execution_enabled(request.skill_id)
    assert_skill_permission(db, user, request.skill_id)
    if request.files or request.replace_roles:
        assert_skill_permission(db, user, request.skill_id, "can_upload")
    acquire_claim_lock(db)
    assert_skill_accepting_new_work(db, request.skill_id, acquire_lock=False)
    if len(request.reconciliation_dates) > 31:
        raise HTTPException(status_code=422, detail="单个批次最多选择 31 个核销日期。")

    parsed_dates: list[str] = []
    for value in request.reconciliation_dates:
        parsed = _parse_date(value)
        if not parsed:
            raise HTTPException(status_code=422, detail=f"核销日期无效或晚于今天：{value}")
        parsed_dates.append(parsed.isoformat())
    parsed_dates = sorted(set(parsed_dates))
    if not parsed_dates:
        raise HTTPException(status_code=422, detail="请至少选择一个核销日期。")
    if len(parsed_dates) > 1:
        start = date.fromisoformat(parsed_dates[0])
        end = date.fromisoformat(parsed_dates[-1])
        if (end - start).days + 1 > 31:
            raise HTTPException(
                status_code=422,
                detail="单个批次的最早日期到最晚日期跨度最多 31 个自然日。",
            )
    if snapshot_workflow_id:
        _validated_snapshot_selection(db, snapshot_workflow_id, parsed_dates, user)

    rerun_reason = sanitize_text(request.rerun_reason.strip(), max_length=500)
    if request.rerun_successful_dates and not rerun_reason:
        raise HTTPException(
            status_code=422,
            detail="勾选重新核销已成功日期后，必须填写重新核销原因。",
        )

    model_connection_id, model_provider, model_name = _workflow_model_snapshot(
        db,
        user,
        request.model_connection_id,
        request.model,
    )
    if not snapshot_workflow_id and not has_service_credential(
        db, user.user_id, user.department_id, "zhiyun"
    ):
        raise HTTPException(status_code=422, detail="尚未配置智云登录凭据，请先安全保存账号密码。")

    _assert_single_flight_available(db, request.skill_id)
    normalized_files = _effective_file_bindings(
        db,
        skill,
        request.files,
        user,
        request.replace_roles,
    )
    missing = [
        FILE_ROLE_LABELS.get(role, role)
        for role in _missing_required_files(skill, normalized_files)
    ]
    if missing:
        raise HTTPException(status_code=422, detail=f"前置文件未上传完整：{'、'.join(missing)}。")

    material_probe = WorkflowSession(
        id=str(uuid.uuid4()),
        owner_id=user.user_id,
        owner_name=user.display_name,
        department_id=user.department_id,
        skill_id=skill.manifest.id,
        skill_name=skill.manifest.name,
        skill_version=skill.manifest.version,
        skill_hash=skill.skill_hash,
        model_connection_id=model_connection_id,
        model_provider=model_provider,
        model_name=model_name,
    )
    normalized_files = _attach_material_snapshot(db, material_probe, user, normalized_files)
    material_set_id = material_probe.material_set_id

    successful_workflows = successful_reconciliation_workflows_for_material_lineage(
        db,
        owner_id=user.user_id,
        department_id=user.department_id,
        skill_id=skill.manifest.id,
        material_set_id=material_set_id,
        reconciliation_dates=parsed_dates,
    )
    successful_dates = set(successful_workflows)
    active_reminder_dates = set(
        db.scalars(
            select(TaskReminder.business_date).where(
                TaskReminder.owner_id == user.user_id,
                TaskReminder.department_id == user.department_id,
                TaskReminder.skill_id == skill.manifest.id,
                TaskReminder.state.in_(("pending", "reopened")),
                TaskReminder.business_date.in_(parsed_dates),
            )
        ).all()
    )
    successful_dates.difference_update(active_reminder_dates)
    rerun_dates = sorted(successful_dates.intersection(parsed_dates))
    excluded_successful_dates = [] if request.rerun_successful_dates else rerun_dates
    if excluded_successful_dates:
        parsed_dates = [item for item in parsed_dates if item not in successful_dates]
    if not parsed_dates:
        raise HTTPException(status_code=409, detail="所选日期均已处理成功，无需再次创建批次。")
    if not request.rerun_successful_dates:
        rerun_dates = []

    batch_id = f"BAT-{_platform_today():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
    batch_display_id = _next_business_task_id(db, skill.manifest.id)
    batch = WorkflowBatch(
        id=batch_id,
        display_id=batch_display_id,
        owner_id=user.user_id,
        owner_name=user.display_name,
        department_id=user.department_id,
        skill_id=skill.manifest.id,
        skill_name=skill.manifest.name,
        skill_version=skill.manifest.version,
        model_connection_id=model_connection_id,
        model_provider=model_provider,
        model_name=model_name,
        reconciliation_dates_json=_json(parsed_dates),
        files_json=_json(normalized_files),
        material_set_id=material_set_id,
        state="running",
        progress=0,
        progress_message=(
            f"已确认重新核销已成功日期：{'、'.join(rerun_dates)}；"
            f"已创建 {len(parsed_dates)} 个核销日批次，等待第 1 个日期执行"
            if rerun_dates
            else (
                f"已排除已成功日期：{'、'.join(excluded_successful_dates)}；"
                f"已创建 {len(parsed_dates)} 个核销日批次，等待第 1 个日期执行"
                if excluded_successful_dates
                else f"已创建 {len(parsed_dates)} 个核销日批次，等待第 1 个日期执行"
            )
        ),
    )
    db.add(batch)
    created_roots: list[Path] = []
    previous_workflow_id = ""
    try:
        for sequence, reconciliation_date in enumerate(parsed_dates, start=1):
            workflow_id = str(uuid.uuid4())
            workflow_display_id = _next_business_task_id(db, skill.manifest.id)
            is_first = sequence == 1
            if is_first:
                _snapshot_skill(skill, user.user_id, workflow_id)
            created_roots.append(workflow_root(user.user_id, workflow_id))
            context = {
                "started_from_form": True,
                "batch_id": batch_id,
                "requires_confirmation": skill.manifest.risk.requires_confirmation,
                "requires_approval": skill.manifest.risk.requires_approval,
                "current_step": "queued" if not is_first else "preparing",
                "current_step_label": (
                    "等待前一个核销日完成后进入后台任务" if not is_first else "已提交后台任务队列"
                ),
                "rerun_successful_date": reconciliation_date in rerun_dates,
                "previous_successful_workflow_ids": (
                    successful_workflows.get(reconciliation_date, [])
                    if reconciliation_date in rerun_dates
                    else []
                ),
                "rerun_reason": rerun_reason if reconciliation_date in rerun_dates else "",
                "fetched_data_source": "snapshot" if snapshot_workflow_id else "live",
                "snapshot_workflow_id": snapshot_workflow_id,
            }
            workflow = WorkflowSession(
                id=workflow_id,
                display_id=workflow_display_id,
                owner_id=user.user_id,
                owner_name=user.display_name,
                department_id=user.department_id,
                skill_id=skill.manifest.id,
                skill_name=skill.manifest.name,
                skill_version=skill.manifest.version,
                skill_hash=skill.skill_hash,
                skill_commit=skill.commit_sha,
                concurrency_limit=skill.manifest.runtime.concurrency_limit,
                model_connection_id=model_connection_id,
                model_provider=model_provider,
                model_name=model_name,
                state="running" if is_first else "queued",
                stage="preparing" if is_first else "queued",
                reconciliation_date=reconciliation_date,
                batch_id=batch_id,
                batch_sequence=sequence,
                previous_workflow_id=previous_workflow_id,
                material_set_id=material_set_id,
                context_json=_json(context),
                files_json=_json(normalized_files if is_first else {}),
                progress=5 if is_first else 0,
                progress_message=(
                    f"正在执行第 {sequence}/{len(parsed_dates)} 个核销日"
                    if is_first
                    else f"等待前一个核销日完成后执行（{sequence}/{len(parsed_dates)}）"
                ),
            )
            db.add(workflow)
            db.flush()
            associate_reminder_with_workflow(db, workflow)
            if is_first:
                _queue_action(db, workflow, "prepare_worklist")
            _message(
                db,
                workflow,
                "assistant",
                (
                    f"批次 {batch_display_id} 的第 "
                    f"{sequence}/{len(parsed_dates)} 个单日任务已创建："
                    f"{_date_label(reconciliation_date)}。"
                ),
                {
                    "kind": "batch_child_created",
                    "batch_id": batch_id,
                    "batch_display_id": batch_display_id,
                    "sequence": sequence,
                },
            )
            previous_workflow_id = workflow_id
        if rerun_dates:
            record_audit(
                db,
                actor=user,
                action="workflow.batch.successful_dates.rerun",
                resource_type="workflow_batch",
                resource_id=batch_id,
                details={
                    "display_id": batch_display_id,
                    "rerun_dates": rerun_dates,
                    "previous_successful_workflow_ids": {
                        item: successful_workflows.get(item, []) for item in rerun_dates
                    },
                    "reason": rerun_reason,
                    "material_set_id": material_set_id,
                },
            )
        db.commit()

    except Exception:
        db.rollback()
        for root in created_roots:
            shutil.rmtree(root, ignore_errors=True)
        raise
    db.refresh(batch)
    return batch


def _workflow_error_detail(workflow: WorkflowSession, reason: object) -> TaskErrorDetail:
    context = _load(workflow.context_json, {})
    step_key = str(context.get("current_step", "unknown"))
    raw_reason = str(reason)
    if step_key == "fetch_zhiyun" or workflow.stage == "supplementing_fetched_data":
        if (
            TRANSIENT_FETCH_FAILURE.search(raw_reason)
            or "超时" in raw_reason
            or "timeout" in raw_reason.lower()
        ):
            safe_reason = "智云暂时无法访问，本次取数未完成。"
        else:
            safe_reason = "智云取数未完成。"
    elif step_key == "write_files" or workflow.stage == "applying":
        safe_reason = "写入前校验未通过，工作副本没有发布。"
    else:
        safe_reason = "当前步骤未完成，请联系管理员查看审计记录。"
    return build_task_error(
        employee=workflow.owner_name or workflow.owner_id,
        skill_id=workflow.skill_id,
        skill_name=workflow.skill_name,
        step_key=step_key,
        step=str(context.get("current_step_label", "当前步骤")),
        reason=safe_reason,
    )


def _workflow_public_error(workflow: WorkflowSession, detail: TaskErrorDetail) -> dict[str, str]:
    date_label = workflow.reconciliation_date or "当前日期"
    if detail.reason == "智云暂时无法访问，本次取数未完成。":
        message = (
            f"{date_label} 取数未完成：智云暂时无法访问，本次取数未完成。请稍后点击“重试失败日期”。"
        )
        error_type = "zhiyun_unavailable"
    elif detail.step_key == "write_files":
        message = f"{date_label} 写入未完成：工作副本没有发布。请联系管理员核对后再处理。"
        error_type = "write_blocked"
    else:
        message = f"{date_label} 未完成：{detail.reason}请联系管理员查看处理建议。"
        error_type = "workflow_failed"
    return {
        "step": detail.step,
        "step_key": detail.step_key,
        "reason": detail.reason,
        "message": message,
        "error_type": error_type,
    }


def _store_workflow_error(workflow: WorkflowSession, detail: TaskErrorDetail) -> None:
    context = _load(workflow.context_json, {})
    public_error = _workflow_public_error(workflow, detail)
    context["step_error"] = public_error["message"]
    context["error_detail"] = {
        key: public_error[key] for key in ("step", "step_key", "reason", "error_type")
    }
    if hasattr(workflow, "context_json"):
        workflow.context_json = _json(context)
    workflow.error_message = public_error["message"]


def list_workflows(db: Session, user: UserContext, limit: int = 50) -> list[WorkflowSession]:
    query = (
        select(WorkflowSession)
        .where(
            owner_list_filter(WorkflowSession, user),
            # Only sessions created by the completed prerequisite form belong
            # in the task list. The legacy conversational bootstrap remains
            # available for API compatibility/tests, but must not create a
            # visible dashboard task before the user clicks 开始核销.
            WorkflowSession.context_json.like('%"started_from_form": true%'),
            WorkflowSession.batch_id.is_(None),
        )
        .order_by(WorkflowSession.updated_at.desc())
        .limit(min(max(limit, 1), 200))
    )
    return list(db.scalars(query).all())


def list_workflow_batches(
    db: Session,
    user: UserContext,
    limit: int = 50,
) -> list[WorkflowBatch]:
    query = (
        select(WorkflowBatch)
        .where(owner_list_filter(WorkflowBatch, user))
        .order_by(WorkflowBatch.updated_at.desc())
        .limit(min(max(limit, 1), 200))
    )
    return list(db.scalars(query).all())


def _cancel_workflow_actions(db: Session, workflow: WorkflowSession) -> None:
    db.execute(
        update(WorkflowAction)
        .where(
            WorkflowAction.workflow_id == workflow.id,
            WorkflowAction.state == "queued",
        )
        .values(state="cancelled", finished_at=datetime.now(UTC))
    )


def _cancel_workflow_immediately(db: Session, workflow: WorkflowSession) -> None:
    _cancel_workflow_actions(db, workflow)
    workflow.stage = "cancelled"
    workflow.state = "cancelled"
    workflow.progress_message = "所属批次已取消"
    workflow.error_message = ""


def _finalize_requested_batch_cancellation(db: Session, batch_id: str | None) -> None:
    if not batch_id:
        return
    batch = db.get(WorkflowBatch, batch_id)
    if not batch or batch.state != "cancelling":
        return
    if any(
        action.state == "running" for workflow in batch.workflows for action in workflow.actions
    ):
        return
    for workflow in batch.workflows:
        if workflow.state not in TERMINAL_WORKFLOW_STATES:
            _cancel_workflow_immediately(db, workflow)
        sync_reminder_from_workflow(db, workflow)
    batch.state = "cancelled"
    batch.progress_message = "批次已取消，未执行日期不会继续运行"
    batch.error_message = ""
    batch.updated_at = datetime.now(UTC)
    _cleanup_terminal_fetched_snapshot(db, _batch_primary_workflow(batch))


def cancel_workflow_batch(
    db: Session,
    batch_id: str,
    user: UserContext,
) -> WorkflowBatch:
    acquire_claim_lock(db)
    batch = get_workflow_batch_or_404(db, batch_id, user)
    if batch.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="只有任务发起人可以取消批次。")
    if batch.state in TERMINAL_WORKFLOW_STATES:
        _cleanup_terminal_fetched_snapshot(db, _batch_primary_workflow(batch))
        db.commit()
        db.refresh(batch)
        return batch
    if batch.state == "cancelling":
        return batch

    atomic_write_started = any(
        workflow.stage == "applying"
        and any(
            action.name == "apply_confirmed" and action.state in {"queued", "running"}
            for action in workflow.actions
        )
        for workflow in batch.workflows
    )
    if atomic_write_started:
        raise HTTPException(
            status_code=409,
            detail="工作副本正在执行原子写入和回读校验，当前不能取消批次，请等待本次写入完成。",
        )

    waiting_for_atomic_action = False
    for workflow in batch.workflows:
        revoke_workflow_approvals(db, workflow, user, "所属批次已由发起人取消。")
        running_action = any(action.state == "running" for action in workflow.actions)
        if running_action:
            context = _load(workflow.context_json, {})
            context["stop_after_action"] = True
            workflow.context_json = _json(context)
            workflow.progress_message = "已申请取消，等待当前原子动作结束"
            waiting_for_atomic_action = True
        elif workflow.state not in TERMINAL_WORKFLOW_STATES:
            _cancel_workflow_immediately(db, workflow)

    if waiting_for_atomic_action:
        batch.state = "cancelling"
        batch.progress_message = "正在等待当前原子动作结束，随后取消剩余日期"
    else:
        batch.state = "cancelled"
        batch.progress_message = "批次已取消，未执行日期不会继续运行"
    batch.error_message = ""
    batch.updated_at = datetime.now(UTC)
    if batch.state == "cancelled":
        _cleanup_terminal_fetched_snapshot(db, _batch_primary_workflow(batch))
    for workflow in batch.workflows:
        sync_reminder_from_workflow(db, workflow)
    record_audit(
        db,
        actor_id=user.user_id,
        actor_role=user.role,
        department_id=user.department_id,
        action="workflow.batch.cancel",
        resource_type="workflow_batch",
        resource_id=batch.id,
        details={"display_id": batch.display_id, "state": batch.state},
    )
    db.commit()
    db.refresh(batch)
    return batch


def _request_workflow_cancellation(
    db: Session,
    workflow: WorkflowSession,
    user: UserContext,
) -> WorkflowSession:
    if workflow.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="只有任务发起人可以取消任务。")
    if workflow.state in TERMINAL_WORKFLOW_STATES or workflow.state == "cancelling":
        return workflow
    if workflow.batch_id:
        raise HTTPException(
            status_code=409,
            detail="该任务属于多日期批次，请取消整个批次，不能跳过其中一天。",
        )

    running_action = next(
        (action for action in workflow.actions if action.state == "running"),
        None,
    )
    atomic_write_started = workflow.stage == "applying" and any(
        action.name == "apply_confirmed" and action.state in {"queued", "running"}
        for action in workflow.actions
    )
    if atomic_write_started:
        raise HTTPException(
            status_code=409,
            detail="工作副本正在执行原子写入和回读校验，当前不能取消，请等待本次写入完成。",
        )

    revoke_workflow_approvals(db, workflow, user, "任务已由发起人取消。")
    if running_action:
        context = _load(workflow.context_json, {})
        context["stop_after_action"] = True
        workflow.context_json = _json(context)
        workflow.state = "cancelling"
        workflow.progress_message = "已申请取消，等待当前取数动作结束"
        message = "取消请求已记录；当前取数动作结束后，任务不会进入下一阶段。"
    else:
        _cancel_workflow_actions(db, workflow)
        workflow.stage = "cancelled"
        workflow.state = "cancelled"
        workflow.progress_message = "任务已取消，不会继续处理或写入"
        workflow.error_message = ""
        message = "任务已取消，没有继续处理或写入。"
    _message(db, workflow, "assistant", message, {"kind": "workflow_cancelled"})
    record_audit(
        db,
        actor_id=user.user_id,
        actor_role=user.role,
        department_id=user.department_id,
        action="workflow.cancel",
        resource_type="workflow",
        resource_id=workflow.id,
        details={"display_id": workflow.display_id, "state": workflow.state},
    )
    return workflow


def cancel_workflow(
    db: Session,
    workflow_id: str,
    user: UserContext,
) -> WorkflowSession:
    acquire_claim_lock(db)
    workflow = get_workflow_or_404(db, workflow_id, user)
    _request_workflow_cancellation(db, workflow, user)
    sync_reminder_from_workflow(db, workflow)
    _cleanup_terminal_fetched_snapshot(db, workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def _validate_file_bindings(
    db: Session,
    skill: RegisteredSkill,
    bindings: dict[str, list[str]],
    user: UserContext,
) -> dict[str, list[dict[str, Any]]]:
    specs = {item.role: item for item in skill.manifest.file_inputs}
    unknown = set(bindings) - set(specs) - {LEGACY_FILE_ROLE}
    if unknown:
        raise HTTPException(status_code=422, detail=f"未知文件角色：{sorted(unknown)}")
    role_ids: dict[str, list[str]] = {}
    for role, ids in bindings.items():
        if role != LEGACY_FILE_ROLE:
            role_ids.setdefault(role, []).extend(ids)
            continue
        for file_id in ids:
            record = db.get(FileRecord, file_id)
            if not record:
                raise HTTPException(status_code=422, detail=f"输入文件不存在：{file_id}")
            role = _file_role_for_name(record.original_name, strict=True)
            role_ids.setdefault(role, []).append(file_id)

    unknown = set(role_ids) - set(specs)
    if unknown:
        raise HTTPException(status_code=422, detail=f"未知文件角色：{sorted(unknown)}")
    normalized: dict[str, list[dict[str, Any]]] = {}
    for role, ids in role_ids.items():
        spec = specs[role]
        if not spec.multiple and len(ids) > 1:
            raise HTTPException(status_code=422, detail=f"{spec.name}只能上传一个文件。")
        records: list[dict[str, Any]] = []
        for file_id in ids:
            record = db.get(FileRecord, file_id)
            current_material_reference = (
                db.scalar(
                    select(WorkflowMaterialSetFile.id)
                    .join(
                        WorkflowMaterialSet,
                        WorkflowMaterialSet.id == WorkflowMaterialSetFile.material_set_id,
                    )
                    .where(
                        WorkflowMaterialSetFile.file_id == file_id,
                        WorkflowMaterialSetFile.role == role,
                        WorkflowMaterialSetFile.sha256 == record.sha256,
                        WorkflowMaterialSet.owner_id == user.user_id,
                        WorkflowMaterialSet.department_id == user.department_id,
                        WorkflowMaterialSet.skill_id == skill.manifest.id,
                        WorkflowMaterialSet.state == "current",
                    )
                )
                if record and record.kind == "output"
                else None
            )
            if not record or (record.kind != "input" and not current_material_reference):
                raise HTTPException(status_code=422, detail=f"输入文件不存在：{file_id}")
            assert_owner(record.owner_id, user, "输入文件", record.department_id)
            suffix = Path(record.original_name).suffix.lower().lstrip(".")
            allowed = [item.lower().lstrip(".") for item in spec.extensions]
            if allowed and suffix not in allowed:
                raise HTTPException(
                    status_code=422,
                    detail=f"{spec.name}不支持 .{suffix}，允许：{', '.join(allowed)}",
                )
            records.append(
                {
                    "file_id": record.id,
                    "name": record.original_name,
                    "size_bytes": record.size_bytes,
                    "sha256": record.sha256,
                }
            )
        normalized[role] = records
    return normalized


def update_workflow_files(
    db: Session,
    workflow: WorkflowSession,
    bindings: dict[str, list[str]],
    user: UserContext,
    replace_roles: list[str] | None = None,
) -> WorkflowSession:
    editable_stages = {
        "awaiting_date",
        "awaiting_date_confirmation",
        "awaiting_files",
    }
    if workflow.stage not in editable_stages:
        raise HTTPException(status_code=409, detail="当前阶段不能更换输入文件。")
    skill = registry.get(workflow.skill_id)
    if not skill:
        raise HTTPException(status_code=409, detail="Skill 当前不可用。")
    replacement_roles = set(replace_roles or [])
    known_roles = {item.role for item in skill.manifest.file_inputs}
    unknown_replacement_roles = replacement_roles - known_roles
    if unknown_replacement_roles:
        raise HTTPException(
            status_code=422,
            detail=f"未知文件替换角色：{sorted(unknown_replacement_roles)}",
        )
    current = _canonicalize_file_bindings(_load(workflow.files_json, {}))
    incoming = _validate_file_bindings(db, skill, bindings, user)
    normalized = _merge_file_bindings(current, incoming)
    for role in replacement_roles:
        # An explicit replacement may intentionally contain an empty list so
        # the user can remove the last file before starting the workflow.
        normalized[role] = list(incoming.get(role, []))
    normalized = {role: entries for role, entries in normalized.items() if entries}
    if not _missing_required_files(skill, normalized):
        normalized = _attach_material_snapshot(db, workflow, user, normalized)
    workflow.files_json = _json(normalized)
    workflow.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(workflow)
    return workflow


def reset_workflow(
    db: Session,
    workflow: WorkflowSession,
    actor: UserContext,
) -> WorkflowSession:
    acquire_claim_lock(db)
    _assert_single_flight_available(
        db,
        workflow.skill_id,
        exclude_workflow_id=workflow.id,
        exclude_batch_id=workflow.batch_id or "",
    )
    pending = db.scalar(
        select(WorkflowAction.id).where(
            WorkflowAction.workflow_id == workflow.id,
            WorkflowAction.state.in_(("queued", "running")),
        )
    )
    if pending or workflow.stage in BUSY_STAGES:
        raise HTTPException(status_code=409, detail="当前动作正在执行，完成后才能重置任务。")

    revoke_workflow_approvals(db, workflow, actor, "工作流已由发起人重置。")
    workflow.state = "active"
    workflow.stage = "awaiting_date"
    workflow.reconciliation_date = ""
    workflow.context_json = "{}"
    workflow.files_json = "{}"
    workflow.artifacts_json = "[]"
    workflow.progress = 0
    workflow.progress_message = "任务已重置，等待确认核销日期"
    workflow.error_message = ""
    _message(
        db,
        workflow,
        "assistant",
        "任务已重置。已清空核销日期、文件绑定和本次输出列表；"
        "历史记录及已经完成的写入不会撤销。请重新告诉我要跑的核销日期。",
        {"kind": "workflow_reset"},
    )
    db.commit()
    db.refresh(workflow)
    return workflow


def _parse_date(value: str) -> date | None:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed <= _platform_today() else None


def _date_label(value: str) -> str:
    parsed = _parse_date(value)
    if not parsed:
        return "未确认"
    return f"{value}（周{WEEKDAYS[parsed.weekday()]}）"


def _has_required_files(workflow: WorkflowSession) -> tuple[bool, list[str]]:
    files = _canonicalize_file_bindings(_load(getattr(workflow, "files_json", "{}"), {}))
    skill = registry.get(workflow.skill_id)
    if not skill:
        return False, list(FILE_ROLES)
    missing = _missing_required_files(skill, files)
    return not missing, missing


def _queue_action(
    db: Session,
    workflow: WorkflowSession,
    name: str,
    input_extra: dict[str, Any] | None = None,
) -> WorkflowAction:
    pending = db.scalar(
        select(WorkflowAction.id).where(
            WorkflowAction.workflow_id == workflow.id,
            WorkflowAction.state.in_(("queued", "running")),
        )
    )
    if pending:
        raise HTTPException(status_code=409, detail="当前已有动作正在执行。")
    return _new_action(db, workflow, name, input_extra)


def _new_action(
    db: Session,
    workflow: WorkflowSession,
    name: str,
    input_extra: dict[str, Any] | None = None,
) -> WorkflowAction:
    action_input = {
        "reconciliation_date": workflow.reconciliation_date,
        "files": _canonicalize_file_bindings(_load(workflow.files_json, {})),
        "context": _load(workflow.context_json, {}),
    }
    action_input.update(input_extra or {})
    action = WorkflowAction(
        id=str(uuid.uuid4()),
        workflow_id=workflow.id,
        name=name,
        input_json=_json(action_input),
    )
    db.add(action)
    return action


def _status_reply(workflow: WorkflowSession) -> str:
    if workflow.stage == "awaiting_date_confirmation":
        return f"当前核销日期是 {_date_label(workflow.reconciliation_date)}，请回复“确认”。"
    if workflow.stage == "preparing":
        return f"正在生成 {_date_label(workflow.reconciliation_date)} 的《核销日清》。"
    labels = {
        "awaiting_date": "请先告诉我核销日期。",
        "awaiting_files": (
            "首次使用请安全保存智云账号，并上传年度盈亏核算表和到账流转表。"
            "后续任务会复用已保存的两类表；需要更换或增加年度表时再上传，完成后回复“上传好了”。"
            "智云核销数据由平台自动获取。"
        ),
        "awaiting_apply_confirmation": "《核销日清》已生成；请打开检查，确认后回复“确认”。",
        "waiting_approval": "已收到写入确认，正在继续执行（旧任务状态已兼容处理）。",
        "applying": "正在执行确认后的写入和回读校验，请不要修改相关表格。",
        "completed": "本次核销已完成，结果文件可以下载。",
        "failed": "上一步没有完成。请根据错误提示，以原始上传文件重新生成核销日清。",
        "cancelled": "本次对话任务已经取消。",
    }
    return labels.get(workflow.stage, workflow.progress_message or "正在处理。")


def _is_explicit_confirmation(content: str, *, apply: bool) -> bool:
    normalized = content.lower().replace(" ", "").strip("。！!，,")
    if normalized in CONFIRM_REPLIES:
        return True
    if apply:
        return normalized in {
            "确认写入",
            "确认回填",
            "可以写入",
            "同意写入",
            "我已检查核销日清，确认写入",
        }
    return normalized in {"确认日期", "日期确认"}


def _apply_decision(
    db: Session,
    workflow: WorkflowSession,
    decision: WorkflowDecision,
    actor: UserContext,
) -> None:
    action = decision.action
    source = {"decision_source": decision.source, "action": action}
    if action == "reply":
        content = str(decision.arguments.get("content", "")).strip()
        _message(
            db,
            workflow,
            "assistant",
            content[:8000] if content else _status_reply(workflow),
            source,
        )
        return
    if action == "set_date":
        value = str(decision.arguments.get("date", ""))
        parsed = _parse_date(value)
        if not parsed:
            _message(
                db,
                workflow,
                "assistant",
                "这个日期无法使用。请给出不晚于今天的有效核销日期，例如 2026-07-24。",
                source,
            )
            return
        workflow.reconciliation_date = parsed.isoformat()
        workflow.stage = "awaiting_date_confirmation"
        workflow.state = "active"
        workflow.progress_message = "等待确认核销日期"
        _message(
            db,
            workflow,
            "assistant",
            f"我按核销日期 {_date_label(workflow.reconciliation_date)} 来跑——"
            "就是销售在这一天核销的到账，对吗？请回复“确认”，日期不对就直接告诉我新日期。",
            source,
        )
        return
    if action == "confirm_date":
        if workflow.stage != "awaiting_date_confirmation" or not workflow.reconciliation_date:
            _message(db, workflow, "assistant", _status_reply(workflow), source)
            return
        workflow.stage = "awaiting_files"
        workflow.state = "active"
        workflow.progress_message = "等待智云凭据和两类财务表"
        ready, _ = _has_required_files(workflow)
        if ready:
            message = (
                "日期已确认。已复用上次保存的年度盈亏核算表和到账流转表，不需要再次上传；"
                "如需更换到账流转表或增加年度盈亏表，请在下方上传，准备好后回复“上传好了”。"
            )
        else:
            message = (
                "日期已确认。请在右侧安全保存智云账号，并上传年度盈亏核算表和到账流转表；"
                "准备好后回复“上传好了”。"
            )
        _message(
            db,
            workflow,
            "assistant",
            message,
            source,
        )
        return
    if action == "prepare_worklist":
        if workflow.stage not in {"awaiting_files", "failed"}:
            _message(db, workflow, "assistant", _status_reply(workflow), source)
            return
        ready, missing = _has_required_files(workflow)
        if not ready:
            _message(
                db,
                workflow,
                "assistant",
                "还缺："
                + "、".join(FILE_ROLE_LABELS.get(item, item) for item in missing)
                + "。上传后再说“上传好了”。",
                source,
            )
            return
        if not has_service_credential(
            db,
            workflow.owner_id,
            workflow.department_id,
            "zhiyun",
        ):
            _message(
                db,
                workflow,
                "assistant",
                "还缺智云账号。请先在右侧“智云自动取数”中安全保存账号和密码，再回复“上传好了”。",
                source,
            )
            return
        workflow.context_json = "{}"
        workflow.artifacts_json = "[]"
        if not workflow.material_set_id:
            normalized = _attach_material_snapshot(
                db,
                workflow,
                actor,
                _canonicalize_file_bindings(_load(workflow.files_json, {})),
            )
            workflow.files_json = _json(normalized)
        _queue_action(db, workflow, "prepare_worklist")
        workflow.stage = "preparing"
        workflow.state = "running"
        workflow.progress = 5
        workflow.progress_message = "已排队，准备生成核销日清"
        workflow.error_message = ""
        _message(
            db,
            workflow,
            "assistant",
            f"材料已收到，开始生成 {_date_label(workflow.reconciliation_date)} 的《核销日清》。"
            "在我明确说清单已生成前，不会写盈亏表或流转表。",
            source,
        )
        return
    if action == "confirm_apply":
        if workflow.stage not in {"awaiting_apply_confirmation", "waiting_approval"}:
            _message(db, workflow, "assistant", _status_reply(workflow), source)
            return
        # Older tasks may still be persisted in waiting_approval from the
        # previous release.  Treat that state as a compatibility alias and
        # invalidate its historical approval record before queuing the write.
        if workflow.stage == "waiting_approval":
            revoke_workflow_approvals(db, workflow, actor, "平台已取消管理员审批流程。")
        _queue_action(db, workflow, "apply_confirmed")
        workflow.stage = "applying"
        workflow.state = "running"
        workflow.progress = max(workflow.progress, 83)
        workflow.progress_message = "已确认，等待执行写入"
        workflow.error_message = ""
        _message(
            db,
            workflow,
            "assistant",
            "已收到写入确认。现在执行：先写盈亏明细，再写流转安全子集，随后回读校验。",
            source,
        )
        return
    if action == "rebuild_worklist":
        if workflow.stage in BUSY_STAGES:
            _message(db, workflow, "assistant", "当前动作还在执行，完成后才能重出清单。", source)
            return
        ready, _ = _has_required_files(workflow)
        has_credential = has_service_credential(
            db,
            workflow.owner_id,
            workflow.department_id,
            "zhiyun",
        )
        if not ready or not has_credential or not workflow.reconciliation_date:
            workflow.stage = "awaiting_files" if workflow.reconciliation_date else "awaiting_date"
            workflow.state = "active"
            _message(db, workflow, "assistant", _status_reply(workflow), source)
            return
        revoke_workflow_approvals(db, workflow, actor, "发起人重新生成变更预览。")
        _queue_action(db, workflow, "prepare_worklist")
        workflow.context_json = "{}"
        workflow.artifacts_json = "[]"
        workflow.stage = "preparing"
        workflow.state = "running"
        workflow.progress = 5
        workflow.progress_message = "正在以原始上传文件生成新的核销日清"
        workflow.error_message = ""
        _message(
            db,
            workflow,
            "assistant",
            "旧任务结果不会继续写入；正在以原始上传文件创建新的日清工作区。",
            source,
        )
        return
    if action == "cancel":
        _request_workflow_cancellation(db, workflow, actor)
        return
    _message(db, workflow, "assistant", _status_reply(workflow), source)


@dataclass(frozen=True)
class WorkflowAgentActionResult:
    action: str
    await_confirmation: bool
    confirmation_kind: str
    message: str


def apply_workflow_agent_action(
    db: Session,
    workflow: WorkflowSession,
    action: str,
    arguments: dict[str, Any],
    actor: UserContext,
) -> WorkflowAgentActionResult:
    """Apply one Pi-requested workflow action without exposing execution internals."""
    assert_workflow_execution_enabled(workflow)
    assert_workflow_agent_action_enabled(workflow.skill_id, action)
    decision = validate_workflow_agent_request(workflow.stage, action, arguments)
    if decision.action == "request_user_confirmation":
        kind = str(decision.arguments["kind"])
        default_message = (
            f"当前核销日期是 {_date_label(workflow.reconciliation_date)}，请确认日期。"
            if kind == "date"
            else "《核销日清》已生成，请检查预览后确认是否继续。"
        )
        message = str(decision.arguments.get("message") or default_message)
        _message(
            db,
            workflow,
            "assistant",
            message,
            {
                "kind": "agent_confirmation_request",
                "await_confirmation": True,
                "confirmation_kind": kind,
            },
        )
    else:
        if decision.action == "cancel":
            db.commit()
            acquire_claim_lock(db)
            db.refresh(workflow)
        _apply_decision(db, workflow, decision, actor)

    db.commit()
    return WorkflowAgentActionResult(
        action=action,
        await_confirmation=decision.action == "request_user_confirmation"
        or action == "set_reconciliation_date",
        confirmation_kind=(
            str(decision.arguments.get("kind", "date"))
            if action == "set_reconciliation_date"
            else str(decision.arguments.get("kind", ""))
        ),
        message=_status_reply(workflow),
    )


def send_workflow_message(
    db: Session,
    workflow: WorkflowSession,
    content: str,
    user: UserContext,
) -> WorkflowSession:
    assert_workflow_execution_enabled(workflow)
    _message(db, workflow, "user", content)
    db.flush()
    recent = list(
        db.scalars(
            select(WorkflowMessage)
            .where(WorkflowMessage.workflow_id == workflow.id)
            .order_by(WorkflowMessage.id.desc())
            .limit(20)
        ).all()
    )
    history = [
        {"role": item.role, "content": item.content}
        for item in reversed(recent)
        if item.role in {"user", "assistant"}
    ]
    llm = (
        None
        if is_background_model_connection(workflow.model_connection_id)
        else resolve_runtime_config(
            db,
            user,
            workflow.model_connection_id,
            workflow.model_name,
        )
    )
    decision = decide_workflow_turn(
        llm,
        workflow.stage,
        content,
        workflow.reconciliation_date,
        history,
    )
    if decision.action == "confirm_date" and not _is_explicit_confirmation(
        content,
        apply=False,
    ):
        decision = WorkflowDecision("show_status", {}, "backend_guard")
    if decision.action == "confirm_apply" and not _is_explicit_confirmation(
        content,
        apply=True,
    ):
        decision = WorkflowDecision("show_status", {}, "backend_guard")
    if decision.action == "cancel":
        db.commit()
        acquire_claim_lock(db)
        db.refresh(workflow)
    _apply_decision(db, workflow, decision, user)
    db.commit()
    db.refresh(workflow)
    return workflow


def claim_next_workflow_action(
    db: Session,
    pools: tuple[str, ...],
    worker_id: str = "workflow-worker",
) -> WorkflowAction | None:
    if "workflow" not in pools:
        return None
    acquire_claim_lock(db)
    now = datetime.now(UTC)
    recover_expired_jobs(db, now)
    candidates = list(
        db.scalars(
            select(WorkflowAction)
            .join(WorkflowSession, WorkflowSession.id == WorkflowAction.workflow_id)
            .outerjoin(WorkflowBatch, WorkflowBatch.id == WorkflowSession.batch_id)
            .where(
                WorkflowAction.state == "queued",
                or_(
                    and_(
                        WorkflowSession.state.in_(("active", "running")),
                        WorkflowSession.stage.in_(BUSY_STAGES),
                    ),
                    and_(
                        WorkflowAction.name == "finalize_batch",
                        WorkflowSession.state == "succeeded",
                        WorkflowSession.stage == "completed",
                        WorkflowBatch.state == "finalizing",
                    ),
                ),
            )
            .order_by(WorkflowAction.queued_at.asc())
            .limit(100)
        ).all()
    )
    selected: WorkflowAction | None = None
    for action in candidates:
        workflow = db.get(WorkflowSession, action.workflow_id)
        if not workflow:
            action.state = "failed"
            action.error_message = "对话任务不存在。"
            action.finished_at = now
            continue
        if active_task_discovery_count(db, workflow.skill_id, now):
            continue
        if action.name == "finalize_batch" and workflow.stage == "completed":
            batch = db.get(WorkflowBatch, workflow.batch_id) if workflow.batch_id else None
            if batch and batch.state == "finalizing":
                context = _load(workflow.context_json, {})
                context["current_step"] = "finalize_batch"
                context["current_step_label"] = "正在生成范围报告"
                workflow.context_json = _json(context)
                workflow.state = "running"
                workflow.stage = "finalizing"
                workflow.progress = 99
                workflow.progress_message = "每日核销已完成，正在生成范围报告"
        if active_workflow_count(db, workflow.skill_id, now) >= max(1, workflow.concurrency_limit):
            continue
        action.state = "running"
        action.started_at = now
        action.worker_id = worker_id
        action.attempt_count += 1
        action.heartbeat_at = now
        action.lease_expires_at = lease_deadline(now)
        selected = action
        break
    db.commit()
    return selected


def _copy_inputs(
    db: Session,
    action: WorkflowAction,
    workflow: WorkflowSession,
    business: Path,
) -> dict[str, list[Path]]:
    payload = _load(action.input_json, {})
    copied: dict[str, list[Path]] = {}
    files = _canonicalize_file_bindings(payload.get("files", {}))
    for role, folder_name in FILE_ROLES.items():
        target_dir = business / folder_name
        target_dir.mkdir(parents=True, exist_ok=True)
        for item in files.get(role, []):
            file_id = _entry_file_id(item)
            record = db.get(FileRecord, file_id)
            if not record:
                raise RuntimeError(f"输入记录不存在：{file_id}")
            batch_output = isinstance(item, dict) and bool(item.get("batch_output"))
            material_output = (
                isinstance(item, dict)
                and record.kind == "output"
                and material_binding_is_allowed_output(db, workflow, item, record)
            )
            output_allowed = (
                record.kind == "output"
                and (batch_output or material_output)
                and Path(record.stored_path)
                .resolve()
                .is_relative_to(settings.workflow_dir.resolve())
            )
            if record.owner_id != workflow.owner_id or (
                record.kind != "input" and not output_allowed
            ):
                raise RuntimeError(f"输入文件所有者校验失败：{record.id}")
            source = Path(record.stored_path).resolve()
            if not source.is_file() or sha256_file(source) != record.sha256:
                raise RuntimeError(f"输入文件完整性校验失败：{record.id}")
            target = target_dir / safe_filename(record.original_name)
            if target.exists():
                target = target_dir / f"{target.stem}_{record.id[:8]}{target.suffix}"
            shutil.copy2(source, target)
            copied.setdefault(role, []).append(target.resolve())
    for folder_name in ("03_台账", "04_产出"):
        (business / folder_name).mkdir(parents=True, exist_ok=True)
    return copied


def _run_script(
    script_dir: Path,
    script_name: str,
    arguments: list[str],
    timeout: int = 900,
    stdin_data: str | None = None,
    sensitive_values: tuple[str, ...] = (),
    extra_env: dict[str, str] | None = None,
    accepted_returncodes: tuple[int, ...] = (0,),
) -> str:
    command = [sys.executable, str(script_dir / script_name), *arguments]
    env = subprocess_base_environment()
    env.update(extra_env or {})
    completed = subprocess.run(
        command,
        cwd=script_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=stdin_data,
        timeout=timeout,
        env=env,
        check=False,
    )
    if completed.returncode not in accepted_returncodes:
        details = (completed.stderr or completed.stdout).strip()
        for value in sensitive_values:
            if value:
                details = details.replace(value, "[已隐藏]")
        suffix = f"：{details[-1200:]}" if details else ""
        raise RuntimeError(f"{script_name} 执行失败（退出码 {completed.returncode}）{suffix}")
    return completed.stdout


TRANSIENT_FETCH_FAILURE = re.compile(
    r"(?:\b408\b|\b429\b|\b5\d\d\b|bad gateway|timeout|connectionerror|urlerror)",
    re.IGNORECASE,
)


def _secure_fetch_timeout_seconds(
    date_count: int,
    runtime_timeout_seconds: int,
) -> int:
    """Budget range fetches by pending day without outliving the Skill runtime."""
    days = max(1, int(date_count))
    runtime_budget = max(60, int(runtime_timeout_seconds) - 60)
    requested = max(600, 300 + 90 * days)
    return min(requested, runtime_budget)


def _run_secure_fetch_with_retry(
    script_dir: Path,
    *,
    stdin_data: str,
    sensitive_values: tuple[str, ...],
    extra_env: dict[str, str],
    legacy_outer_retry: bool,
    timeout_seconds: int = 600,
) -> str:
    """Retry the immutable pre-1.6.4 read-only fetch snapshot on transient failures."""
    attempts = 3 if legacy_outer_retry else 1
    for attempt in range(1, attempts + 1):
        try:
            return _run_script(
                script_dir,
                "fetch_secure.py",
                [],
                timeout=max(60, int(timeout_seconds)),
                stdin_data=stdin_data,
                sensitive_values=sensitive_values,
                extra_env=extra_env,
            )
        except RuntimeError as exc:
            if attempt >= attempts or not TRANSIENT_FETCH_FAILURE.search(str(exc)):
                raise
            time.sleep(float(2 ** (attempt - 1)))
    raise RuntimeError("智云只读取数未执行。")  # pragma: no cover


def _needs_legacy_fetch_retry(skill_version: str) -> bool:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", str(skill_version or ""))
    return bool(match and tuple(map(int, match.groups())) < (1, 6, 4))


def _register_artifact(
    db: Session,
    workflow: WorkflowSession,
    source: Path,
    action_id: str,
) -> dict[str, Any]:
    root = workflow_root(workflow.owner_id, workflow.id)
    allowed_source_root = _workflow_storage_root(db, workflow)
    source = source.resolve()
    if not source.is_file() or not source.is_relative_to(allowed_source_root):
        raise RuntimeError("工作流产物必须位于当前会话目录。")
    delivery = root / "outputs" / action_id
    delivery.mkdir(parents=True, exist_ok=True)
    target = delivery / safe_filename(source.name)
    if target.exists() and source != target:
        digest = sha256_file(source)[:8]
        target = delivery / f"{target.stem}_{digest}{target.suffix}"
    if source != target:
        shutil.copy2(source, target)
    record = FileRecord(
        id=str(uuid.uuid4()),
        owner_id=workflow.owner_id,
        department_id=workflow.department_id,
        kind="output",
        original_name=target.name,
        stored_path=str(target.resolve()),
        content_type="application/octet-stream",
        size_bytes=target.stat().st_size,
        sha256=sha256_file(target),
        skill_id=workflow.skill_id,
        skill_name=workflow.skill_name,
        skill_version=workflow.skill_version,
        workflow_id=workflow.id,
    )
    db.add(record)
    db.flush()
    return {
        "name": record.original_name,
        "file_id": record.id,
        "kind": record.kind,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "download_url": f"/api/files/{record.id}/download",
        "action_id": action_id,
    }


def _discard_registered_artifacts(
    db: Session,
    workflow: WorkflowSession,
    artifacts: list[dict[str, Any]],
    action_id: str,
) -> None:
    if not artifacts:
        return
    delivery = (workflow_root(workflow.owner_id, workflow.id) / "outputs" / action_id).resolve()
    for artifact in artifacts:
        file_id = str(artifact.get("file_id", ""))
        record = db.get(FileRecord, file_id) if file_id else None
        if not record:
            continue
        stored = Path(record.stored_path).resolve()
        if stored.is_file() and stored.is_relative_to(delivery):
            stored.unlink()
        db.delete(record)
    db.flush()
    if delivery.exists() and not any(delivery.iterdir()):
        delivery.rmdir()


def _worklist_summary(stdout: str) -> dict[str, int]:
    summary: dict[str, int] = {}
    line = next((item for item in stdout.splitlines() if "《核销日清》已生成：" in item), "")
    for label in ("今天要填", "已填过·跳过", "冲突·需你定", "挂账待办", "异常"):
        match = re.search(rf"{re.escape(label)}\s+(\d+)", line)
        if match:
            summary[label] = int(match.group(1))
    flow = next((item for item in stdout.splitlines() if item.startswith("流转：")), "")
    for label in ("确认后自动写", "须手填", "跳过"):
        match = re.search(rf"{label}\s+(\d+)", flow)
        if match:
            summary[f"流转{label}"] = int(match.group(1))
    return summary


def _discover_annual_ledger_paths(business: Path) -> dict[int, Path]:
    """Return every annual P&L copy, rejecting ambiguous duplicate years."""
    base = business / "02_我的表副本"
    by_year: dict[int, Path] = {}
    for path in sorted(base.glob("*盈亏*.xls*")):
        if (
            not path.is_file()
            or path.name.startswith(("~$", "."))
            or "便携版" in path.stem
        ):
            continue
        match = re.search(r"(?<!\d)(20\d{2})(?:年)?", path.stem)
        year = int(match.group(1)) if match else _platform_today().year
        resolved = path.resolve()
        previous = by_year.get(year)
        if previous and previous != resolved:
            raise RuntimeError(
                f"检测到两份 {year} 年盈亏表：{previous.name}、{resolved.name}；"
                "每个年度只能上传一份权威工作副本。"
            )
        by_year[year] = resolved
    return dict(sorted(by_year.items()))


def _annual_ledger_arguments(ledgers: dict[int, Path]) -> list[str]:
    arguments: list[str] = []
    for year, path in sorted(ledgers.items()):
        arguments.extend(["--ledger-year", f"{year}={path}"])
    return arguments


def _staged_workspace_path(
    source_workspace: Path,
    staging_workspace: Path,
    source_path: Path,
) -> Path:
    """Map a prepared-workspace file to its isolated write-staging counterpart."""
    source_path = source_path.resolve()
    if not source_path.is_relative_to(source_workspace):
        raise RuntimeError("写入文件超出当前工作区，请重新生成核销日清。")
    return (staging_workspace / source_path.relative_to(source_workspace)).resolve()


def _rewrite_workspace_paths_for_staging(
    value: Any,
    source_workspace: Path,
    staging_workspace: Path,
) -> Any:
    """Rewrite absolute paths in the checked plan so apply_all cannot reach source copies."""
    if isinstance(value, dict):
        return {
            key: _rewrite_workspace_paths_for_staging(item, source_workspace, staging_workspace)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _rewrite_workspace_paths_for_staging(item, source_workspace, staging_workspace)
            for item in value
        ]
    if not isinstance(value, str):
        return value
    candidate = Path(value)
    if not candidate.is_absolute():
        return value
    resolved = candidate.resolve()
    if not resolved.is_relative_to(source_workspace):
        return value
    return str(_staged_workspace_path(source_workspace, staging_workspace, resolved))


def _rewrite_staged_checked_plan(
    checked_plan: Path,
    source_workspace: Path,
    staging_workspace: Path,
) -> None:
    plan = _load(checked_plan.read_text(encoding="utf-8"), None)
    if not isinstance(plan, (dict, list)):
        raise RuntimeError("校验后写入计划格式无效，请重新生成核销日清。")
    staged_plan = _rewrite_workspace_paths_for_staging(plan, source_workspace, staging_workspace)
    checked_plan.write_text(_json(staged_plan), encoding="utf-8")


def _create_write_staging(source_workspace: Path, action_id: str) -> Path:
    """Copy a read-only prepared workspace into the only location allowed to mutate."""
    staging_root = source_workspace / WRITE_STAGING_DIR
    staging_workspace = staging_root / action_id
    if staging_workspace.exists():
        raise RuntimeError("本次写入暂存区已存在，请重新生成核销日清后再执行。")
    staging_root.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(
            source_workspace,
            staging_workspace,
            ignore=shutil.ignore_patterns(WRITE_STAGING_DIR, "__pycache__", ".pytest_cache"),
        )
    except Exception:
        shutil.rmtree(staging_workspace, ignore_errors=True)
        if staging_root.exists() and not any(staging_root.iterdir()):
            staging_root.rmdir()
        raise
    return staging_workspace.resolve()


def _discard_write_staging(source_workspace: Path, staging_workspace: Path) -> None:
    staging_root = (source_workspace / WRITE_STAGING_DIR).resolve()
    staging_workspace = staging_workspace.resolve()
    if not staging_workspace.is_relative_to(staging_root) or staging_workspace == staging_root:
        raise RuntimeError("写入暂存区路径无效，拒绝清理。")
    shutil.rmtree(staging_workspace, ignore_errors=True)
    if staging_root.exists() and not any(staging_root.iterdir()):
        staging_root.rmdir()


def _write_publish_manifest(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _rollback_batch_publish_transaction(source_workspace: Path, transaction: Path) -> None:
    manifest_path = transaction / "manifest.json"
    if not manifest_path.is_file():
        shutil.rmtree(transaction, ignore_errors=True)
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("state") == "completed":
        shutil.rmtree(transaction, ignore_errors=True)
        return
    if manifest.get("state") != "prepared":
        shutil.rmtree(transaction, ignore_errors=True)
        return
    for entry in manifest.get("files") or []:
        relative = Path(str(entry.get("target") or ""))
        target = (source_workspace / relative).resolve()
        if not relative.parts or not target.is_relative_to(source_workspace):
            raise RuntimeError("批次发布事务包含越界目标，拒绝恢复。")
        backup_name = str(entry.get("backup") or "")
        if entry.get("existed"):
            backup = (transaction / backup_name).resolve()
            if not backup.is_file() or not backup.is_relative_to(transaction):
                raise RuntimeError("批次发布事务缺少恢复副本，拒绝继续。")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.rollback.tmp")
            shutil.copy2(backup, temporary)
            os.replace(temporary, target)
        else:
            target.unlink(missing_ok=True)
    shutil.rmtree(transaction, ignore_errors=True)


def _recover_batch_publish_transactions(source_workspace: Path) -> None:
    root = source_workspace / BATCH_PUBLISH_TRANSACTION_DIR
    if not root.is_dir():
        return
    for transaction in sorted(path for path in root.iterdir() if path.is_dir()):
        _rollback_batch_publish_transaction(source_workspace, transaction)
    if root.exists() and not any(root.iterdir()):
        root.rmdir()


def _promote_batch_staging(source_workspace: Path, staging_workspace: Path) -> None:
    """Publish verified batch files with a rollback journal and completion marker."""
    source_workspace = source_workspace.resolve()
    staging_workspace = staging_workspace.resolve()
    _recover_batch_publish_transactions(source_workspace)
    relative_files: list[Path] = []
    for directory_name in ("02_我的表副本", "03_台账", "04_产出"):
        source = staging_workspace / directory_name
        if source.is_dir():
            relative_files.extend(
                path.relative_to(staging_workspace)
                for path in source.rglob("*")
                if path.is_file()
                and not path.name.endswith((".lock", ".tmp"))
                and not path.name.startswith("~$")
            )
    if not relative_files:
        return
    transaction_root = source_workspace / BATCH_PUBLISH_TRANSACTION_DIR
    transaction = transaction_root / staging_workspace.name
    transaction.mkdir(parents=True, exist_ok=False)
    entries: list[dict[str, Any]] = []
    try:
        for index, relative in enumerate(sorted(relative_files, key=lambda item: str(item))):
            source = staging_workspace / relative
            target = source_workspace / relative
            entry: dict[str, Any] = {
                "target": str(relative),
                "sha256": sha256_file(source),
                "existed": target.is_file(),
                "backup": "",
            }
            if target.is_file():
                backup_relative = Path("backups") / f"{index:05d}.bak"
                backup = transaction / backup_relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                entry["backup"] = str(backup_relative)
            entries.append(entry)
        manifest = {"state": "prepared", "files": entries}
        _write_publish_manifest(transaction / "manifest.json", manifest)
        for relative, entry in zip(
            sorted(relative_files, key=lambda item: str(item)), entries, strict=True
        ):
            source = staging_workspace / relative
            target = source_workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{staging_workspace.name}.tmp")
            try:
                shutil.copy2(source, temporary)
                if sha256_file(temporary) != entry["sha256"]:
                    raise RuntimeError(f"批次发布复制校验失败：{relative}")
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        manifest["state"] = "completed"
        _write_publish_manifest(transaction / "manifest.json", manifest)
    except Exception:
        _rollback_batch_publish_transaction(source_workspace, transaction)
        if transaction_root.exists() and not any(transaction_root.iterdir()):
            transaction_root.rmdir()
        raise
    else:
        shutil.rmtree(transaction, ignore_errors=True)
        if transaction_root.exists() and not any(transaction_root.iterdir()):
            transaction_root.rmdir()


def _assert_valid_xlsx_package(path: Path) -> None:
    """Reject a downloadable xlsx whose OOXML package or XML tree cannot be opened."""
    if path.suffix.lower() != ".xlsx":
        return
    try:
        with zipfile.ZipFile(path) as package:
            names = set(package.namelist())
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                raise RuntimeError("缺少 Excel 工作簿结构。")
            if package.testzip() is not None:
                raise RuntimeError("Excel 压缩包校验失败。")
        workbook = load_workbook(path, read_only=True, data_only=False)
        workbook.close()
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"结果工作簿无法打开：{path.name}") from exc


def _assert_static_report(path: Path) -> None:
    """Audit reports must have values/text only; ledger formulas are checked separately."""
    _assert_valid_xlsx_package(path)
    if path.suffix.lower() != ".xlsx":
        return
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows():
                if any(cell.data_type == "f" for cell in row):
                    raise RuntimeError(f"审计报表仍含公式：{path.name}")
    finally:
        workbook.close()


def _validate_staged_delivery(
    staging_workspace: Path,
    ledgers: dict[int, Path],
    flow_file: Path,
) -> None:
    """Validate every deliverable before it is copied to the task output area."""
    worklists = sorted((staging_workspace / "04_产出").glob("核销日清_*.xlsx"))
    if not worklists:
        raise RuntimeError("写入结果缺少《核销日清》，拒绝发布。")
    reports = [
        path
        for path in (staging_workspace / "04_产出").glob("*.xlsx")
        if any(label in path.name for label in ("核销日清", "变更清单", "订单写入差异"))
    ]
    for report in reports:
        _assert_static_report(report)
    for path in [*ledgers.values(), flow_file]:
        _assert_valid_xlsx_package(path)


def _prepare_worklist(
    db: Session,
    action: WorkflowAction,
    workflow: WorkflowSession,
) -> dict[str, Any]:
    root = workflow_root(workflow.owner_id, workflow.id)
    if not (root / "skill").is_dir():
        _ensure_workflow_skill_snapshot(db, workflow)
    storage_root = _workflow_storage_root(db, workflow)
    batch = (
        db.get(WorkflowBatch, workflow.batch_id) if getattr(workflow, "batch_id", None) else None
    )
    batch_dates = (
        _load(batch.reconciliation_dates_json, [])
        if batch is not None
        else [workflow.reconciliation_date]
    )
    action_input = _load(getattr(action, "input_json", "{}"), {})
    action_input = action_input if isinstance(action_input, dict) else {}
    action_context = action_input.get("context", {})
    action_context = action_context if isinstance(action_context, dict) else {}
    resume_existing_workspace = bool(action_input.get("resume_existing_workspace"))
    snapshot_workflow_id = str(
        action_input.get("snapshot_workflow_id")
        or action_context.get("snapshot_workflow_id")
        or ""
    ).strip()
    fetched_data = action_context.get("fetched_data", {})
    fetched_data = fetched_data if isinstance(fetched_data, dict) else {}
    resume_after_review = fetched_data.get("review_status") == "confirmed"
    if (
        batch is not None
        and resume_after_review
        and _is_confirmed_empty_reconciliation_date(fetched_data, workflow.reconciliation_date)
    ):
        raw_workspace = action_context.get("workspace") or ""
        business = Path(raw_workspace).resolve() if isinstance(raw_workspace, str) else Path()
        if not business.is_dir() or not business.is_relative_to(storage_root):
            raise RuntimeError("批次工作区不存在，无法安全跳过空日期。")
        return {
            "workspace": str(business),
            "next_files": _canonicalize_file_bindings(_load(workflow.files_json, {})),
            "material_set_id": workflow.material_set_id,
            "material_version": action_context.get("material_version"),
            "empty_day_skipped": True,
            "artifacts": [],
        }
    if resume_after_review:
        raw_workspace = action_context.get("workspace", "")
        business = Path(raw_workspace).resolve() if isinstance(raw_workspace, str) else Path()
        if not business.is_dir() or not business.is_relative_to(storage_root):
            raise RuntimeError("取数检查工作区不存在，请重新生成日清。")
        copied_files: dict[str, list[Path]] = {}
    else:
        business = (
            storage_root / "batch" / str(workflow.batch_id) / "工作区"
            if getattr(workflow, "batch_id", None)
            else root / "actions" / action.id / "工作区"
        )
        business = business.resolve()
        if not business.is_relative_to(storage_root):
            raise RuntimeError("任务工作区不在平台受控目录中。")

        def persist_workspace_state(state: str) -> None:
            current = _load(getattr(workflow, "context_json", "{}"), {})
            current = current if isinstance(current, dict) else {}
            current["workspace"] = str(business)
            current["workspace_state"] = state
            workflow.context_json = _json(current)
            db.commit()

        copied_inputs_now = False
        if resume_existing_workspace:
            raw_workspace = action_context.get("workspace", "")
            requested = (
                Path(raw_workspace).resolve()
                if isinstance(raw_workspace, str) and raw_workspace
                else Path()
            )
            if requested != business or not business.is_dir():
                raise RuntimeError("失败批次的共享工作区不可安全复用，请由管理员检查。")
            if action_context.get("workspace_state") == "copying_inputs":
                # 复制输入时失败的目录不是有效基线；它尚未开始取数，可以安全重建。
                shutil.rmtree(business)
                business.mkdir(parents=True, exist_ok=False)
                persist_workspace_state("copying_inputs")
                _set_progress_step(db, workflow, "copy_inputs", "正在重新复制平台文件", 7)
                copied_files = _copy_inputs(db, action, workflow, business) or {}
                copied_inputs_now = True
            else:
                copied_files = {}
                _set_progress_step(db, workflow, "copy_inputs", "正在复用失败批次的工作区", 7)
        else:
            persist_workspace_state("copying_inputs")
            business.mkdir(parents=True, exist_ok=False)
            _set_progress_step(db, workflow, "copy_inputs", "正在读取并复制平台文件", 7)
            copied_files = _copy_inputs(db, action, workflow, business) or {}
            copied_inputs_now = True
        if copied_inputs_now:
            # File hashing and copying can be slow for annual workbooks.  Preserve
            # a cancellation requested during that work before this session writes
            # workspace/fetching metadata back to the workflow context.
            db.commit()
            acquire_claim_lock(db)
            db.refresh(workflow)
            persist_workspace_state("inputs_ready")
    ledgers = _discover_annual_ledger_paths(business)
    if not ledgers:
        raise RuntimeError("没有找到盈亏核算表副本。")
    flow_files = copied_files.get(RECEIPT_FLOW_ROLE, [])
    if len(flow_files) != 1:
        flow_files = sorted(
            {
                path.resolve()
                for pattern in ("*到账*.xls*", "*流转*.xls*")
                for path in (business / "02_我的表副本").glob(pattern)
                if path.is_file() and "便携版" not in path.name
            }
        )
    if len(flow_files) != 1:
        raise RuntimeError("没有找到唯一的到账流转表副本。")
    ledger_arguments = _annual_ledger_arguments(ledgers)
    script_dir = root / "skill" / "vendor" / "scripts"
    if not (script_dir / "classify_hexiao.py").is_file():
        raise RuntimeError("应收核销脚本包不完整。")
    workspace = str(business.resolve())
    hexiao_date = workflow.reconciliation_date
    if not resume_after_review:
        _discard_workspace_fetched_snapshot(storage_root, business)
        context = _load(getattr(workflow, "context_json", "{}"), {})
        context["workspace"] = workspace
        context["fetched_data"] = {
            "available": False,
            "reconciliation_date": hexiao_date,
            "date_from": batch_dates[0],
            "date_to": batch_dates[-1],
            "dates": batch_dates,
            "review_status": "fetching",
        }
        if snapshot_workflow_id:
            snapshot_user = UserContext(
                user_id=workflow.owner_id,
                display_name=workflow.owner_name,
                role="finance_user",
                department_id=workflow.department_id,
            )
            snapshot = _copy_fetched_snapshot(
                db,
                snapshot_workflow_id,
                batch_dates,
                business,
                snapshot_user,
            )
            fetched_data = {
                "available": True,
                "source": "snapshot",
                "snapshot_workflow_id": snapshot["source_workflow_id"],
                "reconciliation_date": hexiao_date,
                "date_from": batch_dates[0],
                "date_to": batch_dates[-1],
                "dates": batch_dates,
                "review_status": "waiting",
                "summary": snapshot["summary_by_date"].get(hexiao_date, {}),
                "summary_by_date": snapshot["summary_by_date"],
                "supplement_history": [],
            }
            context["fetched_data"] = fetched_data
            context["snapshot_workflow_id"] = snapshot["source_workflow_id"]
            context["workspace_state"] = "inputs_ready"
            if hasattr(workflow, "context_json"):
                workflow.context_json = _json(context)
            workflow.progress = 10
            _set_progress_step(db, workflow, "fetch_zhiyun", "已加载本地取数快照，等待人工检查", 10)
            db.commit()
            return {
                "workspace": workspace,
                "ledger_years": {str(year): str(path) for year, path in ledgers.items()},
                "flow_file": str(flow_files[0]),
                "fetched_data": fetched_data,
                "awaiting_fetched_data_confirmation": True,
                "artifacts": [],
            }
        if hasattr(workflow, "context_json"):
            workflow.context_json = _json(context)
        db.commit()
        runtime = load_workflow_manifest(workflow).runtime
        network_env = skill_subprocess_environment(runtime)
        if settings.zhiyun_base_url:
            assert_url_allowed(settings.zhiyun_base_url, runtime)
            network_env["ZHIYUN_BASE"] = settings.zhiyun_base_url
        account, password = resolve_service_credential(
            db,
            workflow.owner_id,
            workflow.department_id,
            "zhiyun",
        )
        workflow.progress = 10
        _set_progress_step(db, workflow, "fetch_zhiyun", "正在登录智云并按核销日期自动取数", 10)
        try:
            fetch_payload: dict[str, Any] = {
                "account": account,
                "password": password,
                "workspace": workspace,
            }
            if len(batch_dates) > 1:
                fetch_payload.update({"date_from": batch_dates[0], "date_to": batch_dates[-1]})
            else:
                fetch_payload["reconciliation_date"] = hexiao_date
            _run_secure_fetch_with_retry(
                script_dir,
                stdin_data=_json(fetch_payload),
                sensitive_values=(account, password),
                extra_env=network_env,
                legacy_outer_retry=_needs_legacy_fetch_retry(
                    getattr(workflow, "skill_version", "")
                ),
                timeout_seconds=_secure_fetch_timeout_seconds(
                    (date.fromisoformat(batch_dates[-1]) - date.fromisoformat(batch_dates[0])).days
                    + 1,
                    runtime.timeout_seconds,
                ),
            )
        finally:
            password = ""
        # The user may cancel while fetch_secure.py is running.  Reload under
        # the same lock used by the claim/cancel paths before adding fetched
        # data, otherwise this stale worker session can erase stop_after_action.
        db.commit()
        acquire_claim_lock(db)
        db.refresh(workflow)
        fetched_data = {
            "available": True,
            "reconciliation_date": hexiao_date,
            "date_from": batch_dates[0],
            "date_to": batch_dates[-1],
            "dates": batch_dates,
            "review_status": "waiting",
            "summary": _fetched_summary_from_export(business / "01_智云导出", hexiao_date),
            "summary_by_date": {
                item: _fetched_summary_from_export(business / "01_智云导出", item)
                for item in batch_dates
            },
            "supplement_history": [],
        }
        context = _load(getattr(workflow, "context_json", "{}"), {})
        context["fetched_data"] = fetched_data
        if hasattr(workflow, "context_json"):
            workflow.context_json = _json(context)
        db.commit()
        return {
            "workspace": workspace,
            "ledger_years": {str(year): str(path) for year, path in ledgers.items()},
            "flow_file": str(flow_files[0]),
            "fetched_data": fetched_data,
            "awaiting_fetched_data_confirmation": True,
            "artifacts": [],
        }
    if batch is not None and workflow.batch_sequence == 1:
        _set_progress_step(db, workflow, "audit_shifted_details", "正在审计跨日迁移明细", 22)
        # The audit uses exit code 1 for a business finding: selected dates need
        # shifted details restored by the per-date classification steps below.
        _run_script(
            script_dir,
            "audit_shifted_details.py",
            [
                "--workspace",
                workspace,
                "--date-from",
                batch_dates[0],
                "--date-to",
                batch_dates[-1],
                *[part for item in batch_dates for part in ("--date", item)],
            ],
            accepted_returncodes=(0, 1),
        )
    steps = [
        (
            "inspect_inputs.py",
            ["--workspace", workspace],
            "inspect_inputs",
            "正在检查输入文件和字段",
        ),
        (
            "verify_sources.py",
            ["snapshot", "--workspace", workspace],
            "snapshot_sources",
            "正在建立工作副本校验基线",
        ),
        (
            "classify_hexiao.py",
            ["--workspace", workspace, "--hexiao-date", hexiao_date, *ledger_arguments],
            "classify_receipts",
            "正在按核销日期判定回款和订单",
        ),
        (
            "build_flow_plan.py",
            ["--workspace", workspace, "--hexiao-date", hexiao_date],
            "build_flow_plan",
            "正在生成到账流转写入计划",
        ),
        (
            "apply_flow.py",
            [
                "--plan",
                str(business / "04_产出" / "流转写入计划_校验后.json"),
                "--workspace",
                workspace,
                "--phase",
                "prefill",
                "--in-place",
            ],
            "prefill_flow",
            "正在登记流转表 SO 和交付金额",
        ),
        (
            "verify_sources.py",
            ["snapshot", "--workspace", workspace],
            "snapshot_prefilled_sources",
            "正在记录流转前置登记后的校验基线",
        ),
        (
            "validate_plan.py",
            ["--workspace", workspace, "--hexiao-date", hexiao_date, *ledger_arguments],
            "validate_plan",
            "正在校验盈亏写入计划",
        ),
    ]
    for index, (script, arguments, step_key, label) in enumerate(steps, start=1):
        _set_progress_step(
            db,
            workflow,
            step_key,
            f"{label}（{index}/{len(steps) + 1}）",
            20 + index * 11,
        )
        _run_script(
            script_dir,
            script,
            arguments,
            accepted_returncodes=(0, 1) if script == "validate_plan.py" else (0,),
        )
    _set_progress_step(db, workflow, "build_worklist", "正在生成核销日清文件", 80)
    stdout = _run_script(
        script_dir,
        "build_worklist.py",
        ["--workspace", workspace, "--hexiao-date", hexiao_date],
    )
    worklists = sorted(
        (business / "04_产出").glob("核销日清_*.xlsx"),
        key=lambda path: path.stat().st_mtime,
    )
    if not worklists:
        raise RuntimeError("build_worklist.py 未生成核销日清。")
    artifact = _register_artifact(db, workflow, worklists[-1], action.id)
    checked = sorted(
        (business / "04_产出").glob("写入计划_校验后*.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if not checked or not ledgers:
        raise RuntimeError("日清已生成，但没有找到校验后计划或盈亏副本。")
    _set_progress_step(db, workflow, "review", "核销日清已生成，等待结果确认", 82)
    summary = _worklist_summary(stdout)
    return {
        "workspace": str(business),
        "checked_plan": str(checked[-1]),
        "ledger_years": {str(year): str(path) for year, path in ledgers.items()},
        "flow_file": str(flow_files[0]),
        "summary": summary,
        "artifacts": [artifact],
    }


def _supplement_fetched_data(
    db: Session,
    action: WorkflowAction,
    workflow: WorkflowSession,
) -> dict[str, Any]:
    action_input = _load(action.input_json, {})
    context = action_input.get("context", {})
    supplement = action_input.get("supplement", {})
    if not isinstance(context, dict) or not isinstance(supplement, dict):
        raise RuntimeError("补取动作参数无效。")
    root = workflow_root(workflow.owner_id, workflow.id).resolve()
    raw_workspace = context.get("workspace", "")
    workspace = Path(raw_workspace).resolve() if isinstance(raw_workspace, str) else Path()
    if not workspace.is_dir() or not workspace.is_relative_to(_workflow_storage_root(db, workflow)):
        raise RuntimeError("取数检查工作区不存在，请重新生成日清。")
    ar_ids = _normalized_business_ids(
        list(supplement.get("ar_ids") or []),
        AR_ID_PATTERN,
        "AR 编号",
    )
    so_ids = _normalized_business_ids(
        list(supplement.get("so_ids") or []),
        SO_ID_PATTERN,
        "SO 编号",
    )
    reconciliation_date = str(supplement.get("reconciliation_date") or workflow.reconciliation_date)
    script_dir = root / "skill" / "vendor" / "scripts"
    runtime = load_workflow_manifest(workflow).runtime
    network_env = skill_subprocess_environment(runtime)
    if settings.zhiyun_base_url:
        assert_url_allowed(settings.zhiyun_base_url, runtime)
        network_env["ZHIYUN_BASE"] = settings.zhiyun_base_url
    account, password = resolve_service_credential(
        db,
        workflow.owner_id,
        workflow.department_id,
        "zhiyun",
    )
    _set_progress_step(db, workflow, "fetch_zhiyun", "正在按 SO/AR 编号补取智云数据", 15)
    try:
        _run_secure_fetch_with_retry(
            script_dir,
            stdin_data=_json(
                {
                    "account": account,
                    "password": password,
                    "reconciliation_date": reconciliation_date,
                    "workspace": str(workspace),
                    "supplement_ar_ids": ar_ids,
                    "supplement_so_ids": so_ids,
                }
            ),
            sensitive_values=(account, password),
            extra_env=network_env,
            legacy_outer_retry=_needs_legacy_fetch_retry(getattr(workflow, "skill_version", "")),
            timeout_seconds=_secure_fetch_timeout_seconds(1, runtime.timeout_seconds),
        )
    finally:
        password = ""
    tag = reconciliation_date.replace("-", "")
    result_path = workspace / "01_智云导出" / f"补取结果_{tag}.json"
    if not result_path.is_file():
        raise RuntimeError("智云补取完成，但没有生成补取结果摘要。")
    result = _load(result_path.read_text(encoding="utf-8"), {})
    if not isinstance(result, dict):
        raise RuntimeError("智云补取结果摘要格式无效。")
    return {
        "summary": _fetched_summary_from_export(workspace / "01_智云导出", reconciliation_date),
        "reconciliation_date": reconciliation_date,
        "supplement_result": result,
    }


def _apply_confirmed(
    db: Session,
    action: WorkflowAction,
    workflow: WorkflowSession,
) -> dict[str, Any]:
    if isinstance(workflow, WorkflowSession):
        _ensure_legacy_workflow_material_snapshot(db, workflow)
    context = _load(action.input_json, {}).get("context", {})
    business = Path(context.get("workspace", "")).resolve()
    root = workflow_root(workflow.owner_id, workflow.id)
    if not business.is_dir() or not business.is_relative_to(_workflow_storage_root(db, workflow)):
        raise RuntimeError("上一次日清工作区不存在，请重新生成日清。")
    script_dir = root / "skill" / "vendor" / "scripts"
    _set_progress_step(db, workflow, "write_files", "正在写入工作副本", 85)
    checked = Path(context.get("checked_plan", "")).resolve()
    raw_ledger_years = context.get("ledger_years") or {}
    ledger_years: dict[int, Path] = {}
    for raw_year, raw_path in raw_ledger_years.items():
        if not str(raw_year).isdigit():
            raise RuntimeError("年度盈亏表上下文无效，请重新生成日清。")
        path = Path(raw_path).resolve()
        if not path.is_file() or not path.is_relative_to(business):
            raise RuntimeError("年度盈亏表不存在或超出当前工作区，请重新生成日清。")
        ledger_years[int(raw_year)] = path
    legacy_ledger = Path(context.get("ledger", "")).resolve()
    if not checked.is_file() or not checked.is_relative_to(business):
        raise RuntimeError("校验后计划或盈亏副本不存在，请重新生成日清。")
    if not ledger_years and not legacy_ledger.is_file():
        raise RuntimeError("校验后计划或盈亏副本不存在，请重新生成日清。")
    raw_flow = str(context.get("flow_file", ""))
    flow_file = Path(raw_flow).resolve() if raw_flow else None
    if flow_file is None or not flow_file.is_file():
        candidates = sorted(
            {
                path.resolve()
                for pattern in ("*到账*.xls*", "*流转*.xls*")
                for path in (business / "02_我的表副本").glob(pattern)
                if path.is_file() and "便携版" not in path.name
            }
        )
        flow_file = candidates[0] if len(candidates) == 1 else None
    if flow_file is None or not flow_file.is_relative_to(business):
        raise RuntimeError("到账流转表副本不存在，请重新生成日清。")
    source_workspace = str(business)
    # The preparation snapshot is a pre-write guard. Verify the task copy before
    # staging so a stale or externally changed workbook cannot enter a write run.
    _run_script(script_dir, "verify_sources.py", ["verify", "--workspace", source_workspace])

    staging_workspace: Path | None = None
    artifacts: list[dict[str, Any]] = []
    material_set = None
    try:
        staging_workspace = _create_write_staging(business, action.id)
        staged_checked = _staged_workspace_path(business, staging_workspace, checked)
        staged_ledgers = {
            year: _staged_workspace_path(business, staging_workspace, path)
            for year, path in ledger_years.items()
        }
        staged_legacy_ledger = (
            _staged_workspace_path(
                business,
                staging_workspace,
                legacy_ledger,
            )
            if legacy_ledger.is_file()
            else None
        )
        staged_flow = _staged_workspace_path(business, staging_workspace, flow_file)
        _rewrite_staged_checked_plan(staged_checked, business, staging_workspace)

        staging = str(staging_workspace)
        # The staged copy gets its own baseline. It is the only tree that
        # apply_all is allowed to mutate, including its reports and snapshots.
        _run_script(script_dir, "verify_sources.py", ["snapshot", "--workspace", staging])
        _run_script(script_dir, "verify_sources.py", ["verify", "--workspace", staging])
        ledger_arguments = (
            _annual_ledger_arguments(staged_ledgers)
            if staged_ledgers
            else ["--ledger", str(staged_legacy_ledger)]
        )
        _run_script(
            script_dir,
            "apply_all.py",
            [
                "--checked",
                str(staged_checked),
                *ledger_arguments,
                "--workspace",
                staging,
                "--confirmed",
                "--in-place",
                "--flow-in-place",
            ],
        )
        # apply_all performs planned-cell readback. Commit and verify a new
        # baseline for the staged outputs before any file is published.
        _run_script(script_dir, "verify_sources.py", ["snapshot", "--workspace", staging])
        _run_script(script_dir, "verify_sources.py", ["verify", "--workspace", staging])
        _validate_staged_delivery(staging_workspace, staged_ledgers, staged_flow)

        deliverables: list[tuple[str, Path]] = []
        if staged_ledgers:
            deliverables.extend(
                (ANNUAL_LEDGER_ROLE, path) for _, path in sorted(staged_ledgers.items())
            )
        elif staged_legacy_ledger and staged_legacy_ledger.is_file():
            deliverables.append((ANNUAL_LEDGER_ROLE, staged_legacy_ledger))
        deliverables.append((RECEIPT_FLOW_ROLE, staged_flow))
        for _, path in deliverables:
            if (
                not path.is_file()
                or not path.is_relative_to(staging_workspace)
                or "便携版" in path.name
                or "备份" in path.parts
            ):
                raise RuntimeError("结果工作簿路径无效，拒绝登记非交付文件。")
        # Registration is deliberately last: no result files reach the download
        # area until every staged workbook and report has passed validation.
        for _, path in deliverables:
            artifacts.append(_register_artifact(db, workflow, path, action.id))
        if isinstance(workflow, WorkflowSession):
            published_bindings: dict[str, list[dict[str, Any]]] = {
                ANNUAL_LEDGER_ROLE: [],
                RECEIPT_FLOW_ROLE: [],
            }
            for (role, _), artifact in zip(deliverables, artifacts, strict=True):
                published_bindings[role].append(artifact)
            material_set = publish_workflow_material_set(db, workflow, published_bindings)
        if getattr(workflow, "batch_id", None):
            _promote_batch_staging(business, staging_workspace)
    except MaterialVersionConflict:
        _discard_registered_artifacts(db, workflow, artifacts, action.id)
        if staging_workspace is not None:
            _discard_write_staging(business, staging_workspace)
        raise
    except Exception as exc:
        _discard_registered_artifacts(db, workflow, artifacts, action.id)
        if staging_workspace is not None:
            _discard_write_staging(business, staging_workspace)
        raise StagedWriteError("写入未发布，已丢弃暂存副本。请重新生成核销日清后再执行。") from exc
    else:
        try:
            _discard_write_staging(business, staging_workspace)
        except OSError:
            # The published files no longer depend on staging. A cleanup-only
            # failure must not turn a verified business version into a failed task.
            pass

    next_files: dict[str, list[dict[str, Any]]] = {
        ANNUAL_LEDGER_ROLE: [],
        RECEIPT_FLOW_ROLE: [],
    }
    if material_set is not None:
        next_files = material_set_bindings(db, material_set)
        workflow.material_set_id = material_set.id
        version_context = _load(workflow.context_json, {})
        version_context.update(
            {
                "material_set_id": material_set.id,
                "material_version": material_set.version,
                "material_source_workflow_id": workflow.id,
            }
        )
        workflow.context_json = _json(version_context)
    elif getattr(workflow, "batch_id", None):
        for role, artifact in zip((item[0] for item in deliverables), artifacts, strict=True):
            next_files[role].append({**artifact, "batch_output": True})
    if getattr(workflow, "batch_id", None) and (
        len(next_files.get(ANNUAL_LEDGER_ROLE, [])) < 1
        or len(next_files.get(RECEIPT_FLOW_ROLE, [])) != 1
    ):
        raise PostWriteVerificationError(
            "本日写入已完成，但没有找到可传递给下一日的年度盈亏表和到账流转表；批次已暂停，"
            "请勿重复执行本日任务。"
        )
    return {
        "workspace": str(business),
        "artifacts": artifacts,
        "next_files": next_files,
        "material_set_id": material_set.id if material_set is not None else None,
        "material_version": material_set.version if material_set is not None else None,
    }


def _fail_batch(db: Session, workflow: WorkflowSession, message: str) -> None:
    if not workflow.batch_id:
        return
    batch = db.get(WorkflowBatch, workflow.batch_id)
    if not batch:
        return
    batch.state = "failed"
    batch.error_message = message[:500]
    batch.progress_message = (
        f"第 {workflow.batch_sequence} 天（{workflow.reconciliation_date}）失败，后续日期已暂停"
    )
    batch.updated_at = datetime.now(UTC)
    restore_unfinished_batch_reminders(db, batch.id)


def _batch_has_current_material(db: Session, batch: WorkflowBatch) -> bool:
    current = current_material_set(
        db,
        batch.owner_id,
        batch.department_id,
        batch.skill_id,
    )
    return bool(current is not None and current.id == batch.material_set_id)


def _reject_superseded_batch_material(db: Session, batch: WorkflowBatch) -> None:
    if _batch_has_current_material(db, batch):
        return
    message = (
        "业务材料已更新，当前批次固定在旧版本，不能继续。"
        "请基于最新材料重新创建未完成日期批次。"
    )
    batch.state = "failed"
    batch.error_message = message
    batch.progress_message = "业务材料已更新，当前批次已停止"
    for workflow in batch.workflows:
        if workflow.state == "succeeded":
            continue
        context = _load(workflow.context_json, {})
        context = context if isinstance(context, dict) else {}
        context["material_version_conflict"] = True
        workflow.context_json = _json(context)
    restore_unfinished_batch_reminders(db, batch.id)
    db.commit()
    raise HTTPException(status_code=409, detail=message)


def _finalize_batch_reports(
    db: Session,
    batch: WorkflowBatch,
    workflow: WorkflowSession,
    result: dict[str, Any],
    action: WorkflowAction | None,
) -> None:
    raw_workspace = result.get("workspace", "")
    workspace = Path(raw_workspace).resolve() if isinstance(raw_workspace, str) else Path()
    if not workspace.is_dir() or not workspace.is_relative_to(_workflow_storage_root(db, workflow)):
        raise RuntimeError("多日批次工作区不存在，无法生成范围报告。")
    dates = _load(batch.reconciliation_dates_json, [])
    script_dir = workflow_root(workflow.owner_id, workflow.id) / "skill" / "vendor" / "scripts"
    batch.state = "finalizing"
    batch.progress = 99
    batch.progress_message = "每日核销已完成，正在生成范围报告"
    _run_script(
        script_dir,
        "build_task_reports.py",
        [
            "--workspace",
            str(workspace),
            "--date-from",
            dates[0],
            "--date-to",
            dates[-1],
            *[part for item in dates for part in ("--date", item)],
        ],
    )
    report_name = _batch_integrated_report_name(dates)
    reports = (
        [workspace / "04_产出" / report_name]
        if report_name and (workspace / "04_产出" / report_name).is_file()
        else []
    )
    if len(reports) != 1:
        raise RuntimeError("多日批次整合核销日清未生成，批次不能结束。")
    if action is not None:
        stored_artifacts = _load(workflow.artifacts_json, [])
        for report in reports:
            artifact = _register_artifact(db, workflow, report, action.id)
            stored_artifacts.append(artifact)
            result.setdefault("artifacts", []).append(artifact)
        workflow.artifacts_json = _json(stored_artifacts)


def _advance_batch(
    db: Session,
    workflow: WorkflowSession,
    result: dict[str, Any],
    action: WorkflowAction | None = None,
) -> None:
    if not workflow.batch_id:
        return
    batch = db.get(WorkflowBatch, workflow.batch_id)
    if not batch:
        raise RuntimeError("所属核销批次不存在。")
    result_material_set_id = str(result.get("material_set_id") or "")
    if result_material_set_id:
        batch.material_set_id = result_material_set_id
    children = sorted(batch.workflows, key=lambda item: item.batch_sequence)
    total = len(children)
    completed = len([item for item in children if item.state == "succeeded"])
    batch.progress = int(completed * 100 / max(total, 1))
    batch.error_message = ""
    if batch.state == "cancelling":
        for child in children:
            if child.id != workflow.id and child.state not in TERMINAL_WORKFLOW_STATES:
                _cancel_workflow_immediately(db, child)
        batch.state = "cancelled"
        batch.progress_message = "当前原子写入已完成，剩余日期已取消"
        batch.updated_at = datetime.now(UTC)
        return
    next_workflow = next(
        (item for item in children if item.batch_sequence == workflow.batch_sequence + 1),
        None,
    )
    if not next_workflow:
        context = _load(workflow.context_json, {})
        context["current_step"] = "finalize_batch"
        context["current_step_label"] = "正在生成范围报告"
        context.pop("step_error", None)
        context.pop("error_detail", None)
        workflow.context_json = _json(context)
        workflow.state = "running"
        workflow.stage = "finalizing"
        workflow.progress = 99
        workflow.progress_message = "每日核销已完成，正在生成范围报告"
        batch.state = "finalizing"
        batch.progress = 99
        batch.progress_message = "每日核销已完成，等待生成范围报告"
        batch.updated_at = datetime.now(UTC)
        _new_action(
            db,
            workflow,
            "finalize_batch",
            {"workspace": result.get("workspace", "")},
        )
        return

    next_files = result.get("next_files", {})
    if (
        len(next_files.get(ANNUAL_LEDGER_ROLE, [])) < 1
        or len(next_files.get(RECEIPT_FLOW_ROLE, [])) != 1
    ):
        raise PostWriteVerificationError(
            "本日写入已完成，但工作副本传递不完整；批次已暂停，请勿重复执行本日任务。"
        )
    next_workflow.files_json = _json(next_files)
    next_workflow.material_set_id = str(result.get("material_set_id") or "") or None
    next_context = _load(next_workflow.context_json, {})
    next_context.update(
        {
            "material_set_id": result.get("material_set_id"),
            "material_version": result.get("material_version"),
            "material_source_workflow_id": workflow.id,
            "workspace": result.get("workspace"),
            "fetched_data": {
                **(_load(workflow.context_json, {}).get("fetched_data", {}) or {}),
                "review_status": "confirmed",
            },
        }
    )
    next_workflow.context_json = _json(next_context)
    next_workflow.state = "running"
    next_workflow.stage = "preparing"
    next_workflow.progress = 5
    next_workflow.progress_message = (
        f"前一天已完成，正在执行第 {next_workflow.batch_sequence}/{total} 天核销"
    )
    next_workflow.error_message = ""
    _new_action(db, next_workflow, "prepare_worklist")
    _message(
        db,
        next_workflow,
        "assistant",
        (
            "已接收前一天核销完成后的工作副本，开始执行 "
            f"{_date_label(next_workflow.reconciliation_date)}。"
        ),
        {
            "kind": "batch_child_started",
            "batch_id": batch.id,
            "previous_workflow_id": workflow.id,
        },
    )
    batch.state = "running"
    batch.progress_message = (
        f"已完成 {completed}/{total} 天，正在执行 {next_workflow.reconciliation_date}"
    )
    batch.updated_at = datetime.now(UTC)


def retry_workflow_batch(
    db: Session,
    batch: WorkflowBatch,
) -> WorkflowBatch:
    assert_workflow_skill_execution_enabled(batch.skill_id)
    acquire_claim_lock(db)
    db.refresh(batch)
    if batch.state != "failed":
        raise HTTPException(status_code=409, detail="只有失败并暂停的批次可以继续。")
    _reject_superseded_batch_material(db, batch)
    _assert_single_flight_available(
        db,
        batch.skill_id,
        exclude_batch_id=batch.id,
    )
    children = sorted(batch.workflows, key=lambda item: item.batch_sequence)
    failed = next((item for item in children if item.state == "failed"), None)
    if not failed:
        last = children[-1] if children else None
        failed_finalizer = max(
            (item for item in (last.actions if last else []) if item.name == "finalize_batch"),
            key=lambda item: item.queued_at,
            default=None,
        )
        if not last or not failed_finalizer or failed_finalizer.state != "failed":
            raise HTTPException(status_code=409, detail="没有找到可继续的失败日期或范围报告。")
        context = _load(last.context_json, {})
        context = context if isinstance(context, dict) else {}
        for stale_key in ("step_error", "error_detail"):
            context.pop(stale_key, None)
        context["current_step"] = "finalize_batch"
        context["current_step_label"] = "正在重新生成范围报告"
        last.context_json = _json(context)
        last.progress_message = "正在重新生成范围报告"
        last.error_message = ""
        _queue_action(
            db,
            last,
            "finalize_batch",
            {"workspace": context.get("workspace", "")},
        )
        batch.state = "finalizing"
        batch.error_message = ""
        batch.progress = 99
        batch.progress_message = "正在重新生成范围报告"
        db.commit()
        db.refresh(batch)
        return batch
    last_action = max(failed.actions, key=lambda item: item.queued_at, default=None)
    if not last_action or last_action.name != "prepare_worklist":
        raise HTTPException(
            status_code=409,
            detail="失败发生在写入阶段，不能自动重试；请先由管理员核对工作副本。",
        )
    pending = any(
        action.state in {"queued", "running"} for child in children for action in child.actions
    )
    if pending:
        raise HTTPException(status_code=409, detail="批次中仍有动作正在执行。")

    _cleanup_terminal_fetched_snapshot(db, failed)
    context = _load(failed.context_json, {})
    context = context if isinstance(context, dict) else {}
    for stale_key in ("step_error", "error_detail"):
        context.pop(stale_key, None)
    if not context.get("workspace"):
        expected_workspace = (
            _workflow_storage_root(db, failed) / "batch" / str(batch.id) / "工作区"
        ).resolve()
        if expected_workspace.is_dir():
            context["workspace"] = str(expected_workspace)
            context["workspace_state"] = "copying_inputs"
    resume_existing_workspace = bool(context.get("workspace"))
    failed.context_json = _json(
        {
            **context,
            "started_from_form": True,
            "batch_id": batch.id,
            "requires_confirmation": bool(context.get("requires_confirmation", False)),
        }
    )
    failed.artifacts_json = "[]"
    failed.state = "running"
    failed.stage = "preparing"
    failed.progress = 5
    failed.progress_message = f"正在重新执行 {failed.reconciliation_date}"
    failed.error_message = ""
    _queue_action(
        db,
        failed,
        "prepare_worklist",
        {"resume_existing_workspace": resume_existing_workspace},
    )
    _message(
        db,
        failed,
        "assistant",
        "已从失败日期继续。之前成功的日期不会重复执行。",
        {"kind": "batch_retry", "batch_id": batch.id},
    )
    batch.state = "running"
    batch.error_message = ""
    batch.progress_message = f"正在重新执行失败日期 {failed.reconciliation_date}"
    batch.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(batch)
    return batch


def execute_workflow_action(db: Session, action: WorkflowAction) -> None:
    workflow = db.get(WorkflowSession, action.workflow_id)
    if not workflow:
        action.state = "failed"
        action.error_message = "对话任务不存在。"
        action.finished_at = datetime.now(UTC)
        return
    preview_dates_to_prime: list[str] = []
    try:
        assert_workflow_execution_enabled(workflow)
        if action.name == "prepare_worklist":
            result = _prepare_worklist(db, action, workflow)
            # Release any transaction used by the long-running fetch, then
            # serialize its state transition with cancellation. The worker
            # session uses expire_on_commit=False, so an explicit refresh is
            # required to observe a cancellation requested by another session.
            db.commit()
            acquire_claim_lock(db)
            db.refresh(workflow)
            context = _load(workflow.context_json, {})
            context.update(result)
            workflow.context_json = _json(context)
            fetched_data = context.get("fetched_data", {})
            if isinstance(fetched_data, dict) and fetched_data.get("available"):
                fetched_dates = fetched_data.get("dates", [])
                preview_dates_to_prime = [str(item) for item in fetched_dates if item] or [
                    workflow.reconciliation_date
                ]
            artifacts = _load(workflow.artifacts_json, [])
            artifacts.extend(result["artifacts"])
            workflow.artifacts_json = _json(artifacts)
            stop = bool(context.get("stop_after_action"))
            auto_apply = bool(context.get("started_from_form")) and (
                workflow.skill_id == "ar-hexiao-daily"
                or not bool(context.get("requires_confirmation", True))
            )
            summary = result.get("summary", {})
            if stop:
                context["current_step"] = "stopped"
                context["current_step_label"] = "取数完成，按取消请求停止"
                workflow.context_json = _json(context)
                workflow.stage = "cancelled"
                workflow.state = "cancelled"
                workflow.progress_message = "取数完成后按取消请求停止"
                reply = "智云取数已经完成，但按取消请求，本次不会继续核销判断或写入。"
            elif result.get("awaiting_fetched_data_confirmation"):
                context["current_step"] = "review_fetched_data"
                context["current_step_label"] = "智云取数完成，等待工作人员检查"
                workflow.context_json = _json(context)
                fetched_data = context.get("fetched_data", {})
                workflow.stage = "awaiting_fetched_data_confirmation"
                workflow.state = "waiting_confirmation"
                workflow.progress = 20
                workflow.progress_message = "智云取数完成，等待工作人员检查并确认"
                reply = (
                    f"核销日期 {_date_label(workflow.reconciliation_date)} 的智云数据已经取回。"
                    "请先查看取数数据；确认完整后再继续生成核销日清。"
                )
            elif result.get("empty_day_skipped"):
                _complete_empty_reconciliation_date(db, workflow, context, announce=False)
                _advance_batch(db, workflow, result, action)
                reply = (
                    f"核销日期 {_date_label(workflow.reconciliation_date)} 取数结果确认无核销记录，"
                    "本日已跳过，正在继续下一天。"
                )
            elif auto_apply:
                context["current_step"] = "write_files"
                context["current_step_label"] = "正在写入工作副本"
                workflow.stage = "applying"
                workflow.state = "running"
                workflow.progress = max(workflow.progress, 85)
                workflow.progress_message = "日清与写前校验已通过，正在安全写入工作副本"
                _new_action(db, workflow, "apply_confirmed")
                reply = (
                    f"✅ 核销日期 {_date_label(workflow.reconciliation_date)} "
                    "的日清与写前校验已通过，"
                    "正在按 Skill 规则写入隔离工作副本。"
                )
            else:
                context["current_step"] = "awaiting_confirmation"
                context["current_step_label"] = "核销日清已生成，等待人工确认"
                workflow.stage = "awaiting_apply_confirmation"
                workflow.state = "waiting_confirmation"
                workflow.progress = max(workflow.progress, 82)
                workflow.progress_message = "核销日清已生成，等待人工确认"
                reply = (
                    f"✅ 核销日期 {_date_label(workflow.reconciliation_date)} 的核销判定完了，"
                    "财务工作簿原件一个字节没动；智云只做了查询取数。\n"
                    f"盈亏：今天要填 {summary.get('今天要填', 0)} 行；"
                    f"已填过·跳过 {summary.get('已填过·跳过', 0)} 行；"
                    f"冲突·需你定 {summary.get('冲突·需你定', 0)} 行；"
                    f"挂账待办 {summary.get('挂账待办', 0)} 行；"
                    f"异常 {summary.get('异常', 0)} 行。\n"
                    f"流转：确认后自动写 {summary.get('流转确认后自动写', 0)} 笔；"
                    f"须你手填 {summary.get('流转须手填', 0)} 笔。\n"
                    "请下载并打开《核销日清》检查；没问题回复“确认”或“可以写”。"
                )
            _message(db, workflow, "assistant", reply, {"kind": "worklist_ready"})
        elif action.name == "supplement_fetched_data":
            result = _supplement_fetched_data(db, action, workflow)
            db.commit()
            acquire_claim_lock(db)
            db.refresh(workflow)
            context = _load(workflow.context_json, {})
            fetched_data = context.get("fetched_data", {})
            fetched_data = fetched_data if isinstance(fetched_data, dict) else {}
            history = fetched_data.get("supplement_history", [])
            history = history if isinstance(history, list) else []
            supplement_result = result.get("supplement_result", {})
            history.append(
                {
                    **(supplement_result if isinstance(supplement_result, dict) else {}),
                    "action_id": action.id,
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            )
            fetched_data.update(
                {
                    "available": True,
                    "review_status": "waiting",
                    "summary": result.get("summary", {}),
                    "supplement_history": history,
                }
            )
            summary_by_date = fetched_data.get("summary_by_date", {})
            summary_by_date = summary_by_date if isinstance(summary_by_date, dict) else {}
            result_date = str(result.get("reconciliation_date") or workflow.reconciliation_date)
            summary_by_date[result_date] = result.get("summary", {})
            fetched_data["summary_by_date"] = summary_by_date
            context["fetched_data"] = fetched_data
            stop = bool(context.get("stop_after_action"))
            context["current_step"] = "stopped" if stop else "review_fetched_data"
            context["current_step_label"] = (
                "编号补取完成，按取消请求停止" if stop else "编号补取完成，等待工作人员再次检查"
            )
            workflow.context_json = _json(context)
            preview_dates_to_prime = [result_date]
            workflow.stage = "cancelled" if stop else "awaiting_fetched_data_confirmation"
            workflow.state = "cancelled" if stop else "waiting_confirmation"
            workflow.progress = 20
            workflow.progress_message = (
                "编号补取完成后按取消请求停止"
                if stop
                else "编号补取完成，等待工作人员再次检查并确认"
            )
            _message(
                db,
                workflow,
                "assistant",
                (
                    "SO/AR 编号补取已经完成，但按取消请求不会继续处理。"
                    if stop
                    else "SO/AR 编号补取已经完成。请重新检查取数数据；确认完整后再继续。"
                ),
                {"kind": "fetched_data_supplement_completed"},
            )
            requested = (
                supplement_result.get("requested", {})
                if isinstance(supplement_result, dict)
                else {}
            )
            record_audit(
                db,
                actor_id=workflow.owner_id,
                actor_role="worker",
                department_id=workflow.department_id,
                action="workflow.fetched_data.supplement.completed",
                resource_type="workflow",
                resource_id=workflow.id,
                details={
                    "requested": supplement_audit_summary(requested),
                    "result": supplement_result_audit_summary(supplement_result),
                },
            )
        elif action.name == "apply_confirmed":
            result = _apply_confirmed(db, action, workflow)
            context = _load(workflow.context_json, {})
            context.update(result)
            workflow.context_json = _json(context)
            artifacts = _load(workflow.artifacts_json, [])
            artifacts.extend(result["artifacts"])
            workflow.artifacts_json = _json(artifacts)
            workflow.stage = "completed"
            workflow.state = "succeeded"
            workflow.progress = 100
            workflow.progress_message = "盈亏和流转写入完成，结果文件已生成"
            context["current_step"] = "completed"
            context["current_step_label"] = "写入完成，结果文件已生成"
            context.pop("step_error", None)
            context.pop("error_detail", None)
            workflow.context_json = _json(context)
            _message(
                db,
                workflow,
                "assistant",
                "统一写入完成：先写盈亏明细，再写到账流转表安全子集；"
                "回读校验已通过。到账流转表、年度盈亏核算表和《核销日清》已放到右侧下载区。",
                {"kind": "workflow_completed"},
            )
            _advance_batch(db, workflow, result, action)
        elif action.name == "finalize_batch":
            batch = db.get(WorkflowBatch, workflow.batch_id)
            if not batch:
                raise RuntimeError("所属核销批次不存在。")
            action_input = _load(action.input_json, {})
            result = {"workspace": action_input.get("workspace", ""), "artifacts": []}
            _finalize_batch_reports(db, batch, workflow, result, action)
            context = _load(workflow.context_json, {})
            stop = bool(context.get("stop_after_action"))
            if stop:
                context["current_step"] = "stopped"
                context["current_step_label"] = "范围报告完成后按取消请求停止"
                workflow.stage = "cancelled"
                workflow.state = "cancelled"
                workflow.progress = 100
                workflow.progress_message = "范围报告完成后按取消请求停止"
                batch.progress_message = "范围报告完成后取消批次"
            else:
                context["current_step"] = "completed"
                context["current_step_label"] = "核销及范围报告完成"
                workflow.stage = "completed"
                workflow.state = "succeeded"
                workflow.progress = 100
                workflow.progress_message = "核销及范围报告完成"
                batch.state = "succeeded"
                batch.progress = 100
                batch.progress_message = f"{len(batch.workflows)} 天核销及范围报告全部完成"
                batch.error_message = ""
            workflow.context_json = _json(context)
            batch.updated_at = datetime.now(UTC)
        else:
            raise RuntimeError(f"不支持的工作流动作：{action.name}")
        action.result_json = _json(result)
        action.state = "succeeded"
        action.finished_at = datetime.now(UTC)
        workflow.error_message = ""
        if workflow.state == "cancelled":
            _finalize_requested_batch_cancellation(db, workflow.batch_id)
        if preview_dates_to_prime:
            _prime_fetched_data_previews(db, workflow, preview_dates_to_prime)
    except subprocess.TimeoutExpired:
        detail = _workflow_error_detail(workflow, "脚本执行超时。")
        public_error = _workflow_public_error(workflow, detail)
        action.state = "failed"
        action.error_message = public_error["message"]
        action.finished_at = datetime.now(UTC)
        workflow.state = "failed"
        workflow.stage = "failed"
        workflow.progress_message = "动作执行超时"
        _store_workflow_error(workflow, detail)
        if action.name == "finalize_batch" and workflow.batch_id:
            batch = db.get(WorkflowBatch, workflow.batch_id)
            if batch:
                batch.state = "failed"
                batch.error_message = action.error_message[:500]
                batch.progress = 99
                batch.progress_message = "每日核销已完成，但范围报告生成失败"
                batch.updated_at = datetime.now(UTC)
        else:
            _fail_batch(db, workflow, action.error_message)
        _message(
            db,
            workflow,
            "assistant",
            f"{public_error['message']} 请检查材料后决定是否重新执行。",
            {"kind": "action_failed", "error": public_error},
        )
        if action.name == "supplement_fetched_data":
            supplement = _load(action.input_json, {}).get("supplement", {})
            record_audit(
                db,
                actor_id=workflow.owner_id,
                actor_role="worker",
                department_id=workflow.department_id,
                action="workflow.fetched_data.supplement.completed",
                resource_type="workflow",
                resource_id=workflow.id,
                outcome="failed",
                details={
                    "requested": supplement_audit_summary(supplement),
                    "error_type": "timeout",
                },
            )
    except StagedWriteError as exc:
        detail = _workflow_error_detail(workflow, exc)
        public_error = _workflow_public_error(workflow, detail)
        action.state = "failed"
        action.error_message = public_error["message"]
        action.finished_at = datetime.now(UTC)
        workflow.state = "failed"
        workflow.stage = "failed"
        workflow.progress_message = "写入未发布，原任务副本保持不变"
        _store_workflow_error(workflow, detail)
        _fail_batch(db, workflow, action.error_message)
        _message(
            db,
            workflow,
            "assistant",
            (
                f"{public_error['message']} 原任务副本没有被修改。"
                "请以原始上传文件重新生成核销日清后再执行。"
            ),
            {"kind": "staged_write_discarded", "error": public_error},
        )
    except PostWriteVerificationError as exc:
        detail = _workflow_error_detail(workflow, exc)
        public_error = _workflow_public_error(workflow, detail)
        action.state = "failed"
        action.error_message = public_error["message"]
        action.finished_at = datetime.now(UTC)
        workflow.state = "failed"
        workflow.stage = "failed"
        workflow.progress_message = "写入已完成，等待恢复写入后校验"
        _store_workflow_error(workflow, detail)
        _fail_batch(db, workflow, action.error_message)
        _message(
            db,
            workflow,
            "assistant",
            f"{public_error['message']} 计划内写入已经完成，请勿重复执行，联系管理员恢复校验基线。",
            {"kind": "post_write_verification_failed", "error": public_error},
        )
    except Exception as exc:
        detail = _workflow_error_detail(workflow, exc)
        public_error = _workflow_public_error(workflow, detail)
        action.state = "failed"
        action.error_message = public_error["message"]
        action.finished_at = datetime.now(UTC)
        if action.name == "finalize_batch":
            workflow.state = "succeeded"
            workflow.stage = "completed"
            workflow.progress_message = "每日核销已完成，范围报告生成失败"
        else:
            workflow.state = "failed"
            workflow.stage = "failed"
            workflow.progress_message = "动作没有完成"
        _store_workflow_error(workflow, detail)
        if action.name == "finalize_batch" and workflow.batch_id:
            batch = db.get(WorkflowBatch, workflow.batch_id)
            if batch:
                batch.state = "failed"
                batch.error_message = action.error_message[:500]
                batch.progress = 99
                batch.progress_message = "每日核销已完成，但范围报告生成失败"
                batch.updated_at = datetime.now(UTC)
        else:
            _fail_batch(db, workflow, action.error_message)
        _message(
            db,
            workflow,
            "assistant",
            f"{public_error['message']} 请先查看错误步骤和原因，再决定是否重新执行。",
            {"kind": "action_failed", "error": public_error},
        )
        if action.name == "supplement_fetched_data":
            supplement = _load(action.input_json, {}).get("supplement", {})
            record_audit(
                db,
                actor_id=workflow.owner_id,
                actor_role="worker",
                department_id=workflow.department_id,
                action="workflow.fetched_data.supplement.completed",
                resource_type="workflow",
                resource_id=workflow.id,
                outcome="failed",
                details={
                    "requested": supplement_audit_summary(supplement),
                    "error_type": type(exc).__name__,
                },
            )

    sync_reminder_from_workflow(db, workflow)
    _cleanup_terminal_fetched_snapshot(db, workflow)


def run_workflow_action_once(
    db: Session,
    pools: tuple[str, ...],
    worker_id: str = "workflow-worker",
) -> bool:
    action = claim_next_workflow_action(db, pools, worker_id)
    if not action:
        return False
    with LeaseHeartbeat("workflow_action", action.id, worker_id):
        execute_workflow_action(db, action)
    action.heartbeat_at = datetime.now(UTC)
    action.lease_expires_at = None
    db.commit()
    return True
