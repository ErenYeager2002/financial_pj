"""Bounded additive Native identity migration; default is a read-only preview.

Run inside the verified finance API environment. Does not migrate schema, execute
business tasks, merge records, modify old keys, or delete anything.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.database import engine
from app.infrastructure.database.runtime_check import check_runtime_database
from app.models import RunRecord
from app.modules.execution.native_identity import backfill_page


def digest(rows):
    data = [dict(row) for row in rows]
    return hashlib.sha256(json.dumps(data,sort_keys=True,default=str,separators=(",", ":")).encode()).hexdigest()


def backfill(database, *, page_size=100, dry_run=True):
    columns = [c for c in RunRecord.__table__.columns if c.name not in {"source_session_key", "source_command_id"}]
    with Session(database) as db:
        if database.dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        before = db.execute(select(*columns).where(RunRecord.adapter == "native").order_by(RunRecord.id)).mappings().all()
    ids = [row["id"] for row in before]
    original_digest = digest(before)
    cursor = ""
    pages = []
    stopped = False
    while True:
        with Session(database) as db:
            if database.dialect.name == "postgresql":
                db.execute(text("SET LOCAL statement_timeout = '10s'"))
                db.execute(text("SET LOCAL lock_timeout = '2s'"))
                if dry_run:
                    db.execute(text("SET TRANSACTION READ ONLY"))
            page = backfill_page(db, after_id=cursor, limit=page_size, dry_run=dry_run)
            if page.anomalies:
                db.rollback()
                stopped = True
            elif dry_run:
                db.rollback()
            else:
                db.commit()
        if stopped:
            pages.append({**asdict(page), "processed":0, "rolled_back":True})
            break
        if page.scanned == 0:
            break
        if page.next_cursor <= cursor:
            raise RuntimeError("NATIVE_BACKFILL_CURSOR_DID_NOT_ADVANCE")
        pages.append(asdict(page))
        cursor = page.next_cursor
    with Session(database) as db:
        if database.dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        after = db.execute(select(*columns).where(RunRecord.id.in_(ids)).order_by(RunRecord.id)).mappings().all()
    if len(after) != len(before) or digest(after) != original_digest:
        raise RuntimeError("NATIVE_BACKFILL_ORIGINAL_FIELDS_CHANGED")
    return {"complete":not stopped, "anomalies":sum(len(p["anomalies"]) for p in pages), "dry_run":dry_run, "page_size":page_size, "pages":pages,
        "scanned":sum(p["scanned"] for p in pages), "processed":sum(p["processed"] for p in pages),
        "skipped":sum(p["skipped"] for p in pages), "original_rows":len(before),
        "original_fields_sha256":original_digest, "original_fields_unchanged":True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--page-size",type=int,default=100)
    parser.add_argument("--expected-host",required=True)
    parser.add_argument("--expected-database",required=True)
    parser.add_argument("--expected-revision",required=True)
    args = parser.parse_args()
    if (engine.dialect.name != "postgresql" or engine.url.host != args.expected_host
            or engine.url.database != args.expected_database or (engine.url.port or 5432) != 5432):
        raise RuntimeError("NATIVE_BACKFILL_TARGET_MISMATCH")
    revision = check_runtime_database(engine).revision
    if revision != args.expected_revision or revision != "f3a4b5c6d7e8":
        raise RuntimeError("NATIVE_BACKFILL_REVISION_MISMATCH")
    result = backfill(engine,page_size=args.page_size,dry_run=not args.apply)
    print(json.dumps({"revision":revision,**result},sort_keys=True))
    if not result["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
