"""Current-plan preflight never reads prior audit, but validates new evidence."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import fallback_allocation_ledger as F
from test_allocation_contract import audit,plan

class CurrentPreflight(unittest.TestCase):
    def current(self):
        value=plan(audit());value['business_rules']={'reconciliation_policy':'current-workbook-v1'}
        return value

    def test_current_plan_ignores_old_audit_without_modifying_it(self):
        for old in ('broken old json',json.dumps({'version':999,'parents':{}}),None):
            with self.subTest(old=old),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);path=root/'03_台账'/F.LEDGER_NAME
                if old is not None:path.parent.mkdir();path.write_text(old)
                files={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
                with patch.object(F,'load',side_effect=AssertionError('old audit read')):
                    F.preflight(root,self.current())
                self.assertEqual(files,{str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_current_plan_keeps_duplicate_identity_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            value=self.current();a=value['parent_fallback_allocations']['AR_TEST']
            a['allocations'].append(copy.deepcopy(a['allocations'][0]))
            with self.assertRaises(ValueError):F.preflight(Path(tmp),value)

    def test_legacy_and_unknown_policy_still_read_old_audit(self):
        for policy in (None,'unknown'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);F.ledger_path(root).write_text('broken old json')
                value=plan(audit())
                if policy:value['business_rules']={'reconciliation_policy':policy}
                with self.assertRaisesRegex(ValueError,'台账无法读取'):F.preflight(root,value)
