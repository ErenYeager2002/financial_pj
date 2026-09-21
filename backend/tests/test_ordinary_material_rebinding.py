import copy
import json
import pytest
from app.ar_material_rebinding import differences_from_current_rows, rebind_missing_baseline_events

KEY=json.dumps(["SO_TEST","SOD_TEST"],separators=(",",":"))
def fixture(duplicate=False):
    events={"first":{"signature":[13024.1,"2026-09-03","冲预收"],"signature_index":0}}
    if duplicate: events["second"]={"signature":[13024.1,"2026-09-03","冲预收"],"signature_index":1}
    return {"parents":{"AR_TEST":{"applied":True}},"baseline_receipts":{KEY:{"baseline_receivable":54146.16,"scope_only":True,"events":{},"ordinary_events":events}}}
def row(amount="0",date="",method=""):
    return {"so":"SO_TEST","sod":"SOD_TEST","amount":amount,"date":date,"method":method}
def apply(ledger,rows):
    return rebind_missing_baseline_events(ledger,differences_from_current_rows(ledger,rows))

def test_empty_selected_receipt_unbinds_ordinary_with_audit_and_no_mutation():
    old=fixture(); original=copy.deepcopy(old)
    updated,audit=apply(old,[row()]); group=updated['baseline_receipts'][KEY]
    assert group['ordinary_events']=={}
    assert group['unbound_ordinary_events']==original['baseline_receipts'][KEY]['ordinary_events']
    assert audit[0]['ordinary_event_ids']==['first']
    assert old==original and updated['parents']==old['parents']
    assert apply(updated,[row()])==(updated,[])

@pytest.mark.parametrize('rows',[[],[row('13024.1','2026-09-03','冲预收')],[row('200','2026-09-03','冲预收')],[row('0','2026-09-03','冲预收')],[row('0','','汇')],[row('13024.1','2026-09-04','冲预收')]])
def test_conflicting_or_missing_material_keeps_ordinary_history(rows):
    old=fixture();assert apply(old,rows)==(old,[])

def test_duplicate_signature_partial_count_is_not_guessed():
    old=fixture(True)
    assert apply(old,[row('13024.1','2026-09-03','冲预收')])==(old,[])
    updated,audit=apply(old,[row()])
    assert not updated['baseline_receipts'][KEY]['ordinary_events']
    assert audit[0]['ordinary_event_ids']==['first','second']

def test_keeps_other_paid_event_and_its_occurrence_index():
    old=fixture();old['baseline_receipts'][KEY]['ordinary_events']['other']={'signature':[25,'2026-09-02','汇'],'signature_index':0}
    updated,audit=apply(old,[row('25','2026-09-02','汇'),row()])
    assert updated['baseline_receipts'][KEY]['ordinary_events']=={'other':old['baseline_receipts'][KEY]['ordinary_events']['other']}
    assert audit[0]['ordinary_event_ids']==['first']

def test_baseline_and_ordinary_share_absence_evidence_without_guessing_counts():
    old=fixture();old['baseline_receipts'][KEY]['events']['base']={'so':'SO_TEST','sod':'SOD_TEST','回款明细':13024.1,'收款时间':'2026-09-03','收款方式':'冲预收'}
    assert apply(old,[row('13024.1','2026-09-03','冲预收')])==(old,[])
    updated,audit=apply(old,[row()])
    assert not updated['baseline_receipts'][KEY]['events'] and not updated['baseline_receipts'][KEY]['ordinary_events']
    assert audit[0]['event_ids']==['base'] and audit[0]['ordinary_event_ids']==['first']
