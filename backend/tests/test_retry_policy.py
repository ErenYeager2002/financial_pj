"""Pure common decision matrix; no production task execution."""
from copy import deepcopy
import pytest
from app.modules.execution.risk_policy import evaluate_retry_policy


def eligible():
    return ({"risk_declared": True, "snapshot_verified": True,
             "risk": {"level": "read_only", "requires_confirmation": False,
                      "requires_change_review": False, "requires_approval": False,
                      "modifies_uploaded_files": False}, "adapter": "python"},
            {"adapter_safe_replay": True, "owner_authorized": True,
             "files_accessible": True, "process_exit_confirmed": True,
             "outcome_unknown": False, "cancel_requested": False,
             "state": "failed", "attempts_used": 1, "max_attempts": 2,
             "steps_retryable": True, "steps_idempotent": True})

@pytest.mark.parametrize("reason", ["manual", "lease_expired"])
def test_known_complete_read_only_and_confirmed_exit_can_retry(reason):
    snapshot, facts = eligible()
    if reason == "lease_expired": facts["state"] = "running"
    before = deepcopy((snapshot, facts))
    assert evaluate_retry_policy(snapshot, facts, reason).allowed
    assert (snapshot, facts) == before

@pytest.mark.parametrize("key,value", [
    ("adapter_safe_replay",False),("owner_authorized",False),
    ("files_accessible",False),("process_exit_confirmed",False),
    ("outcome_unknown",True),("cancel_requested",True),
    ("state","waiting_user_action"),("state","cancelled"),
    ("attempts_used",2),("attempts_used",True),("max_attempts",0),
    ("steps_retryable",False),("steps_idempotent",False)])
@pytest.mark.parametrize("reason", ["manual", "lease_expired"])
def test_both_entrypoints_deny_unsafe_or_uncertain_facts(key,value,reason):
    snapshot,facts=eligible()
    if reason == "lease_expired": facts["state"]="running"
    facts[key]=value
    assert not evaluate_retry_policy(snapshot,facts,reason).allowed

@pytest.mark.parametrize("payload", [None,[],"{}",{}, {"risk":[]}])
def test_malformed_snapshot_is_a_denial_not_exception(payload):
    _,facts=eligible()
    assert not evaluate_retry_policy(payload,facts,"manual").allowed

@pytest.mark.parametrize("key", list(eligible()[1]))
def test_missing_fact_never_acquires_default_permission(key):
    snapshot,facts=eligible();del facts[key]
    assert not evaluate_retry_policy(snapshot,facts,"manual").allowed

@pytest.mark.parametrize("key", list(eligible()[0]["risk"]))
def test_missing_risk_field_is_not_completed_by_defaults(key):
    snapshot,facts=eligible();del snapshot["risk"][key]
    assert not evaluate_retry_policy(snapshot,facts,"manual").allowed

@pytest.mark.parametrize("adapter", ["native","http","rpa","unknown",None])
def test_adapter_without_supported_replay_protocol_is_denied(adapter):
    snapshot,facts=eligible();snapshot["adapter"]=adapter
    assert not evaluate_retry_policy(snapshot,facts,"manual").allowed

@pytest.mark.parametrize("key", ["snapshot_verified","risk_declared"])
def test_unverified_normalized_snapshot_is_denied(key):
    snapshot,facts=eligible();snapshot[key]=False
    assert not evaluate_retry_policy(snapshot,facts,"manual").allowed

@pytest.mark.parametrize("risk", ["write","external_action",None])
def test_writing_risk_is_never_replayed(risk):
    snapshot,facts=eligible();snapshot["risk"]["level"]=risk
    assert not evaluate_retry_policy(snapshot,facts,"manual").allowed

@pytest.mark.parametrize("value", [True,"false",None,0])
def test_material_mutation_must_be_explicit_false(value):
    snapshot,facts=eligible();snapshot["risk"]["modifies_uploaded_files"]=value
    assert not evaluate_retry_policy(snapshot,facts,"manual").allowed


@pytest.mark.parametrize("reason", [[],{},None,1])
def test_malformed_reason_is_denied(reason):
    snapshot,facts=eligible()
    assert not evaluate_retry_policy(snapshot,facts,reason).allowed

@pytest.mark.parametrize("state", [[],{},None,1])
def test_malformed_state_is_denied(state):
    snapshot,facts=eligible();facts["state"]=state
    assert not evaluate_retry_policy(snapshot,facts,"manual").allowed

@pytest.mark.parametrize("facts", [[],{},None,"facts"])
def test_malformed_execution_facts_are_denied(facts):
    snapshot,_=eligible()
    assert not evaluate_retry_policy(snapshot,facts,"manual").allowed
