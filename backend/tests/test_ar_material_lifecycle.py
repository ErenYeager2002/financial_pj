import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from sqlalchemy.orm import Session
from app import ar_material_lifecycle as lifecycle, ar_publication as publication
from app.models import AuditEvent, FileRecord, WorkflowMaterialSet, WorkflowSession, WorkflowBatch
from test_refactor_event_transactions import database
from test_publication_current_evidence import seed


def receipt(db, record, manifest, replacement="replacement"):
    details = {"schema_version":"ar-workbook-retirement-v1", "identity":{
        "owner_id":record.owner_id,"department_id":record.department_id,"skill_id":record.skill_id,
        "sha256":record.sha256,"stored_path":record.stored_path},"publication":manifest,
        "replacement_material_set_id":replacement,"receipt_rows":[]}
    from app.credential_service import encrypt_secret
    envelope={"retirement_secret":encrypt_secret(json.dumps(details))}
    db.add(AuditEvent(actor_id="system", actor_role="system", department_id=record.department_id,
        action=lifecycle.RETIRED,resource_type="file",resource_id=record.id,details_json=json.dumps(envelope)))
    db.flush()


@pytest.mark.parametrize("mode", ["valid", "missing_receipt", "changed_receipt", "current", "failed"])
def test_deleted_workbooks_require_exact_historical_attestation(database,tmp_path,monkeypatch,mode):
    monkeypatch.setattr(publication,"workflow_root",lambda *_:tmp_path)
    with Session(database) as db:
        seed(db,tmp_path)
        workflow=db.get(WorkflowSession,"cancel-workflow")
        workflow.state="succeeded"
        material=db.get(WorkflowMaterialSet,"published")
        manifest=publication.publication_manifest(db,workflow)
        material.state="current" if mode=="current" else "superseded"
        record=db.get(FileRecord,"annual")
        if mode!="missing_receipt":
            attestation=dict(manifest)
            if mode=="changed_receipt":attestation["reconciliation_date"]="2026-09-19"
            receipt(db,record,attestation)
        if mode=="failed":workflow.state="failed"
        db.commit()
        Path(record.stored_path).unlink()
        with pytest.raises(ValueError):publication.publication_manifest(db,workflow)
        if mode=="valid":assert publication.publication_manifest(db,workflow,allow_retired=True)==manifest
        else:
            with pytest.raises(ValueError):publication.publication_manifest(db,workflow,allow_retired=True)


@pytest.mark.parametrize("batch_state", ["running","failed","cancelled","succeeded"])
def test_materials_change_only_when_entire_batch_succeeds(database,tmp_path,monkeypatch,batch_state):
    monkeypatch.setattr(lifecycle,"is_ar_skill",lambda _:True)
    with Session(database) as db:
        seed(db,tmp_path)
        workflow=db.get(WorkflowSession,"cancel-workflow")
        workflow.state="succeeded"
        old=WorkflowMaterialSet(id="baseline",owner_id=workflow.owner_id,department_id=workflow.department_id,
            skill_id=workflow.skill_id,version=0,state="superseded")
        db.add(old)
        batch=WorkflowBatch(id="batch",owner_id=workflow.owner_id,department_id=workflow.department_id,
            skill_id=workflow.skill_id,skill_name="test",skill_version="test",model_connection_id="test",
            model_provider="test",model_name="test",state=batch_state)
        db.add(batch);db.flush()
        workflow.batch_id=batch.id
        head=db.get(WorkflowMaterialSet,"published");head.parent_set_id=old.id
        db.commit()
        visible=lifecycle.visible_material_set(db,workflow.owner_id,workflow.department_id,workflow.skill_id)
        assert visible.id==("published" if batch_state=="succeeded" else "baseline")


@pytest.mark.parametrize("protect", ["none","current","failed","shared_path","changed_bytes"])
def test_unlink_is_guarded_and_idempotent(database,tmp_path,monkeypatch,protect):
    from app import settings as settings_module
    monkeypatch.setattr(settings_module,"settings",SimpleNamespace(upload_dir=tmp_path,workflow_dir=tmp_path))
    with Session(database) as db:
        seed(db,tmp_path)
        workflow=db.get(WorkflowSession,"cancel-workflow");workflow.state="succeeded"
        old=db.get(WorkflowMaterialSet,"published");old.state="superseded"
        new=WorkflowMaterialSet(id="replacement",owner_id=workflow.owner_id,department_id=workflow.department_id,
            skill_id=workflow.skill_id,version=2,state="current")
        db.add(new);db.flush()
        record=db.get(FileRecord,"annual")
        receipt(db,record,{})
        if protect=="current":new.state="superseded";db.flush();old.state="current"
        if protect=="failed":workflow.state="failed"
        if protect=="shared_path":
            db.add(FileRecord(id="shared",owner_id=record.owner_id,department_id=record.department_id,
                skill_id=record.skill_id,kind="input",original_name=record.original_name,stored_path=record.stored_path,
                sha256=record.sha256,size_bytes=record.size_bytes))
        db.commit()
        path=Path(record.stored_path)
        if protect=="changed_bytes":
            path.write_bytes(b"changed")
            with pytest.raises(ValueError):lifecycle.finish_retirements(db)
            assert path.exists()
        else:
            count=lifecycle.finish_retirements(db)
            assert count==(1 if protect=="none" else 0)
            assert path.exists()==(protect!="none")
            assert lifecycle.finish_retirements(db)==0
            assert db.get(FileRecord,"annual") is not None


