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
    with pytest.raises(ValueError, match="旧父回款分配台账"):
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


@pytest.mark.parametrize("same_batch", [True, False])
def test_current_batch_scope_marker_is_not_issued_across_batches(tmp_path, monkeypatch, same_batch):
    source = SimpleNamespace(
        id="day-1", context_json='{"ar_execution": {"completed": []}}',
        batch_id="batch-a", batch_sequence=1, reconciliation_date="2026-09-03", **SCOPE,
    )
    material = SimpleNamespace(id="selected", source_workflow_id=source.id, parent_set_id=None, files=[])
    workflow = SimpleNamespace(
        id="day-2", material_set=material,
        batch_id="batch-a" if same_batch else "batch-b", batch_sequence=2,
        reconciliation_date="2026-09-04", **SCOPE,
    )
    ledgers = {
        "父回款顺序分配台账.json": {
            "version": 2, "parents": {"AR_PREVIOUS": {"allocations": []}},
            "baseline_receipts": {},
        },
        "跑批台账.json": {"start_date": "2026-09-03", "runs": {"2026-09-03": {"stage": "applied"}}},
    }
    contents = {name: json.dumps(value).encode() for name, value in ledgers.items()}
    monkeypatch.setattr(service, "read_formal_ledger_bundle", lambda db, src: (
        {"publication": {"files": []}, "json_ledgers": ledgers},
        SimpleNamespace(id="bundle", sha256="a" * 64), contents,
    ))
    result = service.inherit_formal_ledgers(
        Records({(WorkflowSession, source.id): source}), workflow, tmp_path,
    )
    marker = tmp_path / "03_台账" / service.CURRENT_BATCH_PRIOR_NAME
    assert marker.exists() is same_batch
    assert bool(result["current_batch_prior"]) is same_batch
    if same_batch:
        evidence = json.loads(marker.read_text())
        assert evidence["batch_id"] == "batch-a"
        assert evidence["target_reconciliation_date"] == "2026-09-04"
        assert set(evidence["ledger_json_sha256"]) == set(ledgers)


@pytest.mark.parametrize("change", ["add_year", "replace_file", "change_hash", "missing_file", "original_skill"])
def test_legacy_annual_inheritance_checks_current_registered_files(tmp_path, monkeypatch, change):
    import hashlib
    import openpyxl
    from app.models import FileRecord
    scope = {**SCOPE, "skill_id": "ar-hexiao-daily-lab" if change != "original_skill" else SCOPE["skill_id"]}
    records = {}
    def member(role, year, ident):
        path=tmp_path/(ident+'.xlsx')
        wb=openpyxl.Workbook();ws=wb.active;ws.title='明细'
        ws.append(['新智云单号','实收金额','回款明细','收款时间','收款方式'])
        ws.append(['SO_TEST','SOD_TEST',10,'2026-08-20','汇']);wb.save(path);wb.close()
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        records[(FileRecord,ident)]=SimpleNamespace(stored_path=str(path),sha256=digest,**scope)
        return SimpleNamespace(role=role,year=year,file_id=ident,sha256=digest)
    existing=[member('profit_loss_ledgers',2026,'a'),member('receipt_flow_table',0,'b')]
    selected=[SimpleNamespace(**vars(f)) for f in existing]+[member('profit_loss_ledgers',2025,'c')]
    if change=='replace_file':selected[0]=member('profit_loss_ledgers',2026,'replacement')
    if change=='change_hash':selected[0].sha256='d'*64
    if change=='missing_file':(tmp_path/'c.xlsx').unlink()
    source=SimpleNamespace(id='source',context_json='{"ar_execution": {"schema_version":"ar-execution-v2"}}',**scope)
    parent=SimpleNamespace(id='published',parent_set_id=None,source_workflow_id=source.id,files=existing,**scope)
    material=SimpleNamespace(id='extended',parent_set_id=parent.id,source_workflow_id=None,files=selected,**scope)
    workflow=SimpleNamespace(material_set=material,reconciliation_date='2026-09-04',**scope)
    records.update({(WorkflowSession,source.id):source,(WorkflowMaterialSet,parent.id):parent})
    db=Records(records)
    ledgers={'父回款顺序分配台账.json':{'parents':{}},'跑批台账.json':{'runs':{}}}
    calls=[]
    def bundle(db,src):
        calls.append(src.id)
        return ({'publication':{'files':[vars(f) for f in existing]},'json_ledgers':ledgers},
                SimpleNamespace(id='bundle',sha256='e'*64),
                {name:json.dumps(value).encode() for name,value in ledgers.items()})
    monkeypatch.setattr(service,'read_formal_ledger_bundle',bundle)
    if change in ('change_hash','missing_file'):
        with pytest.raises(ValueError,match='指纹'):
            service.inherit_formal_ledgers(db,workflow,tmp_path)
        assert not (tmp_path/'03_台账').exists()
    else:
        result=service.inherit_formal_ledgers(db,workflow,tmp_path)
        assert result['bound_material_set_id']==parent.id
        assert result['selected_material_set_id']==material.id
        assert calls==[source.id]
        assert json.loads((tmp_path/'03_台账/父回款顺序分配台账.json').read_text())==ledgers['父回款顺序分配台账.json']
