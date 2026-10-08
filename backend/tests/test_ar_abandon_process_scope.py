"""Actual process receipts and SQLite disposition; synthetic tmpfs only."""
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
import psutil
from fastapi import HTTPException
from app import ar_abandon as subject
from app import ar_process_evidence as evidence
from app import ar_process_inspection as inspection
from app.ar_process_identity import capture_identity
from app.ar_execution_safety import current_material_blocker
import test_ar_abandon as fixtures

REAL_INSPECT=inspection.inspect_process_evidence

class AbandonProcessScopeTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.AbandonTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.stack.enter_context(patch.object(inspection,'inspect_process_evidence',REAL_INSPECT))
        for module in (evidence,inspection):
            self.f.stack.enter_context(patch.object(module,'workflow_root',return_value=self.f.root))
        self.scripts=self.f.root/'skill'/'vendor'/'scripts'
        self.scripts.mkdir(parents=True)
        self.f.context['plan_fingerprint']='p'*64
        self.f.save()
        self.f.action.worker_id=self.f.failed.worker_id='codex-test-worker'

    def save_proof(self,action,records):
        proof={'action_id':action.id,'process_records':records,
               'process_exit_confirmed':True,'process_evidence_version':evidence.SCHEMA_VERSION}
        if action.state=='succeeded':
            action.result_json=json.dumps(proof)
        else:
            self.f.context['ar_failure']=proof
        self.f.save()
        return proof

    def full_proof(self,action):
        (self.scripts/'synthetic.py').write_text("print('codex synthetic')",encoding='utf-8')
        evidence.run_recorded_script(self.scripts,'synthetic.py',[],action=action,workflow=self.f.workflow,timeout=5)
        return self.save_proof(action,action._ar_process_records)

    def wait_file(self,path):
        deadline=time.monotonic()+4
        while not path.exists() and time.monotonic()<deadline:time.sleep(.01)
        self.assertTrue(path.exists(),path.name)

    def legacy_writer(self):
        action=self.f.action
        release=self.f.root/'child-release';done=self.f.root/'child-done'
        started=self.f.root/'child-started';heartbeat=self.f.root/'heartbeat'
        parent_release=self.f.root/'parent-release'
        child="import os,json,time;from pathlib import Path;Path("+repr(str(started))+").write_text(json.dumps({'pid':os.getpid(),'sid':os.getsid(0)}));deadline=time.monotonic()+8; n=0\nwhile not Path("+repr(str(release))+").exists() and time.monotonic()<deadline:\n n+=1;Path("+repr(str(heartbeat))+").write_text(str(n));time.sleep(.01)\nPath("+repr(str(done))+").write_text('done')"
        parent="import subprocess,sys,time;from pathlib import Path;subprocess.Popen([sys.executable,'-c',"+repr(child)+"],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);deadline=time.monotonic()+8\nwhile not Path("+repr(str(parent_release))+").exists() and time.monotonic()<deadline:time.sleep(.01)"
        script=self.scripts/'synthetic.py';script.write_text(parent,encoding='utf-8')
        record_id=uuid.uuid4().hex
        directory=self.f.root/'execution-processes'/action.id/record_id;directory.mkdir(parents=True)
        binding={'schema_version':evidence.SCHEMA_VERSION,'record_id':record_id,
                 'workflow_id':self.f.workflow.id,'action_id':action.id,'action_name':action.name,
                 'attempt':action.attempt_count,'worker_id':action.worker_id,
                 'reconciliation_date':self.f.workflow.reconciliation_date,'skill_hash':self.f.workflow.skill_hash,
                 'material_set_id':'material','material_version':344,'plan_fingerprint':'p'*64,
                 'host':socket.gethostname(),'worker_pid':os.getpid(),'script':'synthetic.py',
                 'script_sha256':hashlib.sha256(script.read_bytes()).hexdigest(),
                 'arguments_sha256':hashlib.sha256(b'[]').hexdigest()}
        ref={'record_id':record_id,'script':'synthetic.py'}
        ref['prepared_sha256']=evidence._write_fact(directory/'prepared.json',binding)
        process=subprocess.Popen([sys.executable,str(script)],cwd=self.scripts,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.addCleanup(lambda:release.touch())
        def finish_owned():
            release.touch();parent_release.touch()
            process.communicate(timeout=4)
            deadline=time.monotonic()+4
            while started.exists() and not done.exists() and time.monotonic()<deadline:time.sleep(.01)
        self.addCleanup(finish_owned)
        self.wait_file(started)
        ref['started_sha256']=evidence._write_fact(directory/'started.json',{**binding,'pid':process.pid,'identity':capture_identity(process.pid)})
        parent_release.touch()
        stdout,stderr=process.communicate(timeout=4)
        self.assertEqual(process.returncode,0,stderr)
        ref['exit_sha256']=evidence._write_fact(directory/'exited.json',{**binding,'pid':process.pid,'returncode':0,
               'communication_completed':True,'direct_process_exit_confirmed':True})
        info=json.loads(started.read_text())
        self.assertEqual(info['pid'],info['sid'])
        self.assertEqual(os.getsid(info['pid']),info['pid'])
        self.assertTrue(psutil.Process(info['pid']).is_running())
        self.wait_file(heartbeat)
        before=heartbeat.read_text();time.sleep(.05)
        self.assertNotEqual(before,heartbeat.read_text())
        return self.save_proof(action,[ref]),release,done

    def test_legacy_parent_exit_with_live_detached_child_never_unlocks(self):
        writer,release,done=self.legacy_writer()
        self.full_proof(self.f.failed)
        observed=REAL_INSPECT(self.f.workflow,self.f.action,writer)
        self.assertTrue(observed['verified'],observed)
        self.assertEqual(observed['process_evidence_scope'],'direct_children_only')
        self.assertFalse(self.f.status()['allowed'])
        with self.assertRaises(HTTPException) as rejected:
            subject.abandon(self.f.db,self.f.workflow,subject.AbandonRequest(checkpoint_fingerprint='0'*64),self.f.actor)
        self.assertEqual(rejected.exception.status_code,409)
        self.assertFalse(subject.is_abandoned(self.f.workflow))
        self.assertEqual(current_material_blocker(self.f.db,'owner','finance','ar-hexiao-daily-lab')['reason'],'unresolved_write')
        release.touch();self.wait_file(done)
        self.assertFalse(self.f.status()['allowed'])


    def full_pair(self):
        return {action.id:self.full_proof(action) for action in (self.f.action,self.f.failed)}

    def test_complete_real_descendant_receipts_allow_safe_disposition(self):
        proofs=self.full_pair()
        for action in (self.f.action,self.f.failed):
            actual=REAL_INSPECT(self.f.workflow,action,proofs[action.id])
            self.assertTrue(actual['verified'],actual)
            self.assertEqual(actual['process_evidence_scope'],'linux_descendant_tree')
            self.assertEqual(actual['descendant_domains_verified'],actual['total'])
        before={str(p):p.read_bytes() for p in self.f.root.rglob('*') if p.is_file()}
        state=self.f.status();self.assertTrue(state['allowed'],state)
        subject.abandon(self.f.db,self.f.workflow,subject.AbandonRequest(checkpoint_fingerprint=state['checkpoint_fingerprint']),self.f.actor)
        self.assertTrue(subject.is_abandoned(self.f.workflow))
        self.assertTrue(subject.has_verified_abandonment_stop(self.f.workflow))
        self.assertIsNone(current_material_blocker(self.f.db,'owner','finance','ar-hexiao-daily-lab'))
        self.assertEqual(self.f.material.version,344)
        self.assertEqual(self.f.previous.state,'succeeded')
        self.assertEqual(self.f.next.state,'cancelled')
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.f.root.rglob('*') if p.is_file()})
        self.assertFalse(self.f.status()['needs_investigation'])
        with self.assertRaises(ValueError):subject.require_not_abandoned(self.f.workflow)

    def test_real_receipt_changed_after_check_cannot_unlock(self):
        proofs=self.full_pair()
        state=self.f.status();self.assertTrue(state['allowed'],state)
        record=self.f.root/'execution-processes'/self.f.action.id/proofs[self.f.action.id]['process_records'][0]['record_id']
        (record/'domain-exited.json').unlink()
        with self.assertRaises(HTTPException) as rejected:
            subject.abandon(self.f.db,self.f.workflow,subject.AbandonRequest(checkpoint_fingerprint=state['checkpoint_fingerprint']),self.f.actor)
        self.assertEqual(rejected.exception.status_code,409)
        self.assertFalse(subject.is_abandoned(self.f.workflow))
        self.assertEqual(current_material_blocker(self.f.db,'owner','finance','ar-hexiao-daily-lab')['reason'],'unresolved_write')

    def test_incomplete_or_unknown_scope_never_authorizes_disposition(self):
        complete={'verified':True,'total':2,'exited':2,'unconfirmed':0,'descendant_domains_verified':2,
                  'process_evidence_scope':'linux_descendant_tree','fingerprint':'f'*64}
        cases=[{k:v for k,v in complete.items() if k!='process_evidence_scope'},
               {k:v for k,v in complete.items() if k!='descendant_domains_verified'},
               {**complete,'process_evidence_scope':'direct_children_only'},
               {**complete,'process_evidence_scope':'partial_descendant_tree'},
               {**complete,'process_evidence_scope':'unknown'},
               {**complete,'descendant_domains_verified':1},
               {**complete,'unconfirmed':1},{**complete,'exited':1},
               {**complete,'total':True}]
        for observed in cases:
            with self.subTest(observed=observed),patch.object(inspection,'inspect_process_evidence',return_value=observed):
                self.assertFalse(self.f.status()['allowed'])
                with self.assertRaises(HTTPException) as rejected:
                    subject.abandon(self.f.db,self.f.workflow,subject.AbandonRequest(checkpoint_fingerprint='0'*64),self.f.actor)
                self.assertEqual(rejected.exception.status_code,409)
                self.assertFalse(subject.is_abandoned(self.f.workflow))

    def historical_marker(self,proofs):
        context=self.f.context
        bound=subject.binding(self.f.workflow,context)
        snapshots=[[a.id,a.state,a.attempt_count,a.finished_at.isoformat()] for a in (self.f.action,self.f.failed)]
        proof={'binding':bound,'material_version':344,'actions':sorted(snapshots),
               'process_hashes':{a.id:REAL_INSPECT(self.f.workflow,a,proofs[a.id])['fingerprint'] for a in (self.f.action,self.f.failed)}}
        context[subject.KEY]={'schema_version':'ar-abandonment-v1','state':'abandoned','binding':bound,'proof':proof}
        self.f.save()

    def test_legacy_direct_marker_remains_visible_but_keeps_occupancy(self):
        writer,release,done=self.legacy_writer()
        proofs={self.f.action.id:writer,self.f.failed.id:self.full_proof(self.f.failed)}
        self.historical_marker(proofs)
        self.assertTrue(subject.is_abandoned(self.f.workflow))
        self.assertFalse(subject.has_verified_abandonment_stop(self.f.workflow))
        self.assertTrue(self.f.status()['needs_investigation'])
        self.assertEqual(current_material_blocker(self.f.db,'owner','finance','ar-hexiao-daily-lab')['reason'],'unresolved_write')
        from app.ar_material_lifecycle import visible_material_set
        self.assertEqual(visible_material_set(self.f.db,'owner','finance','ar-hexiao-daily-lab').id,'material')
        release.touch();self.wait_file(done)
        self.assertFalse(subject.has_verified_abandonment_stop(self.f.workflow))

    def test_legacy_complete_marker_rechecks_without_rewriting_history(self):
        self.historical_marker(self.full_pair())
        before=self.f.workflow.context_json
        self.assertTrue(subject.has_verified_abandonment_stop(self.f.workflow))
        self.assertIsNone(current_material_blocker(self.f.db,'owner','finance','ar-hexiao-daily-lab'))
        self.assertEqual(self.f.workflow.context_json,before)
        self.assertNotIn('process_stop_evidence_v2',json.loads(before)[subject.KEY]['proof'])


    def test_saved_stop_summary_missing_writer_keeps_material_occupied(self):
        self.full_pair()
        state=self.f.status()
        subject.abandon(self.f.db,self.f.workflow,subject.AbandonRequest(checkpoint_fingerprint=state['checkpoint_fingerprint']),self.f.actor)
        self.f.context=json.loads(self.f.workflow.context_json)
        proof=self.f.context[subject.KEY]['proof']
        proof['process_hashes'].pop(self.f.action.id)
        proof['process_stop_evidence_v2'].pop(self.f.action.id)
        self.f.save()
        self.assertTrue(subject.is_abandoned(self.f.workflow))
        self.assertFalse(subject.has_verified_abandonment_stop(self.f.workflow))
        self.assertEqual(current_material_blocker(self.f.db,'owner','finance','ar-hexiao-daily-lab')['reason'],'unresolved_write')


    def test_saved_stop_summary_binds_worker_and_original_process_references(self):
        self.full_pair()
        state=self.f.status()
        subject.abandon(self.f.db,self.f.workflow,subject.AbandonRequest(checkpoint_fingerprint=state['checkpoint_fingerprint']),self.f.actor)
        original_worker=self.f.action.worker_id
        self.f.action.worker_id='different-worker'
        self.f.db.commit()
        self.assertFalse(subject.has_verified_abandonment_stop(self.f.workflow))
        self.f.action.worker_id=original_worker
        self.f.action.result_json=json.dumps({'process_evidence_version':evidence.SCHEMA_VERSION,'process_records':[]})
        self.f.db.commit()
        self.assertFalse(subject.has_verified_abandonment_stop(self.f.workflow))
        self.assertEqual(current_material_blocker(self.f.db,'owner','finance','ar-hexiao-daily-lab')['reason'],'unresolved_write')