def test_retirement_rejects_symlinks_and_outside_paths(tmp_path,monkeypatch):
    from app import settings as settings_module
    root=tmp_path/"inside";root.mkdir()
    outside=tmp_path/"outside.xlsx";outside.write_bytes(b"original")
    monkeypatch.setattr(settings_module,"settings",SimpleNamespace(upload_dir=root,workflow_dir=root))
    with pytest.raises(ValueError):lifecycle._path(SimpleNamespace(stored_path=str(outside)))
    link=root/"link.xlsx";link.symlink_to(outside)
    with pytest.raises(ValueError):lifecycle._path(SimpleNamespace(stored_path=str(link)))
    assert outside.read_bytes()==b"original"



def test_success_replaces_original_bytes_but_keeps_encrypted_facts(database,tmp_path,monkeypatch):
    import hashlib
    import openpyxl
    from app import settings as settings_module, ar_formal_ledger_service
    from app.models import WorkflowMaterialSetFile
    monkeypatch.setattr(settings_module,"settings",SimpleNamespace(upload_dir=tmp_path,workflow_dir=tmp_path))
    monkeypatch.setattr(lifecycle,"is_ar_skill",lambda _:True)
    monkeypatch.setattr(publication,"workflow_root",lambda *_:tmp_path)
    verified=[]
    monkeypatch.setattr(ar_formal_ledger_service,"read_formal_ledger_bundle",lambda db,w:verified.append(w.id))
    with Session(database) as db:
        seed(db,tmp_path)
        workflow=db.get(WorkflowSession,"cancel-workflow");workflow.state="succeeded"
        head=db.get(WorkflowMaterialSet,"published")
        baseline=WorkflowMaterialSet(id="baseline",owner_id=workflow.owner_id,department_id=workflow.department_id,
            skill_id=workflow.skill_id,version=0,state="superseded")
        db.add(baseline);db.flush();head.parent_set_id=baseline.id
        state=json.loads(workflow.context_json);state["ar_execution"]["material_set_id"]=baseline.id
        workflow.context_json=json.dumps(state)
        for role,key,year in [("profit_loss_ledgers","old-annual",2026),("receipt_flow_table","old-flow",0)]:
            path=tmp_path/(key+".xlsx")
            book=openpyxl.Workbook();sheet=book.active;sheet.title="明细"
            sheet.append(["SO","SOD","回款明细","收款日期","收款方式"])
            sheet.append(["SO-private","SOD-private",120,"2026-09-01","汇"])
            book.save(path);book.close()
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            db.add(FileRecord(id=key,owner_id=workflow.owner_id,department_id=workflow.department_id,
                skill_id=workflow.skill_id,kind="input",original_name=path.name,stored_path=str(path),
                sha256=digest,size_bytes=path.stat().st_size))
            db.flush()
            db.add(WorkflowMaterialSetFile(id=key+"-member",material_set_id=baseline.id,
                role=role,year=year,file_id=key,sha256=digest))
        db.commit()
        assert lifecycle.prepare_retirements(db)==2
        db.commit()
        assert verified==[workflow.id]
        old=db.get(FileRecord,"old-annual")
        assert lifecycle.retirement_receipt(db,old)["receipt_rows"][0]["so"]=="SO-private"
        for event in db.query(AuditEvent).filter_by(action=lifecycle.RETIRED):
            assert "SO-private" not in event.details_json and str(tmp_path) not in event.details_json
        assert lifecycle.finish_retirements(db)==2
        assert not (tmp_path/"old-annual.xlsx").exists()
        assert (tmp_path/"annual.xlsx").exists()
        assert lifecycle.finish_retirements(db)==0
        assert lifecycle.prepare_retirements(db)==0



def test_copy_inventory_preserves_reports_hold_ledgers_and_unfinished_backups(tmp_path):
    from app.ar_material_copies import copy_inventory
    names=["02_我的表副本/ledger.xlsx", "03_写入暂存区/action/02_我的表副本/flow.xlsx",
           "03_写入暂存区/action/execution-review/protection/expected_2026.xlsx",
           "03_写入暂存区/action/execution-review/flow-protection/02_我的表副本/flow.xlsx",
           "03_写入暂存区/action/execution-hold-input/挂账重扫前_20260901.xlsx",
           "03_写入暂存区/action/04_产出/核销日清_20260901.xlsx","03_台账/挂账台账.xlsx"]
    for name in names:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b"synthetic")
    for state in ["completed","prepared"]:
        directory=tmp_path/".批次发布事务"/state
        backup=directory/"backups/00000.bak";backup.parent.mkdir(parents=True);backup.write_bytes(b"backup")
        (directory/"manifest.json").write_text(json.dumps({"state":state,"files":[{
            "target":"02_我的表副本/ledger.xlsx","backup":"backups/00000.bak","existed":True}]}))
    inventory=copy_inventory(tmp_path)
    assert set(inventory)=={str(tmp_path/name) for name in names[:4]} | {
        str(tmp_path/".批次发布事务/completed/backups/00000.bak")}
