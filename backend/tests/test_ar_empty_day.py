from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from app.ar_execution_runner import ArExecution, transition_phase
from app import workflow_service as service


def test_confirmed_empty_probe_skips_classifier_without_writes(tmp_path):
    calls = []
    summary = {key: 0 for key in service.FETCHED_DATASET_COUNT_KEYS.values()}
    def run_script(name, args):
        calls.append(name)
        if name == "classify_hexiao.py":
            raise RuntimeError("目标核销日没有可处理的回款记录：2026-08-01")
    fake = SimpleNamespace(workspace=tmp_path, scripts=tmp_path, date="2026-08-01",
        context={"fetched_data": {"summary_by_date": {"2026-08-01": summary}}}, ledger_args=[],
        service=SimpleNamespace(_fetched_summary_for_date=service._fetched_summary_for_date,
            FETCHED_DATASET_COUNT_KEYS=service.FETCHED_DATASET_COUNT_KEYS,
            _run_script=lambda *args: json.dumps({"empty": True, "date": "2026-08-01", "schema": "ar-empty-day-v1"})),
        script=run_script)
    result = ArExecution.classify_receipts(fake)
    assert result["empty_day_skipped"] is True
    assert calls == ["verify_sources.py"]


def test_empty_transition_finishes_day_advances_batch_and_does_not_queue_write(monkeypatch):
    calls = []
    state = {"completed": ["inspect_materials", "classify_receipts"], "publication": "not_published"}
    result = {"ar_execution": state, "empty_day_skipped": True,
        "empty_day_evidence": {"empty": True, "date": "2026-08-01", "schema": "ar-empty-day-v1"}}
    workflow = SimpleNamespace(id="task", state="running", execution_mode="workflow", reconciliation_date="2026-08-01",
        context_json="{}", artifacts_json="[]", material_set_id="original", batch_id="batch", fetched_bundle_id=None)
    action = SimpleNamespace(id="action", name="ar_classify_receipts")
    db = SimpleNamespace(info={"ar_execution_lock": "action"})
    monkeypatch.setattr(service, "_message", lambda *args: None)
    monkeypatch.setattr(service, "_advance_batch", lambda *args: calls.append(("advance", args[2])))
    monkeypatch.setattr(service, "sync_reminder_from_workflow", lambda *args: None)
    monkeypatch.setattr(service, "_new_action", lambda *args: pytest.fail("empty day queued a write phase"))
    transition_phase(db, action, workflow, result)
    assert workflow.state == "succeeded"
    assert action.state == "succeeded"
    assert calls[0][0] == "advance" and calls[0][1]["material_set_id"] == "original"
    assert json.loads(workflow.context_json)["ar_execution"]["next_tool"] == ""


def test_empty_transition_respects_cancellation(monkeypatch):
    workflow = SimpleNamespace(id="task", state="cancelling", context_json="{}", artifacts_json="[]")
    action = SimpleNamespace(id="action", name="ar_classify_receipts")
    db = SimpleNamespace(info={"ar_execution_lock": "action"})
    monkeypatch.setattr(service, "_advance_batch", lambda *args: pytest.fail("cancelled batch advanced"))
    result = {"ar_execution": {"completed": ["inspect_materials", "classify_receipts"]}, "empty_day_skipped": True}
    transition_phase(db, action, workflow, result)
    assert workflow.state == "cancelled"


@pytest.mark.parametrize("case,expected", [("empty", True), ("recovered", False), ("orphan", False), ("bad_date", "error"), ("missing", "error")])
def test_probe_never_hides_crossdate_records_or_real_input_errors(tmp_path, case, expected):
    from app.ar_empty_day_probe import confirmed_empty
    from datetime import date
    day = date(2026, 8, 1)
    export = tmp_path / "01_智云导出"; export.mkdir()
    (export / "回款记录_20260801.xlsx").touch()
    (export / "核销明细_20260831.xlsx").touch()
    class InputError(ValueError): pass
    def load(*args, **kwargs):
        if case == "recovered": return [{"ar": "synthetic"}]
        if case == "missing": raise InputError("缺少核销明细")
        raise InputError(f"目标核销日没有可处理的回款记录：{day}")
    def rows(path):
        values = [[day]] if case == "orphan" else [[None]] if case == "bad_date" else []
        return ["核销日期"], values if "核销明细" in path.name else []
    fake = SimpleNamespace(InputError=InputError, load_exports=load, _sheet_rows=rows,
        common=SimpleNamespace(norm_date=lambda value: value))
    if expected == "error":
        with pytest.raises(ValueError): confirmed_empty(fake, tmp_path, day)
    else:
        assert confirmed_empty(fake, tmp_path, day) is expected


def test_empty_last_day_in_agent_mode_queues_batch_report(monkeypatch):
    queued = []
    workflow = SimpleNamespace(id="last", batch_id="batch", batch_sequence=1, state="succeeded",
        material_set_id="original", context_json=json.dumps({"empty_day_skipped": True}), execution_mode="pi_harness")
    batch = SimpleNamespace(workflows=[workflow], state="running")
    db = SimpleNamespace(get=lambda *args: batch)
    monkeypatch.setattr(service, "reconciliation_runner", lambda mode: SimpleNamespace(worker_finalizes_batch=lambda: False))
    monkeypatch.setattr(service, "_new_action", lambda db, workflow, name: queued.append(name))
    service._advance_batch(db, workflow, {"material_set_id": "original"})
    assert queued == ["finalize_batch"]
    assert batch.state == "finalizing"
    assert workflow.material_set_id == batch.material_set_id == "original"


def test_empty_day_passes_original_material_to_next_day(monkeypatch):
    queued = []
    first = SimpleNamespace(id="first", batch_id="batch", batch_sequence=1, state="succeeded",
        material_set_id="original", context_json=json.dumps({"empty_day_skipped": True, "fetched_data": {"bundle_id": "fetched"}}),
        fetched_bundle_id="fetched")
    following = SimpleNamespace(id="next", batch_sequence=2, state="queued", context_json="{}", reconciliation_date="2026-08-02")
    batch = SimpleNamespace(id="batch", workflows=[first, following], state="running")
    db = SimpleNamespace(get=lambda *args: batch)
    files = {"profit_loss_ledgers": [{"file_id": "ledger"}], "receipt_flow_table": [{"file_id": "flow"}]}
    monkeypatch.setattr(service, "_authoritative_material_bindings", lambda *args: files)
    monkeypatch.setattr(service, "_queue_initial_execution", lambda db, workflow: queued.append(workflow.id))
    monkeypatch.setattr(service, "_message", lambda *args: None)
    service._advance_batch(db, first, {"material_set_id": "original"})
    assert queued == ["next"] and following.state == "running"
    assert following.material_set_id == "original"
    assert json.loads(following.files_json) == files
    assert following.fetched_bundle_id == "fetched"
