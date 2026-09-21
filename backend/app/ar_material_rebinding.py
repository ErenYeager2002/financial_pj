"""Rebind published receipt evidence when the user selects a different workbook.

Only a verified missing fact can cease to count as applied. Conflicting facts
remain active for the financial validators; original events remain auditable.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json


def _fact(row):
    return (row.get("so"), row.get("sod"), Decimal(str(row.get("amount", 0))),
            row.get("date") or "", row.get("method") or "")


def _event_fact(event):
    return _fact({"so":event.get("so"), "sod":event.get("sod"),
                  "amount":event.get("回款明细"), "date":event.get("收款时间"),
                  "method":event.get("收款方式")})


def _group_event_facts(key, group):
    """Compare both journal kinds without guessing which duplicate is missing."""
    result = {("events", identity): _event_fact(event)
              for identity, event in (group.get("events") or {}).items()}
    ordinary = group.get("ordinary_events") or {}
    if ordinary:
        so, sod = next(iter(result.values()))[:2] if result else json.loads(key)
        for identity, event in ordinary.items():
            amount, day, method = event["signature"]
            result[("ordinary_events", identity)] = (so, sod, Decimal(str(amount)), day or "", method or "")
    return result


def rebind_missing_baseline_events(ledger, differences):
    updated = deepcopy(ledger)
    missing = {}
    for difference in differences:
        if difference.get("status") != "missing":
            continue
        expected = _fact(difference["expected"])
        if any(_fact(row) == expected for row in difference.get("current_rows", [])):
            continue
        missing[expected] = max(missing.get(expected, 0), int(difference.get("count", 0)))
    audit = []
    for key, group in updated.get("baseline_receipts", {}).items():
        facts = _group_event_facts(key, group)
        counts = Counter(facts.values())
        removed = {kind: {} for kind in ("events", "ordinary_events")}
        for (kind, identity), fact in facts.items():
            if 0 < counts[fact] <= missing.get(fact, 0):
                removed[kind][identity] = group[kind][identity]
        if not any(removed.values()):
            continue
        for kind, items in removed.items():
            if items:
                group[kind] = {identity: event for identity, event in group[kind].items() if identity not in items}
                group.setdefault("unbound_" + kind, {}).update(deepcopy(items))
        # Recompute completion on the selected workbook; preserve source allocation.
        group.pop("settled", None)
        group.pop("accrual", None)
        if not group.get("events"):
            group["scope_only"] = True
        entry = {"group": key, "event_ids": sorted(removed["events"]),
                 "reason": "verified_missing_from_selected_material"}
        if removed["ordinary_events"]:
            entry["ordinary_event_ids"] = sorted(removed["ordinary_events"])
        audit.append(entry)
    return updated, audit


def differences_from_current_rows(ledger, current_rows):
    """Prove absent journal events against all currently selected annual files.

    Unknown paid rows or partially filled receipt fields are not absence proof.
    They continue through the ordinary current-workbook validators.
    """
    differences = []
    for key, group in ledger.get("baseline_receipts", {}).items():
        facts = Counter(_group_event_facts(key, group).values())
        if not facts:
            continue
        so, sod = next(iter(facts))[:2]
        rows = [row for row in current_rows if (row.get("so"), row.get("sod")) == (so, sod)]
        if not rows:
            continue  # A missing annual workbook is not an unwritten receipt.
        known = Counter(facts)
        actual = Counter(_fact(row) for row in rows if Decimal(str(row.get("amount", 0))))
        dirty = any(not Decimal(str(row.get("amount", 0))) and
                    (row.get("date") or row.get("method")) for row in rows)
        if dirty or actual - known:
            continue
        for fact, count in facts.items():
            if actual[fact]:
                continue
            differences.append({"status":"missing", "count":count,
                "expected":dict(zip(("so","sod","amount","date","method"), fact)),
                "current_rows":rows})
    return differences
