"""Empty dates fetched alongside a nonempty date must not block ledger inheritance."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from app import ar_formal_ledger_service as service
from app import fetched_bundle_service
from app.models import WorkflowSession


@pytest.fixture
def history_case(tmp_path, monkeypatch):
    scope = {"owner_id": "test-owner", "department_id": "test", "skill_id": "ar-hexiao-daily"}
    source = SimpleNamespace(
        id="previous", context_json='{"ar_execution": {"completed": ["complete_reconciliation"]}}', **scope,
    )
    material = SimpleNamespace(source_workflow_id=source.id, files=[])
    workflow = SimpleNamespace(
        material_set=material, reconciliation_date="2026-09-04", fetched_bundle_id="fetch-bundle",
        batch=SimpleNamespace(reconciliation_dates_json='["2026-09-04", "2026-09-05", "2026-09-06"]'),
        context_json='{"fetched_data": {"review_status": "confirmed"}}', **scope,
    )
    prior = {"hexiao_date": "2026-09-03", "stage": "applied", "written": {"ledger": 2}}
    ledgers = {
        "跑批台账.json": {"start_date": "2026-09-03", "runs": {"2026-09-03": prior}},
        "父回款顺序分配台账.json": {"parents": {"test-parent": {"allocated": 10}}},
    }
    contents = {name: json.dumps(value).encode() for name, value in ledgers.items()}
    monkeypatch.setattr(service, "read_formal_ledger_bundle", lambda db, src: (
        {"publication": {"files": []}, "json_ledgers": ledgers},
        SimpleNamespace(id="formal-bundle", sha256="a" * 64), contents,
    ))
    folder = tmp_path / "03_台账"
    folder.mkdir()
    current = {"hexiao_date": "2026-09-04", "stage": "fetched", "payment_count": 1, "empty_batch": False}
    runs = {"2026-09-04": current}
    export = tmp_path / "01_智云导出"
    export.mkdir()
    members = []
    for day in ("2026-09-05", "2026-09-06"):
        runs[day] = {
            "hexiao_date": day, "stage": "classified", "payment_count": 0, "empty_batch": True,
            "first_run_at": "2026-09-07T09:01:00", "last_run_at": "2026-09-07T09:01:00",
            "note": "空批：那天没有任何核销",
        }
        name = f"取数摘要_{day.replace('-', '')}.json"
        raw = json.dumps({key: 0 for key in (
            "回款记录笔数", "下单行数", "核销明细行数", "订单明细SOD行数",
        )}).encode()
        (export / name).write_bytes(raw)
        members.append(SimpleNamespace(dataset="summary", reconciliation_date=day,
                                       relative_name=name, sha256=hashlib.sha256(raw).hexdigest()))
    bundle = SimpleNamespace(files=members, **scope)
    calls = []

    def checked_bundle(db, *, bundle_id, owner_id, dates):
        calls.append((bundle_id, owner_id, dates))
        return bundle

    monkeypatch.setattr(fetched_bundle_service, "assert_bundle_consumable", checked_bundle)
    db = SimpleNamespace(get=lambda model, key: source if (model, key) == (WorkflowSession, source.id) else None)
    return SimpleNamespace(workflow=workflow, db=db, root=tmp_path, runs=runs, bundle=bundle,
                           calls=calls, prior=prior, current=current)


def _save_local(case):
    path = case.root / "03_台账/跑批台账.json"
    path.write_text(json.dumps({"runs": case.runs}), encoding="utf-8")
    return path


def test_empty_future_dates_allow_inheritance_without_publishing_future_completion(history_case):
    case = history_case
    path = _save_local(case)
    service.inherit_formal_ledgers(case.db, case.workflow, case.root)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["runs"] == {"2026-09-03": case.prior, "2026-09-04": case.current}
    assert saved["start_date"] == "2026-09-03"
    assert json.loads((case.root / "03_台账/父回款顺序分配台账.json").read_text()) == {
        "parents": {"test-parent": {"allocated": 10}},
    }
    assert case.calls == [("fetch-bundle", "test-owner", ["2026-09-05", "2026-09-06"])]


@pytest.mark.parametrize("change", [
    {"stage": "listed"}, {"stage": "applied"}, {"payment_count": 1},
    {"payment_count": False}, {"empty_batch": False}, {"empty_batch": 1},
    {"counts": {}}, {"written": {}}, {"applied_at": "2026-09-07"},
    {"note": ""}, {"hexiao_date": "2026-09-04"},
])
def test_real_processing_or_ambiguous_rows_still_block_without_overwriting(history_case, change):
    case = history_case
    case.runs["2026-09-05"].update(change)
    path = _save_local(case)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        service.inherit_formal_ledgers(case.db, case.workflow, case.root)
    assert path.read_bytes() == before
    assert not (case.root / "03_台账/父回款顺序分配台账.json").exists()


@pytest.mark.parametrize("invalid", [
    "unconfirmed", "missing_bundle", "outside_dates", "changed_summary",
    "nonempty_summary", "missing_count", "boolean_count", "wrong_scope", "invalid_bundle",
])
def test_empty_rows_require_confirmed_matching_fetch_evidence(history_case, invalid, monkeypatch):
    case = history_case
    if invalid == "unconfirmed":
        case.workflow.context_json = '{"fetched_data": {"review_status": "waiting"}}'
    elif invalid == "missing_bundle":
        case.workflow.fetched_bundle_id = None
    elif invalid == "outside_dates":
        case.workflow.batch.reconciliation_dates_json = '["2026-09-04", "2026-09-06"]'
    elif invalid == "wrong_scope":
        case.bundle.skill_id = "other-skill"
    elif invalid == "invalid_bundle":
        def reject_bundle(*args, **kwargs):
            raise fetched_bundle_service.FetchedBundleError("取数包成员哈希不一致。")
        monkeypatch.setattr(fetched_bundle_service, "assert_bundle_consumable", reject_bundle)
    else:
        member = case.bundle.files[0]
        path = case.root / "01_智云导出" / member.relative_name
        summary = json.loads(path.read_bytes())
        if invalid == "missing_count":
            del summary["回款记录笔数"]
        else:
            summary["回款记录笔数"] = False if invalid == "boolean_count" else 1
        raw = json.dumps(summary).encode()
        path.write_bytes(raw)
        if invalid != "changed_summary":
            member.sha256 = hashlib.sha256(raw).hexdigest()
    path = _save_local(case)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        service.inherit_formal_ledgers(case.db, case.workflow, case.root)
    assert path.read_bytes() == before
    assert not (case.root / "03_台账/父回款顺序分配台账.json").exists()


def test_empty_current_date_is_only_inherited_as_fetched(history_case):
    case = history_case
    case.workflow.reconciliation_date = "2026-09-05"
    path = _save_local(case)
    service.inherit_formal_ledgers(case.db, case.workflow, case.root)
    runs = json.loads(path.read_text(encoding="utf-8"))["runs"]
    assert runs == {
        "2026-09-03": case.prior,
        "2026-09-05": {**case.runs["2026-09-05"], "stage": "fetched"},
    }


def test_retry_workspace_without_fetch_ledger_keeps_verified_history(history_case):
    case = history_case
    service.inherit_formal_ledgers(case.db, case.workflow, case.root)
    saved = json.loads((case.root / "03_台账/跑批台账.json").read_text(encoding="utf-8"))
    assert saved["runs"] == {"2026-09-03": case.prior}
    assert case.calls == []
