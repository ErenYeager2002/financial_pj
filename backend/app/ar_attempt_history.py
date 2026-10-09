"""Bounded, read-only projection of registered AR attempt metadata.

This does not inspect processes, prove financial effects, or grant execution.
The cap bounds detailed metadata only. Identity selection traverses the loaded
ORM relationship; neither its SQL load nor the entire GET cost is bounded here.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from heapq import nsmallest
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .ar_execution_safety import EFFECT_PHASES, MAX_ATTEMPTS, _state
from .workflow_action_state import ACTION_STATES


MAX_ACTION_METADATA = 2048
MAX_HISTORY_ITEMS = 256
Phase = Literal["write_ledger", "write_receipt_flow", "publish_reconciliation",
                "complete_reconciliation"]
Reason = Literal["context_invalid", "index_invalid", "index_missing", "action_missing",
                 "action_identity_invalid", "action_identity_conflict", "action_phase_mismatch",
                 "action_counter_invalid", "attempt_identity_conflict", "attempt_history_missing",
                 "timestamp_invalid", "action_scan_truncated", "history_output_truncated",
                 "action_metadata_invalid"]


class ArAttemptHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: UUID
    attempt: int | None = Field(default=None, ge=1)
    phase: Phase
    record_state: Literal["intent_recorded", "phase_completed", "legacy_unknown"]
    binding_sha256: str = Field(default="", pattern=r"^(?:[0-9a-f]{64})?$")
    material_version: int | None = Field(default=None, ge=1)
    intent_at: datetime | None = None
    completed_at: datetime | None = None
    missing_attempt_count: int | None = Field(default=None, ge=0)
    reason_codes: list[Reason] = Field(default_factory=list, max_length=8)


class ArAttemptHistoryRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["ar-attempt-history-metadata-v1"] = "ar-attempt-history-metadata-v1"
    metadata_coverage_complete: bool
    process_evidence_checked: Literal[False] = False
    authorizes_resume: Literal[False] = False
    evidence_revision: int | None = Field(default=None, ge=0)
    snapshot_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    registered_attempt_count: int = Field(ge=0, le=MAX_ATTEMPTS)
    missing_attempt_count: int | None = Field(default=None, ge=0)
    scanned_action_count: int = Field(ge=0, le=MAX_ACTION_METADATA)
    items: list[ArAttemptHistoryItem] = Field(default_factory=list, max_length=MAX_HISTORY_ITEMS)
    reason_codes: list[Reason] = Field(default_factory=list, max_length=16)


def _uuid(value: object) -> UUID | None:
    if not isinstance(value, str) or len(value) > 36:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    except ValueError:
        return None


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def _metadata(action) -> dict:
    # These values contribute only to a digest; none is copied into public DTOs.
    fields = ("id", "workflow_id", "name", "attempt_count", "worker_id", "state",
              "queued_at", "started_at", "finished_at")
    return {name: (value.isoformat() if isinstance(value, datetime)
                   else value if isinstance(value, (str, int, bool)) or value is None
                   else {"invalid_type": type(value).__name__})
            for name in fields for value in (getattr(action, name, None),)}


def read_attempt_history(workflow, context: dict | None) -> ArAttemptHistoryRead:
    """Project immutable index facts and explicit legacy gaps without mutating input."""
    sampled = nsmallest(MAX_ACTION_METADATA + 1, workflow.actions,
                        key=lambda action: (str(action.id), str(action.name)))
    truncated = len(sampled) > MAX_ACTION_METADATA
    actions = sampled[:MAX_ACTION_METADATA]
    reasons: set[Reason] = set()
    missing: int | None = 0
    revision = None
    entries: list[dict] = []
    if context is None:
        reasons.add("context_invalid")
        missing = None
    else:
        try:
            state = _state(context, workflow.id)
            entries = state["attempts"]
            if context.get("execution_safety_v1") is not None:
                revision = state["revision"]
        except (ValueError, TypeError, KeyError, AttributeError):
            reasons.add("index_invalid")
            missing = None
    if truncated:
        reasons.add("action_scan_truncated")
        missing = None
    by_id: dict[str, list] = {}
    for action in actions:
        by_id.setdefault(action.id, []).append(action)
    registered: list[ArAttemptHistoryItem] = []
    entry_groups: dict[str, list[dict]] = {}
    for entry in entries:
        entry_groups.setdefault(entry["action_id"], []).append(entry)
    for entry in sorted(entries, key=lambda item: (item["action_id"], item["attempt"])):
        identity = _uuid(entry["action_id"])
        if identity is None:
            reasons.add("action_identity_invalid")
            missing = None
            continue
        item_reasons: set[Reason] = set()
        matches = by_id.get(entry["action_id"], [])
        if not matches:
            item_reasons.add("action_scan_truncated" if truncated else "action_missing")
            missing = None
        elif len(matches) != 1:
            item_reasons.add("action_identity_conflict")
            missing = None
        else:
            action = matches[0]
            if action.state not in ACTION_STATES:
                item_reasons.add("action_metadata_invalid")
                missing = None
            count = action.attempt_count
            if type(count) is not int or count < 0:
                item_reasons.add("action_counter_invalid")
                missing = None
            elif count < max(item["attempt"] for item in entry_groups[entry["action_id"]]):
                item_reasons.add("attempt_identity_conflict")
                missing = None
            if action.name != "ar_" + entry["phase"]:
                item_reasons.add("action_phase_mismatch")
                missing = None
            if (action.workflow_id != workflow.id
                    or any(entry[field] != getattr(workflow, field, None)
                           for field in ("owner_id", "department_id", "skill_id", "skill_hash",
                                         "reconciliation_date"))
                    or (entry["attempt"] == action.attempt_count
                        and entry["worker_id"] != action.worker_id)):
                item_reasons.add("attempt_identity_conflict")
                missing = None
        intent = _datetime(entry["intent_at"])
        completion = _datetime(entry.get("completed_at")) if entry["status"] == "phase_completed" else None
        if intent is None or (entry["status"] == "phase_completed" and completion is None):
            item_reasons.add("timestamp_invalid")
        reasons.update(item_reasons)
        registered.append(ArAttemptHistoryItem(
            action_id=identity, attempt=entry["attempt"], phase=entry["phase"],
            record_state=entry["status"], binding_sha256=entry["binding_sha256"],
            material_version=entry["material_version"], intent_at=intent, completed_at=completion,
            missing_attempt_count=None if item_reasons - {"timestamp_invalid"} else 0,
            reason_codes=sorted(item_reasons),
        ))
    gaps: list[ArAttemptHistoryItem] = []
    for action in sorted(actions, key=lambda item: (str(item.id), str(item.name))):
        phase = action.name.removeprefix("ar_") if isinstance(action.name, str) else ""
        if phase not in EFFECT_PHASES:
            continue
        identity = _uuid(action.id)
        if identity is None:
            reasons.add("action_identity_invalid")
            missing = None
            continue
        count = action.attempt_count
        started = bool(action.started_at or action.worker_id or action.state in {"running", "succeeded"})
        known = entry_groups.get(action.id, [])
        if (type(count) is int and count == 0 and not started and not known
                and action.state == "queued" and action.workflow_id == workflow.id
                and len(by_id[action.id]) == 1):
            continue
        gap_reasons: set[Reason] = set()
        if action.state not in ACTION_STATES:
            gap_reasons.add("action_metadata_invalid")
        gap_count = None
        if type(count) is not int or count < 0:
            gap_reasons.add("action_counter_invalid")
        elif count < max((entry["attempt"] for entry in known), default=0):
            gap_reasons.add("attempt_identity_conflict")
        elif action.workflow_id != workflow.id or len(by_id[action.id]) != 1:
            gap_reasons.add("action_identity_conflict")
        elif any("attempt_identity_conflict" in item.reason_codes or "action_phase_mismatch" in item.reason_codes
                 for item in registered if str(item.action_id) == action.id):
            gap_reasons.add("attempt_identity_conflict")
        else:
            gap_count = count - len(known)
            if gap_count or started and count == 0:
                gap_reasons.add("attempt_history_missing")
                if count == 0:
                    gap_count = None
        if not gap_reasons:
            continue
        if not known:
            gap_reasons.add("index_missing" if "index_invalid" not in reasons else "index_invalid")
        if "index_invalid" in reasons or "action_metadata_invalid" in gap_reasons:
            gap_count = None
        if gap_count is None:
            missing = None
        elif missing is not None:
            missing += gap_count
        reasons.update(gap_reasons)
        gaps.append(ArAttemptHistoryItem(action_id=identity, phase=phase, record_state="legacy_unknown",
                                       missing_attempt_count=gap_count, reason_codes=sorted(gap_reasons)))
    items = registered + gaps
    if len(items) > MAX_HISTORY_ITEMS:
        reasons.add("history_output_truncated")
        missing = None
        items = items[:MAX_HISTORY_ITEMS]
    fingerprint = _digest({
        "schema": "ar-attempt-history-metadata-v1",
        "context": _digest(workflow.context_json),
        "actions": sorted((_metadata(action) for action in actions), key=lambda item: _digest(item)),
        "truncated": truncated, "revision": revision, "registered": len(entries),
        "missing": missing, "reasons": sorted(reasons),
        "items": [item.model_dump(mode="json") for item in items],
    })
    return ArAttemptHistoryRead(
        metadata_coverage_complete=not reasons, evidence_revision=revision,
        snapshot_fingerprint=fingerprint, registered_attempt_count=len(entries),
        missing_attempt_count=missing, scanned_action_count=len(actions),
        items=items, reason_codes=sorted(reasons),
    )
