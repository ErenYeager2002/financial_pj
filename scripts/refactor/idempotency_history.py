"""Read-only historical key analysis. Never merge, rewrite or select a winner."""
from collections import Counter, defaultdict
import hashlib
import json
import re
from sqlalchemy import text


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def analyze(rows):
    groups, cross = defaultdict(list), defaultdict(set)
    counts = Counter()
    for row in rows:
        row = dict(row)
        counts["total"] += 1
        native = row["adapter"] == "native"
        counts["native" if native else "ordinary"] += 1
        key = row["idempotency_key"] or ""
        if not key:
            counts["empty_key"] += 1
            continue
        if native:
            counts["native_legacy_format" if re.fullmatch(r"[a-f0-9]{64}", key) else "native_unknown_format"] += 1
        scope = (row["owner_id"], row["department_id"], "native" if native else "ordinary", key)
        summary = digest([row.get(k) for k in ("skill_id", "skill_hash", "message", "parameters_json", "files_json", "input_hash")])
        groups[scope].append({"id": row["id"], "input_summary_sha256": summary})
        cross[digest([row["owner_id"], key])].add(row["department_id"])
    duplicates = []
    for scope, members in groups.items():
        if len(members) < 2:
            continue
        kind = scope[2]
        counts[kind + "_duplicate_groups"] += 1
        different = len({v["input_summary_sha256"] for v in members}) > 1
        counts[kind + "_different_input_groups"] += int(different)
        duplicates.append({"scope_sha256": digest(scope), "kind":kind,
                           "classification":"shared_session" if kind == "native" else "ambiguous",
                           "different_input_summaries":different, "records":sorted(members,key=lambda v:v["id"])})
    counts["cross_department_key_groups"] = sum(len(v) > 1 for v in cross.values())
    return {"read_only":True, "counts":dict(counts), "duplicate_groups":sorted(duplicates,key=lambda v:v["scope_sha256"]),
            "limitations":["Historical summaries compare stored raw request fields; they are not canonical v1 fingerprints.",
                           "No historical duplicate is automatically bound, merged or deleted."]}


def inspect_history(engine):
    if engine.dialect.name != "postgresql":
        raise ValueError("Production history probe requires PostgreSQL read-only transaction")
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '15s'"))
            connection.execute(text("SET LOCAL lock_timeout = '2s'"))
            rows = connection.execute(text("SELECT id, owner_id, department_id, adapter, idempotency_key, skill_id, skill_hash, message, parameters_json, files_json, input_hash FROM runs")).mappings()
            return analyze(rows)
