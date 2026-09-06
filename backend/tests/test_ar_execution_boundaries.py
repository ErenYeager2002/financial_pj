from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.database import SessionLocal, init_db
from app.models import WorkflowAction, WorkflowSession
from app.leases import LeaseHeartbeat
from app.workflow_service import pi_harness_task_context
from app.ar_execution_service import require_evidence_coverage, evidence_detail_fingerprint
from app.ar_evidence_paging import PAGING_VERSION
from app.ar_evidence_paging import PAGE_BYTES, detail_page


def test_context_orders_reloaded_and_new_actions_by_actual_time():
    init_db()
    with SessionLocal() as db:
        workflow = WorkflowSession(
            id=str(uuid4()), owner_id="boundary-test", owner_name="Test", department_id="test",
            skill_id="ar-hexiao-daily", skill_name="Test", skill_version="1", skill_hash="a" * 64,
            execution_mode="pi_harness", model_connection_id="background",
            model_provider="platform", model_name="test", reconciliation_date="2026-09-03",
        )
        db.add(workflow)
        old = WorkflowAction(id=str(uuid4()), workflow=workflow, name="first",
                             queued_at=datetime(2026, 9, 3, 0, tzinfo=UTC))
        db.add(old)
        db.commit()
        db.expire_all()
        assert workflow.actions[0].queued_at.tzinfo is None  # SQLite readback
        newer = WorkflowAction(id=str(uuid4()), workflow=workflow, name="second",
            queued_at=datetime(2026, 9, 3, 9, tzinfo=timezone(timedelta(hours=8))))
        db.add(newer)
        db.flush()
        assert [item["name"] for item in pi_harness_task_context(workflow)["actions"]] == ["first", "second"]
        db.rollback()


def test_v2_action_heartbeat_preserves_queue_isolation():
    init_db()
    with SessionLocal() as db:
        action = WorkflowAction(id=str(uuid4()), workflow_id="isolated-heartbeat", name="ar_write_ledger",
            state="ar_v2:running", worker_id="v2-worker", lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        db.add(action)
        db.commit()
        LeaseHeartbeat("workflow_action", action.id, "wrong-worker")._touch()
        db.refresh(action)
        assert action.lease_expires_at.replace(tzinfo=UTC) < datetime.now(UTC)
        LeaseHeartbeat("workflow_action", action.id, "v2-worker")._touch()
        db.refresh(action)
        assert action.lease_expires_at.replace(tzinfo=UTC) > datetime.now(UTC)
        assert db.execute(text("select state from workflow_actions where id=:id"), {"id": action.id}).scalar_one() == "ar_v2:running"
        assert db.execute(text("select count(*) from workflow_actions where id=:id and state='running'"), {"id": action.id}).scalar_one() == 0
        action.state = "cancelled"
        db.commit()


def test_final_evidence_requires_current_complete_detail_not_summary_or_initial_read():
    fingerprint, record_id = "a" * 64, "b" * 64
    context = {"ar_evidence_review": {"fingerprint": fingerprint, "paging_version": PAGING_VERSION,
        "read_record_ids": [record_id], "details": {}}, "final_result": {"fingerprint": "c" * 64}}
    with pytest.raises(ValueError, match="完整明细未读完"):
        require_evidence_coverage(context, fingerprint, {record_id})
    progress = {"fingerprint": evidence_detail_fingerprint(fingerprint, "", record_id), "total": 200,
                "ranges": [[0, 100], [150, 200]]}
    context["ar_evidence_review"]["details"][record_id] = progress
    with pytest.raises(ValueError, match="完整明细未读完"):
        require_evidence_coverage(context, fingerprint, {record_id})
    progress["ranges"] = [[0, 200]]
    require_evidence_coverage(context, fingerprint, {record_id})
    with pytest.raises(ValueError, match="完整明细未读完"):
        require_evidence_coverage(context, fingerprint, {record_id}, final=True)
    progress["fingerprint"] = evidence_detail_fingerprint(fingerprint, "c" * 64, record_id)
    require_evidence_coverage(context, fingerprint, {record_id}, final=True)
    context["final_result"]["fingerprint"] = "d" * 64
    with pytest.raises(ValueError, match="完整明细未读完"):
        require_evidence_coverage(context, fingerprint, {record_id}, final=True)


def test_evidence_pages_pack_small_fields_without_losing_large_text_or_byte_bound():
    source = {"rows": [{"amount": i, "settled": True} for i in range(1500)], "reason": "说明" * 100000}
    offset, entries, page_count = 0, [], 0
    while True:
        page = detail_page("e" * 64, lambda: source, offset, "f" * 64)
        assert len(page.model_dump_json().encode("utf8")) < PAGE_BYTES + 1024
        entries.extend(page.entries)
        page_count += 1
        if page.next_offset == page.total:
            break
        assert page.next_offset > offset
        offset = page.next_offset
    assert len([entry for entry in entries if entry.path[-1] == "amount"]) == 1500
    assert "".join(entry.text for entry in entries if entry.path == ["reason"]) == source["reason"]
    assert page_count < 20
