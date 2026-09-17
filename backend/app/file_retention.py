"""Retain the latest successful input/output set per owner, department and tool.

Only registered file-center copies are retired. Task snapshots, financial
material versions, recovery workspaces and running-task inputs remain intact.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
import json
import hashlib
import os
from pathlib import Path
import uuid

from sqlalchemy import select, text

from . import models
from .ar_skill_identity import is_ar_skill
from .audit_service import record_audit
from .database import SessionLocal
from .resource_policy import run_root, upload_root, workflow_root
from .scheduler import acquire_claim_lock
from .settings import settings
from .storage import sha256_file

TERMINAL = {'succeeded', 'failed', 'cancelled', 'canceled', 'timed_out'}


def _scope(row):
    return row.owner_id, row.department_id, row.skill_id


def _stamp(value):
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _references(raw, file_ids):
    value = json.loads(raw or '{}')
    found = set()
    def walk(item):
        if isinstance(item, dict):
            for child in item.values(): walk(child)
        elif isinstance(item, list):
            for child in item: walk(child)
        elif isinstance(item, str) and item in file_ids:
            found.add(item)
    walk(value)
    return found


def _safe_path(entry):
    path = Path(entry['path'])
    data = settings.data_dir.resolve()
    if not path.is_absolute() or path.resolve() != path or not path.is_relative_to(data):
        raise ValueError('unsafe_storage_path')
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent.is_relative_to(data)):
        raise ValueError('symlink_storage_path')
    roots = [upload_root(entry['owner_id'], entry['file_id'])]
    if entry.get('run_id'):
        roots.append(run_root(entry['owner_id'], entry['run_id']))
    if entry.get('workflow_id'):
        # Registered delivery copies only: never original ledgers or recovery staging.
        roots.append(workflow_root(entry['owner_id'], entry['workflow_id']) / 'outputs')
    if not any(path.is_relative_to(root) for root in roots):
        raise ValueError('not_a_registered_delivery_or_upload')
    return path


def _entry(record, skill_id, replacement):
    return dict(file_id=record.id, path=record.stored_path, sha256=record.sha256,
                size_bytes=record.size_bytes, kind=record.kind, owner_id=record.owner_id,
                department_id=record.department_id, skill_id=skill_id,
                run_id=record.run_id, workflow_id=record.workflow_id,
                replacement_type=replacement[0], replacement_id=replacement[1])


def plan(db, *, check_files=True):
    files = list(db.scalars(select(models.FileRecord)))
    by_id = {f.id: f for f in files}
    file_ids = set(by_id)
    runs = list(db.scalars(select(models.RunRecord)))
    workflows = list(db.scalars(select(models.WorkflowSession)))
    batches = {b.id: b for b in db.scalars(select(models.WorkflowBatch))}
    groups, origins, consumers = {}, {}, defaultdict(set)
    protected, blocked_scopes = set(), set()
    latest = {}

    def add_references(row, key, columns):
        for name in columns:
            try:
                refs = _references(getattr(row, name, '{}'), file_ids)
            except (ValueError, TypeError):
                blocked_scopes.add(_scope(row)); continue
            for file_id in refs:
                consumers[file_id].add(key)

    for kind, rows in [('run', runs), ('workflow', workflows)]:
        for row in rows:
            parent = batches.get(row.batch_id) if kind == 'workflow' and row.batch_id else row
            if parent is None or _scope(parent) != _scope(row):
                blocked_scopes.add(_scope(row)); continue
            key = ('batch', parent.id) if parent is not row else (kind, row.id)
            group_scope = _scope(row)
            was_active = groups.get(key, {}).get('active', False)
            groups[key] = dict(scope=group_scope, state=parent.state, active=was_active,
                               rank=(_stamp(getattr(parent, 'finished_at', None) or getattr(parent, 'updated_at', None) or parent.created_at), key),
                               created=_stamp(parent.created_at))
            origins[(kind, row.id)] = key
            add_references(row, key, ('files_json',))
            if parent is not row:
                add_references(parent, key, ('files_json',))
            if row.state not in TERMINAL or parent.state not in TERMINAL:
                groups[key]['active'] = True
                add_references(row, key, ('context_json', 'parameters_json'))
            if parent.state == 'succeeded':
                previous = latest.get(group_scope)
                if previous is None or groups[key]['rank'] > groups[previous]['rank']:
                    latest[group_scope] = key

    # Actions can outlive their parent's displayed terminal state.
    actions = list(db.scalars(select(models.WorkflowAction)))
    for action in actions:
        key = origins.get(('workflow', action.workflow_id))
        if key is None: continue
        if action.state in {'queued', 'running'}:
            groups[key]['active'] = True
            try:
                protected.update(_references(action.input_json, file_ids))
            except (ValueError, TypeError):
                blocked_scopes.add(groups[key]['scope'])

    drafts = list(db.scalars(select(models.TaskDraftRecord)))
    for draft in drafts:
        # Submitted drafts already belong to a Run. Other drafts remain user inputs.
        if draft.run_id: continue
        if draft.state in {'cancelled', 'canceled', 'expired', 'superseded'}: continue
        try:
            protected.update(_references(draft.files_json, file_ids))
            protected.update(_references(draft.parameters_json, file_ids))
        except (ValueError, TypeError): blocked_scopes.add(_scope(draft))

    file_groups = defaultdict(set)
    for f in files:
        if f.workflow_id:
            key = origins.get(('workflow', f.workflow_id))
        elif f.run_id:
            key = origins.get(('run', f.run_id))
        else:
            key = None
        if key:
            file_groups[f.id].add(key)
        file_groups[f.id].update(consumers[f.id])

    # Referential business records are not disposable file-center copies.
    foreign_key_ids = set()
    for table in models.Base.metadata.tables.values():
        for column in table.columns:
            if any(fk.target_fullname == 'files.id' for fk in column.foreign_keys):
                foreign_key_ids.update(db.scalars(select(column).where(column.in_(file_ids))))
    protected.update(foreign_key_ids)

    keep_groups = set(latest.values())
    for key, group in groups.items():
        selected = latest.get(group['scope'])
        if group.get('active') or selected is None or group['rank'] >= groups[selected]['rank']:
            keep_groups.add(key)
    for file_id, keys in file_groups.items():
        if keys.intersection(keep_groups): protected.add(file_id)

    valid_scopes = set()
    for group_scope, key in latest.items():
        current = [f for f in files if key in file_groups[f.id]]
        # A successful task with no published files cannot replace a prior delivery.
        if not any(f.kind == 'output' and origins.get(('workflow', f.workflow_id) if f.workflow_id else ('run', f.run_id)) == key for f in current): continue
        if any((f.owner_id, f.department_id) != group_scope[:2] or (f.skill_id and f.skill_id != group_scope[2]) for f in current): continue
        try:
            healthy = not check_files or all(Path(f.stored_path).is_file()
                          and not Path(f.stored_path).is_symlink()
                          and Path(f.stored_path).stat().st_size == f.size_bytes
                          and sha256_file(Path(f.stored_path)) == f.sha256 for f in current)
        except OSError:
            healthy = False
        if healthy and group_scope not in blocked_scopes:
            valid_scopes.add(group_scope)

    candidates, reasons = [], Counter()
    for f in files:
        if f.kind not in {'input', 'output'}: continue
        # Uploaded AR workbooks are a reusable candidate library. Only outputs
        # follow latest-success retention; users may explicitly delete inputs.
        if f.kind == 'input' and is_ar_skill(f.skill_id):
            reasons['ar_material_candidate'] += 1; continue
        keys = file_groups[f.id]
        inferred = {groups[key]['scope'] for key in keys}
        group_scope = _scope(f)
        if not f.skill_id:
            same_owner = {value for value in inferred if value[:2] == group_scope[:2]}
            if len(same_owner) != 1:
                reasons['unassigned'] += 1; continue
            group_scope = next(iter(same_owner))
        if any(value != group_scope for value in inferred):
            reasons['shared_or_mismatched_scope'] += 1; continue
        if group_scope not in valid_scopes:
            reasons['no_verified_successful_replacement'] += 1; continue
        if f.id in protected:
            reasons['latest_or_referenced'] += 1; continue
        selected = latest[group_scope]
        if not keys and _stamp(f.created_at) >= groups[selected]['created']:
            reasons['new_upload'] += 1; continue
        if sum(other.stored_path == f.stored_path for other in files) > 1:
            reasons['shared_storage_path'] += 1; continue
        entry = _entry(f, group_scope[2], selected)
        try:
            path = _safe_path(entry)
            if check_files and path.exists() and (not path.is_file() or sha256_file(path) != f.sha256):
                reasons['changed_file'] += 1; continue
        except (ValueError, OSError):
            reasons['protected_storage_location'] += 1; continue
        candidates.append(entry)
    snapshot = [[(row.__tablename__, row.id, {c.name: str(getattr(row, c.name)) for c in row.__table__.columns}) for row in rows] for rows in (files, runs, workflows, list(batches.values()), actions, drafts)]
    fingerprint = hashlib.sha256(json.dumps([snapshot, sorted(foreign_key_ids)], sort_keys=True).encode()).hexdigest()
    return {'entries': candidates, 'protected': dict(reasons), 'files_before': len(files),
            'replacement_groups': len(valid_scopes), 'fingerprint': fingerprint}


def _write_journal(path, entries):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.pending')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        json.dump(entries, handle); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(directory_fd)
    finally: os.close(directory_fd)


def _finish_pending(db, directory):
    removed_bytes = 0
    pending_count = 0
    for journal in directory.glob('*.json'):
        pending = []
        for entry in json.loads(journal.read_text()):
            # A failed transaction leaves all registrations and original files intact.
            if db.get(models.FileRecord, entry['file_id']) is not None: continue
            try:
                path = _safe_path(entry)
                if not path.exists(): continue
                if db.scalar(select(models.FileRecord.id).where(models.FileRecord.stored_path == str(path)).limit(1)):
                    pending.append(entry); continue
                if not path.is_file() or sha256_file(path) != entry['sha256']:
                    pending.append(entry); continue
                size = path.stat().st_size
                path.unlink(); removed_bytes += size
            except (ValueError, OSError):
                pending.append(entry)
        if pending:
            _write_journal(journal, pending)
            pending_count += len(pending)
        else:
            journal.unlink()
    return removed_bytes, pending_count


def cleanup(*, dry_run=True):
    directory = settings.data_dir / 'maintenance' / 'superseded-file-deletions'
    # Hashes and filesystem checks run without holding up task submissions.
    with SessionLocal() as db:
        result = plan(db)
    if dry_run:
        return result
    with SessionLocal() as db:
        acquire_claim_lock(db)
        postgres = db.get_bind().dialect.name == 'postgresql'
        if postgres:
            if not db.scalar(text("SELECT to_regclass('file_retention_receipts') IS NOT NULL")):
                raise RuntimeError('Install the reference guard before enabling retention')
            if not db.scalar(text('SELECT pg_try_advisory_xact_lock(7816091001)')):
                db.rollback()
                result.update(entries=[], postponed='file_references_busy')
                return result
        fresh = plan(db, check_files=False)
        if fresh['fingerprint'] != result['fingerprint']:
            db.rollback()
            result.update(entries=[], postponed='task_or_file_state_changed')
            return result
        entries = result['entries']
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if entries:
            journal = directory / (str(uuid.uuid4()) + '.json')
            _write_journal(journal, entries)
            for entry in entries:
                record = db.get(models.FileRecord, entry['file_id'])
                if postgres:
                    db.execute(text('INSERT INTO file_retention_receipts(file_id,stored_path) VALUES (:id,:path)'),
                               {'id': entry['file_id'], 'path': entry['path']})
                record_audit(db, action='file.superseded_by_successful_task',
                             actor_id=entry['owner_id'], actor_role='system',
                             department_id=entry['department_id'], resource_type='file',
                             resource_id=entry['file_id'], details={key: entry[key] for key in (
                                 'kind', 'skill_id', 'run_id', 'workflow_id',
                                 'replacement_type', 'replacement_id', 'sha256', 'size_bytes')})
                db.delete(record)
        db.commit()
    # Receipts prevent new references/path reuse after commit. File I/O is outside
    # the claim lock; journal replay handles interruption without losing inputs.
    with SessionLocal() as db:
        removed_bytes, pending = _finish_pending(db, directory)
    result.update(removed_bytes=removed_bytes, pending_files=pending)
    return result


def summary(result):
    counts = Counter((e['skill_id'], e['kind']) for e in result['entries'])
    return {'files_before': result['files_before'], 'retired_files': len(result['entries']),
            'by_tool_and_kind': [{'skill_id': key[0], 'kind': key[1], 'count': value}
                                 for key, value in sorted(counts.items())],
            'replacement_groups': result['replacement_groups'], 'protected': result['protected'],
            'removed_bytes': result.get('removed_bytes', 0), 'pending_files': result.get('pending_files', 0),
            'postponed': result.get('postponed')}
