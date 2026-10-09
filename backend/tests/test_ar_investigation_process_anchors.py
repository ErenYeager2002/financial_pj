"""Read-only investigation original refs through actual public execution and PG."""
import hashlib,json,os,unittest
from datetime import UTC,datetime,timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from sqlalchemy import func,select
from sqlalchemy.orm import Session
from app import ar_process_evidence as evidence,workflow_service as service
from app.ar_execution_contract import INVESTIGATION_ACTION,PHASES
from app.ar_business_investigation import investigation_status
from app.ar_execution_safety import register_effect_intent
from app.ar_execution_service import read_execution
from app.ar_process_supervisor import validate_receipt
from app.models import AuditEvent,WorkflowAction,WorkflowSession
from app.registry import hash_skill_directory

class InvestigationProcessAnchorsPostgresTests(unittest.TestCase):
 def setUp(self):
  from test_ar_rescan_process_anchors import RescanProcessAnchorsPostgresTests
  self.base=RescanProcessAnchorsPostgresTests('test_rescan_original_refs_are_visible_before_spawn_and_business_transition')
  self.addCleanup(self.base.doCleanups);self.base.setUp();f=self.base.fixture;self.f=f
  b=self.base;c=json.loads(f.workflow.context_json)
  script=f.root/'skill/vendor/scripts/investigate_failed_write.py'
  script.write_text("import argparse,hashlib,json\nfrom pathlib import Path\n"
   "p=argparse.ArgumentParser()\n"
   "for name in ('baseline','workspace','checked','flow-file','manifest-sha256','workflow-id','phase','attempt'):p.add_argument('--'+name,required=True)\n"
   "p.add_argument('--ledger-year',action='append');a=p.parse_args()\nw=Path(a.workspace);baseline=Path(a.baseline)\n"
   "assert w!=baseline and Path(a.checked).parent==w/'04_产出'\n"
   "m=json.loads((w/'execution-manifest.json').read_text());assert hashlib.sha256((w/'execution-manifest.json').read_bytes()).hexdigest()==a.manifest_sha256\n"
   "assert a.ledger_year and Path(a.ledger_year[0].split('=',1)[1]).is_relative_to(baseline)\n"
   "assert Path(a.flow_file).parent==w/'02_我的表副本'\n"
   "result={'schema_version':'ar-write-investigation-v1','workflow_id':a.workflow_id,'attempt':a.attempt,'manifest_sha256':a.manifest_sha256,'plan_sha256':m['staged_plan_fingerprint'],'material_set_id':m['material_set_id'],'reconciliation_date':'2026-09-01','failed_phase':a.phase,'authorizes_resume':False,'publication_verified':False,'inputs_unchanged':True,'business_files_match_expected':False,'ledger_results':{'2026':{'state':'unconfirmed'}},'flow_result':{'state':'unconfirmed'}}\n"
   "report=w/'execution-investigations'/a.attempt/'result.json';report.parent.mkdir(parents=True);report.write_text(json.dumps(result))\n"
   "print(json.dumps({'schema_version':'ar-write-investigation-v1','report_sha256':hashlib.sha256(report.read_bytes()).hexdigest()}))\n",encoding='utf-8')
  digest=hash_skill_directory(f.root/'skill');f.workflow.skill_hash=digest;c['ar_execution']['skill_hash']=digest
  index=next(i for i,p in enumerate(PHASES) if p.name=='write_ledger')
  c['ar_execution']['completed']=[p.name for p in PHASES[:index]]
  c['ar_execution']['steps']={'stage_reconciliation':c['ar_execution']['steps']['stage_reconciliation']}
  f.action.name='ar_write_ledger'
  register_effect_intent(c,f.workflow,f.action,'write_ledger')
  f.action.state='failed';f.action.finished_at=datetime.now(UTC);f.workflow.state='failed'
  c['ar_failure']={'action_id':f.action_id,'phase':'write_ledger','process_exit_confirmed':False}
  f.workflow.context_json=json.dumps(c);f.db.commit();f.db.refresh(f.action);f.db.expire(f.workflow,['actions'])
  # Investigation must accept actual partial staged bytes, not baseline equality.
  self.partial=next(iter(b.stage_materials));self.partial.write_bytes(b'synthetic partial original write; no financial workbook')
  status=investigation_status(f.workflow);self.assertTrue(status['allowed'],status)
  now=datetime.now(UTC)
  self.action=WorkflowAction(id=str(uuid4()),workflow_id=f.workflow_id,name=INVESTIGATION_ACTION,
   state='running',attempt_count=1,worker_id='synthetic-investigator',queued_at=now,started_at=now,
   heartbeat_at=now,lease_expires_at=now+timedelta(minutes=5),input_json=json.dumps({
    'failed_action_id':status['failed_action_id'],'checkpoint_fingerprint':status['checkpoint_fingerprint'],
    'requested_by':f.owner_id}))
  f.db.add(self.action);f.db.commit();f.db.expire(f.workflow,['actions'])
  self.original=json.loads(f.workflow.context_json)
  self.files={p:p.read_bytes() for p in (*b.input_bytes,*f.material_bytes,*b.stage_materials)}

 def run_original(self,*,after_child=None):
  f=self.f;launches=[];finished=[];native=evidence.subprocess.Popen;producer=evidence.run_recorded_script
  def spawn(*args,**kwargs):
   with Session(f.engine) as db:
    c=json.loads(db.get(WorkflowSession,f.workflow_id).context_json)
    audits=[json.loads(a.details_json) for a in db.scalars(select(AuditEvent).where(AuditEvent.action=='ar_process_prepared_registered'))]
    launches.append((c,audits))
   return native(*args,**kwargs)
  def complete(*args,**kwargs):
   stdout=producer(*args,**kwargs)
   with Session(f.engine) as db:
    c=json.loads(db.get(WorkflowSession,f.workflow_id).context_json)
    current=db.get(WorkflowAction,self.action.id)
    finished.append((c,current.state,current.result_json))
   if after_child:after_child()
   return stdout
  with patch.object(evidence.subprocess,'Popen',side_effect=spawn),patch.object(evidence,'run_recorded_script',side_effect=complete):
   service.execute_workflow_action(f.db,self.action)
  return launches,finished

 def test_original_investigation_refs_are_durable_before_business_result(self):
  f=self.f;launches,finished=self.run_original()
  self.assertEqual(len(launches),1);self.assertEqual(len(finished),1)
  with Session(f.engine) as db:
   current=db.get(WorkflowAction,self.action.id);self.assertEqual(current.state,'succeeded',current.error_message)
   produced=json.loads(current.result_json)['process_records'];self.assertEqual(len(produced),1)
   ref=produced[0];self.assertEqual(ref['state'],'exited');self.assertEqual(ref['script'],'investigate_failed_write.py')
   record=f.root/'execution-processes'/self.action.id/ref['record_id']
   prepared=json.loads((record/'prepared.json').read_text());started=json.loads((record/'started.json').read_text())
   receipt=json.loads((record/'domain-exited.json').read_text())
   validate_receipt(receipt,token=prepared['domain_token'],supervisor_pid=started['pid'])
   self.assertGreaterEqual(receipt['reaped_count'],1);self.assertTrue(self.action._ar_process_exit_confirmed)
   self.assertFalse(hasattr(self.action,'_ar_terminate_process'))
   wf=db.get(WorkflowSession,f.workflow_id);c=json.loads(wf.context_json)
   self.assertEqual(wf.state,'failed');self.assertEqual(db.get(WorkflowAction,f.action_id).state,'failed')
   self.assertEqual(c['ar_execution'],self.original['ar_execution']);self.assertEqual(c['ar_failure'],self.original['ar_failure'])
   self.assertEqual(c['execution_safety_v1']['attempts'],self.original['execution_safety_v1']['attempts'])
   self.assertEqual(c['execution_safety_v1']['revision'],1)
   obs=c['execution_safety_v1'].get('process_observations')
   print(json.dumps({'event':'codex_f4e3_actual_investigation_before_ref_assertion','actual_children':1,
    'linux_receipts':1,'cleanup_complete':True,'public_handler_succeeded':True,'workflow_and_writer_failed':True,
    'financial_script':False,'observation_present':obs is not None},sort_keys=True))
   self.assertIsInstance(obs,dict,'actual investigation must preserve original durable observations')
   self.assertEqual(obs['schema_version'],'ar-process-observations-v3');self.assertEqual(obs['revision'],3)
   self.assertEqual(len(obs['attempts']),1);entry=obs['attempts'][0]
   self.assertEqual(entry['phase'],INVESTIGATION_ACTION);self.assertEqual(entry['attempt'],1)
   self.assertEqual(entry['worker_id'],'synthetic-investigator');self.assertEqual(len(entry['input_binding']),7)
   self.assertEqual(len(entry['prepared_process_refs']),1);self.assertEqual(len(entry['terminal_process_refs']),1)
   for key in ('record_id','prepared_sha256','script','started_sha256','exit_sha256','domain_exit_sha256'):
    self.assertEqual(entry['terminal_process_refs'][0][key],ref[key])
   self.assertEqual(launches[0][0]['execution_safety_v1']['process_observations']['revision'],2)
   self.assertEqual(len(launches[0][1]),1)
   self.assertEqual(finished[0][0]['execution_safety_v1']['process_observations'],obs)
   self.assertEqual(finished[0][1],'running');self.assertEqual(json.loads(finished[0][2] or '{}'),{})
   audits=[json.loads(a.details_json) for a in db.scalars(select(AuditEvent).where(AuditEvent.action=='ar_process_terminal_registered'))]
   self.assertEqual(len(audits),1);self.assertIs(audits[0]['late_observation'],False)
   self.assertIs(read_execution(wf).process_details,None)
   self.assertFalse(read_execution(wf).attempt_history.authorizes_resume)
   self.assertEqual(read_execution(wf,include_process_details=True).process_details.whole_workflow_coverage,'unknown')
  self.assertEqual({p:p.read_bytes() for p in self.files},self.files)

 def test_same_worker_new_attempt_fences_original_result_registration(self):
  f=self.f;marker={'synthetic_second_attempt':'must remain running'}
  def reclaim_after_child():
   with Session(f.engine) as db:
    current=db.get(WorkflowAction,self.action.id)
    current.attempt_count=2;current.result_json=json.dumps(marker);db.commit()
  launches,finished=self.run_original(after_child=reclaim_after_child)
  self.assertEqual(len(launches),1);self.assertEqual(len(finished),1)
  self.assertTrue(self.action._ar_process_exit_confirmed)
  print(json.dumps({'event':'codex_f4e3_actual_same_worker_attempt_fence','actual_children':1,
   'original_cleanup_complete':True,'same_worker_claim_now':2},sort_keys=True))
  with Session(f.engine) as db:
   current=db.get(WorkflowAction,self.action.id)
   self.assertEqual(current.attempt_count,2)
   self.assertEqual(current.state,'running','same worker new attempt must fence original result registration')
   self.assertEqual(json.loads(current.result_json),marker)
   c=json.loads(db.get(WorkflowSession,f.workflow_id).context_json)
   obs=c['execution_safety_v1']['process_observations']
   self.assertEqual(obs['revision'],3);self.assertEqual(obs['attempts'][0]['attempt'],1)
   self.assertEqual(len(obs['attempts'][0]['terminal_process_refs']),1)
   self.assertEqual(c['ar_execution'],self.original['ar_execution'])
   self.assertEqual(c['ar_failure'],self.original['ar_failure'])
  self.assertTrue(f.db.info.get('ar_execution_lease_lost'))
  self.assertEqual({p:p.read_bytes() for p in self.files},self.files)
