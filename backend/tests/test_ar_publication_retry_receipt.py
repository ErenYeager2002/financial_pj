"""A lost publish response must resolve to its committed action, never republish."""
import json
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app import ar_execution_runner as runner
from app.ar_execution_contract import CONTRACT_VERSION, PHASES
from app.models import WorkflowAction, WorkflowSession, WorkflowMaterialSet
from test_ar_postpublish_occupancy import PostPublishOccupancyTests

class PublicationReceiptRetryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=PostPublishOccupancyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        db,flow=self.fixture.db,self.fixture.workflow
        flow.state,flow.stage,flow.execution_mode='running','applying','pi_harness'
        context=json.loads(flow.context_json)
        state=context['ar_execution']
        state.update(schema_version=CONTRACT_VERSION,completed=[p.name for p in PHASES][:-1],
            reconciliation_date=flow.reconciliation_date,skill_hash=flow.skill_hash)
        context['plan_fingerprint']='checked-plan'
        flow.context_json=json.dumps(context)
        self.guard={key:state[key] for key in ['reconciliation_date','material_set_id','material_version']}
        self.guard['plan_fingerprint']=context['plan_fingerprint']
        self.action=WorkflowAction(id='committed-publication',workflow=flow,name='ar_publish_reconciliation',
            state='succeeded',attempt_count=1,worker_id='worker',result_json=json.dumps({'publication':'verified'}))
        db.add(self.action)
        db.commit()  # Publication and completed action are durable; response is discarded.
        self.flow_id=flow.id

    def request(self, db, arguments=None):
        flow=db.get(WorkflowSession,self.flow_id)
        with patch('app.pi_harness_lease.require_harness_lease'), \
             patch('app.workflow_service.workflow_owner_context'), \
             patch.object(runner,'execution_version',return_value=CONTRACT_VERSION), \
             patch('app.workflow_service._queue_action',side_effect=AssertionError('duplicate publication queued')):
            return runner.queue_execution_phase(db,flow,'publish_reconciliation',
                self.guard if arguments is None else arguments,harness_action_id='agent',worker_id='worker',attempt=1)

    def test_new_request_session_reads_committed_receipt_without_new_action(self):
        for _ in range(2):
            with Session(self.fixture.engine) as db:
                result=self.request(db)
                self.assertEqual(result.id,'committed-publication')
                self.assertEqual(json.loads(result.result_json)['publication'],'verified')
                self.assertEqual(db.scalar(select(func.count()).select_from(WorkflowAction)),1)
                self.assertEqual(db.scalar(select(func.count()).select_from(WorkflowMaterialSet)),2)
                db.rollback()

    def test_changed_guard_is_not_treated_as_same_publish(self):
        with Session(self.fixture.engine) as db:
            with self.assertRaises(HTTPException) as caught:
                self.request(db,{**self.guard,'plan_fingerprint':'changed-plan'})
            self.assertEqual(caught.exception.status_code,409)
            db.rollback()

    def test_missing_committed_action_is_not_recreated(self):
        self.fixture.db.delete(self.action)
        self.fixture.db.commit()
        with Session(self.fixture.engine) as db:
            with self.assertRaises(HTTPException) as caught:
                self.request(db)
            self.assertEqual(caught.exception.status_code,409)
            self.assertIn('缺少对应执行事实',caught.exception.detail)
            db.rollback()

if __name__ == '__main__':
    unittest.main()
