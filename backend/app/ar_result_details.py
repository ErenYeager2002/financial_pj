"""Read-only, owner-scoped projection of the same records used by final metrics."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .ar_publication import published_report
from .ar_result_summary import metrics_from_report, public_final_metrics
from .resource_policy import workflow_root

ResultCategory = Literal["written", "skipped", "hold", "conflict", "exception"]
CATEGORIES = ("written", "skipped", "hold", "conflict", "exception")
STATUS_CATEGORY = {"skipped": "skipped", "hold": "hold", "conflict": "conflict", "exception": "exception"}


class ArResultItem(BaseModel):
    record_id: str
    sod: str
    categories: list[ResultCategory]
    reason: str
    final_state: str


class ArResultGroup(BaseModel):
    id: str
    date: str
    ar: str
    so: str
    categories: list[ResultCategory]
    records: list[ArResultItem]


class ArResultDate(BaseModel):
    date: str
    state: Literal["available", "empty", "pending", "unavailable"]
    message: str


class ArResultPage(BaseModel):
    groups: list[ArResultGroup] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    total: int
    record_total: int
    next_offset: int
    dates: list[ArResultDate]


def identifier(value: object) -> str:
    # Only document identifiers, never arbitrary business text or source objects.
    return value.strip() if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.\-/]{1,100}", value.strip()) else ""


def reason_text(value: object) -> str:
    from .model_visible_data import visible_value as pi_harness_visible_value

    safe = pi_harness_visible_value(value) if isinstance(value, str) else ""
    return str(safe or "未记录原因")[:500]


def categories(row: dict) -> list[str]:
    result = ["written"] if row.get("execution_status") == "written_verified" else []
    final = STATUS_CATEGORY.get(row.get("final_status"))
    if final:
        result.append(final)
    return result


def report_records(db: Session, workflow) -> tuple[list[dict], ArResultDate]:
    date = workflow.reconciliation_date
    unavailable = ArResultDate(date=date, state="unavailable", message="最终报告缺失或校验未通过，无法读取明细")
    try:
        context = json.loads(workflow.context_json or "{}")
        public = public_final_metrics(context)
    except (ValueError, TypeError, AttributeError):
        return [], unavailable
    if public and public[0].get("confirmed_empty_day", {}).get("value") == 1:
        return [], ArResultDate(date=date, state="empty", message="当日无核销记录")
    if not public or public[0]["result_dates_reviewed"]["value"] != 1:
        state = "unavailable" if workflow.state == "succeeded" else "pending"
        return [], ArResultDate(date=date, state=state, message="旧版任务未记录最终明细" if state == "unavailable" else "尚未形成最终结果")
    reference = context.get("final_result") or {}
    try:
        if (context.get("ar_execution") or {}).get("publication") == "verified":
            source = published_report(db, workflow, f"最终核销结果_{date.replace('-', '')}.json")
            path, fingerprint = source.path, source.sha256
        else:
            path = Path(reference.get("path") or "")
            fingerprint = reference.get("fingerprint")
        root = workflow_root(workflow.owner_id, workflow.id)
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError("Invalid report path")
        with path.open("rb") as handle:
            raw = handle.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError("Report exceeds read limit")
        if hashlib.sha256(raw).hexdigest() != fingerprint or fingerprint != reference.get("metrics_fingerprint"):
            raise ValueError("Report changed")
        report = json.loads(raw)
        metrics = metrics_from_report(report, date)
        if metrics != reference.get("metrics"):
            raise ValueError("Metrics changed")
        for row in report["records"]:
            if not categories(row):
                raise ValueError("Record has no verified outcome")
            outcomes = row.get("final_outcomes") or []
            if not isinstance(outcomes, list) or any(not isinstance(item, dict) for item in outcomes):
                raise ValueError("Invalid SOD outcomes")
            if any(not isinstance(item.get("status"), str) or item["status"] not in
                   {"skipped", "hold", "conflict", "exception", "completed"} for item in outcomes):
                raise ValueError("Invalid SOD status")
        return report["records"], ArResultDate(date=date, state="available",
            message="" if workflow.state == "succeeded" else "已有写后复核结果，任务尚未完成")
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return [], unavailable


def read_result_page(db: Session, workflows: list, *, category: str = "all", offset: int = 0, limit: int = 5) -> ArResultPage:
    groups: dict[tuple, ArResultGroup] = {}
    counts = dict.fromkeys(CATEGORIES, 0)
    dates = []
    record_total = 0
    for workflow in sorted(workflows, key=lambda item: (item.reconciliation_date, item.id)):
        rows, date_state = report_records(db, workflow)
        dates.append(date_state)
        for row in rows:
            selected = categories(row)
            for status in selected:
                counts[status] += 1
            record_total += 1
            if category != "all" and category not in selected:
                continue
            ar, so = identifier(row.get("ar")), identifier(row.get("so"))
            key = (workflow.id, ar, so, row["record_id"] if not ar or not so else "")
            if key not in groups:
                groups[key] = ArResultGroup(id=hashlib.sha256(json.dumps(key).encode()).hexdigest(),
                    date=workflow.reconciliation_date, ar=ar, so=so, categories=[], records=[])
            group = groups[key]
            for status in selected:
                if status not in group.categories:
                    group.categories.append(status)
            outcomes = row.get("final_outcomes") or []
            # Keep every descendant SOD, including mixed outcomes and repeated receipts.
            details = outcomes or [{"sod": row.get("sod"), "reason": row.get("final_reason")}]
            for index, outcome in enumerate(details):
                group.records.append(ArResultItem(record_id=f"{row['record_id']}:{index}",
                    sod=identifier(outcome.get("sod")), categories=selected,
                    reason=reason_text(outcome.get("reason") or row.get("final_reason")),
                    final_state={"skipped": "无需再写", "hold": "挂账", "conflict": "冲突", "exception": "异常", "completed": "已完成"}.get(outcome.get("status") or row.get("final_status"), "未记录")))
    priority = {"exception": 0, "conflict": 1, "hold": 2, "written": 3, "skipped": 4}
    ordered = sorted(groups.values(), key=lambda group: (min(priority[x] for x in group.categories), group.date, group.ar, group.so, group.id))
    return ArResultPage(groups=ordered[offset:offset + limit], counts=counts, total=len(ordered), record_total=record_total,
                        next_offset=min(offset + limit, len(ordered)), dates=dates)
