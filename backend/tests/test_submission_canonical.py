from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
import pytest
from app.modules.execution.canonical import request_fingerprint, validate_request_key


def fingerprint(value, **scope):
    return request_fingerprint(operation=scope.get("operation", "run.create"), owner_id=scope.get("owner_id", "owner"), department_id=scope.get("department_id", "finance"), pinned_revision=scope.get("pinned_revision", {"skill_id":"synthetic", "hash":"a" * 64}), submitted=value)


def test_object_order_and_array_order():
    assert fingerprint({"a":1,"b":2}) == fingerprint({"b":2,"a":1})
    assert fingerprint({"a":[1,2]}) != fingerprint({"a":[2,1]})
    assert fingerprint({"a":[1,1]}) != fingerprint({"a":[1]})


def test_text_is_preserved():
    assert fingerprint({"text":" hello "}) != fingerprint({"text":"hello"})
    assert fingerprint({"text":"é"}) != fingerprint({"text":"e\u0301"})
    assert fingerprint({"text":"中文"}) == fingerprint({"text":"中文"})


def test_decimal_is_exact_and_context_independent():
    amount = Decimal("12345678901234567890123456789.1234500")
    expected = fingerprint({"amount":amount})
    with localcontext() as context:
        context.prec = 3
        assert fingerprint({"amount":amount}) == expected
    assert fingerprint({"amount":Decimal("1.00")}) == fingerprint({"amount":Decimal("1")})
    assert fingerprint({"amount":Decimal("-0.00")}) == fingerprint({"amount":Decimal("0")})
    assert fingerprint({"amount":Decimal("1")}) != fingerprint({"amount":"1"})
    assert fingerprint({"amount":Decimal("1")}) != fingerprint({"amount":["decimal","1"]})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("NaN"), Decimal("Infinity"), {1:"bad"}, {"set":{1,2}}, datetime(2026,9,20)])
def test_invalid_values_rejected(value):
    with pytest.raises(ValueError):
        fingerprint({"value":value})


def test_time_normalization_and_date_type():
    utc = datetime(2026,9,20,tzinfo=timezone.utc)
    local = utc.astimezone(timezone(timedelta(hours=8)))
    assert fingerprint({"time":utc}) == fingerprint({"time":local})
    assert fingerprint({"date":date(2026,9,20)}) != fingerprint({"date":"2026-09-20"})


@pytest.mark.parametrize("field,value", [("operation","run.retry"),("owner_id","other"),("department_id","other"),("pinned_revision",{"skill_id":"synthetic","hash":"b" * 64})])
def test_scope_and_pinned_revision_are_in_fingerprint(field, value):
    assert fingerprint({}) != fingerprint({}, **{field:value})


def test_files_roles_hashes_and_fixed_defaults():
    first = {"files":{"ledger":{"id":"one","sha256":"a"}}, "date":"2026-09-20", "mode":"default"}
    assert fingerprint(first) == fingerprint(dict(first))
    assert fingerprint(first) != fingerprint({**first,"files":{"flow":{"id":"one","sha256":"a"}}})
    assert fingerprint(first) != fingerprint({**first,"files":{"ledger":{"id":"one","sha256":"b"}}})
    assert fingerprint(first) != fingerprint({**first,"date":"2026-09-21"})
    assert fingerprint(first) != fingerprint({k:v for k,v in first.items() if k != "mode"})


@pytest.mark.parametrize("key", ["", "a" * 201, "hello\nworld", "a\u200bb", "a\x00b"])
def test_invalid_keys(key):
    with pytest.raises(ValueError):
        validate_request_key(key)


def test_valid_key_is_not_trimmed():
    assert validate_request_key(" key ") == " key "


def test_unknown_version_rejected():
    with pytest.raises(ValueError):
        request_fingerprint(operation="run.create", owner_id="one", department_id="finance", pinned_revision={}, submitted={}, version=2)
