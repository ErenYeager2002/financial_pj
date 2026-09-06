"""Project verified AR report counts into the existing public metric contract."""
from __future__ import annotations

from collections import Counter
from typing import Any

from .ar_execution_contract import CONTRACT_VERSION


METRIC_MEANINGS = {
    "ledger_written": "已写入并回读的首次判定记录数",
    "ledger_written_orders": "写入 SO 数；单日去重，批次为各日去重数合计，同一 SO 跨日分别计数",
    "ledger_final_records": "最终处置覆盖的首次判定记录数",
    "ledger_final_skipped": "写后复核无需再写且本条未独立写入的首次记录数",
    "ledger_skipped": "首次校验跳过记录数，与写后最终跳过分开",
    "ledger_to_fill": "写后复核新增待写记录数；非零时禁止发布",
    "unallocated_pending": "最终仍挂账的首次记录数，不重复加入独立历史挂账",
    "conflicts_pending": "最终仍有冲突的首次记录数",
    "exceptions": "最终异常的首次记录数，包含无关联 SO 的到账",
    "flow_auto_written": "流转按登记与状态回填分别统计，不相加为到账笔数",
    "flow_prefill_changed": "流转登记 SO 与交付金额后最终保留改动数",
    "flow_prefill_unchanged": "流转登记时相同值无需改动数",
    "flow_status_changed": "流转状态回填后最终保留改动数",
    "flow_status_unchanged": "流转状态回填时相同值无需改动数",
    "flow_manual_pending": "流转需人工填写的到账记录数，两个阶段不重复累加",
    "flow_incomplete_dates": "流转尚未完整执行的日期数；盈亏结果独立保留",
}
PENDING_KEYS = ("unallocated_pending", "conflicts_pending", "flow_manual_pending", "exceptions")


def metric(value: int | None, meaning: str, state: str = "value") -> dict[str, Any]:
    return {"value": value, "state": state, "meaning": meaning}


def is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def pending_items(metrics: dict) -> bool | None:
    values = [metrics[key] for key in PENDING_KEYS]
    if any(item["state"] == "value" and is_count(item["value"]) and item["value"] > 0 for item in values):
        return True
    return False if all(item["state"] == "value" and item["value"] == 0 for item in values) else None


def metrics_from_report(report: dict, date: str) -> dict[str, dict]:
    """Called once when the fixed final report is built; no workbook arithmetic."""
    if report.get("schema_version") != "ar-final-result-v1" or report.get("reconciliation_date") != date:
        raise ValueError("最终摘要的来源版本或日期与任务不一致")
    records = report.get("records")
    counts = report.get("counts") or {}
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise ValueError("最终摘要缺少逐条结果，不能从首次计划推算")
    identities = [row.get("record_id") for row in records]
    if any(not isinstance(value, str) or not value for value in identities) or len(set(identities)) != len(identities):
        raise ValueError("最终摘要存在缺失或重复的判定记录身份，不能重复计数")
    actual = Counter(row.get("final_status") for row in records)
    if set(actual) - {"completed", "skipped", "hold", "exception", "conflict"}:
        raise ValueError("最终结果存在未知处置状态，不能归入完成数量")
    written = [row for row in records if row.get("execution_status") == "written_verified"]
    expected = {**{key: actual[key] for key in ("completed", "skipped", "hold", "exception", "conflict")},
                "total": len(records), "written_records": len(written),
                "written_orders": len({row["so"] for row in written if row.get("so")}),
                "initial_skipped_records": sum(row.get("execution_status") == "skipped" for row in records)}
    for key, value in expected.items():
        supplied = counts.get(key, 0) if key in {"completed", "skipped", "hold", "exception", "conflict"} else counts.get(key)
        if not is_count(supplied) or supplied != value:
            raise ValueError(f"最终摘要数量 {key} 与逐条结果不一致")
    if (not is_count(report.get("write_count")) or report["write_count"] != len(written)
            or not is_count(report.get("skip_count")) or report["skip_count"] != expected["initial_skipped_records"]):
        raise ValueError("最终摘要的实际写入或首次跳过数量与逐条执行事实不一致")
    post_write = (report.get("post_write_validation") or {}).get("write")
    if not is_count(post_write) or post_write != 0:
        raise ValueError("最终摘要缺少零新增待写的写后校验结果")
    values = {
        "ledger_written": expected["written_records"], "ledger_written_orders": expected["written_orders"],
        "ledger_final_records": len(records), "ledger_final_skipped": actual["skipped"],
        "ledger_skipped": expected["initial_skipped_records"], "ledger_to_fill": post_write,
        "unallocated_pending": actual["hold"], "conflicts_pending": actual["conflict"], "exceptions": actual["exception"],
    }
    metrics = {key: metric(value, METRIC_MEANINGS[key]) for key, value in values.items()}
    metrics["flow_auto_written"] = metric(None, METRIC_MEANINGS["flow_auto_written"], "not_applicable")
    flow = report.get("flow") or {}
    phases = flow.get("phases") or {}
    for phase_name in ("prefill", "status"):
        phase = phases.get(phase_name) or {}
        for count_name in ("changed", "unchanged"):
            key = f"flow_{phase_name}_{count_name}"
            value = phase.get(f"{count_name}_count")
            metrics[key] = metric(value if is_count(value) else None, METRIC_MEANINGS[key],
                                  "value" if is_count(value) else "read_failed" if phase.get("state") == "failed" else "not_recorded")
    manual = flow.get("manual_count")
    metrics["flow_manual_pending"] = metric(manual if is_count(manual) else None, METRIC_MEANINGS["flow_manual_pending"],
                                            "value" if is_count(manual) else "read_failed")
    incomplete = any((phases.get(name) or {}).get("state") != "verified" for name in ("prefill", "status"))
    metrics["flow_incomplete_dates"] = metric(int(incomplete), METRIC_MEANINGS["flow_incomplete_dates"])
    return metrics


