"""On-demand observation of original AR attempts, never an execution grant.

Original registered fingerprints are the only authority for reading facts.
This read model does not change the historical index, recovery or occupancy.
Counts bound this additional inspection, not the existing ORM/GET work.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .ar_attempt_history import ArAttemptHistoryRead, Phase
from .ar_execution_safety import _prepared_process_refs, _state, _terminal_process_refs
from .ar_process_evidence import SCHEMA_VERSION
from .ar_process_identity import observe_identity
from .ar_process_inspection import BINDING_FIELDS
from .ar_process_supervisor import DOMAIN_VERSION, validate_receipt
from .resource_policy import SAFE_STORAGE_COMPONENT
from .settings import settings


MAX_RECORDS = 128
MAX_FACTS = 512
MAX_FACT_BYTES = 16 * 1024
MAX_TOTAL_FACT_BYTES = 8 * 1024 * 1024
MAX_DIRECTORY_ENTRIES = 1024
MAX_PAYLOAD_BYTES = 128 * 1024
MAX_TOTAL_PAYLOAD_BYTES = 2 * 1024 * 1024
HASH = re.compile(r'[0-9a-f]{64}')
RECORD = re.compile(r'[0-9a-f]{32}')
FACT_NAMES = frozenset({'prepared.json', 'started.json', 'exited.json', 'domain-exited.json'})
Reason = Literal['context_invalid', 'index_invalid', 'attempt_unregistered',
                 'binding_invalid', 'prepared_refs_missing', 'terminal_refs_missing',
                 'terminal_refs_conflict', 'fact_missing', 'fact_invalid', 'directory_extra',
                 'scan_truncated', 'budget_exceeded', 'identity_unconfirmed',
                 'non_effect_unanchored', 'investigation_unanchored']
Liveness = Literal['running', 'not_running', 'exited_unreaped', 'identity_changed',
                   'different_scope', 'not_recorded', 'unavailable']


class ArAttemptProcessDetailsItem(BaseModel):
    model_config = ConfigDict(extra='forbid')

    action_id: UUID
    attempt: int | None = Field(default=None, ge=1)
    phase: Phase
    inspection_state: Literal['verified', 'unknown', 'invalid'] = 'unknown'
    prepared_record_count: int | None = Field(default=None, ge=0)
    registered_terminal_count: int | None = Field(default=None, ge=0)
    direct_exit_count: int | None = Field(default=None, ge=0)
    descendant_domain_count: int | None = Field(default=None, ge=0)
    coverage_complete: bool = False
    reason_codes: list[Reason] = Field(default_factory=list, max_length=12)
    liveness: dict[Liveness, int] = Field(default_factory=dict)


class ArAttemptProcessDetailsRead(BaseModel):
    model_config = ConfigDict(extra='forbid')

    schema_version: Literal['ar-attempt-process-details-v1'] = 'ar-attempt-process-details-v1'
    metadata_snapshot_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    evidence_revision: int | None = Field(default=None, ge=0)
    registered_effect_coverage_complete: bool = False
    whole_workflow_coverage: Literal['unknown'] = 'unknown'
    reason_codes: list[Reason] = Field(default_factory=list, max_length=16)
    observation_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    items: list[ArAttemptProcessDetailsItem] = Field(default_factory=list, max_length=256)


class _ReadFailure(ValueError):
    def __init__(self, reason: Reason):
        self.reason = reason


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _same(actual: object, expected: object) -> bool:
    return type(actual) is type(expected) and actual == expected


def _check_payload_encoding_size(value: dict, limit: int) -> None:
    """Bound JSON traversal and escaped UTF-8 size before allocating encoder chunks."""
    remaining = limit

    def spend(size: int) -> None:
        nonlocal remaining
        remaining -= size
        if remaining < 0:
            raise _ReadFailure('budget_exceeded')

    def visit(item: object, depth: int) -> None:
        if depth > 64:
            raise _ReadFailure('budget_exceeded')
        if isinstance(item, str):
            if len(item) > remaining - 2:
                raise _ReadFailure('budget_exceeded')
            spend(2)
            for character in item:
                ordinal = ord(character)
                if 0xD800 <= ordinal <= 0xDFFF:
                    raise _ReadFailure('terminal_refs_conflict')
                if character in '\"\\\b\f\n\r\t':
                    spend(2)
                elif ordinal < 0x20:
                    spend(6)
                else:
                    spend(1 if ordinal < 0x80 else 2 if ordinal < 0x800 else 3 if ordinal < 0x10000 else 4)
        elif isinstance(item, dict):
            spend(2 + max(len(item) - 1, 0) * 2 + len(item) * 2)
            for key, child in item.items():
                if not isinstance(key, str):
                    raise _ReadFailure('terminal_refs_conflict')
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif isinstance(item, (list, tuple)):
            spend(2 + max(len(item) - 1, 0) * 2)
            for child in item:
                visit(child, depth + 1)
        elif item is None or type(item) in {bool, int, float}:
            spend(len(json.dumps(item)))
        else:
            raise _ReadFailure('terminal_refs_conflict')

    visit(value, 0)


class _Budget:
    def __init__(self):
        self.directory_entries = self.records = self.facts = self.fact_bytes = self.payload_bytes = 0
        self.observed: list[str] = []

    def names(self, descriptor: int) -> list[str]:
        names = []
        with os.scandir(descriptor) as entries:
            for entry in entries:
                self.directory_entries += 1
                if self.directory_entries > MAX_DIRECTORY_ENTRIES:
                    raise _ReadFailure('scan_truncated')
                names.append(entry.name)
        return sorted(names)

    def fact(self, descriptor: int, name: str, fingerprint: object) -> dict:
        self.facts += 1
        if self.facts > MAX_FACTS or self.fact_bytes >= MAX_TOTAL_FACT_BYTES:
            raise _ReadFailure('budget_exceeded')
        if not isinstance(fingerprint, str) or not HASH.fullmatch(fingerprint):
            raise _ReadFailure('terminal_refs_missing')
        try:
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            try:
                info = os.fstat(handle)
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FACT_BYTES:
                    raise _ReadFailure('fact_invalid')
                raw = os.read(handle, min(MAX_FACT_BYTES, MAX_TOTAL_FACT_BYTES - self.fact_bytes) + 1)
            finally:
                os.close(handle)
        except FileNotFoundError as exc:
            raise _ReadFailure('fact_missing') from exc
        except OSError as exc:
            raise _ReadFailure('fact_invalid') from exc
        self.fact_bytes += len(raw)
        if len(raw) > MAX_FACT_BYTES or self.fact_bytes > MAX_TOTAL_FACT_BYTES:
            raise _ReadFailure('budget_exceeded')
        if hashlib.sha256(raw).hexdigest() != fingerprint:
            raise _ReadFailure('fact_invalid')
        try:
            fact = json.loads(raw)
        except (ValueError, RecursionError) as exc:
            raise _ReadFailure('fact_invalid') from exc
        if not isinstance(fact, dict):
            raise _ReadFailure('fact_invalid')
        self.observed.append(fingerprint)
        return fact

    def payload(self, value: object) -> dict | None:
        # The ORM/context are already loaded; this bounds additional encoding/parsing.
        if isinstance(value, str):
            if len(value) > MAX_PAYLOAD_BYTES:
                raise _ReadFailure('budget_exceeded')
            raw = value.encode('utf-8')
        elif isinstance(value, dict):
            _check_payload_encoding_size(value, min(
                MAX_PAYLOAD_BYTES, MAX_TOTAL_PAYLOAD_BYTES - self.payload_bytes))
            chunks, size = [], 0
            for part in json.JSONEncoder(ensure_ascii=False, sort_keys=True).iterencode(value):
                if len(part) > MAX_PAYLOAD_BYTES - size:
                    raise _ReadFailure('budget_exceeded')
                chunk = part.encode('utf-8')
                size += len(chunk)
                if size > MAX_PAYLOAD_BYTES:
                    raise _ReadFailure('budget_exceeded')
                chunks.append(chunk)
            raw = b''.join(chunks)
        else:
            return None
        if len(raw) > MAX_PAYLOAD_BYTES or self.payload_bytes + len(raw) > MAX_TOTAL_PAYLOAD_BYTES:
            raise _ReadFailure('budget_exceeded')
        self.payload_bytes += len(raw)
        try:
            payload = json.loads(raw)
        except (ValueError, RecursionError) as exc:
            raise _ReadFailure('terminal_refs_conflict') from exc
        return payload if isinstance(payload, dict) else None


@contextmanager
def _directory(parent: int, name: str):
    if (not isinstance(name, str) or not SAFE_STORAGE_COMPONENT.fullmatch(name)
            or name in {'.', '..'}):
        raise _ReadFailure('binding_invalid')
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    except FileNotFoundError as exc:
        raise _ReadFailure('fact_missing') from exc
    except OSError as exc:
        raise _ReadFailure('fact_invalid') from exc
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _journal_root(workflow):
    components = [workflow.owner_id, workflow.id, 'execution-processes']
    if any(not isinstance(part, str) or not SAFE_STORAGE_COMPONENT.fullmatch(part)
           or part in {'.', '..'} for part in components):
        raise _ReadFailure('binding_invalid')
    base = Path(settings.workflow_dir)
    if not base.is_absolute():
        raise _ReadFailure('binding_invalid')
    descriptor = os.open(base.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    opened = [descriptor]
    try:
        for part in [*base.parts[1:], *components]:
            try:
                descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                     dir_fd=descriptor)
            except FileNotFoundError as exc:
                raise _ReadFailure('fact_missing') from exc
            except OSError as exc:
                raise _ReadFailure('fact_invalid') from exc
            opened.append(descriptor)
        yield descriptor
    finally:
        for handle in reversed(opened):
            os.close(handle)


def _terminal_refs(payload: dict, entries: list[dict], *, success: bool) -> tuple[dict, list[dict]] | None:
    if 'process_records' not in payload and 'process_evidence_version' not in payload:
        return None
    refs = payload.get('process_records')
    if (payload.get('process_evidence_version') != SCHEMA_VERSION or not isinstance(refs, list)
            or not refs or len(refs) > MAX_RECORDS):
        raise _ReadFailure('terminal_refs_conflict')
    ids = [ref.get('record_id') if isinstance(ref, dict) else None for ref in refs]
    if (any(not isinstance(value, str) or not RECORD.fullmatch(value) for value in ids)
            or len(set(ids)) != len(ids)):
        raise _ReadFailure('terminal_refs_conflict')
    candidates = []
    for entry in entries:
        anchors = {ref['record_id']: ref for ref in entry.get('prepared_process_refs', [])}
        if set(ids) != set(anchors):
            continue
        if any(not _same(ref.get(key), anchors[ref['record_id']][key])
               for ref in refs for key in ('prepared_sha256', 'script')):
            continue
        if success:
            if (entry['status'] != 'phase_completed'
                    or entry['result_sha256'] != hashlib.sha256(_canonical(payload)).hexdigest()):
                continue
        elif (not _same(payload.get('action_id'), entry['action_id'])
              or not _same(payload.get('phase'), entry['phase'])):
            continue
        candidates.append(entry)
    if len(candidates) != 1:
        raise _ReadFailure('terminal_refs_conflict')
    return candidates[0], refs


def _terminal_source_keys(payload: dict | None, entries: list[dict]) -> set[tuple]:
    if isinstance(payload, dict):
        refs = payload.get('process_records')
        if isinstance(refs, list) and len(refs) <= MAX_RECORDS:
            ids = {ref.get('record_id') for ref in refs if isinstance(ref, dict)
                   and isinstance(ref.get('record_id'), str)
                   and len(ref['record_id']) == 32 and RECORD.fullmatch(ref['record_id'])}
            keys = {(entry['action_id'], entry['attempt']) for entry in entries
                    if ids & {ref['record_id'] for ref in entry.get('prepared_process_refs', [])}}
            if keys:
                return keys
        if type(payload.get('attempt')) is int:
            return {(entry['action_id'], entry['attempt']) for entry in entries
                    if all(_same(payload.get(key), entry[key]) for key in ('action_id', 'phase', 'attempt'))}
    return set()


def _prepared_fact(record_fd: int, entry: dict, anchor: dict, budget: _Budget) -> dict:
    names = budget.names(record_fd)
    if set(names) - FACT_NAMES:
        raise _ReadFailure('directory_extra')
    if any(not stat.S_ISREG(os.stat(name, dir_fd=record_fd, follow_symlinks=False).st_mode)
           for name in names):
        raise _ReadFailure('fact_invalid')
    prepared = budget.fact(record_fd, 'prepared.json', anchor['prepared_sha256'])
    expected = {'schema_version': SCHEMA_VERSION, 'record_id': anchor['record_id'],
                'action_name': 'ar_' + entry['phase'],
                **{key: entry[key] for key in ('workflow_id', 'action_id', 'attempt', 'worker_id',
                    'reconciliation_date', 'skill_hash', 'material_set_id', 'material_version',
                    'plan_fingerprint')},
                **{key: anchor[key] for key in ('script', 'script_sha256', 'arguments_sha256')}}
    if any(not _same(prepared.get(key), value) for key, value in expected.items()):
        raise _ReadFailure('binding_invalid')
    return prepared


def _registered_terminal(prepared: dict, terminal: dict | None) -> dict | None:
    if terminal is None:
        raise _ReadFailure('terminal_refs_missing')
    domain = prepared.get('execution_domain_schema')
    if domain is not None and domain != DOMAIN_VERSION:
        raise _ReadFailure('fact_invalid')
    required = ('started_sha256', 'exit_sha256', 'domain_exit_sha256') if domain else ('started_sha256', 'exit_sha256')
    if any(key not in terminal or terminal[key] is None for key in required):
        return None
    if any(not isinstance(terminal[key], str) or not HASH.fullmatch(terminal[key]) for key in required):
        raise _ReadFailure('terminal_refs_conflict')
    return terminal


def _inspect_record(record_fd: int, prepared: dict, terminal: dict,
                    budget: _Budget, item: ArAttemptProcessDetailsItem) -> tuple[int, int]:
    domain = prepared.get('execution_domain_schema')
    started = budget.fact(record_fd, 'started.json', terminal['started_sha256'])
    exited = budget.fact(record_fd, 'exited.json', terminal['exit_sha256'])
    if any(not _same(fact.get(key), prepared.get(key)) for key in BINDING_FIELDS
           for fact in (started, exited)):
        raise _ReadFailure('binding_invalid')
    pid = started.get('pid')
    if (type(pid) is not int or pid <= 0 or not _same(exited.get('pid'), pid)
            or type(exited.get('returncode')) is not int
            or exited.get('direct_process_exit_confirmed') is not True):
        raise _ReadFailure('fact_invalid')
    identity = started.get('identity')
    if (isinstance(identity, dict) and identity.get('available') is True
            and not _same(identity.get('pid'), pid)):
        raise _ReadFailure('binding_invalid')
    live = observe_identity(identity)
    item.liveness[live] = item.liveness.get(live, 0) + 1
    if live == 'running':
        raise _ReadFailure('fact_invalid')
    descendants = 0
    if domain is not None:
        if domain != DOMAIN_VERSION:
            raise _ReadFailure('fact_invalid')
        receipt = budget.fact(record_fd, 'domain-exited.json', terminal['domain_exit_sha256'])
        try:
            validate_receipt(receipt, token=prepared.get('domain_token'), supervisor_pid=pid)
        except ValueError as exc:
            raise _ReadFailure('fact_invalid') from exc
        code = receipt['script_returncode']
        if exited['returncode'] != (code if code >= 0 else 128 - code):
            raise _ReadFailure('fact_invalid')
        descendants = 1
    elif live in {'not_recorded', 'unavailable', 'different_scope', 'identity_changed'}:
        raise _ReadFailure('identity_unconfirmed')
    if exited.get('communication_completed') is not True:
        raise _ReadFailure('identity_unconfirmed')
    return 1, descendants


def read_attempt_process_details(workflow, context: dict | None,
                                 history: ArAttemptHistoryRead) -> ArAttemptProcessDetailsRead:
    """Inspect only original registered facts; no DB mutation or process control."""
    budget = _Budget()
    reasons: set[Reason] = {'non_effect_unanchored', 'investigation_unanchored'}
    items = [ArAttemptProcessDetailsItem(action_id=row.action_id, attempt=row.attempt, phase=row.phase)
             for row in history.items]
    entries = []
    revision = None
    try:
        if not isinstance(context, dict):
            raise _ReadFailure('context_invalid')
        index = _state(context, workflow.id)
        _prepared_process_refs(index)
        entries = index['attempts']
        revision = index['revision'] if context.get('execution_safety_v1') is not None else None
    except _ReadFailure as exc:
        reasons.add(exc.reason)
    except (ValueError, TypeError, KeyError, AttributeError):
        reasons.add('index_invalid')
    grouped = {}
    for entry in entries:
        grouped.setdefault(entry['action_id'], []).append(entry)
    by_key = {(entry['action_id'], entry['attempt']): entry for entry in entries}
    actions = {action.id: action for action in workflow.actions if action.id in grouped}
    terminals = {}
    terminal_errors = {}
    for action_id, originals in sorted(grouped.items()):
        legacy = [entry for entry in originals if 'terminal_process_refs' not in entry]
        for entry in originals:
            key = (entry['action_id'], entry['attempt'])
            if 'terminal_process_refs' in entry:
                try:
                    terminals[key] = _terminal_process_refs(entry)
                except (ValueError, TypeError, KeyError, AttributeError):
                    terminal_errors[key] = 'terminal_refs_conflict'
        if not legacy:
            continue
        action = actions.get(action_id)
        inputs = [(action.result_json, True)] if action is not None else []
        failure = context.get('ar_failure') if context else None
        if isinstance(failure, dict) and failure.get('action_id') == action_id:
            inputs.append((failure, False))
        legacy_keys = {(entry['action_id'], entry['attempt']) for entry in legacy}
        for raw, success in inputs:
            # Already parsed dict metadata can still identify its original source
            # when payload encoding is rejected; never parse or guess raw strings.
            source_keys = _terminal_source_keys(raw, originals) if isinstance(raw, dict) else set()
            payload = None
            try:
                payload = budget.payload(raw)
                if payload is None:
                    continue
                bridge = _terminal_refs(payload, originals, success=success)
                if bridge is None:
                    continue
                entry, refs = bridge
                if 'terminal_process_refs' in entry:
                    continue
                key = (entry['action_id'], entry['attempt'])
                if key in terminals and _canonical(terminals[key]) != _canonical(refs):
                    raise _ReadFailure('terminal_refs_conflict')
                terminals[key] = refs
            except (_ReadFailure, ValueError, TypeError, KeyError, RecursionError) as exc:
                reason = exc.reason if isinstance(exc, _ReadFailure) else 'terminal_refs_conflict'
                keys = source_keys | _terminal_source_keys(payload, originals)
                for key in keys & legacy_keys:
                    terminal_errors[key] = reason
                if not keys:
                    reasons.add(reason)
    directory_errors = {}
    try:
        if entries:
            with _journal_root(workflow) as root_fd:
                found_actions = set(budget.names(root_fd))
                if found_actions - set(grouped):
                    reasons.add('directory_extra')
                for action_id, originals in sorted(grouped.items()):
                    anchors = {ref['record_id'] for entry in originals
                               for ref in entry.get('prepared_process_refs', [])}
                    try:
                        if action_id not in found_actions:
                            raise _ReadFailure('fact_missing')
                        with _directory(root_fd, action_id) as action_fd:
                            found = set(budget.names(action_fd))
                            if found - anchors:
                                raise _ReadFailure('directory_extra')
                            for item, row in zip(items, history.items):
                                if str(item.action_id) != action_id:
                                    continue
                                entry = by_key.get((action_id, item.attempt))
                                if entry is None:
                                    item.reason_codes = ['attempt_unregistered']
                                    continue
                                refs = entry.get('prepared_process_refs', [])
                                item.prepared_record_count = len(refs)
                                try:
                                    if row.reason_codes:
                                        raise _ReadFailure('binding_invalid')
                                    if not refs:
                                        raise _ReadFailure('prepared_refs_missing')
                                    if (action_id, item.attempt) in terminal_errors:
                                        raise _ReadFailure(terminal_errors[(action_id, item.attempt)])
                                    terminal = terminals.get((action_id, item.attempt))
                                    terminal_by_id = {ref['record_id']: ref for ref in terminal} if terminal else {}
                                    counts = [0, 0]
                                    with ExitStack() as records:
                                        prepared_records = []
                                        for anchor in sorted(refs, key=lambda ref: ref['record_id']):
                                            budget.records += 1
                                            if budget.records > MAX_RECORDS:
                                                raise _ReadFailure('budget_exceeded')
                                            if anchor['record_id'] not in found:
                                                raise _ReadFailure('fact_missing')
                                            record_fd = records.enter_context(_directory(action_fd, anchor['record_id']))
                                            prepared = _prepared_fact(record_fd, entry, anchor, budget)
                                            registered = _registered_terminal(prepared, terminal_by_id.get(anchor['record_id']))
                                            prepared_records.append((record_fd, prepared, registered))
                                        # The whole original set is now attributable and its required
                                        # fingerprints are known; missing exit files do not erase it.
                                        item.registered_terminal_count = sum(
                                            registered is not None for _, _, registered in prepared_records)
                                        if any(registered is None for _, _, registered in prepared_records):
                                            raise _ReadFailure('terminal_refs_missing')
                                        for record_fd, prepared, registered in prepared_records:
                                            observed = _inspect_record(record_fd, prepared, registered, budget, item)
                                            counts = [total + count for total, count in zip(counts, observed)]
                                    item.direct_exit_count, item.descendant_domain_count = counts
                                    item.inspection_state, item.coverage_complete = 'verified', True
                                except _ReadFailure as exc:
                                    item.reason_codes = [exc.reason]
                                    if exc.reason in {'budget_exceeded', 'scan_truncated'}:
                                        item.registered_terminal_count = None
                    except _ReadFailure as exc:
                        directory_errors[action_id] = exc.reason
    except _ReadFailure as exc:
        reasons.add(exc.reason)
        directory_errors.update({action_id: exc.reason for action_id in grouped})
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        reasons.add('fact_invalid')
        directory_errors.update({action_id: 'fact_invalid' for action_id in grouped})
    for item, row in zip(items, history.items):
        key = (str(item.action_id), item.attempt)
        entry = by_key.get(key)
        if entry is None:
            item.reason_codes = ['attempt_unregistered' if row.attempt is None else 'index_invalid']
        elif item.prepared_record_count is None:
            item.prepared_record_count = len(entry.get('prepared_process_refs', []))
        reason = directory_errors.get(str(item.action_id))
        if reason:
            item.reason_codes = sorted(set(item.reason_codes) | {reason})
            item.coverage_complete = False
            item.registered_terminal_count = item.direct_exit_count = item.descendant_domain_count = None
        if item.reason_codes:
            item.inspection_state = ('invalid' if set(item.reason_codes) & {
                'binding_invalid', 'terminal_refs_conflict', 'fact_invalid', 'directory_extra'} else 'unknown')
        reasons.update(item.reason_codes)
    if history.reason_codes or len(items) != len(entries):
        reasons.add('scan_truncated' if set(history.reason_codes) & {
            'action_scan_truncated', 'history_output_truncated'} else 'binding_invalid')
    complete = bool(items) and all(item.coverage_complete for item in items) and reasons == {
        'non_effect_unanchored', 'investigation_unanchored'}
    public_items = [item.model_dump(mode='json') for item in items]
    fingerprint = hashlib.sha256(_canonical({
        'schema': 'ar-attempt-process-details-v1', 'metadata': history.snapshot_fingerprint,
        'revision': revision, 'registered': [(entry['binding_sha256'],
            [ref['prepared_sha256'] for ref in entry.get('prepared_process_refs', [])]) for entry in entries],
        'observed': budget.observed, 'items': public_items, 'reasons': sorted(reasons),
        'coverage': complete, 'whole_workflow': 'unknown',
    })).hexdigest()
    return ArAttemptProcessDetailsRead(metadata_snapshot_fingerprint=history.snapshot_fingerprint,
        evidence_revision=revision, registered_effect_coverage_complete=complete,
        reason_codes=sorted(reasons), observation_fingerprint=fingerprint, items=items)
