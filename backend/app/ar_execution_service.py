"""Task-owned evidence access for the AR execution workflow."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .ar_execution_contract import EVIDENCE_VERSION
from .ar_publication import PublishedReportError, published_report
from .ar_evidence_paging import ArEvidenceDetail, PAGING_VERSION, detail_page, merge_read_ranges
from .model_visible_data import visible_value
from .models import WorkflowSession


class ArEvidenceSummary(BaseModel):
    record_id: str
    ar: str = ""
    so: str = ""
    sod: str = ""
    initial_bucket: str
    code: str = ""
    reason: str = ""
    reason_truncated: bool = False


class ArEvidencePage(BaseModel):
    available: bool
    message: str = ""
    schema_version: str = EVIDENCE_VERSION
    paging_version: str = PAGING_VERSION
    reconciliation_date: str
    fingerprint: str = ""
    total: int = 0
    offset: int = 0
    limit: int = 20
    next_offset: int = 0
    counts: dict[str, int] = Field(default_factory=dict)
    records: list[ArEvidenceSummary] = Field(default_factory=list)
    detail: ArEvidenceDetail | None = None


def _evidence_path(db: Session, workflow: WorkflowSession) -> Path | None:
    # Local import keeps the workflow adapter independent of the API response type.
    from .workflow_service import _workflow_storage_root

    context = json.loads(workflow.context_json or "{}")
    raw = context.get("workspace")
    if not raw:
        return None
    root = _workflow_storage_root(db, workflow).resolve()
    workspace = Path(str(raw)).resolve()
    if not workspace.is_dir() or not workspace.is_relative_to(root):
        raise HTTPException(status_code=409, detail="任务证据工作区不存在或已失效。")
    date = workflow.reconciliation_date
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return None
    candidate = workspace / "04_产出" / f"逐单证据_{date.replace('-', '')}.json"
    if not candidate.exists():
        return None
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(workspace):
        raise HTTPException(status_code=409, detail="任务证据文件路径无效。")
    return candidate


def read_evidence_page(
    db: Session,
    workflow: WorkflowSession,
    *,
    offset: int = 0,
    limit: int = 20,
    query: str = "",
    record_id: str = "",
    detail_offset: int = 0,
    fingerprint: str = "",
) -> ArEvidencePage:
    if (offset < 0 or not 1 <= limit <= 50 or len(query) > 100 or detail_offset < 0
            or len(record_id) > 128 or len(fingerprint) > 64
            or (detail_offset and not record_id) or (record_id and offset)):
        raise HTTPException(status_code=422, detail="逐单证据分页参数无效。")
    path = _evidence_path(db, workflow)
    if path is None:
        return ArEvidencePage(
            available=False, reconciliation_date=workflow.reconciliation_date,
            offset=offset, limit=limit,
            message="尚未生成逐单证据；旧版本任务可能未记录此项，不能据此认定没有异常。",
        )
    if path.stat().st_size > 32 * 1024 * 1024:
        raise HTTPException(status_code=409, detail="逐单证据超出当前读取上限。")
    try:
        with path.open("rb") as handle:
            raw = handle.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError("evidence exceeds input bound")
        payload = json.loads(raw)
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != EVIDENCE_VERSION
            or payload.get("reconciliation_date") != workflow.reconciliation_date
            or not isinstance(payload.get("records"), list)
            or any(not isinstance(item, dict) for item in payload["records"])
        ):
            raise ValueError("invalid evidence")
        evidence_fingerprint = hashlib.sha256(raw).hexdigest()
        context = json.loads(workflow.context_json or "{}")
        pinned = (context.get("ar_evidence") or {}).get("fingerprint")
        if pinned and pinned != evidence_fingerprint:
            raise ValueError("evidence fingerprint changed")
        rows = payload["records"]
        if len({row.get("record_id") for row in rows}) != len(rows):
            raise ValueError("duplicate evidence identity")
        if record_id:
            rows = [row for row in rows if row.get("record_id") == record_id]
        if query.strip():
            term = query.strip().casefold()
            rows = [row for row in rows if any(term in str(row.get(key) or "").casefold()
                                              for key in ("ar", "so", "sod", "code"))]
        selected = rows[offset:offset + limit]
        if record_id and not selected:
            raise HTTPException(status_code=404, detail="当前任务未找到该判定记录。")
        summaries = []
        for row in selected:
            safe_summary = visible_value({key: row.get(key) for key in (
                "record_id", "ar", "so", "sod", "initial_bucket", "code", "reason",
            )})
            if (not isinstance(safe_summary.get("record_id"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", safe_summary["record_id"])):
                raise ValueError("invalid evidence identity")
            reason = str(safe_summary.get("reason") or "")
            summaries.append(ArEvidenceSummary(
                **{key: str(safe_summary.get(key) or "")[:256] for key in (
                    "record_id", "ar", "so", "sod", "initial_bucket", "code",
                )}, reason=reason[:512], reason_truncated=len(reason) > 512,
            ))
        final_results = []
        final_ref = context.get("final_result") or {}
        if record_id and final_ref:
            final_path = Path(str(final_ref.get("path") or "")).resolve()
            workspace = path.parent.parent.resolve()
            if not final_path.is_relative_to(workspace):
                raise ValueError("final result outside workspace")
            if (context.get("ar_execution") or {}).get("publication") == "verified":
                registered = published_report(db, workflow, f"最终核销结果_{workflow.reconciliation_date.replace('-', '')}.json")
                if registered.sha256 != final_ref.get("fingerprint"):
                    raise PublishedReportError("已发布最终结果与原复核结果的指纹不一致，不能展示为已复核结论。")
                final_path = registered.path
            if not final_path.is_file():
                raise ValueError("final result missing")
            if final_path.stat().st_size > 32 * 1024 * 1024:
                raise ValueError("final result exceeds input bound")
            with final_path.open("rb") as handle:
                final_raw = handle.read(32 * 1024 * 1024 + 1)
            if len(final_raw) > 32 * 1024 * 1024:
                raise ValueError("final result exceeds input bound")
            if hashlib.sha256(final_raw).hexdigest() != final_ref.get("fingerprint"):
                raise ValueError("final result fingerprint changed")
            final_payload = json.loads(final_raw)
            if (not isinstance(final_payload, dict)
                    or final_payload.get("schema_version") != "ar-final-result-v1"
                    or final_payload.get("reconciliation_date") != workflow.reconciliation_date
                    or not isinstance(final_payload.get("records"), list)
                    or any(not isinstance(row, dict) for row in final_payload["records"])):
                raise ValueError("invalid final evidence")
            final_results = [row for row in final_payload.get("records", [])
                             if row.get("record_id") == record_id]
        detail = None
        if record_id:
            row = selected[0]
            detail_fingerprint = evidence_detail_fingerprint(
                evidence_fingerprint, final_ref.get("fingerprint") or "", record_id,
            )
            detail = detail_page(record_id, lambda: visible_value({
                    "record": row,
                    "order": payload.get("orders", {}).get(str(row.get("order_key") or ""), {}),
                    "parent": payload.get("parents", {}).get(str(row.get("ar") or ""), {}),
                    "sources": payload.get("sources") or {},
                    "final_results": final_results,
                }), detail_offset, detail_fingerprint)
            if fingerprint and fingerprint != detail.fingerprint:
                raise HTTPException(status_code=409, detail="逐单明细版本已变化，请从明细首页重新读取。")
            if detail_offset and not fingerprint:
                raise HTTPException(status_code=422, detail="继续读取明细时必须携带首页返回的明细指纹。")
        page = ArEvidencePage(
            available=True, reconciliation_date=workflow.reconciliation_date,
            fingerprint=evidence_fingerprint, total=len(rows), offset=offset, limit=limit,
            next_offset=min(offset + len(selected), len(rows)), counts=payload.get("counts") or {},
            records=summaries, detail=detail,
        )
        if len(page.model_dump_json().encode("utf-8")) > 512 * 1024:
            raise ValueError("evidence response exceeds total byte boundary")
        return page
    except PublishedReportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, ValueError, TypeError, AttributeError, RecursionError) as exc:
        raise HTTPException(status_code=409, detail="逐单证据格式、版本或指纹无效，不能用于执行判断。") from exc


def record_evidence_read(workflow: WorkflowSession, page: ArEvidencePage) -> None:
    """Called only by the authenticated harness tool, under the claim lock."""
    if not page.available or page.detail is None:
        return
    context = json.loads(workflow.context_json or "{}")
    review = context.get("ar_evidence_review") or {}
    if review.get("fingerprint") != page.fingerprint or review.get("paging_version") != PAGING_VERSION:
        review = {"fingerprint": page.fingerprint, "paging_version": PAGING_VERSION,
                  "read_record_ids": [], "details": {}}
    detail = page.detail
    details = review.setdefault("details", {})
    progress = details.get(detail.record_id) or {}
    seen = set(review.get("read_record_ids") or [])
    if progress.get("fingerprint") != detail.fingerprint or progress.get("total") != detail.total:
        progress = {"fingerprint": detail.fingerprint, "total": detail.total, "ranges": []}
        seen.discard(detail.record_id)
    progress["ranges"] = merge_read_ranges(progress["ranges"], detail.offset, detail.next_offset)
    if progress["ranges"] == [[0, detail.total]]:
        seen.add(detail.record_id)
    details[detail.record_id] = progress
    review["read_record_ids"] = sorted(seen)
    context["ar_evidence_review"] = review
    workflow.context_json = json.dumps(context, ensure_ascii=False)


def evidence_detail_fingerprint(evidence_fingerprint: str, final_fingerprint: str, record_id: str) -> str:
    return hashlib.sha256(json.dumps([
        PAGING_VERSION, evidence_fingerprint, final_fingerprint, record_id,
    ]).encode("utf-8")).hexdigest()


def require_evidence_coverage(context: dict, fingerprint: str, record_ids: set[str], *, final: bool = False) -> None:
    """A final review must read the new result, not reuse initial-only coverage."""
    if not record_ids:
        return
    review = context.get("ar_evidence_review") or {}
    if review.get("fingerprint") != fingerprint or review.get("paging_version") != PAGING_VERSION:
        raise ValueError("逐单检查版本不匹配，请读取当前版本的完整明细")
    final_fingerprint = (context.get("final_result") or {}).get("fingerprint", "") if final else ""
    if final and not final_fingerprint:
        raise ValueError("最终结果尚未生成，不能确认最终检查完成")
    details = review.get("details") or {}
    incomplete = []
    for record_id in sorted(record_ids):
        progress = details.get(record_id) or {}
        if (progress.get("fingerprint") != evidence_detail_fingerprint(fingerprint, final_fingerprint, record_id)
                or not isinstance(progress.get("total"), int) or progress["total"] <= 0
                or progress.get("ranges") != [[0, progress["total"]]]):
            incomplete.append(record_id)
    if incomplete:
        raise ValueError(f"还有 {len(incomplete)} 条判定的完整明细未读完；请先查询记录 {incomplete[0]} 的剩余明细")


class ArExecutionRead(BaseModel):
    available: bool
    schema_version: str = ""
    publication: str = "not_published"
    phases: list[dict[str, Any]] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    flow: dict[str, Any] = Field(default_factory=dict)
    next_tool: str = ""
    recovery_allowed: bool = False
    recovery_reason: str = ""
    recovery_failed_action_id: str = ""
    checkpoint_fingerprint: str = ""
    formal_ledgers_registered: bool = False


def read_execution(workflow: WorkflowSession) -> ArExecutionRead:
    from .ar_execution_contract import CONTRACT_VERSION, PHASES
    from .ar_execution_recovery import recovery_status
    from .ar_business_investigation import investigation_status
    from .ar_retention_policy import workflow_retention_hold

    context = json.loads(workflow.context_json or "{}")
    state = context.get("ar_execution") or {}
    if state.get("schema_version") != CONTRACT_VERSION:
        return ArExecutionRead(available=False)
    completed = set(state.get("completed") or [])
    phases = []
    from .workflow_service import _action_queued_at_utc

    actions = sorted(workflow.actions, key=_action_queued_at_utc)
    recovery = recovery_status(workflow, include_write_inspection=True)
    investigation = investigation_status(workflow)
    retention = workflow_retention_hold(workflow)
    archived = context.get("ar_staging_retention") or {}
    if not retention and isinstance(archived, dict) and archived.get("reason"):
        retention = {"code": str(archived.get("reason_code") or ""),
                     "message": str(archived["reason"])[:1000]}
    for phase in PHASES:
        actions_for_phase = [action for action in actions if action.name == f"ar_{phase.name}"]
        latest = actions_for_phase[-1] if actions_for_phase else None
        phases.append({
            "name": phase.name, "label": phase.label,
            "state": "succeeded" if phase.name in completed else latest.state if latest else "pending",
            "error": latest.error_message if latest and latest.state == "failed" else "",
            "process_evidence_message": (recovery.get("process_inspection", {}).get("message", "")
                                         if latest and latest.id == recovery["failed_action_id"] else ""),
            "write_evidence": (recovery.get("write_inspection", {})
                               if latest and latest.id == recovery["failed_action_id"] else {}),
            "investigation": (investigation if latest and latest.id == investigation["failed_action_id"] else {}),
            "retention": (retention or {}) if phase.name == "stage_reconciliation" else {},
        })
    return ArExecutionRead(
        available=True, schema_version=CONTRACT_VERSION,
        publication=state.get("publication", "not_published"), phases=visible_value(phases),
        counts=(context.get("final_result") or {}).get("counts") or {},
        flow=visible_value(context.get("flow_result") or {}),
        next_tool=state.get("next_tool") or "",
        recovery_allowed=recovery["allowed"], recovery_reason=recovery["reason"],
        recovery_failed_action_id=recovery["failed_action_id"],
        checkpoint_fingerprint=recovery["checkpoint_fingerprint"],
        formal_ledgers_registered=bool(context.get("formal_ledgers")),
    )
