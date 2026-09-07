"""Synthetic result projection regressions; no live financial writes or services."""
import hashlib
import json
from collections import Counter
from types import SimpleNamespace

import pytest

from app import ar_result_details as details
from app.ar_execution_contract import CONTRACT_VERSION
from app.ar_result_summary import metrics_from_report


def report(rows, day="2026-09-04"):
    actual = Counter(row["final_status"] for row in rows)
    written = [row for row in rows if row["execution_status"] == "written_verified"]
    skipped = sum(row["execution_status"] == "skipped" for row in rows)
    return {
        "schema_version": "ar-final-result-v1", "reconciliation_date": day,
        "records": rows,
        "counts": {**actual, "total": len(rows), "written_records": len(written),
                   "written_orders": len({row["so"] for row in written if row.get("so")}),
                   "initial_skipped_records": skipped},
        "write_count": len(written), "skip_count": skipped,
        "post_write_validation": {"write": 0},
    }


def row(identity, status, *, written=False, ar="AR-DEMO", so="SO-DEMO"):
    return {"record_id": identity, "ar": ar, "so": so, "sod": f"SOD-{identity}",
            "execution_status": "written_verified" if written else "skipped" if status == "skipped" else "not_executed",
            "final_status": status, "final_reason": "业务原因"}


def workflow_for(tmp_path, monkeypatch, payload, *, identity="workflow-a"):
    root = tmp_path / identity
    root.mkdir(exist_ok=True)
    path = root / "final.json"
    raw = json.dumps(payload).encode()
    path.write_bytes(raw)
    fingerprint = hashlib.sha256(raw).hexdigest()
    day = payload["reconciliation_date"]
    context = {
        "ar_execution": {"schema_version": CONTRACT_VERSION, "reconciliation_date": day,
                         "completed": ["build_final_report"]},
        "final_result": {"path": str(path), "fingerprint": fingerprint,
                         "metrics": metrics_from_report(payload, day),
                         "metrics_schema_version": "ar-final-metrics-v1", "metrics_fingerprint": fingerprint},
    }
    monkeypatch.setattr(details, "workflow_root", lambda owner_id, workflow_id: tmp_path / workflow_id)
    workflow = SimpleNamespace(id=identity, owner_id="owner", reconciliation_date=day,
                               state="running", context_json=json.dumps(context))
    return workflow, path


def test_all_five_filters_preserve_metric_record_units_and_grouping(tmp_path, monkeypatch):
    rows = [row("a", "completed", written=True), row("b", "skipped"), row("c", "hold"),
            row("d", "conflict"), row("e", "exception", so=None)]
    workflow, _ = workflow_for(tmp_path, monkeypatch, report(rows))
    page = details.read_result_page(None, [workflow])
    assert page.counts == dict.fromkeys(details.CATEGORIES, 1)
    assert page.record_total == 5 and page.total == 2
    assert page.dates[0].state == "available"
    for category in details.CATEGORIES:
        selected = details.read_result_page(None, [workflow], category=category)
        assert selected.total == 1
        assert selected.groups[0].categories == [category]


def test_written_record_can_retain_hold_and_distinct_sod_outcomes(tmp_path, monkeypatch):
    record = row("a", "hold", written=True)
    record["final_outcomes"] = [
        {"sod": "SOD-A", "status": "skipped", "reason": "相同值无需再写"},
        {"sod": "SOD-B", "status": "hold", "reason": "等待交付"},
    ]
    workflow, _ = workflow_for(tmp_path, monkeypatch, report([record]))
    page = details.read_result_page(None, [workflow], category="written")
    assert page.counts["written"] == page.counts["hold"] == 1
    assert page.groups[0].categories == ["written", "hold"]
    assert [(item.sod, item.final_state) for item in page.groups[0].records] == [("SOD-A", "无需再写"), ("SOD-B", "挂账")]


def test_pagination_orders_pending_first_and_does_not_merge_dates(tmp_path, monkeypatch):
    first, _ = workflow_for(tmp_path, monkeypatch, report([row("a", "completed", written=True)]))
    second, _ = workflow_for(tmp_path, monkeypatch, report([row("b", "conflict")], "2026-09-05"), identity="workflow-b")
    page = details.read_result_page(None, [first, second], limit=1)
    assert page.total == 2 and page.next_offset == 1
    assert page.groups[0].date == "2026-09-05"
    following = details.read_result_page(None, [first, second], offset=1, limit=1)
    assert following.groups[0].date == "2026-09-04"


@pytest.mark.parametrize("failure", ["missing", "changed", "outside", "invalid_outcome"])
def test_invalid_report_is_unavailable_not_empty(tmp_path, monkeypatch, failure):
    record = row("a", "hold")
    if failure == "invalid_outcome":
        record["final_outcomes"] = [{"sod": "SOD-A", "status": [], "reason": "原因"}]
    workflow, path = workflow_for(tmp_path, monkeypatch, report([record]))
    if failure == "missing":
        path.unlink()
    elif failure == "changed":
        path.write_text("{}")
    elif failure == "outside":
        context = json.loads(workflow.context_json)
        outside = tmp_path / "outside.json"
        outside.write_bytes(path.read_bytes())
        context["final_result"]["path"] = str(outside)
        workflow.context_json = json.dumps(context)
    page = details.read_result_page(None, [workflow])
    assert page.dates[0].state == "unavailable"
    assert not page.groups


def test_reasons_redact_credentials_before_truncating(tmp_path, monkeypatch):
    record = row("a", "exception")
    record["final_reason"] = "接口凭据 password=synthetic-secret"
    workflow, _ = workflow_for(tmp_path, monkeypatch, report([record]))
    page = details.read_result_page(None, [workflow])
    assert "synthetic-secret" not in page.groups[0].records[0].reason
