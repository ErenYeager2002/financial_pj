"""Historical completion may register its verified publication, never write new materials."""
import json
from types import SimpleNamespace
import pytest
from sqlalchemy.orm import Session
from app import ar_execution_runner as runner, ar_publication as publication
from app import workflow_material_service as materials
from app.models import WorkflowSession
from test_refactor_event_transactions import database
from test_publication_current_evidence import seed

@pytest.mark.parametrize("case", ["completion", "no_stop", "write_ledger", "publish", "changed_bytes", "wrong_date", "missing_current"])
def test_historical_registration_only(database, tmp_path, monkeypatch, case):
    monkeypatch.setattr(publication, "workflow_root", lambda *_: tmp_path)
    with Session(database) as db: seed(db, tmp_path)
    with Session(database) as db:
        flow = db.get(WorkflowSession, "cancel-workflow")
        ctx = json.loads(flow.context_json)
        ctx["stop_after_action"] = case != "no_stop"
        flow.context_json = json.dumps(ctx)
        obj = object.__new__(runner.ArExecution)
        obj.db, obj.workflow, obj.execution, obj.date = db, flow, ctx["ar_execution"], flow.reconciliation_date
        obj.action = SimpleNamespace(name={"write_ledger":"ar_write_ledger", "publish":"ar_publish_reconciliation"}.get(case,"ar_complete_reconciliation"))
        if case == "wrong_date": obj.date = "2026-09-19"
        if case == "changed_bytes": (tmp_path/"annual.xlsx").write_bytes(b"changed")
        newer = SimpleNamespace(id="new-material", version=2)
        monkeypatch.setattr(materials,"current_material_set",lambda *args: None if case=="missing_current" else newer)
        if case == "completion": obj._verify_material_binding()
        else:
            with pytest.raises(ValueError): obj._verify_material_binding()
        assert newer.id == "new-material" and newer.version == 2
        assert flow.material_set_id == "published"
        db.rollback()
