"""Published evidence must reject metadata changed after a Session cached it."""
import hashlib, json
import pytest
from sqlalchemy.orm import Session
from app import ar_publication as publication
from app.ar_execution_contract import CONTRACT_VERSION, PHASES
from app.models import FileRecord, WorkflowSession, WorkflowMaterialSet, WorkflowMaterialSetFile
from test_refactor_event_transactions import database
from test_execution_authorization import _cancellation_fixture


def seed(db, root):
    _cancellation_fixture(db, "workflow")
    db.flush()
    flow = db.get(WorkflowSession, "cancel-workflow")
    flow.reconciliation_date = "2026-09-20"
    material = WorkflowMaterialSet(id="published", owner_id=flow.owner_id, department_id="finance",
        skill_id="synthetic", source_workflow_id=flow.id, version=1)
    db.add(material)
    db.flush()
    bindings = {}
    for key, role, year in [("annual", "profit_loss_ledgers", 2026), ("receipt", "receipt_flow_table", 0)]:
        path = root / (key+".xlsx")
        path.write_bytes(("synthetic "+key).encode())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        db.add(FileRecord(id=key, owner_id=flow.owner_id, department_id="finance", skill_id="synthetic",
            workflow_id=flow.id, kind="output", original_name=path.name, stored_path=str(path),
            size_bytes=path.stat().st_size, sha256=digest))
        db.flush()
        db.add(WorkflowMaterialSetFile(id=key+"-member", material_set_id=material.id,
            role=role, year=year, file_id=key, sha256=digest))
        bindings[role] = [{"file_id":key,"sha256":digest,"year":year}]
    flow.material_set_id = material.id
    flow.context_json = json.dumps({"ar_execution":{"schema_version":CONTRACT_VERSION,
        "completed":[phase.name for phase in PHASES][:-1], "publication":"verified",
        "reconciliation_date":flow.reconciliation_date,"skill_hash":flow.skill_hash,"material_set_id":None,
        "steps":{"publish_reconciliation":{"material_set_id":material.id,"material_version":1,"next_files":bindings},
                 "write_ledger":{"ledger_written":True},"write_receipt_flow":{"flow_written":True}}}})
    db.commit()


@pytest.mark.parametrize("change", ["unchanged", "historical", "material_scope", "member_hash", "member_deleted", "file_scope", "file_hash", "file_bytes"])
def test_publication_rechecks_current_evidence(database, tmp_path, monkeypatch, change):
    monkeypatch.setattr(publication, "workflow_root", lambda *_: tmp_path)
    with Session(database) as db: seed(db, tmp_path)
    with Session(database) as db:
        flow = db.get(WorkflowSession, "cancel-workflow")
        material = db.get(WorkflowMaterialSet, "published")
        members = list(material.files)
        file = db.get(FileRecord, "annual")
        assert publication.publication_manifest(db, flow)["material_set_id"] == "published"
        with Session(database) as other:
            if change == "historical": other.get(WorkflowMaterialSet, "published").state = "superseded"
            elif change == "material_scope": other.get(WorkflowMaterialSet, "published").department_id = "another"
            elif change == "member_hash": other.get(WorkflowMaterialSetFile, "annual-member").sha256 = "b"*64
            elif change == "member_deleted": other.delete(other.get(WorkflowMaterialSetFile, "annual-member"))
            elif change == "file_scope": other.get(FileRecord, "annual").department_id = "another"
            elif change == "file_hash": other.get(FileRecord, "annual").sha256 = "b"*64
            elif change == "file_bytes": (tmp_path/"annual.xlsx").write_bytes(b"changed")
            other.commit()
        if change in {"unchanged", "historical"}: assert publication.publication_manifest(db, flow)["material_set_id"] == "published"
        else:
            with pytest.raises(ValueError): publication.publication_manifest(db, flow)


@pytest.mark.parametrize("change", ["unchanged", "scope", "hash"])
def test_published_report_refreshes_its_registered_file(database, tmp_path, monkeypatch, change):
    monkeypatch.setattr(publication, "workflow_root", lambda *_: tmp_path)
    name = "核销日清_20260920.xlsx"
    path = tmp_path/name
    path.write_bytes(b"synthetic report")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with Session(database) as db:
        seed(db, tmp_path)
        flow = db.get(WorkflowSession, "cancel-workflow")
        context = json.loads(flow.context_json)
        context["ar_execution"]["steps"]["publish_reconciliation"]["artifacts"] = [{"name":name,"file_id":"report","sha256":digest}]
        flow.context_json = json.dumps(context)
        db.add(FileRecord(id="report", owner_id=flow.owner_id, department_id="finance", skill_id="synthetic",
            workflow_id=flow.id, kind="output", original_name=name, stored_path=str(path), size_bytes=path.stat().st_size, sha256=digest))
        db.commit()
    with Session(database) as db:
        flow = db.get(WorkflowSession, "cancel-workflow")
        cached = db.get(FileRecord, "report")
        assert publication.published_report(db, flow, name).sha256 == digest
        with Session(database) as other:
            if change == "scope": other.get(FileRecord, "report").department_id = "another"
            elif change == "hash": other.get(FileRecord, "report").sha256 = "b"*64
            other.commit()
        if change == "unchanged": assert publication.published_report(db, flow, name).sha256 == digest
        else:
            with pytest.raises(publication.PublishedReportError): publication.published_report(db, flow, name)
