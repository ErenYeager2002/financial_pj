"""Original rescan observations; real isolated PG/native synthetic scripts only."""
import hashlib
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import ar_process_evidence as evidence
from app import workflow_service as service
from app.ar_execution_contract import CONTRACT_VERSION, PHASES
from app.ar_execution_runner import execute_phase, transition_phase
from app.ar_execution_service import read_execution
from app.ar_process_supervisor import validate_receipt
from app.models import AuditEvent, WorkflowAction, WorkflowSession
from app.registry import hash_skill_directory

URL = 'postgresql+psycopg://synthetic:synthetic-only@127.0.0.1:5432/material_policy_test'


class RescanProcessAnchorsPostgresTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.environ.get('AR_POLICY_SYNTHETIC_DB_URL'), URL)
        from test_ar_process_anchor_postgres import ArProcessAnchorPostgresTests
        self.fixture = ArProcessAnchorPostgresTests('test_prepared_reference_and_audit_are_visible_before_popen')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        f = self.fixture
        self.assertFalse((f.root / 'execution-processes').exists())
        context = json.loads(f.workflow.context_json)
        self.workspace = Path(context['workspace'])
        self.tag = f.workflow.reconciliation_date.replace('-', '')
        output = self.workspace / '04_产出'
        output.mkdir()
        self.original_checked = output / ('写入计划_校验后_' + self.tag + '.json')
        self.original_checked.write_bytes(b'{"synthetic_original_plan":true}')
        context['checked_plan'] = str(self.original_checked)
        context['plan_fingerprint'] = hashlib.sha256(self.original_checked.read_bytes()).hexdigest()
        self.stage = self.workspace / service.WRITE_STAGING_DIR / 'synthetic-rescan'
        (self.stage / '04_产出').mkdir(parents=True)
        (self.stage / '02_我的表副本').mkdir()
        self.stage_materials = {}
        for path, raw in f.material_bytes.items():
            target = self.stage / path.relative_to(self.workspace)
            shutil.copy2(path, target)
            self.stage_materials[target] = raw
        self.checked = self.stage / '04_产出' / self.original_checked.name
        self.checked.write_bytes(b'{"synthetic_staged_plan":true}')
        self.result = self.stage / '04_产出' / ('判定结果_' + self.tag + '.json')
        self.result.write_bytes(b'{"synthetic_initial_result":true}')
        report = self.stage / '04_产出' / ('首次核销日清_' + self.tag + '.xlsx')
        report.write_bytes(b'synthetic report placeholder; no financial workbook')
        flow_plan = self.stage / '04_产出' / '流转写入计划_校验后.json'
        flow_plan.write_bytes(b'{"synthetic_flow_plan":true}')
        self.review = self.stage / 'execution-review'
        (self.review / '04_产出').mkdir(parents=True)
        self.review_result = self.review / '04_产出' / self.result.name
        self.review_result.write_bytes(b'{"synthetic_reviewed_result":true}')
        review_checked = self.review / '04_产出' / self.original_checked.name
        review_checked.write_bytes(b'{"write":[],"synthetic_review":true}')
        fingerprints = {p.relative_to(self.stage).as_posix(): hashlib.sha256(raw).hexdigest()
                        for p, raw in self.stage_materials.items()}
        manifest = {
            'schema_version': CONTRACT_VERSION, 'workflow_id': f.workflow_id,
            'material_set_id': f.workflow.material_set_id,
            'initial_plan_fingerprint': context['plan_fingerprint'],
            'checked_plan': str(self.checked),
            'staged_plan_fingerprint': hashlib.sha256(self.checked.read_bytes()).hexdigest(),
            'files': fingerprints,
            'protected_inputs': {p.relative_to(self.stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (self.checked, report, self.result, flow_plan)},
        }
        self.manifest = self.stage / 'execution-manifest.json'
        self.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        script = f.root / 'skill' / 'vendor' / 'scripts' / 'rescan_execution_holds.py'
        script.write_text("import argparse,json\nfrom pathlib import Path\n"
            "p=argparse.ArgumentParser()\np.add_argument('--workspace',required=True)\n"
            "p.add_argument('--result',required=True)\np.add_argument('--ledger-year',action='append')\n"
            "a=p.parse_args()\nw=Path(a.workspace)\nr=Path(a.result)\n"
            "assert r.parent==w/'04_产出'\n"
            "assert r.read_bytes()==b'{\"synthetic_initial_result\":true}'\n"
            "assert (w/'execution-review'/'04_产出'/r.name).read_bytes()==b'{\"synthetic_reviewed_result\":true}'\n"
            "m=json.loads((w/'execution-manifest.json').read_text(encoding='utf-8'))\n"
            "assert Path(m['checked_plan']).read_bytes()==b'{\"synthetic_staged_plan\":true}'\n"
            "assert a.ledger_year and a.ledger_year[0].startswith('2026=')\n"
            "(w/'04_产出'/'synthetic-rescan-observed.txt').write_bytes(b'synthetic native child completed; no financial write')\n"
            "print(json.dumps({'rescanned':True,'count':0}))\n", encoding='utf-8')
        digest = hash_skill_directory(f.root / 'skill')
        f.workflow.skill_hash = digest
        context['ar_execution']['skill_hash'] = digest
        index = next(i for i, phase in enumerate(PHASES) if phase.name == 'rescan_holds')
        # These preconditions are synthetic metadata, never claims that writers ran.
        context['ar_execution']['completed'] = [p.name for p in PHASES[:index]]
        context['ar_execution']['steps'] = {
            'stage_reconciliation': {'staging_workspace': str(self.stage), 'manifest': manifest},
            'verify_reconciliation': {'files': fingerprints, 'review_workspace': str(self.review),
                                      'checked_fingerprint': hashlib.sha256(review_checked.read_bytes()).hexdigest()},
        }
        # Base fixture has no real produced refs/child; no historical fact is deleted.
        context['execution_safety_v1'] = {'schema_version': 'ar-execution-safety-v1', 'revision': 0, 'attempts': []}
        f.action.name = 'ar_rescan_holds'
        f.workflow.context_json = json.dumps(context)
        f.db.commit()
        self.initial_context = json.loads(f.workflow.context_json)
        self.input_bytes = {p: p.read_bytes() for p in (self.original_checked, self.manifest, self.checked,
                                                       self.result, self.review_result)}
        self.expected_arguments = ['--workspace', str(self.stage), '--result', str(self.result), '--ledger-year',
            '2026=' + str(self.stage / next(iter(f.material_bytes)).relative_to(self.workspace))]

    def test_rescan_original_refs_are_visible_before_spawn_and_business_transition(self):
        f = self.fixture
        launches = []
        native = evidence.subprocess.Popen

        def observe_original_launch(*args, **kwargs):
            with Session(f.engine) as observer:
                context = json.loads(observer.get(WorkflowSession, f.workflow_id).context_json)
                audits = [json.loads(r.details_json) for r in observer.scalars(select(AuditEvent).where(
                    AuditEvent.action == 'ar_process_prepared_registered'))]
                launches.append((context, audits))
            return native(*args, **kwargs)

        with patch.object(evidence.subprocess, 'Popen', side_effect=observe_original_launch):
            result = execute_phase(f.db, f.action, f.workflow)
        # Required new index assertions occur only after actual native child cleanup.
        self.assertEqual(len(launches), 1)
        self.assertIs(result['holds_rescanned'], True)
        self.assertEqual(len(result['process_records']), 1)
        produced = result['process_records'][0]
        self.assertEqual(produced['script'], 'rescan_execution_holds.py')
        self.assertEqual(produced['state'], 'exited')
        self.assertTrue(f.action._ar_process_exit_confirmed)
        self.assertFalse(hasattr(f.action, '_ar_terminate_process'))
        self.assertEqual((self.stage / '04_产出' / 'synthetic-rescan-observed.txt').read_bytes(),
                         b'synthetic native child completed; no financial write')
        record = f.root / 'execution-processes' / f.action_id / produced['record_id']
        prepared = json.loads((record / 'prepared.json').read_text())
        started = json.loads((record / 'started.json').read_text())
        receipt = json.loads((record / 'domain-exited.json').read_text())
        validate_receipt(receipt, token=prepared['domain_token'], supervisor_pid=started['pid'])
        self.assertGreaterEqual(receipt['reaped_count'], 1)
        with Session(f.engine) as observer:
            workflow = observer.get(WorkflowSession, f.workflow_id)
            context = json.loads(workflow.context_json)
            original = observer.get(WorkflowAction, f.action_id)
            self.assertEqual(original.state, 'running')
            self.assertEqual(json.loads(original.result_json), {})
            self.assertEqual(context['ar_execution'], self.initial_context['ar_execution'])
            self.assertEqual(context['execution_safety_v1']['revision'], 0)
            self.assertEqual(context['execution_safety_v1']['attempts'], [])
            observed = context['execution_safety_v1'].get('process_observations')
            print(json.dumps({'event': 'codex_f4e2_actual_rescan_before_ref_assertion', 'actual_native_children': 1,
                'actual_linux_receipts': 1, 'cleanup_complete': True, 'phase_handler_unmocked': True,
                'financial_script_invoked': False, 'effect_revision': 0, 'effect_attempts': 0,
                'observation_partition_present': observed is not None}, sort_keys=True))
            self.assertIsInstance(observed, dict, 'actual rescan must preserve original durable observations')
            self.assertEqual(observed['schema_version'], 'ar-process-observations-v2')
            self.assertEqual(observed['revision'], 3)
            self.assertEqual(len(observed['attempts']), 1)
            entry = observed['attempts'][0]
            self.assertEqual(entry['phase'], 'rescan_holds')
            self.assertEqual(entry['attempt'], 1)
            self.assertEqual(entry['worker_id'], 'synthetic-worker')
            self.assertFalse({'status', 'completed_at', 'result_sha256', 'effect_disposition'} & set(entry))
            self.assertEqual(entry['input_binding'], {
                'staging_workspace_sha256': hashlib.sha256(str(self.stage).encode('utf-8')).hexdigest(),
                'manifest_sha256': hashlib.sha256(self.input_bytes[self.manifest]).hexdigest(),
                'staged_plan_sha256': hashlib.sha256(self.input_bytes[self.checked]).hexdigest(),
                'initial_result_sha256': hashlib.sha256(self.input_bytes[self.result]).hexdigest(),
                'reviewed_result_sha256': hashlib.sha256(self.input_bytes[self.review_result]).hexdigest(),
                'arguments_sha256': hashlib.sha256(json.dumps(self.expected_arguments, ensure_ascii=False).encode('utf-8')).hexdigest(),
            })
            self.assertEqual(len(entry['prepared_process_refs']), 1)
            self.assertEqual(len(entry['terminal_process_refs']), 1)
            anchor, terminal = entry['prepared_process_refs'][0], entry['terminal_process_refs'][0]
            self.assertEqual(anchor['arguments_sha256'], entry['input_binding']['arguments_sha256'])
            for key in ('record_id', 'prepared_sha256', 'script', 'started_sha256', 'exit_sha256', 'domain_exit_sha256'):
                self.assertEqual(terminal[key], produced[key])
            self.assertEqual(terminal['binding_sha256'], entry['binding_sha256'])
            self.assertEqual(terminal['terminal_state'], 'exited')
            at_spawn, audits = launches[0]
            self.assertEqual(at_spawn['execution_safety_v1']['process_observations']['revision'], 2)
            self.assertEqual(at_spawn['execution_safety_v1']['process_observations']['attempts'][0]['prepared_process_refs'], [anchor])
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0]['evidence_namespace'], 'process_observations')
            terminals = [json.loads(r.details_json) for r in observer.scalars(select(AuditEvent).where(
                AuditEvent.action == 'ar_process_terminal_registered'))]
            self.assertEqual(len(terminals), 1)
            self.assertEqual(terminals[0]['evidence_namespace'], 'process_observations')
            self.assertIs(terminals[0]['late_observation'], False)
        self.assertEqual({p: p.read_bytes() for p in self.input_bytes}, self.input_bytes)
        self.assertEqual({p: p.read_bytes() for p in f.material_bytes}, f.material_bytes)
        self.assertEqual({p: p.read_bytes() for p in self.stage_materials}, self.stage_materials)
        transition_phase(f.db, f.action, f.workflow, result)
        f.db.commit()
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            after = json.loads(workflow.context_json)
            self.assertEqual(after['execution_safety_v1']['process_observations'], observed)
            self.assertEqual(after['execution_safety_v1']['revision'], 0)
            self.assertEqual(after['execution_safety_v1']['attempts'], [])
            self.assertEqual(reader.get(WorkflowAction, f.action_id).state, 'succeeded')
            self.assertIn('rescan_holds', after['ar_execution']['completed'])
            view = read_execution(workflow)
            self.assertIsNone(view.process_details)
            self.assertEqual(view.attempt_history.registered_attempt_count, 0)
            self.assertIs(view.attempt_history.authorizes_resume, False)
            detailed = read_execution(workflow, include_process_details=True)
            self.assertEqual(detailed.process_details.whole_workflow_coverage, 'unknown')
        self.assertEqual({p: p.read_bytes() for p in f.material_bytes}, f.material_bytes)
        self.assertEqual({p: p.read_bytes() for p in self.stage_materials}, self.stage_materials)


    def test_original_review_result_change_after_real_prepared_ack_denies_native_launch(self):
        from sqlalchemy import event
        f = self.fixture
        prepared_connections, changed = set(), []
        native_commit = f.engine.dialect.do_commit

        def mark(connection, cursor, statement, parameters, execution_context, executemany):
            values = parameters.values() if isinstance(parameters, dict) else parameters
            if statement.startswith('INSERT INTO audit_events') and 'ar_process_prepared_registered' in values:
                prepared_connections.add(id(connection.connection.dbapi_connection))

        def committed_then_change_review(connection):
            physical = getattr(connection, 'dbapi_connection', connection)
            native_commit(connection)
            if id(physical) in prepared_connections and not changed:
                self.review_result.write_bytes(b'{"synthetic_reviewed_result":"changed after actual ACK"}')
                changed.append(True)

        event.listen(f.engine, 'before_cursor_execute', mark)
        try:
            with patch.object(f.engine.dialect, 'do_commit', side_effect=committed_then_change_review), \
                    patch.object(evidence.subprocess, 'Popen', wraps=evidence.subprocess.Popen) as popen:
                with self.assertRaises(ValueError):
                    execute_phase(f.db, f.action, f.workflow)
                actual_children = popen.call_count
        finally:
            event.remove(f.engine, 'before_cursor_execute', mark)
        self.assertEqual(changed, [True])
        self.assertEqual(actual_children, 0)
        self.assertFalse(hasattr(f.action, '_ar_terminate_process'))
        with Session(f.engine) as reader:
            context = json.loads(reader.get(WorkflowSession, f.workflow_id).context_json)
            outer = context['execution_safety_v1']
            state = outer['process_observations']
            self.assertEqual(state['schema_version'], 'ar-process-observations-v2')
            self.assertEqual(state['revision'], 3)
            self.assertEqual(len(state['attempts']), 1)
            entry = state['attempts'][0]
            self.assertEqual(entry['input_binding']['reviewed_result_sha256'],
                             hashlib.sha256(self.input_bytes[self.review_result]).hexdigest())
            self.assertEqual(len(entry['prepared_process_refs']), 1)
            self.assertEqual(len(entry['terminal_process_refs']), 1)
            terminal = entry['terminal_process_refs'][0]
            self.assertEqual(terminal['terminal_state'], 'launch_unconfirmed')
            self.assertTrue(all(terminal[k] is None for k in ('started_sha256', 'exit_sha256', 'domain_exit_sha256')))
            self.assertEqual(context['ar_execution'], self.initial_context['ar_execution'])
            self.assertEqual(outer['revision'], 0)
            self.assertEqual(outer['attempts'], [])
            self.assertEqual(reader.get(WorkflowAction, f.action_id).state, 'running')
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action.in_(['ar_process_prepared_registered', 'ar_process_terminal_registered']))), 2)
        record = f.root / 'execution-processes' / f.action_id / f.action._ar_process_records[-1]['record_id']
        self.assertTrue((record / 'prepared.json').is_file())
        self.assertFalse((record / 'started.json').exists())
        self.assertEqual({p: p.read_bytes() for p in f.material_bytes}, f.material_bytes)
        self.assertEqual({p: p.read_bytes() for p in self.stage_materials}, self.stage_materials)
        print(json.dumps({'event': 'codex_f4e2_actual_review_input_fence', 'actual_children': 0,
            'real_prepared_commit': True, 'second_fresh_gate_rejected_change': True,
            'original_review_sha_retained': True, 'nullable_terminal_preserved': True,
            'business_completion_and_financial_writes': 0}, sort_keys=True))


    def test_late_rescan_observation_preserves_real_second_attempt_and_changed_input(self):
        from app.ar_execution_runner import ArExecution
        from app import workflow_service as service
        from app.ar_execution_contract import CONTRACT_VERSION,ExecutionLeaseLost
        from app.models import WorkflowMaterialSet
        from app.workflow_action_state import isolated_action_state
        f=self.fixture
        snapshots=[]
        native_record=ArExecution.record_terminal
        def projection(db):
            workflow=db.get(WorkflowSession,f.workflow_id,populate_existing=True)
            context=json.loads(workflow.context_json)
            business=tuple(getattr(workflow,key) for key in ('state','stage','progress','progress_message',
                                                            'artifacts_json','updated_at','material_set_id'))
            actions=list(db.execute(select(WorkflowAction.id,WorkflowAction.name,WorkflowAction.state,
                WorkflowAction.attempt_count,WorkflowAction.worker_id,WorkflowAction.result_json,
                WorkflowAction.finished_at,WorkflowAction.heartbeat_at,WorkflowAction.lease_expires_at)
                .order_by(WorkflowAction.id)).all())
            material=db.get(WorkflowMaterialSet,workflow.material_set_id)
            return context,business,actions,(material.id,material.version,material.state)
        def capture_after_second_actual_attempt(execution,anchor,observation):
            if dict(anchor.prepared_identity)['attempt'] != 1:
                return native_record(execution,anchor,observation)
            self.assertFalse(hasattr(execution.action,'_ar_terminate_process'))
            self.assertTrue(execution.action._ar_process_exit_confirmed)
            with Session(f.engine) as migration:
                action=migration.get(WorkflowAction,f.action_id)
                action.state=isolated_action_state('queued')
                action.worker_id,action.lease_expires_at='',None
                migration.commit()  # Owned synthetic contention, no financial retry.
            with Session(f.engine,expire_on_commit=False) as second_db:
                claimed=service.claim_next_workflow_action(second_db,('workflow',),'synthetic-worker-two',
                                                           execution_contracts=(CONTRACT_VERSION,))
                self.assertEqual(claimed.id,f.action_id)
                self.assertEqual(claimed.attempt_count,2)
                workflow=second_db.get(WorkflowSession,f.workflow_id)
                result=execute_phase(second_db,claimed,workflow)
                transition_phase(second_db,claimed,workflow,result)
                second_db.commit()
                context=json.loads(workflow.context_json)
                context['synthetic_new_attempt_marker']='must survive original callback'
                context['plan_fingerprint']='b'*64
                workflow.context_json=json.dumps(context)
                second_db.commit()
            with Session(f.engine) as reader:
                snapshots.append(projection(reader))
            self.review_result.write_bytes(b'synthetic newer input after both real native children')
            return native_record(execution,anchor,observation)
        with patch.object(ArExecution,'record_terminal',capture_after_second_actual_attempt):
            old_result=execute_phase(f.db,f.action,f.workflow)
        self.assertEqual(len(snapshots),1)
        before_context,business,actions,material=snapshots[0]
        with Session(f.engine) as reader:
            after,after_business,after_actions,after_material=projection(reader)
            self.assertEqual(after_business,business)
            self.assertEqual(after_actions,actions)
            self.assertEqual(after_material,material)
            state=after['execution_safety_v1']['process_observations']
            original,new=state['attempts']
            self.assertEqual([original['attempt'],new['attempt']],[1,2])
            self.assertEqual(original['worker_id'],'synthetic-worker')
            self.assertEqual(original['input_binding']['reviewed_result_sha256'],
                             hashlib.sha256(self.input_bytes[self.review_result]).hexdigest())
            self.assertEqual(new,before_context['execution_safety_v1']['process_observations']['attempts'][1])
            self.assertEqual(len(original['terminal_process_refs']),1)
            self.assertEqual(len(new['terminal_process_refs']),1)
            self.assertEqual(state['revision'],6)
            self.assertEqual(original['terminal_process_refs'][0]['record_id'],old_result['process_records'][0]['record_id'])
            restored=json.loads(json.dumps(after))
            restored['execution_safety_v1']['process_observations']['attempts'][0]['terminal_process_refs']=[]
            restored['execution_safety_v1']['process_observations']['revision']-=1
            self.assertEqual(restored,before_context)
            audits=[json.loads(a.details_json) for a in reader.scalars(select(AuditEvent).where(
                AuditEvent.action=='ar_process_terminal_registered'))]
            self.assertEqual(len(audits),2)
            self.assertIs(next(a for a in audits if a['attempt']==1)['late_observation'],True)
            self.assertIs(next(a for a in audits if a['attempt']==2)['late_observation'],False)
            self.assertEqual(after['execution_safety_v1']['revision'],0)
            self.assertEqual(after['execution_safety_v1']['attempts'],[])
        with self.assertRaises(ExecutionLeaseLost):
            transition_phase(f.db,f.action,f.workflow,old_result)
        f.db.rollback()
        self.assertEqual(len(list((f.root/'execution-processes'/f.action_id).glob('*/domain-exited.json'))),2)
        self.assertEqual({p:p.read_bytes() for p in f.material_bytes},f.material_bytes)
        print(json.dumps({'event':'codex_f4e2_late_actual_second_attempt','actual_children_exited':2,
            'second_claim_actual':True,'second_business_transition_actual':True,'old_terminal_late':True,
            'new_context_business_actions_material_unchanged_by_callback':True,
            'old_business_transition_fenced':True},sort_keys=True))



    def test_fresh_same_content_stage_cannot_redirect_original_prepared_invocation(self):
        from sqlalchemy import event
        f = self.fixture
        replacement = self.stage.with_name('synthetic-replacement-stage')
        shutil.copytree(self.stage, replacement)
        replacement_manifest = json.loads(self.manifest.read_text(encoding='utf-8'))
        replacement_manifest['checked_plan'] = str(replacement / self.checked.relative_to(self.stage))
        (replacement / 'execution-manifest.json').write_text(
            json.dumps(replacement_manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        self.assertEqual((replacement / self.result.relative_to(self.stage)).read_bytes(), self.input_bytes[self.result])
        self.assertEqual((replacement / self.review_result.relative_to(self.stage)).read_bytes(), self.input_bytes[self.review_result])
        prepared_connections, redirected = set(), []
        native_commit = f.engine.dialect.do_commit

        def mark(connection, cursor, statement, parameters, execution_context, executemany):
            values = parameters.values() if isinstance(parameters, dict) else parameters
            if statement.startswith('INSERT INTO audit_events') and 'ar_process_prepared_registered' in values:
                prepared_connections.add(id(connection.connection.dbapi_connection))

        def commit_then_redirect(connection):
            physical = getattr(connection, 'dbapi_connection', connection)
            native_commit(connection)
            if id(physical) in prepared_connections and not redirected:
                redirected.append(True)
                with Session(f.engine) as change:
                    workflow = change.get(WorkflowSession, f.workflow_id)
                    context = json.loads(workflow.context_json)
                    context['ar_execution']['steps']['stage_reconciliation'] = {
                        'staging_workspace': str(replacement), 'manifest': replacement_manifest}
                    context['ar_execution']['steps']['verify_reconciliation']['review_workspace'] = str(replacement / 'execution-review')
                    workflow.context_json = json.dumps(context)
                    change.commit()

        event.listen(f.engine, 'before_cursor_execute', mark)
        try:
            with patch.object(f.engine.dialect, 'do_commit', side_effect=commit_then_redirect), \
                    patch.object(evidence.subprocess, 'Popen', wraps=evidence.subprocess.Popen) as popen:
                with self.assertRaises(ValueError):
                    execute_phase(f.db, f.action, f.workflow)
                actual_children = popen.call_count
        finally:
            event.remove(f.engine, 'before_cursor_execute', mark)
        self.assertEqual(redirected, [True])
        self.assertEqual(actual_children, 0)
        self.assertFalse(hasattr(f.action, '_ar_terminate_process'))
        with Session(f.engine) as reader:
            context = json.loads(reader.get(WorkflowSession, f.workflow_id).context_json)
            state = context['execution_safety_v1']['process_observations']
            entry = state['attempts'][0]
            self.assertEqual(entry['input_binding']['staging_workspace_sha256'],
                             hashlib.sha256(str(self.stage).encode('utf-8')).hexdigest())
            self.assertEqual(context['ar_execution']['steps']['stage_reconciliation'],
                             {'staging_workspace': str(replacement), 'manifest': replacement_manifest})
            self.assertEqual(context['ar_execution']['steps']['verify_reconciliation']['review_workspace'],
                             str(replacement / 'execution-review'))
            self.assertEqual(entry['terminal_process_refs'][0]['terminal_state'], 'launch_unconfirmed')
            self.assertTrue(all(entry['terminal_process_refs'][0][k] is None
                                for k in ('started_sha256', 'exit_sha256', 'domain_exit_sha256')))
            self.assertEqual(state['revision'], 3)
            self.assertEqual(context['execution_safety_v1']['revision'], 0)
            self.assertEqual(context['execution_safety_v1']['attempts'], [])
            self.assertEqual(reader.get(WorkflowAction, f.action_id).state, 'running')
        self.assertEqual({p: p.read_bytes() for p in self.input_bytes}, self.input_bytes)
        self.assertEqual({p: p.read_bytes() for p in f.material_bytes}, f.material_bytes)
        self.assertEqual({p: p.read_bytes() for p in self.stage_materials}, self.stage_materials)
        print(json.dumps({'event': 'codex_f4e2_actual_stage_redirect_fence', 'actual_children': 0,
            'prepared_ack_real': True, 'fresh_replacement_same_input_content': True,
            'original_stage_not_silently_rebound': True, 'new_checkpoint_preserved': True,
            'nullable_original_terminal_preserved': True, 'financial_writes': 0}, sort_keys=True))


    def test_actual_v1_report_records_survive_v2_rescan_without_backfill_or_rewrite(self):
        from datetime import UTC, datetime, timedelta
        from uuid import uuid4
        from app.workflow_action_state import isolated_action_state
        f = self.fixture
        script = f.root / 'skill' / 'vendor' / 'scripts' / 'build_worklist.py'
        script.write_text("import argparse\nfrom pathlib import Path\n"
            "p=argparse.ArgumentParser()\np.add_argument('--workspace')\np.add_argument('--hexiao-date')\n"
            "p.add_argument('--checked')\np.add_argument('--out')\na=p.parse_args()\n"
            "assert Path(a.checked).read_bytes()==b'{\"synthetic_original_plan\":true}'\n"
            "Path(a.out).write_bytes(b'synthetic report only; no financial workbook')\n"
            "print('synthetic original report completed')\n", encoding='utf-8')
        digest = hash_skill_directory(f.root / 'skill')
        context = json.loads(f.workflow.context_json)
        context['ar_execution']['skill_hash'] = digest
        index = next(i for i, phase in enumerate(PHASES) if phase.name == 'build_initial_report')
        context['ar_execution']['completed'] = [phase.name for phase in PHASES[:index]]
        context['ar_execution']['steps'] = {}
        f.workflow.skill_hash = digest
        f.action.name = 'ar_build_initial_report'
        f.workflow.context_json = json.dumps(context)
        f.db.commit()
        old_result = execute_phase(f.db, f.action, f.workflow)
        transition_phase(f.db, f.action, f.workflow, old_result)
        f.db.commit()
        old_action_id = f.action.id
        old_record = f.root / 'execution-processes' / old_action_id / old_result['process_records'][0]['record_id']
        old_facts = {p.name: p.read_bytes() for p in old_record.iterdir()}
        with Session(f.engine) as reader:
            old_context = json.loads(reader.get(WorkflowSession, f.workflow_id).context_json)
        old_state = old_context['execution_safety_v1']['process_observations']
        self.assertEqual(old_state['schema_version'], 'ar-process-observations-v1')
        self.assertEqual(old_state['revision'], 3)
        old_entry = old_state['attempts'][0]
        self.assertEqual(len(old_entry), 18)
        self.assertNotIn('input_binding', old_entry)

        # Construct only synthetic staged preconditions; no financial writer ran.
        staged_report = self.stage / '04_产出' / ('首次核销日清_' + self.tag + '.xlsx')
        shutil.copy2(Path(old_result['initial_report']['path']), staged_report)
        manifest = json.loads(self.manifest.read_text(encoding='utf-8'))
        manifest['protected_inputs'][staged_report.relative_to(self.stage).as_posix()] = hashlib.sha256(staged_report.read_bytes()).hexdigest()
        self.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        f.db.refresh(f.workflow)
        context = json.loads(f.workflow.context_json)
        index = next(i for i, phase in enumerate(PHASES) if phase.name == 'rescan_holds')
        context['ar_execution']['completed'] = [phase.name for phase in PHASES[:index]]
        context['ar_execution']['steps'] = json.loads(json.dumps(self.initial_context['ar_execution']['steps']))
        context['ar_execution']['steps']['stage_reconciliation']['manifest'] = manifest
        f.workflow.context_json = json.dumps(context)
        for queued in f.db.scalars(select(WorkflowAction).where(WorkflowAction.state == 'queued')):
            queued.state = isolated_action_state('cancelled')
        now = datetime.now(UTC)
        new_action = WorkflowAction(id=str(uuid4()), workflow_id=f.workflow_id, name='ar_rescan_holds',
            state='running', attempt_count=1, worker_id='synthetic-rescan-worker', queued_at=now,
            started_at=now, heartbeat_at=now, lease_expires_at=now + timedelta(minutes=5))
        f.db.add(new_action)
        f.db.commit()
        before_json = f.workflow.context_json
        before = read_execution(f.workflow, include_process_details=True)
        self.assertEqual(f.workflow.context_json, before_json)
        result = execute_phase(f.db, new_action, f.workflow)
        self.assertEqual(result['process_records'][0]['state'], 'exited')
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession, f.workflow_id)
            context = json.loads(workflow.context_json)
            state = context['execution_safety_v1']['process_observations']
            self.assertEqual(state['schema_version'], 'ar-process-observations-v2')
            self.assertEqual(state['revision'], 6)
            self.assertEqual(len(state['attempts']), 2)
            self.assertEqual(state['attempts'][0], old_entry)
            self.assertEqual(len(state['attempts'][0]), 18)
            current = state['attempts'][1]
            self.assertEqual(len(current), 19)
            self.assertEqual(current['phase'], 'rescan_holds')
            self.assertEqual(current['action_id'], new_action.id)
            self.assertEqual(current['prepared_process_refs'][0]['script'], 'rescan_execution_holds.py')
            self.assertEqual(len(current['terminal_process_refs']), 1)
            self.assertEqual(current['input_binding']['manifest_sha256'], hashlib.sha256(self.manifest.read_bytes()).hexdigest())
            self.assertEqual(context['execution_safety_v1']['revision'], 0)
            self.assertEqual(context['execution_safety_v1']['attempts'], [])
            raw = workflow.context_json
            plain = read_execution(workflow)
            detailed = read_execution(workflow, include_process_details=True)
            self.assertIsNone(plain.process_details)
            self.assertEqual(detailed.attempt_history.registered_attempt_count, 0)
            self.assertIs(detailed.attempt_history.authorizes_resume, False)
            self.assertEqual(detailed.process_details.whole_workflow_coverage, 'unknown')
            self.assertNotEqual(detailed.process_details.metadata_snapshot_fingerprint,
                                before.process_details.metadata_snapshot_fingerprint)
            self.assertEqual(workflow.context_json, raw)
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action.in_(['ar_process_prepared_registered', 'ar_process_terminal_registered']))), 4)
        self.assertEqual({p.name: p.read_bytes() for p in old_record.iterdir()}, old_facts)
        self.assertEqual({p: p.read_bytes() for p in f.material_bytes}, f.material_bytes)
        self.assertEqual({p: p.read_bytes() for p in self.stage_materials}, self.stage_materials)
        print(json.dumps({'event': 'codex_f4e2_actual_v1_v2_preservation', 'actual_native_children': 2,
            'original_report_entry_and_facts_unchanged': True, 'v2_rescan_added_only': True,
            'effect_revision_and_registered_history': 0, 'public_whole_coverage': 'unknown',
            'read_did_not_backfill': True, 'financial_writers_run': 0}, sort_keys=True))


    def test_v2_invalid_input_bridge_and_capacity_do_not_rewrite_original_evidence(self):
        from copy import deepcopy
        from app.ar_execution_runner import ArExecution
        from app.ar_execution_safety import BINDING_FIELDS
        from app.ar_process_evidence import TerminalProcessRegistrationError
        f = self.fixture
        captured = []
        native_record = ArExecution.record_terminal

        def capture(execution, anchor, observation):
            captured.append((execution, anchor, observation))
            return native_record(execution, anchor, observation)

        with patch.object(ArExecution, 'record_terminal', capture):
            result = execute_phase(f.db, f.action, f.workflow)
        self.assertEqual(result['process_records'][0]['state'], 'exited')
        self.assertEqual(len(captured), 1)
        execution, anchor, observation = captured[0]
        record = f.root / 'execution-processes' / f.action_id / anchor.record_id
        original_facts = {p.name: p.read_bytes() for p in record.iterdir()}
        with Session(f.engine) as reader:
            baseline = json.loads(reader.get(WorkflowSession, f.workflow_id).context_json)
            audit_count = reader.scalar(select(func.count()).select_from(AuditEvent))
        original = baseline['execution_safety_v1']['process_observations']['attempts'][0]

        def bind(entry):
            fields = (*BINDING_FIELDS, 'input_binding') if entry['phase'] == 'rescan_holds' else BINDING_FIELDS
            entry['binding_sha256'] = hashlib.sha256(json.dumps(
                {k: entry[k] for k in fields}, ensure_ascii=False,
                sort_keys=True, separators=(',', ':')).encode()).hexdigest()

        def persist(context):
            raw = json.dumps(context)
            with Session(f.engine) as change:
                workflow = change.get(WorkflowSession, f.workflow_id)
                workflow.context_json = raw
                change.commit()
            return raw

        def unchanged(raw):
            with Session(f.engine) as reader:
                workflow = reader.get(WorkflowSession, f.workflow_id)
                self.assertEqual(workflow.context_json, raw)
                self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), audit_count)
                self.assertEqual(reader.get(WorkflowAction, f.action_id).state, 'running')
                plain = read_execution(workflow)
                self.assertIsNone(plain.process_details)
                self.assertIs(plain.attempt_history.authorizes_resume, False)
            self.assertEqual({p.name: p.read_bytes() for p in record.iterdir()}, original_facts)
            self.assertEqual({p: p.read_bytes() for p in f.material_bytes}, f.material_bytes)
            self.assertEqual({p: p.read_bytes() for p in self.stage_materials}, self.stage_materials)

        cases = []
        for key in original['input_binding']:
            context = deepcopy(baseline)
            entry = context['execution_safety_v1']['process_observations']['attempts'][0]
            entry['input_binding'][key] = 'G' * 64
            bind(entry)
            cases.append(('bad_hex:' + key, context))
        for value in (None, [], True):
            context = deepcopy(baseline)
            entry = context['execution_safety_v1']['process_observations']['attempts'][0]
            entry['input_binding'] = value
            bind(entry)
            cases.append(('input_type:' + repr(value), context))
        for label in ('missing_input_field', 'extra_input_field', 'v1_rescan', 'unsupported_schema',
                      'unknown_phase', 'extra_completion', 'bool_revision', 'duplicate_attempt', 'wrong_phase_script'):
            context = deepcopy(baseline)
            state = context['execution_safety_v1']['process_observations']
            entry = state['attempts'][0]
            if label == 'missing_input_field':
                del entry['input_binding']['arguments_sha256']
                bind(entry)
            elif label == 'extra_input_field':
                entry['input_binding']['extra'] = 'a' * 64
                bind(entry)
            elif label == 'v1_rescan':
                state['schema_version'] = 'ar-process-observations-v1'
            elif label == 'unsupported_schema':
                state['schema_version'] = 'ar-process-observations-v3'
            elif label == 'unknown_phase':
                entry['phase'] = 'inspect_materials'
                bind(entry)
            elif label == 'extra_completion':
                entry['status'] = 'phase_completed'
            elif label == 'bool_revision':
                state['revision'] = True
            elif label == 'duplicate_attempt':
                state['attempts'].append(deepcopy(entry))
            elif label == 'wrong_phase_script':
                entry['prepared_process_refs'][0]['script'] = 'build_worklist.py'
                entry['terminal_process_refs'][0]['script'] = 'build_worklist.py'
            cases.append((label, context))
        for key in original['input_binding']:
            context = deepcopy(baseline)
            entry = context['execution_safety_v1']['process_observations']['attempts'][0]
            entry['input_binding'][key] = '0' * 64
            bind(entry)
            for ref in entry['prepared_process_refs'] + entry['terminal_process_refs']:
                ref['binding_sha256'] = entry['binding_sha256']
            cases.append(('changed_original_bridge:' + key, context))
        for label, context in cases:
            with self.subTest(invalid=label):
                raw = persist(context)
                with self.assertRaises(TerminalProcessRegistrationError):
                    execution.record_terminal(anchor, observation)
                unchanged(raw)
        boundary = deepcopy(baseline)
        state = boundary['execution_safety_v1']['process_observations']
        for number in range(1, 128):
            entry = deepcopy(original)
            entry.update(action_id='synthetic-cap-' + str(number), prepared_process_refs=[], terminal_process_refs=[])
            bind(entry)
            state['attempts'].append(entry)
        raw = persist(boundary)
        self.assertEqual(len(state['attempts']), 128)
        self.assertEqual(execution.record_terminal(anchor, observation)['record_id'], anchor.record_id)
        unchanged(raw)
        rejected = deepcopy(boundary)
        extra = deepcopy(rejected['execution_safety_v1']['process_observations']['attempts'][-1])
        extra['action_id'] = 'synthetic-cap-129'
        bind(extra)
        rejected['execution_safety_v1']['process_observations']['attempts'].append(extra)
        raw = persist(rejected)
        with self.assertRaises(TerminalProcessRegistrationError):
            execution.record_terminal(anchor, observation)
        unchanged(raw)
        print(json.dumps({'event': 'codex_f4e2_v2_storage_and_bridge_validation', 'actual_native_children': 1,
            'invalid_fixture_cases_rejected': len(cases), 'boundary_128_duplicate_allowed': True,
            'boundary_129_rejected': True, 'original_facts_context_audit_material_unchanged': True,
            'no_mutable_history_backfill_or_business_authority': True}, sort_keys=True))
