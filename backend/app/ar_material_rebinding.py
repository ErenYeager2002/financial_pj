"""Rebind published receipt evidence when the user selects a different workbook.

Only a verified missing fact can cease to count as applied. Conflicting facts
remain active for the financial validators; original events remain auditable.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal


def _fact(row):
    return (row.get("so"), row.get("sod"), Decimal(str(row.get("amount", 0))),
            row.get("date") or "", row.get("method") or "")


def _event_fact(event):
    return _fact({"so":event.get("so"), "sod":event.get("sod"),
                  "amount":event.get("回款明细"), "date":event.get("收款时间"),
                  "method":event.get("收款方式")})


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
        events = group.get("events") or {}
        counts = Counter(_event_fact(event) for event in events.values())
        removed = {identity:event for identity,event in events.items()
                   if 0 < counts[_event_fact(event)] <= missing.get(_event_fact(event), 0)}
        if not removed:
            continue
        group["events"] = {identity:event for identity,event in events.items() if identity not in removed}
        group.setdefault("unbound_events", {}).update(deepcopy(removed))
        # A former fully settled result cannot describe a workbook that omits
        # one of its receipts. The classifier recomputes settlement from source.
        group.pop("settled", None)
        group.pop("accrual", None)
        if not group["events"] and (group.get("receivable_group_scope") or group.get("ordinary_events")):
            group["scope_only"] = True
        audit.append({"group":key,"event_ids":sorted(removed),
                      "reason":"verified_missing_from_selected_material"})
    return updated, audit


def differences_from_current_rows(ledger, current_rows):
    """Prove absent journal events against all currently selected annual files.

    Unknown paid rows or partially filled receipt fields are not absence proof.
    They continue through the ordinary current-workbook validators.
    """
    differences = []
    for group in ledger.get("baseline_receipts", {}).values():
        events = group.get("events") or {}
        if not events:
            continue
        facts = Counter(_event_fact(event) for event in events.values())
        so, sod = next(iter(facts))[:2]
        rows = [row for row in current_rows if (row.get("so"), row.get("sod")) == (so, sod)]
        if not rows:
            continue  # A missing annual workbook is not an unwritten receipt.
        known = Counter(facts)
        for identity, event in (group.get("ordinary_events") or {}).items():
            amount, day, method = event['signature']
            known[(so, sod, Decimal(str(amount)), day, method)] += 1
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
