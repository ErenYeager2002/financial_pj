import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import RunRecord
from app.modules.execution.native_identity import backfill_page, command_id, session_key, session_runs_query
from test_refactor_event_transactions import database

KEY = "a" * 64
OTHER = "b" * 64


def make_run(rid, **kwargs):
    values = dict(id=rid, owner_id="synthetic-owner", department_id="finance", skill_id="synthetic", skill_name="Synthetic", skill_version="1", skill_hash="c" * 64, manifest_path="/synthetic", manifest_snapshot="{}", adapter="native", worker_pool="native", idempotency_key=KEY)
    values.update(kwargs)
    return RunRecord(**values)


def test_session_query_prefers_new_identity_and_isolates_scope(database):
    with Session(database) as db:
        db.add_all([make_run("legacy"),
                    *[make_run("new"+str(i), idempotency_key="", source_session_key=KEY, source_command_id=command_id("new"+str(i))) for i in range(3)],
                    make_run("moved", source_session_key=OTHER, source_command_id=command_id("moved")),
                    make_run("other-owner", owner_id="other"),
                    make_run("other-dept", department_id="other"),
                    make_run("ordinary", adapter="python")])
        db.commit()
        rows = db.scalars(session_runs_query(owner_id="synthetic-owner", department_id="finance", key=KEY)).all()
        assert {v.id for v in rows} == {"legacy", "new0", "new1", "new2"}
        assert len({v.source_command_id for v in rows if v.source_command_id}) == 3
        assert session_key(db.get(RunRecord, "moved")) == OTHER
        assert session_key(db.get(RunRecord, "ordinary")) is None


def test_backfill_is_dry_by_default_transactional_and_repeatable(database):
    with Session(database) as db:
        db.add_all([make_run("a"), make_run("b"), make_run("c", idempotency_key="unknown"), make_run("d", adapter="python"), make_run("e", source_session_key=KEY)])
        db.commit()
        dry = backfill_page(db)
        assert dry.processed == 2 and dry.anomalies == ["c", "e"]
        assert all(row.source_command_id is None for row in db.scalars(select(RunRecord)))
        page = backfill_page(db, limit=1, dry_run=False)
        assert page.next_cursor == "a" and page.processed == 1
        db.rollback()
        assert db.get(RunRecord, "a").source_session_key is None
        page = backfill_page(db, limit=1, dry_run=False)
        db.commit()
        page = backfill_page(db, after_id=page.next_cursor, limit=1, dry_run=False)
        assert page.next_cursor == "b" and page.processed == 1
        db.commit()
        page = backfill_page(db, after_id=page.next_cursor, dry_run=False)
        assert page.anomalies == ["c", "e"] and page.scanned == 2
        db.commit()
        page = backfill_page(db, dry_run=False)
        assert page.processed == 0 and page.skipped == 2 and page.anomalies == ["c", "e"]
        db.commit()
    with Session(database) as db:
        rows = db.scalars(select(RunRecord)).all()
        assert len(rows) == 5
        assert db.get(RunRecord, "a").idempotency_key == KEY
        assert db.get(RunRecord, "a").source_command_id == command_id("a")
        assert db.get(RunRecord, "b").source_command_id == command_id("b")
        assert db.get(RunRecord, "d").source_session_key is None
        assert db.get(RunRecord, "e").source_command_id is None


def test_bad_session_or_page_rejected(database):
    with pytest.raises(ValueError):
        session_runs_query(owner_id="owner", department_id="finance", key="../outside")
    with Session(database) as db, pytest.raises(ValueError):
        backfill_page(db, limit=0)


def test_backfill_command_pages_preserve_history_and_report_partial_stop(database):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "scripts/refactor/backfill_native_identity.py"
    spec = importlib.util.spec_from_file_location("native_backfill_command",path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Session(database) as db:
        db.add_all([make_run("a"),make_run("b"),make_run("c",idempotency_key="invalid")])
        db.commit()
    dry = module.backfill(database,page_size=1)
    assert not dry["complete"] and dry["processed"]==2 and dry["anomalies"]==1
    with Session(database) as db:
        assert db.get(RunRecord,"a").source_command_id is None
    applied = module.backfill(database,page_size=1,dry_run=False)
    assert not applied["complete"] and applied["processed"]==2
    assert applied["pages"][-1]["rolled_back"] is True
    assert applied["original_fields_sha256"]==dry["original_fields_sha256"]
    repeated = module.backfill(database,page_size=1,dry_run=False)
    assert repeated["processed"]==0 and repeated["skipped"]==2
    with Session(database) as db:
        db.get(RunRecord,"c").idempotency_key=OTHER
        db.commit()
    completed = module.backfill(database,page_size=1,dry_run=False)
    assert completed["complete"] and completed["processed"]==1 and completed["skipped"]==2
    assert completed["original_fields_unchanged"] is True
