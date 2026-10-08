"""Exercise actual snapshot copying across a simulated lab publication."""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from app import workflow_service as service, ar_execution_runner as runner
from app.ar_snapshot_contract import snapshot_reconciliation_policy, validate_snapshot
from app.ar_execution_contract import CONTRACT_VERSION


def tree(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


class FixedSnapshotIsolation(unittest.TestCase):
    def test_publication_keeps_old_batch_and_new_task_separate(self):
        live=Path('/app/skills/ar-hexiao-daily-lab')
        self.assertEqual(snapshot_reconciliation_policy(live),'current-workbook-v1')
        live_before=tree(live)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); published=root/'published'
            shutil.copytree(live,published)
            marker=published/'config/execution-pipeline.json'
            original=marker.read_bytes();payload=json.loads(original)
            payload.pop('reconciliation_policy',None)
            marker.write_text(json.dumps(payload))
            self.assertEqual(validate_snapshot(published),CONTRACT_VERSION)
            folder=lambda owner,ident:root/'tasks'/owner/ident
            fields=dict(owner_id='owner',department_id='dept',skill_id='ar-hexiao-daily-lab',
                        skill_hash='old-pinned-hash',execution_mode='workflow',context_json='{}')
            first=NS(id='first',batch_id='batch',batch_sequence=1,**fields)
            later=NS(id='later',batch_id='batch',batch_sequence=2,**fields)
            batch=NS(workflows=[first,later]);first.batch=later.batch=batch
            class DB:
                def get(self,model,key):
                    if key!='batch':raise AssertionError('unexpected database lookup')
                    return batch
            with patch.object(service,'workflow_root',folder),patch.object(runner,'workflow_root',folder):
                old=service._snapshot_skill(NS(directory=published),'owner','first')
                old_before=tree(old)
                marker.write_bytes(original)  # Simulate a new publication at the live source.
                new=service._snapshot_skill(NS(directory=published),'owner','new')
                self.assertEqual(snapshot_reconciliation_policy(new),'current-workbook-v1')
                self.assertFalse((folder('owner','later')/'skill').exists())
                self.assertEqual(runner.execution_version(later),CONTRACT_VERSION)
                child=service._ensure_workflow_skill_snapshot(DB(),later)
                self.assertEqual(snapshot_reconciliation_policy(child),'legacy')
                self.assertEqual(tree(child),old_before)
                self.assertEqual(tree(old),old_before)
                # Checkpoint disagreement must fail, never change the old snapshot.
                later.context_json=json.dumps({'ar_execution':{'reconciliation_policy':'current-workbook-v1'}})
                with self.assertRaisesRegex(ValueError,'策略'):
                    runner.execution_version(later)
                later.context_json='{}'
                # A mismatched child policy is rejected instead of silently refreshed.
                child_marker=child/'config/execution-pipeline.json'
                child_marker.write_bytes(original)
                with self.assertRaisesRegex(ValueError,'策略'):
                    runner.execution_version(later)
                self.assertEqual(tree(old),old_before)
        self.assertEqual(tree(live),live_before)

if __name__=='__main__':unittest.main()
