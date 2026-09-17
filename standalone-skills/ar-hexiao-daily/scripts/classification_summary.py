"""Summarize classification outcomes without workbook mutation."""
from __future__ import annotations

from typing import Dict
from typing import List
import datetime as dt


_FLOW_WAIT_CODES = {"E2", "E3", "E_DELIVERY_DATE_MISSING", "E_DELIVERY_DATE_CONFLICT", "E_PARENT_ALLOCATION_HISTORY_MISSING", "E_PARENT_ALLOCATION_BASELINE_CHANGED"}

def _flow_ready(item: dict) -> str:
    """这笔 SOD 今天能不能在盈亏表里更新：ready=能（auto/拆行/指认）；wait=不能（没交付/异常）。"""
    if item.get("bucket") == "auto":
        return "ready"
    if item.get("bucket") == "hold" and (item.get("code") or "") not in _FLOW_WAIT_CODES:
        return "ready"  # E5 拆行 / E8 指认：行在表里，她更得动
    return "wait"       # E2/E3 没交付进表；exception 数据问题 → 今天都更新不了

def build_ar_summary(results: List[dict]) -> List[dict]:
    """按 AR 汇总，派生到账流转表「是否更新应收款」三态（是 / 部分 / 空白）。"""
    try:
        from flow_ledger import derive_flow_status
    except Exception:  # pragma: no cover
        def derive_flow_status(states):
            ready = sum(1 for s in states if s in ("ready", "auto"))
            if not states or ready == 0:
                return ""
            return "是" if ready == len(states) else "部分"

    by_ar: Dict[str, List[dict]] = {}
    for r in results:
        by_ar.setdefault(r.get("ar") or "-", []).append(r)
    out = []
    for ar, items in by_ar.items():
        flow_states = [_flow_ready(i) for i in items]
        out.append({
            "ar": ar,
            "so_count": len({i.get("so") for i in items if i.get("so")}),
            "行数": len(items),
            "buckets": [i["bucket"] for i in items],
            "流转表_是否更新应收款_建议": derive_flow_status(flow_states),
            "flow_locate": next((i.get("flow_locate") for i in items if i.get("flow_locate")), ""),
            "待处理SO": sorted({i.get("so") for i in items if i["bucket"] != "auto" and i.get("so")}),
        })
    return out

def _dist(items: List[dict]) -> Dict[str, int]:
    d: Dict[str, int] = {}
    for it in items:
        c = it.get("code") or "OK"
        d[c] = d.get(c, 0) + 1
    return d

def serialize_result(result: dict) -> dict:
    def fix(obj):
        if isinstance(obj, dt.date):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: fix(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [fix(x) for x in obj]
        return obj

    return fix(result)
