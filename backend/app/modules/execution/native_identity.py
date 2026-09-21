"""Native session lookup and additive historical identity backfill."""
from dataclasses import dataclass, field
import re
from sqlalchemy import and_, or_, select, update
from ...models import RunRecord

LEGACY_SESSION = re.compile(r"[a-f0-9]{64}")


def command_id(run_id: str) -> str:
    return "native-run:" + run_id


def session_key(run: RunRecord) -> str | None:
    if run.adapter != "native":
        return None
    key = run.source_session_key if run.source_session_key is not None else run.idempotency_key
    return key if key and LEGACY_SESSION.fullmatch(key) else None


def session_runs_query(*, owner_id: str, department_id: str, key: str):
    if not LEGACY_SESSION.fullmatch(key):
        raise ValueError("Invalid Native session key")
    return select(RunRecord).where(
        RunRecord.owner_id == owner_id, RunRecord.department_id == department_id,
        RunRecord.adapter == "native",
        or_(RunRecord.source_session_key == key,
            and_(RunRecord.source_session_key.is_(None), RunRecord.idempotency_key == key)),
    ).order_by(RunRecord.created_at.desc(), RunRecord.id.desc())


@dataclass
class BackfillPage:
    next_cursor: str
    scanned: int = 0
    processed: int = 0
    skipped: int = 0
    anomalies: list[str] = field(default_factory=list)


def backfill_page(db, *, after_id: str = "", limit: int = 200, dry_run: bool = True):
    """Caller owns one page transaction. Report IDs only; preserve every old key.

    A concurrent change is skipped and reported, never overwritten. Restart a full
    scan after resolving anomalies. New writers already populate both fields.
    """
    if not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("Invalid backfill page size")
    rows = db.scalars(select(RunRecord).where(
        RunRecord.adapter == "native", RunRecord.id > after_id,
    ).order_by(RunRecord.id).limit(limit)).all()
    result = BackfillPage(next_cursor=after_id)
    for row in rows:
        result.scanned += 1
        result.next_cursor = row.id
        expected_command = command_id(row.id)
        if row.source_session_key is not None or row.source_command_id is not None:
            if row.source_session_key and LEGACY_SESSION.fullmatch(row.source_session_key) and row.source_command_id == expected_command:
                result.skipped += 1
            else:
                result.anomalies.append(row.id)
            continue
        if not row.idempotency_key or not LEGACY_SESSION.fullmatch(row.idempotency_key):
            result.anomalies.append(row.id)
            continue
        if not dry_run:
            changed = db.execute(update(RunRecord).where(
                RunRecord.id == row.id, RunRecord.owner_id == row.owner_id,
                RunRecord.department_id == row.department_id, RunRecord.adapter == "native",
                RunRecord.idempotency_key == row.idempotency_key,
                RunRecord.source_session_key.is_(None), RunRecord.source_command_id.is_(None),
            ).values(source_session_key=row.idempotency_key, source_command_id=expected_command)
              .execution_options(synchronize_session=False)).rowcount
            if changed != 1:
                result.anomalies.append(row.id)
                continue
        result.processed += 1
    return result
