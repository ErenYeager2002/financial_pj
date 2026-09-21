"""One comparison contract for persisted parent allocations and readback.

Only fully allocated unique SO mappings are order-independent. Partial waterfalls
retain their original order. Financial fields, execution order and unknown fields
remain part of the comparison; evidence provenance remains strict in readback.
"""
from __future__ import annotations
import copy
import math
import amount_policy


def _canonical_complete(entry: dict) -> dict:
    result = copy.deepcopy(entry)
    rows = result.get("allocations")
    if not isinstance(rows, list) or not rows:
        return result
    names = []
    for row in rows:
        so = row.get("so") if isinstance(row, dict) else None
        if not isinstance(so, str) or not so.strip() or so in names:
            raise ValueError("父回款分配的 SO 缺失或重复，不能比较或登记")
        names.append(so)
    declared = result.get("allocated_sos")
    if declared is not None and (not isinstance(declared, list) or
            any(not isinstance(so, str) for so in declared) or len(set(declared)) != len(declared)):
        raise ValueError("父回款已分配 SO 列表无效或重复")
    complete = not any(result.get(k) for k in ("partial_sos", "zero_sos", "already_settled_sos"))
    for row in rows:
        try:
            allocated, delivery = float(row["allocated"]), float(row["delivery"])
            complete = complete and row.get("status") == "full" and all(
                math.isfinite(v) and v > 0 for v in (allocated, delivery)
            ) and abs(allocated - delivery) <= float(amount_policy.TECHNICAL_EPSILON)
        except (KeyError, TypeError, ValueError):
            complete = False
    if complete:
        if declared is not None and set(declared) != set(names):
            raise ValueError("父回款完整分配的 SO 清单与分配记录不一致")
        result["allocations"] = sorted(rows, key=lambda row: row["so"])
        if declared is not None:
            result["allocated_sos"] = sorted(declared)
    return result


def readback_payload(entry: dict) -> dict:
    return _canonical_complete({k: v for k, v in entry.items()
        if k not in {"applied_at", "last_verified_at", "reused_successful_allocation"}})


def stable_payload(entry: dict) -> dict:
    return {k: v for k, v in readback_payload(entry).items()
        if k not in {"applied_sos", "applied_cases", "reconstructed_from_current_material",
                     "current_material_evidence"}}
