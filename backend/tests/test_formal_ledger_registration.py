"""Registration must reject a package that its subsequent reader would reject."""
import base64, hashlib, json
from types import SimpleNamespace
import pytest
from sqlalchemy.orm import Session
from app import ar_execution_runner as runner, ar_publication as publication
from app.models import WorkflowSession
from test_refactor_event_transactions import database
from test_publication_current_evidence import seed


@pytest.mark.parametrize("case", ["valid", "malformed", "publication", "missing_ledger", "extra_file", "binary_hash", "invalid_base64", "symlink", "copy_changed", "batch_valid", "other_date", "other_attempt", "outside_root"])
def test_validate_package_before_registering(database, tmp_path, monkeypatch, case):
    monkeypatch.setattr(publication, "workflow_root", lambda *_: tmp_path)
    monkeypatch.setattr(runner, "workflow_root", lambda *_: tmp_path)
    with Session(database) as db: seed(db, tmp_path)
    with Session(database) as db:
        workflow = db.get(WorkflowSession, "cancel-workflow")
        proof = publication.publication_manifest(db, workflow)
        binary = b"synthetic hold ledger"
        payload = {"schema_version":"ar-formal-ledgers-v1", "publication":proof,
            "json_ledgers":{"父回款顺序分配台账.json":{"parents":{}}, "跑批台账.json":{"runs":{}}},
            "binary_ledgers":{"挂账台账.xlsx":{"base64":base64.b64encode(binary).decode(),"sha256":hashlib.sha256(binary).hexdigest()}}}
        if case == "publication": payload["publication"] = {**proof,"material_version":99}
        elif case == "missing_ledger": payload["json_ledgers"].pop("跑批台账.json")
        elif case == "extra_file": payload["binary_ledgers"]["other.xlsx"] = payload["binary_ledgers"]["挂账台账.xlsx"]
        elif case == "binary_hash": payload["binary_ledgers"]["挂账台账.xlsx"]["sha256"] = "b"*64
        elif case == "invalid_base64": payload["binary_ledgers"]["挂账台账.xlsx"]["base64"] = "!invalid!"
        raw = b"not json" if case == "malformed" else json.dumps(payload).encode()
        stage = tmp_path / "batch" / "date-02" / "stage"
        stage.mkdir(parents=True)
        candidate_dir = stage / "formal-ledger-build" / "completion"
        candidate_dir.mkdir(parents=True)
        path = candidate_dir / "核销辅助台账_20260902.json"
        if case == "other_date":
            path = tmp_path / "other-date.json"
        elif case == "other_attempt":
            path = candidate_dir.parent / "other-attempt.json"
        elif case == "outside_root":
            path = tmp_path.parent / (tmp_path.name + "-outside.json")
        path.write_bytes(raw)
        if case == "symlink":
            link = tmp_path/"candidate-link.json"
            link.symlink_to(path)
            path = link
        action = SimpleNamespace(id="completion")
        db.info["ar_execution_lock"] = action.id
        # This case isolates post-script registration; authorization/leases have
        # their own entry tests. Publication proof and package reads stay real.
        monkeypatch.setattr(runner, "ArExecution", lambda *args: SimpleNamespace(verify_input_binding=lambda: None, staging=lambda: (stage, stage/"checked.json"), tag="20260902"))
        from app import workflow_service
        registrations = []
        class ReachedRegistration(Exception): pass
        original_register = workflow_service._register_artifact
        monkeypatch.setattr(workflow_service, "workflow_root", lambda *_: tmp_path)
        monkeypatch.setattr(workflow_service, "_workflow_storage_root", lambda *_: tmp_path)
        if case == "batch_valid":
            monkeypatch.setattr(runner, "workflow_root", lambda *_: tmp_path / "separate-date-task")
        def register(*args):
            registrations.append(args)
            if case == "copy_changed":
                path.write_bytes(b"changed after validation")
                return original_register(*args)
            raise ReachedRegistration()
        monkeypatch.setattr(workflow_service, "_register_artifact", register)
        result = {"formal_ledger_candidate":{"path":str(path),"fingerprint":hashlib.sha256(raw).hexdigest()}}
        with pytest.raises(ReachedRegistration if case in {"valid", "batch_valid"} else ValueError):
            runner.transition_phase(db, action, workflow, result)
        assert len(registrations) == (1 if case in {"valid", "batch_valid", "copy_changed"} else 0)
        if case == "copy_changed":
            from sqlalchemy import select
            from app.models import FileRecord
            assert not (tmp_path/"outputs"/action.id).exists()
            assert {item.id for item in db.scalars(select(FileRecord))} == {"annual", "receipt"}
            assert "formal_ledgers" not in result
        db.rollback()
