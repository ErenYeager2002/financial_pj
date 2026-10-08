"""Real lab completion package -> backend registration under a real DB transaction.

The existing fixture isolates construction/auth setup; the lab producer and its
process journal are real. This does not cover the initial write/publish phases.
"""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import ar_execution_runner as runner, ar_formal_ledger_service as formal
from app.models import WorkflowSession, FileRecord, WorkflowMaterialSet
from test_refactor_event_transactions import database
from test_completion_after_revocation import prepare


@pytest.mark.parametrize("corruption", [None, "archive_hash", "publication"])
def test_lab_completion_package_registers_only_verified_current_state(database, tmp_path, monkeypatch, corruption):
    monkeypatch.setattr(formal,"workflow_root",lambda *_:tmp_path)
    with Session(database) as db:
        action, flow, result = prepare(db, tmp_path, monkeypatch, owner="active", action_id="a" * 32)
        original_workbooks={name:(tmp_path / (name+".xlsx")).read_bytes() for name in ("annual","receipt")}
        candidate = Path(result["formal_ledger_candidate"]["path"])
        publication = json.loads(candidate.read_text())["publication"]
        candidate.unlink()  # Fixture-owned package replaced by the real producer.
        stage = candidate.parents[2]
        checked = stage / "checked.json"
        checked.write_text(json.dumps({"hexiao_date": flow.reconciliation_date, "write": [], "skip": []}))
        from app.ar_execution_safety import register_effect_intent
        parent=WorkflowMaterialSet(id="original-material",owner_id=flow.owner_id,
                                   department_id=flow.department_id,skill_id=flow.skill_id,
                                   version=1,state="superseded")
        published=db.get(WorkflowMaterialSet,flow.material_set_id)
        published.version=2
        db.flush()
        db.add(parent);db.flush()
        published.parent_set_id=parent.id
        publication["material_version"]=2
        context = json.loads(flow.context_json)
        context["ar_execution"]["steps"]["publish_reconciliation"]["material_version"]=2
        result["ar_execution"]["steps"]["publish_reconciliation"]["material_version"]=2
        context.update(workspace=str(stage), plan_fingerprint=hashlib.sha256(checked.read_bytes()).hexdigest())
        context["ar_execution"].update(material_set_id=parent.id,
                                       material_version=parent.version,
                                       reconciliation_policy="current-workbook-v1")
        register_effect_intent(context,flow,action,"complete_reconciliation")
        flow.context_json=json.dumps(context)
        result["ar_execution"].update(material_set_id=parent.id,
                                      material_version=parent.version,
                                      reconciliation_policy="current-workbook-v1")
        db.commit()
        reference = stage / "publication-confirmed.json"
        reference.write_text(json.dumps(publication))
        journal = stage / "03_台账"
        journal.mkdir()
        old = b"unparseable historical audit"
        old_name = "父回款顺序分配台账.json"
        (journal / old_name).write_bytes(old)
        (journal / "跑批台账.json").write_bytes(old)
        vendor = Path(__file__).resolve().parents[2] / "skills/ar-hexiao-daily-lab/vendor"
        shutil.copytree(vendor,tmp_path / "skill/vendor",ignore=shutil.ignore_patterns("__pycache__"))
        scripts = tmp_path / "skill/vendor/scripts"
        subprocess.run([sys.executable, "-B", "-c",
                        "from pathlib import Path; import sys; import rescan_holds as H; w=Path(sys.argv[1]); H.save_ledger(H.ledger_path(w),[])",
                        str(stage)], cwd=scripts, check=True, capture_output=True)
        from app import ar_process_evidence as process_evidence
        monkeypatch.setattr(process_evidence,"workflow_root",lambda *_:tmp_path)
        action._ar_process_records=[]
        process_evidence.run_recorded_script(scripts,"complete_execution.py",
            ["--workspace",str(stage),"--checked",str(checked),
             "--publication",str(reference),"--attempt",action.id],action=action,workflow=flow)
        result["process_records"]=list(action._ar_process_records)
        assert action._ar_process_exit_confirmed
        assert len(result["process_records"])==1
        assert result["process_records"][0]["state"]=="exited"
        payload = json.loads(candidate.read_text())
        assert payload["json_ledgers"][old_name]["parents"] == {}
        assert set(payload["json_ledgers"]["跑批台账.json"]["runs"]) == {flow.reconciliation_date}
        assert base64.b64decode(payload["historical_audit_files"][old_name]["base64"]) == old
        assert (journal / old_name).read_bytes() == old
        if corruption == "archive_hash":
            payload["historical_audit_files"][old_name]["sha256"] = "0" * 64
        elif corruption == "publication":
            payload["publication"]["material_version"] += 1
        if corruption:
            candidate.write_text(json.dumps(payload))
        result["formal_ledger_candidate"]["fingerprint"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if corruption:
            expected_error="历史审计归档指纹不一致" if corruption=="archive_hash" else "正式辅助台账与原发布"
            with pytest.raises(ValueError,match=expected_error):
                runner.transition_phase(db, action, flow, result)
            db.rollback()
            assert {r.id for r in db.scalars(select(FileRecord))} == {"annual", "receipt"}
            assert "formal_ledgers" not in json.loads(db.get(WorkflowSession,flow.id).context_json)
            assert not (tmp_path / "outputs" / action.id).exists()
        else:
            runner.transition_phase(db, action, flow, result)
            db.commit()
            db.expire_all()
            flow = db.get(WorkflowSession, flow.id)
            assert flow.state == "succeeded"
            payload, record, contents = formal.read_formal_ledger_bundle(db,flow)
            assert json.loads(contents[old_name])["parents"] == {}
            assert old not in contents.values()
            assert base64.b64decode(payload["historical_audit_files"][old_name]["base64"]) == old
            assert record.sha256 == hashlib.sha256(candidate.read_bytes()).hexdigest()

        assert all((tmp_path / (name+".xlsx")).read_bytes()==raw for name,raw in original_workbooks.items())
