"""Original first-report process observations; isolated PG/native synthetic only."""
import hashlib
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app import ar_process_evidence as evidence
from app.ar_execution_contract import PHASES
from app.ar_execution_runner import ArExecution, execute_phase, transition_phase
from app.ar_execution_service import read_execution
from app.ar_process_supervisor import validate_receipt
from app.models import AuditEvent, WorkflowAction, WorkflowSession
from app.registry import hash_skill_directory

URL = 'postgresql+psycopg://synthetic:synthetic-only@127.0.0.1:5432/material_policy_test'


class NonEffectProcessAnchorsPostgresTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.environ.get('AR_POLICY_SYNTHETIC_DB_URL'), URL)
        from test_ar_process_anchor_postgres import ArProcessAnchorPostgresTests
        self.fixture = ArProcessAnchorPostgresTests('test_prepared_reference_and_audit_are_visible_before_popen')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        f = self.fixture
        self.scripts = f.root / 'skill' / 'vendor' / 'scripts'
        # This synthetic fixture has never launched a child or registered refs.
        # Start before effect phases; no previously produced immutable ref is deleted.
        self.assertFalse((f.root / 'execution-processes').exists())
        script = self.scripts / 'build_worklist.py'
        script.write_text("import argparse\nfrom pathlib import Path\n"
            "p=argparse.ArgumentParser()\np.add_argument('--workspace')\np.add_argument('--hexiao-date')\n"
            "p.add_argument('--checked')\np.add_argument('--out')\na=p.parse_args()\n"
            "assert Path(a.checked).read_bytes()==b'{\\\"synthetic_plan\\\":true}'\n"
            "Path(a.out).parent.mkdir(parents=True,exist_ok=True)\n"
            "Path(a.out).write_bytes(b'synthetic report only; no financial workbook parser/writer')\n"
            "print('synthetic first report complete')\n", encoding='utf-8')
        digest = hash_skill_directory(f.root / 'skill')
        context = json.loads(f.workflow.context_json)
        self.workspace = Path(context['workspace'])
        self.checked = self.workspace / '04_产出' / 'synthetic-checked.json'
        self.checked.parent.mkdir(parents=True)
        self.checked.write_bytes(b'{"synthetic_plan":true}')
        context['checked_plan'] = str(self.checked)
        context['plan_fingerprint'] = hashlib.sha256(self.checked.read_bytes()).hexdigest()
        context['ar_execution']['skill_hash'] = digest
        report_index = next(i for i,p in enumerate(PHASES) if p.name == 'build_initial_report')
        context['ar_execution']['completed'] = [p.name for p in PHASES[:report_index]]
        context['ar_execution']['steps'] = {}
        context['execution_safety_v1'] = {'schema_version':'ar-execution-safety-v1','revision':0,'attempts':[]}
        f.workflow.skill_hash = digest
        f.action.name = 'ar_build_initial_report'
        f.workflow.context_json = json.dumps(context)
        f.db.commit()
        self.initial_context = json.loads(f.workflow.context_json)

    def test_original_report_refs_are_committed_before_business_transition_and_spawn(self):
        f = self.fixture
        launches = []
        native_popen = evidence.subprocess.Popen

        def observe_original_launch(*args, **kwargs):
            # Independent SELECT snapshot only; child and launch gates are real.
            with Session(f.engine) as observer:
                context = json.loads(observer.get(WorkflowSession, f.workflow_id).context_json)
                audits = [json.loads(row.details_json) for row in observer.scalars(
                    select(AuditEvent).where(AuditEvent.action == 'ar_process_prepared_registered'))]
                launches.append((context, audits))
            return native_popen(*args, **kwargs)

        with patch.object(evidence.subprocess, 'Popen', side_effect=observe_original_launch):
            result = execute_phase(f.db, f.action, f.workflow)
        # Child and cleanup completed before any newly required refs assertion.
        self.assertEqual(len(launches), 1)
        self.assertEqual(len(result['process_records']), 1)
        produced = result['process_records'][0]
        self.assertEqual(produced['script'], 'build_worklist.py')
        self.assertEqual(produced['state'], 'exited')
        self.assertTrue(f.action._ar_process_exit_confirmed)
        self.assertFalse(hasattr(f.action, '_ar_terminate_process'))
        report = Path(result['initial_report']['path'])
        self.assertEqual(report.read_bytes(), b'synthetic report only; no financial workbook parser/writer')
        record = f.root / 'execution-processes' / f.action_id / produced['record_id']
        prepared = json.loads((record/'prepared.json').read_text())
        started = json.loads((record/'started.json').read_text())
        receipt = json.loads((record/'domain-exited.json').read_text())
        validate_receipt(receipt, token=prepared['domain_token'], supervisor_pid=started['pid'])
        self.assertGreaterEqual(receipt['reaped_count'],1)
        with Session(f.engine) as observer:
            workflow = observer.get(WorkflowSession, f.workflow_id)
            context = json.loads(workflow.context_json)
            latest = observer.get(WorkflowAction, f.action_id)
            terminal_audits = [json.loads(row.details_json) for row in observer.scalars(
                select(AuditEvent).where(AuditEvent.action == 'ar_process_terminal_registered'))]
            self.assertEqual(context['ar_execution']['completed'],self.initial_context['ar_execution']['completed'])
            self.assertEqual(latest.state,'running')
            self.assertEqual(json.loads(latest.result_json),{})
            self.assertEqual(context['execution_safety_v1']['revision'],0)
            self.assertEqual(context['execution_safety_v1']['attempts'],[])
            self.assertEqual({p:p.read_bytes() for p in f.material_bytes},f.material_bytes)
            observed = context['execution_safety_v1'].get('process_observations')
            print(json.dumps({'event':'codex_f4e1_actual_report_before_ref_assertion',
                'actual_children_exited':1,'actual_linux_receipts':1,'cleanup_complete':True,
                'phase_handler_unmocked':True,'financial_script_invoked':False,
                'effect_revision':0,'effect_attempts':0,'business_completion_before_transition':False,
                'observation_partition_present':observed is not None},sort_keys=True))
            self.assertIsInstance(observed,dict,'actual first-report producer must preserve original observations')
            self.assertEqual(observed['schema_version'],'ar-process-observations-v1')
            self.assertEqual(observed['revision'],3)
            self.assertEqual(len(observed['attempts']),1)
            entry = observed['attempts'][0]
            self.assertEqual(entry['phase'],'build_initial_report')
            self.assertEqual(entry['attempt'],1)
            self.assertEqual(entry['worker_id'],'synthetic-worker')
            self.assertFalse({'status','completed_at','result_sha256','effect_disposition'} & set(entry))
            self.assertEqual(len(entry['prepared_process_refs']),1)
            self.assertEqual(len(entry['terminal_process_refs']),1)
            anchor,terminal = entry['prepared_process_refs'][0],entry['terminal_process_refs'][0]
            for key in ('record_id','prepared_sha256','script'):
                self.assertEqual(anchor[key],produced[key])
            for key in ('script_sha256','arguments_sha256'):
                self.assertEqual(anchor[key],prepared[key])
            for key in ('record_id','prepared_sha256','script','started_sha256','exit_sha256','domain_exit_sha256'):
                self.assertEqual(terminal[key],produced[key])
            self.assertEqual(anchor['binding_sha256'],entry['binding_sha256'])
            self.assertEqual(terminal['binding_sha256'],entry['binding_sha256'])
            self.assertEqual(terminal['terminal_state'],'exited')
            self.assertEqual(len(terminal_audits),1)
            self.assertEqual(terminal_audits[0]['evidence_namespace'],'process_observations')
            self.assertEqual(terminal_audits[0]['evidence_revision'],3)
            self.assertIs(terminal_audits[0]['late_observation'],False)
            at_spawn,prepared_audits = launches[0]
            self.assertEqual(at_spawn['execution_safety_v1']['process_observations']['revision'],2)
            self.assertEqual(at_spawn['execution_safety_v1']['process_observations']['attempts'][0]['prepared_process_refs'],[anchor])
            self.assertEqual(len(prepared_audits),1)
            self.assertEqual(prepared_audits[0]['evidence_namespace'],'process_observations')
            self.assertEqual(prepared_audits[0]['evidence_revision'],2)
        # Existing transition owns lifecycle and synthetic artifact registration.
        transition_phase(f.db,f.action,f.workflow,result)
        f.db.commit()
        with Session(f.engine) as reader:
            workflow = reader.get(WorkflowSession,f.workflow_id)
            after = json.loads(workflow.context_json)
            self.assertEqual(after['execution_safety_v1']['process_observations'],observed)
            self.assertEqual(after['execution_safety_v1']['revision'],0)
            self.assertIn('build_initial_report',after['ar_execution']['completed'])
            self.assertEqual(reader.get(WorkflowAction,f.action_id).state,'succeeded')
            before_json = workflow.context_json
            before_audits = reader.scalar(select(func.count()).select_from(AuditEvent))
            mutations=[]
            def observe_sql(connection,cursor,statement,parameters,execution_context,executemany):
                if statement.lstrip().split(None,1)[0].upper() in {'INSERT','UPDATE','DELETE'}:
                    mutations.append(statement)
            event.listen(f.engine,'before_cursor_execute',observe_sql)
            try:
                baseline=read_execution(workflow)
                details=read_execution(workflow,include_process_details=True)
                self.assertIsNone(baseline.process_details)
                self.assertIs(details.attempt_history.process_evidence_checked,False)
                self.assertFalse(details.attempt_history.authorizes_resume)
                self.assertEqual(details.process_details.whole_workflow_coverage,'unknown')
                self.assertEqual(details.attempt_history.registered_attempt_count,0)
                self.assertEqual(workflow.context_json,before_json)
                self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)),before_audits)
            finally:
                event.remove(f.engine,'before_cursor_execute',observe_sql)
            self.assertEqual(mutations,[])
            self.assertEqual({p:p.read_bytes() for p in f.material_bytes},f.material_bytes)

    def test_original_plan_and_fixed_script_are_fenced_again_after_prepared_commit(self):
        f = self.fixture
        execution = ArExecution(f.db,f.action,f.workflow)
        with self.assertRaisesRegex(ValueError,'固定 build_worklist'):
            execution.script('anchor_probe.py',[])
        original_plan = self.checked.read_bytes()
        self.checked.write_bytes(b'synthetic changed before phase')
        with self.assertRaisesRegex(ValueError,'原校验计划已改变'):
            execute_phase(f.db,f.action,f.workflow)
        f.db.rollback()
        with Session(f.engine) as reader:
            context=json.loads(reader.get(WorkflowSession,f.workflow_id).context_json)
            self.assertNotIn('process_observations',context['execution_safety_v1'])
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)),0)
        self.checked.write_bytes(original_plan)
        prepared_connections,changed=set(),[]
        native_commit=f.engine.dialect.do_commit
        def mark(connection,cursor,statement,parameters,execution_context,executemany):
            values=parameters.values() if isinstance(parameters,dict) else parameters
            if statement.startswith('INSERT INTO audit_events') and 'ar_process_prepared_registered' in values:
                prepared_connections.add(id(connection.connection.dbapi_connection))
        def commit_then_change_original_plan(connection):
            physical=getattr(connection,'dbapi_connection',connection)
            native_commit(connection)
            if id(physical) in prepared_connections and not changed:
                # Real PG commit succeeded; the second gate must re-read input bytes.
                self.checked.write_bytes(b'synthetic changed after prepared commit')
                changed.append(True)
        event.listen(f.engine,'before_cursor_execute',mark)
        try:
            with patch.object(f.engine.dialect,'do_commit',side_effect=commit_then_change_original_plan), \
                    patch.object(evidence.subprocess,'Popen',wraps=evidence.subprocess.Popen) as popen:
                with self.assertRaisesRegex(ValueError,'原校验计划已改变'):
                    execute_phase(f.db,f.action,f.workflow)
                self.assertEqual(popen.call_count,0)
        finally:
            event.remove(f.engine,'before_cursor_execute',mark)
        self.assertEqual(changed,[True])
        self.assertFalse(hasattr(f.action,'_ar_terminate_process'))
        with Session(f.engine) as reader:
            context=json.loads(reader.get(WorkflowSession,f.workflow_id).context_json)
            state=context['execution_safety_v1']['process_observations']
            entry=state['attempts'][0]
            self.assertEqual(state['revision'],3)
            self.assertEqual(len(entry['prepared_process_refs']),1)
            self.assertEqual(len(entry['terminal_process_refs']),1)
            terminal=entry['terminal_process_refs'][0]
            self.assertEqual(terminal['terminal_state'],'launch_unconfirmed')
            self.assertTrue(all(terminal[key] is None for key in ('started_sha256','exit_sha256','domain_exit_sha256')))
            self.assertEqual(context['ar_execution']['completed'],self.initial_context['ar_execution']['completed'])
            self.assertEqual(context['execution_safety_v1']['revision'],0)
            self.assertEqual(context['execution_safety_v1']['attempts'],[])
            self.assertEqual(reader.get(WorkflowAction,f.action_id).state,'running')
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action.in_(['ar_process_prepared_registered','ar_process_terminal_registered']))),2)
        record=f.root/'execution-processes'/f.action_id/f.action._ar_process_records[-1]['record_id']
        self.assertTrue((record/'prepared.json').is_file())
        self.assertFalse((record/'started.json').exists())
        self.assertEqual({p:p.read_bytes() for p in f.material_bytes},f.material_bytes)
        print(json.dumps({'event':'codex_f4e1_actual_plan_fences','fixed_script_denied':True,
            'before_phase_plan_denied':True,'after_real_prepared_commit_plan_denied':True,
            'actual_children':0,'original_nullable_terminal_preserved':True},sort_keys=True))

    def test_original_checked_argument_cannot_be_redirected_to_same_digest_other_path(self):
        f=self.fixture
        replacement=self.checked.with_name('synthetic-replacement.json')
        replacement.write_bytes(self.checked.read_bytes())
        registered,redirected=set(),[]
        native_commit=f.engine.dialect.do_commit
        def mark(connection,cursor,statement,parameters,execution_context,executemany):
            values=parameters.values() if isinstance(parameters,dict) else parameters
            if statement.startswith('INSERT INTO audit_events') and 'ar_process_prepared_registered' in values:
                registered.add(id(connection.connection.dbapi_connection))
        def commit_then_redirect(connection):
            physical=getattr(connection,'dbapi_connection',connection)
            native_commit(connection)
            if id(physical) in registered and not redirected:
                redirected.append(True)
                self.checked.write_bytes(b'synthetic original A changed')
                with Session(f.engine) as changed:
                    workflow=changed.get(WorkflowSession,f.workflow_id)
                    context=json.loads(workflow.context_json)
                    context['checked_plan']=str(replacement)
                    workflow.context_json=json.dumps(context)
                    changed.commit()
        error=None
        event.listen(f.engine,'before_cursor_execute',mark)
        try:
            with patch.object(f.engine.dialect,'do_commit',side_effect=commit_then_redirect), \
                    patch.object(evidence.subprocess,'Popen',wraps=evidence.subprocess.Popen) as popen:
                try:
                    execute_phase(f.db,f.action,f.workflow)
                except Exception as caught:
                    error=caught
                actual_launches=popen.call_count
        finally:
            event.remove(f.engine,'before_cursor_execute',mark)
        self.assertEqual(redirected,[True])
        self.assertFalse(hasattr(f.action,'_ar_terminate_process'))
        print(json.dumps({'event':'codex_f4e1_original_plan_redirect','actual_children':actual_launches,
            'prepare_commit_real':True,'fresh_B_same_original_sha':True,'original_argv_A_bytes_changed':True,
            'error_type':type(error).__name__,'cleanup_complete':True},sort_keys=True))
        self.assertEqual(actual_launches,0,'fresh B must not validate the original --checked A argument')
        self.assertIsInstance(error,ValueError)
        with Session(f.engine) as reader:
            context=json.loads(reader.get(WorkflowSession,f.workflow_id).context_json)
            state=context['execution_safety_v1']['process_observations']
            entry=state['attempts'][0]
            self.assertEqual(entry['plan_fingerprint'],self.initial_context['plan_fingerprint'])
            self.assertEqual(entry['terminal_process_refs'][0]['terminal_state'],'launch_unconfirmed')
            self.assertTrue(all(entry['terminal_process_refs'][0][key] is None
                for key in ('started_sha256','exit_sha256','domain_exit_sha256')))
            self.assertEqual(context['ar_execution']['completed'],self.initial_context['ar_execution']['completed'])
            self.assertEqual(context['execution_safety_v1']['revision'],0)
            self.assertEqual(context['execution_safety_v1']['attempts'],[])
        self.assertEqual({p:p.read_bytes() for p in f.material_bytes},f.material_bytes)

    def test_observation_prepared_audit_failure_and_real_commit_ack_loss_never_spawn(self):
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        from app import workflow_service as service
        from app.ar_execution_contract import CONTRACT_VERSION
        from app.workflow_action_state import isolated_action_state
        f=self.fixture
        with f.engine.begin() as setup:
            setup.execute(text("ALTER TABLE audit_events ADD CONSTRAINT codex_e1_prepared_fault "
                               "CHECK (action <> 'ar_process_prepared_registered')"))
        with patch.object(evidence.subprocess,'Popen',wraps=evidence.subprocess.Popen) as popen:
            with self.assertRaises(IntegrityError) as failed:
                execute_phase(f.db,f.action,f.workflow)
            self.assertEqual(popen.call_count,0)
        self.assertEqual(failed.exception.orig.sqlstate,'23514')
        self.assertEqual(failed.exception.orig.diag.constraint_name,'codex_e1_prepared_fault')
        self.assertFalse(hasattr(f.action,'_ar_terminate_process'))
        with Session(f.engine) as reader:
            state=json.loads(reader.get(WorkflowSession,f.workflow_id).context_json)['execution_safety_v1']['process_observations']
            self.assertEqual(state['revision'],1)
            self.assertEqual(state['attempts'][0]['prepared_process_refs'],[])
            self.assertEqual(state['attempts'][0]['terminal_process_refs'],[])
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action.in_(['ar_process_prepared_registered','ar_process_terminal_registered']))),0)
        with f.engine.begin() as setup:
            setup.execute(text('ALTER TABLE audit_events DROP CONSTRAINT codex_e1_prepared_fault'))
        f.db.refresh(f.action)
        f.action.state=isolated_action_state('queued')
        f.action.worker_id,f.action.lease_expires_at='',None
        f.db.commit()  # Only this owned synthetic action is made claimable.
        registered,lost=set(),[]
        native_commit=f.engine.dialect.do_commit
        def mark(connection,cursor,statement,parameters,execution_context,executemany):
            values=parameters.values() if isinstance(parameters,dict) else parameters
            if statement.startswith('INSERT INTO audit_events') and 'ar_process_prepared_registered' in values:
                registered.add(id(connection.connection.dbapi_connection))
        def commit_then_lose_ack(connection):
            physical=getattr(connection,'dbapi_connection',connection)
            native_commit(connection)
            if id(physical) in registered and not lost:
                lost.append(True)
                raise RuntimeError('synthetic E1 prepared commit acknowledgement lost')
        with Session(f.engine,expire_on_commit=False) as run_db:
            claimed=service.claim_next_workflow_action(run_db,('workflow',),'synthetic-worker-two',
                                                       execution_contracts=(CONTRACT_VERSION,))
            self.assertEqual(claimed.id,f.action_id)
            self.assertEqual(claimed.attempt_count,2)
            workflow=run_db.get(WorkflowSession,f.workflow_id)
            event.listen(f.engine,'before_cursor_execute',mark)
            try:
                with patch.object(f.engine.dialect,'do_commit',side_effect=commit_then_lose_ack), \
                        patch.object(evidence.subprocess,'Popen',wraps=evidence.subprocess.Popen) as popen:
                    with self.assertRaisesRegex(RuntimeError,'acknowledgement lost'):
                        execute_phase(run_db,claimed,workflow)
                    self.assertEqual(popen.call_count,0)
            finally:
                event.remove(f.engine,'before_cursor_execute',mark)
            self.assertFalse(hasattr(claimed,'_ar_terminate_process'))
        self.assertEqual(lost,[True])
        with Session(f.engine) as reader:
            context=json.loads(reader.get(WorkflowSession,f.workflow_id).context_json)
            state=context['execution_safety_v1']['process_observations']
            self.assertEqual(state['revision'],3)
            self.assertEqual([e['attempt'] for e in state['attempts']],[1,2])
            self.assertEqual([len(e['prepared_process_refs']) for e in state['attempts']],[0,1])
            self.assertEqual([e['terminal_process_refs'] for e in state['attempts']],[[],[]])
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action=='ar_process_prepared_registered')),1)
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action=='ar_process_terminal_registered')),0)
            self.assertEqual(context['ar_execution']['completed'],self.initial_context['ar_execution']['completed'])
            self.assertEqual(context['execution_safety_v1']['revision'],0)
        self.assertFalse(any((f.root/'execution-processes'/f.action_id).glob('*/started.json')))
        self.assertEqual({p:p.read_bytes() for p in f.material_bytes},f.material_bytes)
        print(json.dumps({'event':'codex_f4e1_prepared_atomic_ack','actual_attempts':2,
            'real_pg_constraint_rejection':True,'real_pg_commit_ack_lost':True,
            'actual_children':0,'terminal_callbacks_no_sql':True},sort_keys=True))

    def test_observation_terminal_audit_failure_preserves_callback_caller_dml_and_original_prepared(self):
        from uuid import uuid4
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError
        from app.auth_models import User
        from app.ar_process_evidence import TerminalProcessRegistrationError
        f=self.fixture
        with f.engine.begin() as setup:
            setup.execute(text("ALTER TABLE audit_events ADD CONSTRAINT codex_e1_terminal_fault "
                               "CHECK (action <> 'ar_process_terminal_registered')"))
        flushed_id,pending_id=str(uuid4()),str(uuid4())
        caller=[]
        native_record=ArExecution.record_terminal
        def record_after_cleanup(execution,anchor,observation):
            self.assertFalse(hasattr(execution.action,'_ar_terminate_process'))
            self.assertTrue(execution.action._ar_process_exit_confirmed)
            flushed=User(id=flushed_id,username=flushed_id,department_id='finance',
                         role='finance_user',status='active',password_hash='synthetic-unusable')
            pending=User(id=pending_id,username=pending_id,department_id='finance',
                         role='finance_user',status='active',password_hash='synthetic-unusable')
            execution.db.add(flushed)
            execution.db.flush()
            execution.db.add(pending)
            caller.append((execution.db.get_transaction(),pending))
            return native_record(execution,anchor,observation)
        with patch.object(ArExecution,'record_terminal',record_after_cleanup):
            with self.assertRaises(TerminalProcessRegistrationError) as failed:
                execute_phase(f.db,f.action,f.workflow)
        self.assertEqual(failed.exception.code,'terminal_registration_failed')
        self.assertIsInstance(failed.exception.__cause__,IntegrityError)
        self.assertEqual(failed.exception.__cause__.orig.sqlstate,'23514')
        self.assertEqual(failed.exception.__cause__.orig.diag.constraint_name,'codex_e1_terminal_fault')
        self.assertEqual(len(caller),1)
        transaction,pending=caller[0]
        self.assertIs(f.db.get_transaction(),transaction)
        self.assertTrue(transaction.is_active)
        self.assertIn(pending,f.db.new)
        with f.db.no_autoflush:
            self.assertEqual(f.db.scalar(select(User.id).where(User.id==flushed_id)),flushed_id)
            self.assertIsNone(f.db.scalar(select(User.id).where(User.id==pending_id)))
        produced=f.action._ar_process_records[-1]
        self.assertEqual(produced['state'],'exited')
        record=f.root/'execution-processes'/f.action_id/produced['record_id']
        self.assertTrue((record/'domain-exited.json').is_file())
        self.assertFalse(hasattr(f.action,'_ar_terminate_process'))
        with Session(f.engine) as reader:
            self.assertIsNone(reader.get(User,flushed_id))
            self.assertIsNone(reader.get(User,pending_id))
            workflow=reader.get(WorkflowSession,f.workflow_id)
            context=json.loads(workflow.context_json)
            state=context['execution_safety_v1']['process_observations']
            self.assertEqual(state['revision'],2)
            self.assertEqual(len(state['attempts'][0]['prepared_process_refs']),1)
            self.assertEqual(state['attempts'][0]['terminal_process_refs'],[])
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action=='ar_process_prepared_registered')),1)
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action=='ar_process_terminal_registered')),0)
            self.assertEqual(context['ar_execution']['completed'],self.initial_context['ar_execution']['completed'])
            self.assertEqual(context['execution_safety_v1']['revision'],0)
            self.assertEqual(reader.get(WorkflowAction,f.action_id).state,'running')
            before=workflow.context_json
            details=read_execution(workflow,include_process_details=True)
            self.assertEqual(details.attempt_history.registered_attempt_count,0)
            self.assertEqual(details.process_details.whole_workflow_coverage,'unknown')
            self.assertEqual(workflow.context_json,before)
        self.assertEqual({p:p.read_bytes() for p in f.material_bytes},f.material_bytes)
        print(json.dumps({'event':'codex_f4e1_terminal_atomic_callback','actual_children_exited':1,
            'cleanup_complete_before_callback':True,'real_pg_terminal_constraint_rejection':True,
            'prepared_retained':True,'terminal_revision_audit_partial_commits':0,
            'aux_only_pending_and_flushed_caller_dml_preserved':True},sort_keys=True))

    def test_late_original_observation_preserves_real_second_attempt_transition_and_new_business(self):
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
        print(json.dumps({'event':'codex_f4e1_late_actual_second_attempt','actual_children_exited':2,
            'second_claim_actual':True,'second_business_transition_actual':True,'old_terminal_late':True,
            'new_context_business_actions_material_unchanged_by_callback':True,
            'old_business_transition_fenced':True},sort_keys=True))

    def test_launch_window_holds_real_workflow_row_lock_before_native_popen(self):
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        f=self.fixture
        probes=[]
        native_popen=evidence.subprocess.Popen
        def probe_original_workflow_lock(*args,**kwargs):
            with f.engine.connect() as contender:
                try:
                    contender.execute(text('SELECT id FROM workflow_sessions WHERE id=:id FOR UPDATE NOWAIT'),
                                      {'id':f.workflow_id})
                    probes.append('lock_acquired')
                except DBAPIError as error:
                    self.assertEqual(error.orig.sqlstate,'55P03')
                    probes.append('55P03')
                finally:
                    contender.rollback()
            return native_popen(*args,**kwargs)
        with patch.object(evidence.subprocess,'Popen',side_effect=probe_original_workflow_lock):
            result=execute_phase(f.db,f.action,f.workflow)
        self.assertEqual(result['process_records'][0]['state'],'exited')
        self.assertFalse(hasattr(f.action,'_ar_terminate_process'))
        print(json.dumps({'event':'codex_f4e1_launch_workflow_lock','actual_children_exited':1,
            'actual_pg_nowait_result':probes,'cleanup_complete':True},sort_keys=True))
        self.assertEqual(probes,['55P03'],'second real launch gate must hold the original workflow row lock')
        self.assertEqual({p:p.read_bytes() for p in f.material_bytes},f.material_bytes)

    def test_observation_namespace_is_bounded_idempotent_and_public_fingerprint_only(self):
        from concurrent.futures import ThreadPoolExecutor
        from datetime import datetime
        from app.ar_process_evidence import TerminalProcessRegistrationError
        f=self.fixture
        captured,launch_fingerprints=[],[]
        native_record,native_popen=ArExecution.record_terminal,evidence.subprocess.Popen
        def capture(execution,anchor,observation):
            captured.append((execution,anchor,observation))
            return native_record(execution,anchor,observation)
        def snapshot_original_launch(*args,**kwargs):
            with Session(f.engine) as reader:
                workflow=reader.get(WorkflowSession,f.workflow_id)
                launch_fingerprints.append(read_execution(workflow).attempt_history.snapshot_fingerprint)
            return native_popen(*args,**kwargs)
        with patch.object(ArExecution,'record_terminal',capture), \
                patch.object(evidence.subprocess,'Popen',side_effect=snapshot_original_launch):
            result=execute_phase(f.db,f.action,f.workflow)
        self.assertEqual(result['process_records'][0]['state'],'exited')
        self.assertEqual(len(captured),1)
        execution,anchor,observation=captured[0]
        record=f.root/'execution-processes'/f.action_id/anchor.record_id
        original_facts={p.name:p.read_bytes() for p in record.iterdir()}
        with Session(f.engine) as reader:
            workflow=reader.get(WorkflowSession,f.workflow_id)
            original_context=workflow.context_json
            writes=[]
            def observe_sql(connection,cursor,statement,parameters,execution_context,executemany):
                if statement.lstrip().split(None,1)[0].upper() in {'INSERT','UPDATE','DELETE'}:
                    writes.append(statement)
            event.listen(f.engine,'before_cursor_execute',observe_sql)
            try:
                baseline=read_execution(workflow)
                details=read_execution(workflow,include_process_details=True)
                self.assertIsNone(baseline.process_details)
                self.assertNotEqual(launch_fingerprints,[baseline.attempt_history.snapshot_fingerprint])
                self.assertEqual(details.process_details.metadata_snapshot_fingerprint,baseline.attempt_history.snapshot_fingerprint)
                self.assertEqual(details.attempt_history.registered_attempt_count,0)
                self.assertIs(details.attempt_history.process_evidence_checked,False)
                self.assertFalse(details.attempt_history.authorizes_resume)
                self.assertEqual(details.process_details.whole_workflow_coverage,'unknown')
            finally:
                event.remove(f.engine,'before_cursor_execute',observe_sql)
            self.assertEqual(writes,[])
            self.assertEqual(workflow.context_json,original_context)
        with ThreadPoolExecutor(max_workers=2) as pool:
            duplicates=list(pool.map(lambda _:execution.record_terminal(anchor,observation),range(2)))
        self.assertEqual(duplicates[0],duplicates[1])
        with Session(f.engine) as reader:
            workflow=reader.get(WorkflowSession,f.workflow_id)
            self.assertEqual(workflow.context_json,original_context)
            context=json.loads(original_context)
            self.assertEqual(context['execution_safety_v1']['revision'],0)
            self.assertEqual(context['execution_safety_v1']['process_observations']['revision'],3)
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action=='ar_process_terminal_registered')),1)
        long_stamp='2026-10-08T00:00:00.'+'1'*100+'+00:00'
        self.assertGreater(len(long_stamp),64)
        self.assertIsNotNone(datetime.fromisoformat(long_stamp).utcoffset())
        # Explicit corrupt-storage fixture retains every produced ref and SHA.
        context['execution_safety_v1']['process_observations']['attempts'][0]['prepared_process_refs'][0]['registered_at']=long_stamp
        tampered=json.dumps(context)
        with Session(f.engine) as change:
            workflow=change.get(WorkflowSession,f.workflow_id)
            workflow.context_json=tampered
            change.commit()
        error=None
        try:
            execution.record_terminal(anchor,observation)
        except TerminalProcessRegistrationError as caught:
            error=caught
        print(json.dumps({'event':'codex_f4e1_namespace_bounds','actual_children_exited':1,
            'public_fingerprint_changed_only_after_terminal_append':True,'effect_revision':0,
            'public_get_mutations':0,'concurrent_identical_terminal_audit_count':1,
            'prepared_timestamp_iso_accepted_but_length_over64':True,
            'bad_prepared_timestamp_rejected':error is not None},sort_keys=True))
        self.assertIsInstance(error,TerminalProcessRegistrationError,'E1 prepared timestamp must reject over64 before ISO parsing')
        self.assertIsInstance(error.__cause__,ValueError)
        with Session(f.engine) as reader:
            self.assertEqual(reader.get(WorkflowSession,f.workflow_id).context_json,tampered)
            self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action=='ar_process_terminal_registered')),1)
        self.assertEqual({p.name:p.read_bytes() for p in record.iterdir()},original_facts)
        self.assertEqual({p:p.read_bytes() for p in f.material_bytes},f.material_bytes)

    def test_actual_nonzero_public_action_failure_merges_original_observations_from_fresh_context(self):
        from dataclasses import replace
        from app import workflow_service as service,workflow_execution_policy as policy
        from app.models import FileRecord,WorkflowMaterialSet
        f=self.fixture
        marker='synthetic E1 deliberate nonzero after valid inputs'
        script=self.scripts/'build_worklist.py'
        script.write_text(script.read_text()+"\nimport sys\nsys.stderr.write("+repr(marker+'\n')+")\nraise SystemExit(7)\n")
        digest=hash_skill_directory(f.root/'skill')
        context=json.loads(f.workflow.context_json)
        context['ar_execution']['skill_hash']=digest
        f.workflow.skill_hash=digest
        f.workflow.context_json=json.dumps(context)
        f.db.commit()
        material=f.db.get(WorkflowMaterialSet,f.workflow.material_set_id)
        original_material=(material.id,material.version,material.state)
        early=[]
        native_record=ArExecution.record_terminal
        def capture_before_original_failure_transition(execution,anchor,observation):
            ref=native_record(execution,anchor,observation)
            with Session(f.engine) as reader:
                workflow=reader.get(WorkflowSession,f.workflow_id)
                early.append(json.loads(workflow.context_json)['execution_safety_v1']['process_observations'])
                self.assertEqual(reader.get(WorkflowAction,f.action_id).state,'running')
                self.assertNotIn('ar_failure',json.loads(workflow.context_json))
            return ref
        # Scoped deployment setting only in network-none synthetic PG. Real gates remain enabled.
        isolated_settings=replace(service.settings,ar_hexiao_execution_enabled=True)
        with patch.object(service,'settings',isolated_settings),patch.object(policy,'settings',isolated_settings), \
                patch.object(ArExecution,'record_terminal',capture_before_original_failure_transition):
            service.execute_workflow_action(f.db,f.action)
        f.db.commit()  # Public action caller owns the real failure transaction.
        self.assertEqual(len(early),1,'valid-input child must reach original terminal capture before failure')
        self.assertFalse(hasattr(f.action,'_ar_terminate_process'))
        with Session(f.engine) as reader:
            workflow=reader.get(WorkflowSession,f.workflow_id)
            action=reader.get(WorkflowAction,f.action_id)
            context=json.loads(workflow.context_json)
            self.assertEqual(action.state,'failed')
            self.assertEqual(workflow.state,'failed')
            self.assertEqual(context['error_detail']['step_key'],'build_initial_report')
            self.assertEqual(context['ar_failure']['phase'],'build_initial_report')
            self.assertEqual(context['ar_failure']['error_type'],'RuntimeError')
            self.assertTrue(context['ar_failure']['process_exit_confirmed'])
            self.assertEqual(context['execution_safety_v1']['process_observations'],early[0])
            self.assertEqual(context['execution_safety_v1']['revision'],0)
            self.assertEqual(context['execution_safety_v1']['attempts'],[])
            self.assertEqual(context['ar_execution']['completed'],self.initial_context['ar_execution']['completed'])
            entry=early[0]['attempts'][0]
            self.assertEqual(entry['terminal_process_refs'][0]['terminal_state'],'exited')
            self.assertFalse({'status','completed_at','result_sha256','effect_disposition'} & set(entry))
            produced=context['ar_failure']['process_records'][0]
            terminal=entry['terminal_process_refs'][0]
            for key in ('record_id','prepared_sha256','started_sha256','exit_sha256','domain_exit_sha256'):
                self.assertEqual(terminal[key],produced[key])
            record=f.root/'execution-processes'/f.action_id/produced['record_id']
            exited=json.loads((record/'exited.json').read_text())
            self.assertEqual(exited['returncode'],7)
            self.assertTrue(exited['communication_completed'])
            self.assertEqual(exited['stderr_sha256'],hashlib.sha256((marker+'\n').encode()).hexdigest())
            material=reader.get(WorkflowMaterialSet,workflow.material_set_id)
            self.assertEqual((material.id,material.version,material.state),original_material)
            self.assertEqual(reader.scalar(select(func.count()).select_from(WorkflowMaterialSet)),1)
            self.assertEqual(reader.scalar(select(func.count()).select_from(FileRecord)),2)
            self.assertEqual(json.loads(workflow.artifacts_json),[])
            details=read_execution(workflow,include_process_details=True)
            self.assertEqual(details.attempt_history.registered_attempt_count,0)
            self.assertFalse(details.attempt_history.authorizes_resume)
            self.assertEqual(details.process_details.whole_workflow_coverage,'unknown')
        self.assertEqual({p:p.read_bytes() for p in f.material_bytes},f.material_bytes)
        print(json.dumps({'event':'codex_f4e1_actual_public_failure_transition','actual_children_exited':1,
            'actual_returncode':7,'valid_inputs_before_deliberate_nonzero':True,'cleanup_complete':True,
            'original_cause_type_retained':'RuntimeError','failure_transition_actual':True,
            'original_refs_survive_fresh_merge':True,'effect_completion_new_material_financial_writes':0},sort_keys=True))

    def test_malformed_observation_partition_and_boundaries_reject_without_effect_or_evidence_mutation(self):
        from copy import deepcopy
        from dataclasses import replace
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
            # Synthetic corrupt-storage fixture construction, never a new original file SHA.
            entry['binding_sha256'] = hashlib.sha256(json.dumps(
                {key: entry[key] for key in BINDING_FIELDS}, ensure_ascii=False,
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
                self.assertEqual(reader.get(WorkflowSession, f.workflow_id).context_json, raw)
                self.assertEqual(reader.scalar(select(func.count()).select_from(AuditEvent)), audit_count)
                self.assertEqual(reader.get(WorkflowAction, f.action_id).state, 'running')
            self.assertEqual({p.name: p.read_bytes() for p in record.iterdir()}, original_facts)
            self.assertEqual({p: p.read_bytes() for p in f.material_bytes}, f.material_bytes)

        cases = []
        for key, value in [('schema_version', 'wrong'), ('revision', True), ('revision', -1),
                           ('revision', '3'), ('attempts', {}), ('attempts', [None])]:
            context = deepcopy(baseline)
            context['execution_safety_v1']['process_observations'][key] = value
            cases.append((key + ':' + repr(value), context))
        for value in (None, [], 'wrong'):
            context = deepcopy(baseline)
            context['execution_safety_v1']['process_observations'] = value
            cases.append(('partition_type:' + repr(value), context))
        for field, value in [('attempt', True), ('attempt', 0), ('material_version', True),
                             ('material_version', 0), ('owner_id', ''), ('owner_id', 'x' * 256),
                             ('phase', 'write_ledger'), ('workflow_id', 'another-workflow'),
                             ('skill_hash', 'G' * 64), ('plan_fingerprint', 'a' * 63),
                             ('workspace_sha256', None)]:
            context = deepcopy(baseline)
            entry = context['execution_safety_v1']['process_observations']['attempts'][0]
            entry[field] = value
            bind(entry)
            cases.append(('entry:' + field + ':' + repr(value), context))
        for label in ('missing_field', 'extra_status', 'bad_digest', 'bad_intent_time',
                      'prepared_type', 'two_prepared', 'two_terminal', 'duplicate_attempt',
                      'duplicate_record', 'cross_partition_record', 'extra_partition_field'):
            context = deepcopy(baseline)
            state = context['execution_safety_v1']['process_observations']
            entry = state['attempts'][0]
            if label == 'missing_field':
                del entry['terminal_process_refs']
            elif label == 'extra_status':
                entry['status'] = 'phase_completed'
            elif label == 'bad_digest':
                entry['binding_sha256'] = '0' * 64
            elif label == 'bad_intent_time':
                entry['intent_at'] = '2026-10-09T00:00:00'
            elif label == 'prepared_type':
                entry['prepared_process_refs'][0]['registered_at'] = True
            elif label == 'two_prepared':
                entry['prepared_process_refs'].append(deepcopy(entry['prepared_process_refs'][0]))
            elif label == 'two_terminal':
                entry['terminal_process_refs'].append(deepcopy(entry['terminal_process_refs'][0]))
            elif label == 'duplicate_attempt':
                state['attempts'].append(deepcopy(entry))
            elif label == 'duplicate_record':
                other = deepcopy(entry)
                other['attempt'] = 2
                other['terminal_process_refs'] = []
                bind(other)
                other['prepared_process_refs'][0]['binding_sha256'] = other['binding_sha256']
                state['attempts'].append(other)
            elif label == 'cross_partition_record':
                effect = {key: deepcopy(entry[key]) for key in BINDING_FIELDS}
                effect.update(phase='write_ledger', attempt=2, status='intent_recorded',
                              intent_at=entry['intent_at'])
                bind(effect)
                ref = deepcopy(entry['prepared_process_refs'][0])
                ref['binding_sha256'] = effect['binding_sha256']
                effect['prepared_process_refs'] = [ref]
                context['execution_safety_v1']['attempts'] = [effect]
            else:
                state['extra'] = 'not-allowed'
            cases.append((label, context))

        # Exactly 128 intent entries are allowed. Original produced refs remain intact;
        # the other entries are explicitly synthetic historical intent-only fixtures.
        boundary = deepcopy(baseline)
        attempts = boundary['execution_safety_v1']['process_observations']['attempts']
        for number in range(2, 129):
            entry = {key: deepcopy(original[key]) for key in BINDING_FIELDS}
            entry.update(attempt=number, intent_at=original['intent_at'],
                         prepared_process_refs=[], terminal_process_refs=[])
            bind(entry)
            attempts.append(entry)
        self.assertEqual(len(attempts), 128)
        boundary_raw = persist(boundary)
        self.assertEqual(execution.record_terminal(anchor, observation)['record_id'], anchor.record_id)
        unchanged(boundary_raw)
        overflow = deepcopy(boundary)
        entry = deepcopy(attempts[-1])
        entry['attempt'] = 129
        bind(entry)
        overflow['execution_safety_v1']['process_observations']['attempts'].append(entry)
        cases.append(('129_attempts', overflow))

        for label, context in cases:
            with self.subTest(boundary=label):
                raw = persist(context)
                with self.assertRaises(TerminalProcessRegistrationError) as caught:
                    execution.record_terminal(anchor, observation)
                self.assertIsInstance(caught.exception.__cause__, ValueError)
                unchanged(raw)
                if label != 'cross_partition_record':
                    with Session(f.engine) as reader:
                        workflow = reader.get(WorkflowSession, f.workflow_id)
                        public = read_execution(workflow, include_process_details=True)
                        self.assertEqual(public.attempt_history.registered_attempt_count, 0)
                        self.assertFalse(public.attempt_history.authorizes_resume)
                        self.assertEqual(public.process_details.whole_workflow_coverage, 'unknown')
                    unchanged(raw)
        clean_raw = persist(baseline)
        for field in ('started_sha256', 'exit_sha256', 'domain_exit_sha256'):
            with self.subTest(conflict=field):
                with self.assertRaises(TerminalProcessRegistrationError) as caught:
                    execution.record_terminal(anchor, replace(observation, **{field: None}))
                self.assertEqual(caught.exception.code, 'terminal_ref_conflict')
                unchanged(clean_raw)
        print(json.dumps({'event': 'codex_f4e1_namespace_validation', 'actual_children_exited': 1,
            'invalid_fixture_cases_rejected': len(cases), 'boundary_128_accepted': True,
            'boundary_129_rejected': True, 'null_conflicts_rejected': 3,
            'effect_reader_ignores_bad_observation': True, 'original_facts_audit_material_unchanged': True},
            sort_keys=True))

    def test_legacy_absence_is_not_backfilled_and_only_current_invocation_creates_observations(self):
        f = self.fixture
        context = json.loads(f.workflow.context_json)
        context.pop('execution_safety_v1')
        f.workflow.context_json = json.dumps(context)
        legacy_id = 'e' * 32
        # Explicit misleading mutable-result fixture, with no produced original facts.
        legacy_result = {'process_records': [{'record_id': legacy_id, 'script': 'build_worklist.py',
            'prepared_sha256': 'b' * 64, 'started_sha256': 'c' * 64, 'exit_sha256': 'd' * 64,
            'domain_exit_sha256': 'f' * 64, 'state': 'exited'}]}
        f.action.result_json = json.dumps(legacy_result)
        f.db.commit()
        before = f.workflow.context_json
        self.assertFalse((f.root / 'execution-processes').exists())
        native_popen = evidence.subprocess.Popen
        launches = []
        writes = []

        def native_launch(*args, **kwargs):
            launches.append(True)
            return native_popen(*args, **kwargs)

        def observe_write(connection, cursor, statement, parameters, execution_context, executemany):
            if statement.lstrip().split(None, 1)[0].upper() in {'INSERT', 'UPDATE', 'DELETE'}:
                writes.append(statement)

        with patch.object(evidence.subprocess, 'Popen', side_effect=native_launch):
            event.listen(f.engine, 'before_cursor_execute', observe_write)
            try:
                public = read_execution(f.workflow, include_process_details=True)
                self.assertEqual(public.attempt_history.registered_attempt_count, 0)
                self.assertFalse(public.attempt_history.authorizes_resume)
                self.assertEqual(public.process_details.whole_workflow_coverage, 'unknown')
            finally:
                event.remove(f.engine, 'before_cursor_execute', observe_write)
            self.assertEqual(writes, [])
            self.assertEqual(launches, [])
            self.assertEqual(f.workflow.context_json, before)
            with Session(f.engine) as observer:
                self.assertEqual(observer.get(WorkflowSession, f.workflow_id).context_json, before)
                self.assertEqual(observer.scalar(select(func.count()).select_from(AuditEvent).where(
                    AuditEvent.action.in_(['ar_process_prepared_registered', 'ar_process_terminal_registered']))), 0)
            result = execute_phase(f.db, f.action, f.workflow)
        self.assertEqual(launches, [True])
        self.assertEqual(result['process_records'][0]['state'], 'exited')
        produced_id = result['process_records'][0]['record_id']
        self.assertNotEqual(produced_id, legacy_id)
        with Session(f.engine) as observer:
            workflow = observer.get(WorkflowSession, f.workflow_id)
            current = json.loads(workflow.context_json)
            outer = current['execution_safety_v1']
            self.assertEqual(outer['schema_version'], 'ar-execution-safety-v1')
            self.assertEqual(outer['revision'], 0)
            self.assertEqual(outer['attempts'], [])
            observed = outer['process_observations']
            self.assertEqual(observed['revision'], 3)
            self.assertEqual(len(observed['attempts']), 1)
            entry = observed['attempts'][0]
            self.assertEqual(entry['attempt'], 1)
            self.assertEqual([ref['record_id'] for ref in entry['prepared_process_refs']], [produced_id])
            self.assertEqual([ref['record_id'] for ref in entry['terminal_process_refs']], [produced_id])
            self.assertEqual(current['ar_execution'], context['ar_execution'])
            self.assertEqual(json.loads(observer.get(WorkflowAction, f.action_id).result_json), legacy_result)
            public = read_execution(workflow, include_process_details=True)
            self.assertEqual(public.attempt_history.registered_attempt_count, 0)
            self.assertFalse(public.attempt_history.authorizes_resume)
            self.assertEqual(public.process_details.whole_workflow_coverage, 'unknown')
        self.assertFalse((f.root / 'execution-processes' / f.action_id / legacy_id).exists())
        self.assertEqual({p: p.read_bytes() for p in f.material_bytes}, f.material_bytes)
        print(json.dumps({'event': 'codex_f4e1_legacy_absence', 'actual_children_exited': 1,
            'legacy_get_spawn_and_sql_writes': 0, 'legacy_refs_backfilled': 0,
            'current_original_prepared_and_terminal_only': True, 'effect_revision': 0,
            'mutable_legacy_result_and_business_material_unchanged': True}, sort_keys=True))
