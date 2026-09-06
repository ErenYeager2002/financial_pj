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
