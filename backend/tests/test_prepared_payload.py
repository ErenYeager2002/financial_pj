from datetime import UTC, datetime
import json
import pytest
from app.models import RunRecord
from app.orchestrator import LlmConfig
from app.run_service import PreparedRun
from app.modules.execution.prepared_payload import freeze_prepared, restore_prepared
from pydantic import ValidationError


def prepared():
    run = RunRecord(id="synthetic", owner_id="owner", owner_name="Synthetic", department_id="finance", skill_id="tool", skill_name="Tool", skill_version="1", skill_commit="", skill_hash="a"*64, manifest_path="/synthetic/tool.yaml", manifest_snapshot="{}", adapter="python", worker_pool="python", concurrency_limit=1, state="queued", progress=0, progress_message="Queued", message="request", parameters_json='{"date":"2026-09-20"}', files_json="{}", input_hash="b"*64, idempotency_key="intent", confirmation_required=False, queued_at=datetime.now(UTC))
    config = LlmConfig(provider="synthetic", connection_id="connection", base_url="https://private.invalid", api_key="secret-not-for-storage", model="model", extra_body={"secret":"private-option"})
    return PreparedRun(run, config, {"status":"succeeded","failure_code":"","raw_response":"private-response"})


def test_freeze_restore_preserves_identity_inputs_and_fixed_timestamp_without_credentials():
    original = prepared()
    data = freeze_prepared(original)
    raw = json.dumps(data)
    for secret in ["secret-not-for-storage", "private.invalid", "private-option", "private-response"]:
        assert secret not in raw
    restored = restore_prepared(json.loads(raw))
    for field in ["id","owner_id","department_id","skill_hash","parameters_json","files_json","manifest_path","queued_at"]:
        assert getattr(restored.run,field) == getattr(original.run,field)
    assert restored.llm_config.model == "model"
    assert not hasattr(restored.llm_config,"api_key")
    assert freeze_prepared(restored) == data


@pytest.mark.parametrize("mutation", ["version", "terminal", "lease", "credentials", "unknown"])
def test_restore_rejects_unsupported_or_execution_fields(mutation):
    data = freeze_prepared(prepared())
    if mutation == "version": data["version"] = 2
    if mutation == "terminal": data["run"]["state"] = "succeeded"
    if mutation == "lease": data["run"]["worker_id"] = "worker"
    if mutation == "credentials": data["model_selection"]["api_key"] = "secret"
    if mutation == "unknown": data["extra"] = "value"
    with pytest.raises(ValidationError):
        restore_prepared(data)


def test_naive_timestamp_rejected():
    value = prepared()
    value.run.queued_at = datetime(2026,9,20)
    with pytest.raises(ValidationError):
        freeze_prepared(value)


def test_without_model_and_confirmation_preserved():
    value = prepared()
    value.run.state = "waiting_confirmation"
    value.run.confirmation_required = True
    value.run.queued_at = None
    restored = restore_prepared(freeze_prepared(PreparedRun(value.run,None,{})))
    assert restored.llm_config is None
    assert restored.run.state == "waiting_confirmation"
    assert restored.run.confirmation_required


@pytest.mark.parametrize("change", ["disabled", "workflow", "write", "external_action", "modifies"])
def test_standard_policy_rejects_unsafe_pinned_manifest(change):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.modules.execution.run_submission import assert_standard_submission
    manifest = SimpleNamespace(status="published",handler=SimpleNamespace(adapter="python"),risk=SimpleNamespace(level="read_only",modifies_uploaded_files=False))
    assert_standard_submission(manifest)
    if change == "disabled": manifest.status = "disabled"
    elif change == "workflow": manifest.handler.adapter = "workflow"
    elif change == "modifies": manifest.risk.modifies_uploaded_files = True
    else: manifest.risk.level = change
    with pytest.raises(HTTPException) as error:
        assert_standard_submission(manifest)
    assert error.value.status_code == 403
