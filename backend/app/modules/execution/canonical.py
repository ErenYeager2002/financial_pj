"""Versioned submission fingerprints; callers supply already pinned, validated inputs.

This module does not resolve defaults, revisions, model choices or relative dates.
Replays must use the original reservation's pinned values. Values are type tagged
so Decimal/date representations cannot collide with user supplied JSON objects.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import unicodedata

CANONICAL_VERSION = 1
MAX_REQUEST_KEY_LENGTH = 200


def validate_request_key(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_REQUEST_KEY_LENGTH:
        raise ValueError("Invalid idempotency key length")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("Idempotency key contains control or invisible characters")
    return value


def _value(value):
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, str):
        # Preserve user text, including whitespace and Unicode code points.
        return ["str", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite decimal")
        # Decimal.normalize() rounds under the ambient context; format does not.
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        if value == 0:
            text = "0"
        return ["decimal", text]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite float")
        return ["float", repr(value)]
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("Datetime must include a timezone")
        return ["datetime", value.astimezone(timezone.utc).isoformat(timespec="microseconds")]
    if isinstance(value, date):
        return ["date", value.isoformat()]
    if isinstance(value, list):
        return ["list", [_value(item) for item in value]]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Object keys must be strings")
        return ["object", [[key, _value(value[key])] for key in sorted(value)]]
    raise ValueError("Unsupported canonical value type")


def canonical_request(*, operation: str, owner_id: str, department_id: str,
                      pinned_revision: dict, submitted: dict,
                      version: int = CANONICAL_VERSION) -> bytes:
    """Return stable bytes; operation and identity must come from server context.

    submitted is the schema-validated original request, with fixed defaults and
    file IDs/hashes grouped by role. It is not the model's interpreted output.
    No implicit collection sorting, date resolution or numeric coercion occurs.
    """
    if version != CANONICAL_VERSION:
        raise ValueError("Unsupported canonical version")
    if not all(isinstance(item, str) and item for item in (operation, owner_id, department_id)):
        raise ValueError("Missing server submission scope")
    if not isinstance(pinned_revision, dict) or not isinstance(submitted, dict):
        raise ValueError("Submission and pinned revision must be objects")
    body = {"version": version, "operation": operation, "owner_id": owner_id,
            "department_id": department_id, "pinned_revision": pinned_revision,
            "submitted": submitted}
    return json.dumps(_value(body), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def request_fingerprint(**kwargs) -> str:
    return hashlib.sha256(canonical_request(**kwargs)).hexdigest()
