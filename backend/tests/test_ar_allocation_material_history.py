"""History-less legacy materials must not be treated as unwritten inputs."""
import json
from types import SimpleNamespace

import pytest

from app import ar_formal_ledger_service as service
from app.models import WorkflowMaterialSet, WorkflowSession


SCOPE = {"owner_id": "test-owner", "department_id": "test", "skill_id": "ar-hexiao-daily"}


class Records:
    def __init__(self, records):
        self.records = records

    def get(self, model, key):
        return self.records.get((model, key))


def test_legacy_output_without_bound_ledger_stops_before_copy(tmp_path):
    source = SimpleNamespace(id="old-task", context_json="{}", **SCOPE)
    material = SimpleNamespace(id="selected", source_workflow_id=source.id, parent_set_id=None)
    workflow = SimpleNamespace(material_set=material, **SCOPE)
    db = Records({(WorkflowSession, source.id): source})
    with pytest.raises(ValueError, match="旧父回款分配台账"):
        service.inherit_formal_ledgers(db, workflow, tmp_path)
    assert not (tmp_path / "03_台账").exists()


def test_manual_replacement_cannot_erase_legacy_parent_history(tmp_path):
    source = SimpleNamespace(id="old-task", context_json="{}", **SCOPE)
    parent = SimpleNamespace(id="parent", source_workflow_id=source.id, parent_set_id=None, **SCOPE)
    material = SimpleNamespace(id="replacement", source_workflow_id=None, parent_set_id=parent.id)
    workflow = SimpleNamespace(material_set=material, **SCOPE)
    db = Records({(WorkflowSession, source.id): source, (WorkflowMaterialSet, parent.id): parent})
    with pytest.raises(ValueError, match="对应关系未核实"):
        service.inherit_formal_ledgers(db, workflow, tmp_path)


def test_initial_material_without_history_is_unchanged(tmp_path):
    material = SimpleNamespace(id="initial", source_workflow_id=None, parent_set_id=None)
    workflow = SimpleNamespace(material_set=material, **SCOPE)
    assert service.inherit_formal_ledgers(Records({}), workflow, tmp_path) == {"mode": "initial_material"}


def test_verified_bundle_still_inherits_exact_parent_allocation(tmp_path, monkeypatch):
    source = SimpleNamespace(id="new-task", context_json='{"ar_execution": {"completed": []}}', **SCOPE)
    material = SimpleNamespace(id="selected", source_workflow_id=source.id, parent_set_id=None, files=[])
    workflow = SimpleNamespace(material_set=material, reconciliation_date="2026-09-03", **SCOPE)
    allocation = {"version": 1, "parents": {"AR_TEST": {"parent_amount": 150.0,
                   "allocations": [{"so": "SO_SMALL", "allocated_local": 40.0},
                                   {"so": "SO_LARGE", "allocated_local": 110.0}]}}}
    ledgers = {"父回款顺序分配台账.json": allocation, "跑批台账.json": {"runs": {}}}
    contents = {name: json.dumps(value).encode() for name, value in ledgers.items()}
    record = SimpleNamespace(id="bundle", sha256="a" * 64)
    monkeypatch.setattr(service, "read_formal_ledger_bundle", lambda db, src: (
        {"publication": {"files": []}, "json_ledgers": ledgers}, record, contents,
    ))
    result = service.inherit_formal_ledgers(Records({(WorkflowSession, source.id): source}), workflow, tmp_path)
    assert result["mode"] == "published_bundle"
    assert json.loads((tmp_path / "03_台账/父回款顺序分配台账.json").read_text()) == allocation


@pytest.mark.parametrize("change", ["add_year", "replace_file", "change_hash", "remove_flow", "original_skill"])
def test_lab_annual_addition_preserves_verified_history(tmp_path, monkeypatch, change):
    scope = {**SCOPE, "skill_id": "ar-hexiao-daily-lab" if change != "original_skill" else SCOPE["skill_id"]}
    def member(role, year, ident):
        return SimpleNamespace(role=role, year=year, file_id=ident, sha256=ident * 64)
    existing = [member("profit_loss_ledgers", 2026, "a"), member("receipt_flow_table", 0, "b")]
    selected = [member(f.role, f.year, f.file_id) for f in existing]
    selected.append(member("profit_loss_ledgers", 2025, "c"))
    if change == "replace_file":
        selected[0].file_id = "replacement"
    elif change == "change_hash":
        selected[0].sha256 = "d" * 64
    elif change == "remove_flow":
        selected.pop(1)
    source = SimpleNamespace(id="source", context_json='{"ar_execution": {"schema_version": "ar-execution-v2"}}', **scope)
    parent = SimpleNamespace(id="published", parent_set_id=None, source_workflow_id=source.id, files=existing, **scope)
    material = SimpleNamespace(id="extended", parent_set_id=parent.id, source_workflow_id=None, files=selected, **scope)
    workflow = SimpleNamespace(material_set=material, reconciliation_date="2026-09-04", **scope)
    db = Records({(WorkflowSession, source.id): source, (WorkflowMaterialSet, parent.id): parent})
    ledgers = {"父回款顺序分配台账.json": {"parents": {"synthetic-parent": {"amount": 150}}}, "跑批台账.json": {"runs": {}}}
    calls = []
    def bundle(db, src):
        calls.append(src.id)
        return ({"publication": {"files": [vars(f) for f in existing]}, "json_ledgers": ledgers},
                SimpleNamespace(id="bundle", sha256="e" * 64),
                {name: json.dumps(value).encode() for name, value in ledgers.items()})
    monkeypatch.setattr(service, "read_formal_ledger_bundle", bundle)
    if change == "add_year":
        result = service.inherit_formal_ledgers(db, workflow, tmp_path)
        assert result["bound_material_set_id"] == parent.id
        assert result["selected_material_set_id"] == material.id
        assert calls == [source.id]
        assert json.loads((tmp_path / "03_台账/父回款顺序分配台账.json").read_text()) == ledgers["父回款顺序分配台账.json"]
    else:
        with pytest.raises(ValueError, match="对应关系未核实"):
            service.inherit_formal_ledgers(db, workflow, tmp_path)
        assert calls == []
        assert not (tmp_path / "03_台账").exists()
