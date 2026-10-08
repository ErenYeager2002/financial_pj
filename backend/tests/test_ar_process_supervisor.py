"""Synthetic subprocesses only; all files live in the canary tmpfs."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from app import ar_process_evidence as evidence
from app import ar_process_inspection as inspection
from app.ar_process_supervisor import validate_receipt

class ProcessSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scripts = self.root/'skill'/'vendor'/'scripts'
        self.scripts.mkdir(parents=True)
        self.script = self.scripts/'synthetic.py'
        self.workflow = SimpleNamespace(id='synthetic-workflow',owner_id='synthetic-owner',
            reconciliation_date='2026-09-01',skill_hash='hash',
            context_json=json.dumps({'plan_fingerprint':'plan','ar_execution':
                {'material_set_id':'synthetic-material','material_version':1}}))
        self.action = SimpleNamespace(id='synthetic-action',workflow_id=self.workflow.id,
            name='ar_write_ledger',attempt_count=1,worker_id='synthetic-worker')
        for module in [evidence,inspection]:
            patcher=patch.object(module,'workflow_root',return_value=self.root)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_script(self, text, **kwargs):
        self.script.write_text(text)
        return evidence.run_recorded_script(self.scripts,self.script.name,[],
            action=self.action,workflow=self.workflow,**kwargs)

    def proof(self):
        return {'action_id':self.action.id,'process_records':self.action._ar_process_records,
                'process_exit_confirmed':self.action._ar_process_exit_confirmed,
                'process_evidence_version':evidence.SCHEMA_VERSION}

    def record(self):
        return self.root/'execution-processes'/self.action.id/self.action._ar_process_records[0]['record_id']

    def test_simple_script_has_bound_descendant_exit_receipt(self):
        self.assertEqual(self.run_script("print('synthetic output')"),'synthetic output\n')
        self.assertTrue(self.action._ar_process_exit_confirmed)
        self.assertTrue(inspection.inspect_process_evidence(self.workflow,self.action,self.proof())['verified'])
        self.assertTrue(inspection.action_process_exit_confirmed(self.workflow,self.action))
        self.assertIn('domain_exit_sha256',self.action._ar_process_records[0])

    def test_parent_exit_does_not_finish_while_detached_child_is_still_writing(self):
        # setsid + closed output: communicate() alone would report parent exit.
        marker=self.root/'detached-finished'
        child="import time; from pathlib import Path; time.sleep(0.35); Path("+repr(str(marker))+").write_text('finished')"
        text="import subprocess,sys; subprocess.Popen([sys.executable,'-c',"+repr(child)+"], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"
        self.run_script(text)
        self.assertEqual(marker.read_text(),'finished')
        fact=json.loads((self.record()/'domain-exited.json').read_text())
        self.assertGreaterEqual(fact['reaped_count'],2)
        self.assertTrue(self.action._ar_process_exit_confirmed)

    def test_double_fork_descendant_is_also_reaped(self):
        marker=self.root/'grandchild-finished'
        child="import os,time; from pathlib import Path; pid=os.fork(); os._exit(0) if pid else None; os.setsid(); time.sleep(0.2); Path("+repr(str(marker))+").write_text('finished')"
        self.run_script("import subprocess,sys; subprocess.Popen([sys.executable,'-c',"+repr(child)+"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)")
        self.assertEqual(marker.read_text(),'finished')
        self.assertGreaterEqual(json.loads((self.record()/'domain-exited.json').read_text())['reaped_count'],2)

    def test_timeout_does_not_claim_descendants_stopped(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_script('import time; time.sleep(30)',timeout=0.15)
        self.assertFalse(self.action._ar_process_exit_confirmed)
        self.assertFalse(inspection.inspect_process_evidence(self.workflow,self.action,self.proof())['verified'])
        self.assertFalse(inspection.action_process_exit_confirmed(self.workflow,self.action))

    def test_started_receipt_failure_cannot_certify_unobserved_launch(self):
        original=evidence._write_fact
        def fail_started(path,fact):
            if path.name == 'started.json':
                raise OSError('synthetic journal failure')
            return original(path,fact)
        with patch.object(evidence,'_write_fact',side_effect=fail_started):
            with self.assertRaisesRegex(OSError,'synthetic journal failure'):
                self.run_script('import time; time.sleep(30)')
        self.assertFalse(self.action._ar_process_exit_confirmed)
        self.assertFalse(inspection.inspect_process_evidence(self.workflow,self.action,self.proof())['verified'])

    def test_timeout_with_detached_child_retains_unknown_until_investigation(self):
        marker=self.root/'detached-timeout-finished'
        child="import time; from pathlib import Path; time.sleep(0.45); Path("+repr(str(marker))+").write_text('finished')"
        text="import subprocess,sys; subprocess.Popen([sys.executable,'-c',"+repr(child)+"],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)"
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                self.run_script(text,timeout=0.2)
            self.assertFalse(self.action._ar_process_exit_confirmed)
            self.assertFalse(inspection.action_process_exit_confirmed(self.workflow,self.action))
            self.assertFalse(inspection.inspect_process_evidence(self.workflow,self.action,self.proof())['verified'])
        finally:
            # The synthetic detached child is finite; let it finish before
            # removing its tmpfs directory. Never signal unrelated processes.
            deadline=time.monotonic()+3
            while not marker.exists() and time.monotonic()<deadline:
                time.sleep(0.02)
        self.assertTrue(marker.exists())

    def test_missing_domain_receipt_cannot_be_replaced_by_direct_exit(self):
        self.run_script("print('done')")
        (self.record()/'domain-exited.json').unlink()
        self.assertFalse(inspection.inspect_process_evidence(self.workflow,self.action,self.proof())['verified'])
        self.assertFalse(inspection.action_process_exit_confirmed(self.workflow,self.action))

    def test_tampered_receipt_is_rejected(self):
        self.run_script("print('done')")
        path=self.record()/'domain-exited.json'
        fact=json.loads(path.read_text())
        fact['token']='0'*32
        raw=json.dumps(fact).encode()
        path.write_bytes(raw)
        self.action._ar_process_records[0]['domain_exit_sha256']=hashlib.sha256(raw).hexdigest()
        self.assertFalse(inspection.inspect_process_evidence(self.workflow,self.action,self.proof())['verified'])
        self.assertFalse(inspection.action_process_exit_confirmed(self.workflow,self.action))

    def test_script_error_preserves_confirmed_exit_without_marking_success(self):
        with self.assertRaises(RuntimeError):
            self.run_script('import sys; sys.exit(7)')
        self.assertTrue(self.action._ar_process_exit_confirmed)
        self.assertTrue(inspection.inspect_process_evidence(self.workflow,self.action,self.proof())['verified'])

    def test_unknown_domain_schema_is_rejected(self):
        self.run_script("print('done')")
        for name in ['prepared','started','exited']:
            path=self.record()/(name+'.json')
            fact=json.loads(path.read_text())
            fact['execution_domain_schema']='future-unknown'
            raw=json.dumps(fact).encode()
            path.write_bytes(raw)
            key={'prepared':'prepared_sha256','started':'started_sha256','exited':'exit_sha256'}[name]
            self.action._ar_process_records[0][key]=hashlib.sha256(raw).hexdigest()
        self.assertFalse(inspection.inspect_process_evidence(self.workflow,self.action,self.proof())['verified'])
        self.assertFalse(inspection.action_process_exit_confirmed(self.workflow,self.action))

class ExpiredWriterOccupancyTests(unittest.TestCase):
    def test_expired_parent_with_live_detached_writer_cannot_admit_second_write(self):
        from concurrent.futures import ThreadPoolExecutor
        from datetime import UTC, datetime, timedelta
        from app.ar_execution_safety import register_effect_intent, assert_operation_allowed, MaterialOccupancyConflict
        from app.models import WorkflowAction
        from test_ar_claim_material_policy import ClaimMaterialPolicyTests
        fixture=ClaimMaterialPolicyTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        db,flow=fixture.db,fixture.blocker
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            scripts=root/'skill'/'vendor'/'scripts'
            scripts.mkdir(parents=True)
            started,release,finished=[root/name for name in ['child-started','release-child','child-finished']]
            child="import time; from pathlib import Path; Path("+repr(str(started))+").write_text('started'); deadline=time.monotonic()+5\nwhile not Path("+repr(str(release))+").exists() and time.monotonic()<deadline: time.sleep(0.01)\nPath("+repr(str(finished))+").write_text('finished')"
            (scripts/'synthetic.py').write_text("import subprocess,sys; subprocess.Popen([sys.executable,'-c',"+repr(child)+"],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)")
            action=WorkflowAction(id='original-writer',workflow=flow,name='ar_write_ledger',
                state='running',attempt_count=1,worker_id='synthetic-worker',
                lease_expires_at=datetime.now(UTC)+timedelta(minutes=1))
            db.add(action)
            db.flush()
            flow.state='running'
            context={'workspace':str(root),'plan_fingerprint':'synthetic-plan',
                'ar_execution':{'material_set_id':'published','material_version':2,
                    'publication':'not_published','completed':[]}}
            register_effect_intent(context,flow,action,'write_ledger')
            flow.context_json=json.dumps(context)
            db.commit()
            second=fixture.action(fixture.candidate('second-writer'))
            with patch.object(evidence,'workflow_root',return_value=root), ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(evidence.run_recorded_script,scripts,'synthetic.py',[],action=action,workflow=flow,timeout=8)
                try:
                    deadline=time.monotonic()+3
                    while not started.exists() and time.monotonic()<deadline:
                        time.sleep(0.01)
                    self.assertTrue(started.exists())
                    self.assertFalse(future.done())
                    action.lease_expires_at=datetime.now(UTC)-timedelta(seconds=1)
                    action.state='failed'
                    flow.state='failed'
                    db.commit()
                    for operation in ['create_run','replace_materials','continue_batch']:
                        with self.assertRaises(MaterialOccupancyConflict):
                            assert_operation_allowed(db,flow.owner_id,flow.department_id,flow.skill_id,operation=operation)
                        db.rollback()
                    self.assertIsNone(fixture.claim())
                    self.assertEqual(second.state,'queued')
                    self.assertEqual(second.attempt_count,0)
                    self.assertFalse(finished.exists())
                finally:
                    release.write_text('release synthetic child')
                    future.result(timeout=5)
                self.assertTrue(finished.exists())
                # Even complete process exit does not prove workbook correctness.
                with self.assertRaises(MaterialOccupancyConflict):
                    assert_operation_allowed(db,flow.owner_id,flow.department_id,flow.skill_id,operation='create_run')
                db.rollback()


if __name__ == '__main__':
    unittest.main()
