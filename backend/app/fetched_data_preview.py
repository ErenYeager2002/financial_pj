from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    WorkflowFetchedDataPreview,
    WorkflowFetchedDataPreviewArGroup,
    WorkflowSession,
)
from .schemas import WorkflowFetchedDataArGroup
from .storage import sha256_file

CURRENT_AR_AMOUNT_SUMMARY_KEY = "本日AR汇总金额"
CURRENT_WRITEOFF_AMOUNT_SUMMARY_KEY = "本日总核销金额"


@dataclass(frozen=True)
class FetchedDataPreviewPage:
    summary: dict[str, Any]
    total: int
    groups: list[WorkflowFetchedDataArGroup]
    revision: str


def _reconciliation_date_text(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if len(text) >= 10:
        candidate = text[:10]
        try:
            date.fromisoformat(candidate)
        except ValueError:
            pass
        else:
            return candidate
    return text


def fetched_data_revision(paths: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted((item.resolve() for item in paths), key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def fetched_data_group_search_text(group: WorkflowFetchedDataArGroup) -> str:
    values = [
        group.ar_id,
        *(payment.customer for payment in group.payments),
        *(order.so_id for order in group.orders),
        *(detail.sod_id for order in group.orders for detail in order.order_details),
    ]
    return "\n".join(value.casefold() for value in values if value)


def _add_current_ar_payment_amount(
    totals: dict[str, float],
    *,
    amount_original: object,
    amount_local: object,
    currency: object,
    historical_parent_only: object,
) -> None:
    """Add one current-day parent payment without mixing currencies or history."""
    if historical_parent_only is True:
        return
    amount = amount_original if amount_original is not None else amount_local
    if isinstance(amount, bool):
        return
    try:
        numeric_amount = float(amount)
    except (TypeError, ValueError):
        return
    if not math.isfinite(numeric_amount):
        return
    amount_currency = str(currency or "").strip() if amount_original is not None else "CNY"
    amount_currency = amount_currency or "币种未提供"
    totals[amount_currency] = round(totals.get(amount_currency, 0.0) + numeric_amount, 2)


def current_ar_amounts_by_currency(
    groups: Sequence[WorkflowFetchedDataArGroup],
) -> dict[str, float]:
    """Summarize only the selected reconciliation date's AR parent payments."""
    totals: dict[str, float] = {}
    for group in groups:
        for payment in group.payments:
            _add_current_ar_payment_amount(
                totals,
                amount_original=payment.amount_original,
                amount_local=payment.amount_local,
                currency=payment.currency,
                historical_parent_only=payment.historical_parent_only,
            )
    return totals


def _add_current_writeoff_amount(
    totals: dict[str, float],
    *,
    amount_original: object,
    amount_local: object,
    currency: object,
    reconciliation_date: object,
    selected_reconciliation_date: str,
    revoked: object,
) -> None:
    """Add one effective writeoff from the selected reconciliation date."""
    if revoked is True or (
        isinstance(revoked, str)
        and revoked.strip().casefold() in {"1", "true", "yes", "是", "已撤销"}
    ):
        return
    if _reconciliation_date_text(reconciliation_date) != _reconciliation_date_text(
        selected_reconciliation_date
    ):
        return
    amount = amount_original if amount_original is not None else amount_local
    if isinstance(amount, bool):
        return
    try:
        numeric_amount = float(amount)
    except (TypeError, ValueError):
        return
    if not math.isfinite(numeric_amount):
        return
    amount_currency = str(currency or "").strip() if amount_original is not None else "CNY"
    amount_currency = amount_currency or "币种未提供"
    totals[amount_currency] = round(totals.get(amount_currency, 0.0) + numeric_amount, 2)


def current_writeoff_amounts_by_currency(
    groups: Sequence[WorkflowFetchedDataArGroup],
    reconciliation_date: str,
) -> dict[str, float]:
    """Summarize effective writeoffs whose actual reconciliation date is selected."""
    selected_date = _reconciliation_date_text(reconciliation_date)
    if not selected_date:
        return {}
    totals: dict[str, float] = {}
    for group in groups:
        for order in group.orders:
            for writeoff in order.writeoffs:
                _add_current_writeoff_amount(
                    totals,
                    amount_original=writeoff.amount_original,
                    amount_local=writeoff.amount_local,
                    currency=writeoff.currency,
                    reconciliation_date=writeoff.reconciliation_date,
                    selected_reconciliation_date=selected_date,
                    revoked=writeoff.revoked,
                )
    return totals


def _current_ar_amounts_from_payloads(payloads: Sequence[str]) -> dict[str, float]:
    """Backfill the amount for previews created before the aggregate was introduced."""
    totals: dict[str, float] = {}
    for payload in payloads:
        try:
            group = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(group, dict):
            continue
        payments = group.get("payments")
        if not isinstance(payments, list):
            continue
        for payment in payments:
            if not isinstance(payment, dict):
                continue
            _add_current_ar_payment_amount(
                totals,
                amount_original=payment.get("amount_original"),
                amount_local=payment.get("amount_local"),
                currency=payment.get("currency"),
                historical_parent_only=payment.get("historical_parent_only"),
            )
    return totals


def _current_writeoff_amounts_from_payloads(
    payloads: Sequence[str],
    reconciliation_date: str,
) -> dict[str, float]:
    """Backfill the writeoff amount for previews created before the aggregate existed."""
    selected_date = _reconciliation_date_text(reconciliation_date)
    if not selected_date:
        return {}
    totals: dict[str, float] = {}
    for payload in payloads:
        try:
            group = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(group, dict):
            continue
        orders = group.get("orders")
        if not isinstance(orders, list):
            continue
        for order in orders:
            if not isinstance(order, dict):
                continue
            writeoffs = order.get("writeoffs")
            if not isinstance(writeoffs, list):
                continue
            for writeoff in writeoffs:
                if not isinstance(writeoff, dict):
                    continue
                _add_current_writeoff_amount(
                    totals,
                    amount_original=writeoff.get("amount_original"),
                    amount_local=writeoff.get("amount_local"),
                    currency=writeoff.get("currency"),
                    reconciliation_date=writeoff.get("reconciliation_date"),
                    selected_reconciliation_date=selected_date,
                    revoked=writeoff.get("revoked"),
                )
    return totals


def _ensure_current_ar_amount_summary(
    db: Session,
    preview: WorkflowFetchedDataPreview,
) -> dict[str, Any]:
    """Keep old persisted previews compatible without rereading the Excel files."""
    try:
        summary = json.loads(preview.summary_json or "{}")
    except json.JSONDecodeError:
        summary = {}
    if not isinstance(summary, dict):
        summary = {}
    missing_ar_amount = CURRENT_AR_AMOUNT_SUMMARY_KEY not in summary
    missing_writeoff_amount = CURRENT_WRITEOFF_AMOUNT_SUMMARY_KEY not in summary
    if missing_ar_amount or missing_writeoff_amount:
        payloads = list(
            db.scalars(
                select(WorkflowFetchedDataPreviewArGroup.payload_json).where(
                    WorkflowFetchedDataPreviewArGroup.preview_id == preview.id
                )
            )
        )
        if missing_ar_amount:
            summary[CURRENT_AR_AMOUNT_SUMMARY_KEY] = _current_ar_amounts_from_payloads(payloads)
        if missing_writeoff_amount:
            summary[CURRENT_WRITEOFF_AMOUNT_SUMMARY_KEY] = _current_writeoff_amounts_from_payloads(
                payloads, preview.reconciliation_date
            )
        preview.summary_json = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
        db.flush()
    return summary


def _build_preview(
    db: Session,
    *,
    workflow_id: str,
    reconciliation_date: str,
    revision: str,
    summary: dict[str, Any],
    groups: Sequence[WorkflowFetchedDataArGroup],
) -> WorkflowFetchedDataPreview:
    preview_summary = dict(summary)
    preview_summary[CURRENT_AR_AMOUNT_SUMMARY_KEY] = current_ar_amounts_by_currency(groups)
    preview_summary[CURRENT_WRITEOFF_AMOUNT_SUMMARY_KEY] = current_writeoff_amounts_by_currency(
        groups, reconciliation_date
    )
    preview = WorkflowFetchedDataPreview(
        id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        reconciliation_date=reconciliation_date,
        revision=revision,
        summary_json=json.dumps(preview_summary, ensure_ascii=False, separators=(",", ":")),
    )
    db.add(preview)
    db.flush()
    db.add_all(
        [
            WorkflowFetchedDataPreviewArGroup(
                preview_id=preview.id,
                position=position,
                ar_id=group.ar_id,
                search_text=fetched_data_group_search_text(group),
                has_issues=bool(group.issues),
                payload_json=json.dumps(
                    group.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
                ),
            )
            for position, group in enumerate(groups)
        ]
    )
    db.flush()

    stale_ids = list(
        db.scalars(
            select(WorkflowFetchedDataPreview.id).where(
                WorkflowFetchedDataPreview.workflow_id == workflow_id,
                WorkflowFetchedDataPreview.reconciliation_date == reconciliation_date,
                WorkflowFetchedDataPreview.id != preview.id,
            )
        )
    )
    if stale_ids:
        db.execute(
            delete(WorkflowFetchedDataPreviewArGroup).where(
                WorkflowFetchedDataPreviewArGroup.preview_id.in_(stale_ids)
            )
        )
        db.execute(
            delete(WorkflowFetchedDataPreview).where(WorkflowFetchedDataPreview.id.in_(stale_ids))
        )
    return preview


def ensure_fetched_data_preview(
    db: Session,
    *,
    workflow_id: str,
    reconciliation_date: str,
    revision: str,
    summary: dict[str, Any],
    build_groups: Callable[[], Sequence[WorkflowFetchedDataArGroup]],
) -> WorkflowFetchedDataPreview:
    preview = db.scalar(
        select(WorkflowFetchedDataPreview).where(
            WorkflowFetchedDataPreview.workflow_id == workflow_id,
            WorkflowFetchedDataPreview.reconciliation_date == reconciliation_date,
            WorkflowFetchedDataPreview.revision == revision,
        )
    )
    if preview is None:
        # Serialize first-build work in PostgreSQL. The second request waits,
        # rechecks the immutable revision, and skips Excel parsing.
        db.execute(
            select(WorkflowSession.id).where(WorkflowSession.id == workflow_id).with_for_update()
        ).scalar_one()
        preview = db.scalar(
            select(WorkflowFetchedDataPreview).where(
                WorkflowFetchedDataPreview.workflow_id == workflow_id,
                WorkflowFetchedDataPreview.reconciliation_date == reconciliation_date,
                WorkflowFetchedDataPreview.revision == revision,
            )
        )
    if preview is None:
        try:
            with db.begin_nested():
                preview = _build_preview(
                    db,
                    workflow_id=workflow_id,
                    reconciliation_date=reconciliation_date,
                    revision=revision,
                    summary=summary,
                    groups=build_groups(),
                )
        except IntegrityError:
            # A concurrent request may have completed the same immutable
            # revision first. Reuse that winner instead of returning a 500.
            preview = db.scalar(
                select(WorkflowFetchedDataPreview).where(
                    WorkflowFetchedDataPreview.workflow_id == workflow_id,
                    WorkflowFetchedDataPreview.reconciliation_date == reconciliation_date,
                    WorkflowFetchedDataPreview.revision == revision,
                )
            )
            if preview is None:
                raise
    return preview


def _load_preview_page(
    db: Session,
    preview: WorkflowFetchedDataPreview,
    *,
    revision: str,
    offset: int,
    limit: int,
    query: str,
    issues_only: bool,
) -> FetchedDataPreviewPage:
    filters = [WorkflowFetchedDataPreviewArGroup.preview_id == preview.id]
    normalized_query = query.strip()[:100].casefold()
    if normalized_query:
        filters.append(
            WorkflowFetchedDataPreviewArGroup.search_text.contains(
                normalized_query, autoescape=True
            )
        )
    if issues_only:
        filters.append(WorkflowFetchedDataPreviewArGroup.has_issues.is_(True))

    total = int(
        db.scalar(
            select(func.count()).select_from(WorkflowFetchedDataPreviewArGroup).where(*filters)
        )
        or 0
    )
    rows = list(
        db.scalars(
            select(WorkflowFetchedDataPreviewArGroup)
            .where(*filters)
            .order_by(WorkflowFetchedDataPreviewArGroup.position.asc())
            .offset(offset)
            .limit(limit)
        )
    )
    return FetchedDataPreviewPage(
        summary=_ensure_current_ar_amount_summary(db, preview),
        total=total,
        groups=[
            WorkflowFetchedDataArGroup.model_validate(json.loads(row.payload_json)) for row in rows
        ],
        revision=revision,
    )


def load_persisted_fetched_data_preview_page(
    db: Session,
    *,
    workflow_id: str,
    reconciliation_date: str,
    offset: int,
    limit: int,
    query: str,
    issues_only: bool,
) -> FetchedDataPreviewPage | None:
    """Read a retained completed-task preview without the raw fetch workspace."""
    preview = db.scalar(
        select(WorkflowFetchedDataPreview)
        .where(
            WorkflowFetchedDataPreview.workflow_id == workflow_id,
            WorkflowFetchedDataPreview.reconciliation_date == reconciliation_date,
        )
        .order_by(
            WorkflowFetchedDataPreview.created_at.desc(),
            WorkflowFetchedDataPreview.id.desc(),
        )
    )
    if preview is None:
        return None
    return _load_preview_page(
        db,
        preview,
        revision=preview.revision,
        offset=offset,
        limit=limit,
        query=query,
        issues_only=issues_only,
    )


def load_fetched_data_preview_page(
    db: Session,
    *,
    workflow_id: str,
    reconciliation_date: str,
    revision: str,
    summary: dict[str, Any],
    offset: int,
    limit: int,
    query: str,
    issues_only: bool,
    build_groups: Callable[[], Sequence[WorkflowFetchedDataArGroup]],
) -> FetchedDataPreviewPage:
    preview = ensure_fetched_data_preview(
        db,
        workflow_id=workflow_id,
        reconciliation_date=reconciliation_date,
        revision=revision,
        summary=summary,
        build_groups=build_groups,
    )
    return _load_preview_page(
        db,
        preview,
        revision=revision,
        offset=offset,
        limit=limit,
        query=query,
        issues_only=issues_only,
    )