def public_final_metrics(context: dict) -> tuple[dict, str, bool | None] | None:
    execution = context.get("ar_execution") or {}
    fetched = context.get("fetched_data") or {}
    empty = context.get("empty_day_skipped") or (isinstance(fetched, dict) and fetched.get("empty_day_skipped"))
    if empty and not execution:
        metrics = {key: metric(0, meaning) for key, meaning in METRIC_MEANINGS.items()}
        metrics["flow_auto_written"] = metric(None, METRIC_MEANINGS["flow_auto_written"], "not_applicable")
        metrics.update({
            "confirmed_empty_day": metric(1, "取数已确认本日无核销记录，未执行核销写入"),
            "result_dates_total": metric(1, "本次所选日期数"),
            "result_dates_reviewed": metric(0, "空日不执行写后业务复核"),
            "result_dates_published": metric(0, "空日沿用材料，不新发布"),
            "result_dates_empty": metric(1, "取数已确认无核销记录的日期数"),
            "result_dates_legacy": metric(0, "旧版结果单独查看"),
        })
        return metrics, "day", False
    if execution.get("schema_version") != CONTRACT_VERSION:
        return None
    reference = context.get("final_result") or {}
    raw = reference.get("metrics")
    valid = (isinstance(raw, dict) and set(raw) == set(METRIC_MEANINGS)
             and reference.get("metrics_schema_version") == "ar-final-metrics-v1"
             and bool(reference.get("fingerprint"))
             and reference.get("metrics_fingerprint") == reference.get("fingerprint")
             and "build_final_report" in (execution.get("completed") or []))
    if valid:
        valid = all(isinstance(item, dict) and item.get("state") in {"value", "not_recorded", "not_applicable", "read_failed"}
                    and (is_count(item.get("value")) if item.get("state") == "value" else item.get("value") is None)
                    for item in raw.values())
    if valid:
        metrics = {key: metric(raw[key]["value"], meaning, raw[key]["state"]) for key, meaning in METRIC_MEANINGS.items()}
    else:
        metrics = {key: metric(None, meaning, "read_failed" if reference else "not_recorded") for key, meaning in METRIC_MEANINGS.items()}
    metrics.update({
        "result_dates_total": metric(1, "本次所选日期数"),
        "result_dates_reviewed": metric(int(valid), "已具备最终业务复核结果的日期数，不代表已发布"),
        "result_dates_published": metric(int(execution.get("publication") == "verified"), "已发布材料的日期数"),
        "result_dates_empty": metric(0, "取数已确认无核销记录的日期数"),
        "result_dates_legacy": metric(0, "仅有旧版结果，未混入新版最终数量的日期数"),
    })
    return metrics, "day", pending_items(metrics)


def aggregate_final_metrics(workflows: list) -> tuple[dict, bool | None] | None:
    if not any("ledger_written" in item.result_metrics or "confirmed_empty_day" in item.result_metrics for item in workflows):
        return None

    def field(workflow, key, name="value"):
        item = workflow.result_metrics.get(key)
        return item.get(name) if isinstance(item, dict) else getattr(item, name, None)

    reviewed = [item for item in workflows if field(item, "result_dates_reviewed") == 1]
    empty = [item for item in workflows if field(item, "confirmed_empty_day") == 1]
    metrics = {}
    for key, meaning in METRIC_MEANINGS.items():
        values = [field(item, key) for item in reviewed]
        states = [field(item, key, "state") for item in reviewed]
        if key == "flow_auto_written":
            metrics[key] = metric(None, meaning, "not_applicable")
        elif (reviewed or empty) and all(state == "value" for state in states) and all(is_count(value) for value in values):
            metrics[key] = metric(sum(values), meaning + "；仅统计已复核日期及已确认空日")
        else:
            metrics[key] = metric(None, meaning, "read_failed" if "read_failed" in states else "not_recorded")
    legacy_count = sum("ledger_written" not in item.result_metrics and item not in empty
                       and item.state == "succeeded" for item in workflows)
    metrics.update({
        "result_dates_total": metric(len(workflows), "批次所选日期数"),
        "result_dates_reviewed": metric(len(reviewed), "已具备最终业务复核结果的日期数，不代表已发布"),
        "result_dates_published": metric(sum(field(item, "result_dates_published") == 1 for item in workflows), "已发布材料的日期数"),
        "result_dates_empty": metric(len(empty), "取数已确认无核销记录的日期数"),
        "result_dates_legacy": metric(legacy_count, "旧版结果单独查看，未混入新版最终数量"),
    })
    pending = pending_items(metrics)
    complete = len(reviewed) + len(empty) == len(workflows)
    return metrics, pending if pending is True or complete else None
