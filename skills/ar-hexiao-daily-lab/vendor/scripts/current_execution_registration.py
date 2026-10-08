"""Standalone completion evidence, isolated from historical audit journals."""
import copy
import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path

import batch_ledger
import common
import fallback_allocation_ledger as F


def allocation_facts(value):
    result = copy.deepcopy(value)
    for entry in result.get('parents', {}).values():
        entry.pop('applied_at', None)
        entry.pop('last_verified_at', None)
    return result


def record(workspace, plan, written):
    workspace = Path(workspace)
    if (plan.get('business_rules') or {}).get('reconciliation_policy') != 'current-workbook-v1':
        raise ValueError('Current execution registration requires current-workbook-v1')
    day = common.norm_date(plan.get('hexiao_date'))
    if day is None:
        raise ValueError('Current execution registration requires a date')
    encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    fingerprint = hashlib.sha256(encoded).hexdigest()
    historical = {}
    for name in (F.LEDGER_NAME, batch_ledger.LEDGER_NAME):
        path = workspace / '03_台账' / name
        if path.is_file():
            raw = path.read_bytes()
            historical[name] = {'sha256': hashlib.sha256(raw).hexdigest(),
                                'base64': base64.b64encode(raw).decode('ascii')}
    output = workspace / '04_产出'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.current-registration-', dir=output) as tmp:
        proof = Path(tmp)
        allocation, added = F.commit(proof, plan)
        batch_ledger.record(proof, day, 'applied', written=written)
        payload = {'schema_version': 'ar-standalone-completion-v1',
                   'reconciliation_policy': 'current-workbook-v1',
                   'hexiao_date': day.isoformat(), 'checked_sha256': fingerprint,
                   'written': written,
                   'json_ledgers': {F.LEDGER_NAME: json.loads(allocation.read_text()),
                       batch_ledger.LEDGER_NAME: json.loads((proof / '03_台账' / batch_ledger.LEDGER_NAME).read_text())},
                   'historical_audit_files': historical}
        # A fresh proof directory means previous executions can never supply allocations.
        identity = hashlib.sha256(encoded + json.dumps(written, sort_keys=True).encode()).hexdigest()
        target = output / ('本次执行登记_' + day.isoformat() + '_' + identity[:16] + '.json')
        if target.exists():
            existing = json.loads(target.read_text(encoding='utf-8'))
            if (existing.get('checked_sha256') != fingerprint or existing.get('written') != written
                    or allocation_facts(existing.get('json_ledgers', {}).get(F.LEDGER_NAME, {})) != allocation_facts(payload['json_ledgers'][F.LEDGER_NAME])):
                raise ValueError('Existing completion receipt differs from current evidence')
            for audit in existing.get('historical_audit_files', {}).values():
                if hashlib.sha256(base64.b64decode(audit['base64'])).hexdigest() != audit['sha256']:
                    raise ValueError('Archived audit checksum differs')
            return target, added
        candidate = proof / 'receipt.json'
        candidate.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        if json.loads(candidate.read_text(encoding='utf-8')) != payload:
            raise ValueError('Standalone completion readback differs')
        os.replace(candidate, target)
    return target, added
