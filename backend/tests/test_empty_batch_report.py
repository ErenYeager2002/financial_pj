"""Empty-day handoff through the real batch report collector; no business writes."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from app import workflow_service as s

class BuilderReached(Exception):
    pass

class EmptyBatchReportTests(unittest.TestCase):
    def collect(self, contexts, *, counts=None, bundle=True):
        counts = counts if counts is not None else {k: 0 for k in s.FETCHED_DATASET_COUNT_KEYS.values()}
        children = [NS(context_json=json.dumps(c), fetched_bundle_id='bundle', owner_id='owner', skill_id='skill', reconciliation_date=f'2026-08-{i+1:02d}') for i,c in enumerate(contexts)]
        batch = NS(workflows=children, reconciliation_dates_json=json.dumps([c.reconciliation_date for c in children]))
        db=Mock()
        db.scalar.side_effect=lambda query: NS(id="bundle",summary_json=json.dumps(counts)) if bundle else None
        with patch.object(s, '_prepare_batch_report_workspace', return_value=Path('/unused')), patch.object(s, 'workflow_root', return_value=Path('/unused')), patch.object(s, '_run_batch_report_builder', side_effect=BuilderReached) as builder:
            with self.assertRaises(BuilderReached):
                s._finalize_batch_reports(db,batch,NS(owner_id='owner',id='workflow'),{},NS(id='action'))
        return builder.call_args.kwargs['empty_dates']

    def test_first_day_nested_and_middle_top_level(self):
        self.assertEqual(self.collect([{'fetched_data':{'empty_day_skipped':True}}, {}, {'empty_day_skipped':True}]), ['2026-08-01','2026-08-03'])

    def test_nonempty_summary_cannot_skip(self):
        counts={k:0 for k in s.FETCHED_DATASET_COUNT_KEYS.values()}
        counts[next(iter(counts))]=1
        self.assertEqual(self.collect([{'empty_day_skipped':True}],counts=counts),[])

    def test_missing_bundle_or_incomplete_summary_cannot_skip(self):
        self.assertEqual(self.collect([{'empty_day_skipped':True}],bundle=False),[])
        self.assertEqual(self.collect([{'empty_day_skipped':True}],counts={}),[])

    def test_new_empty_completion_has_canonical_marker(self):
        context={'fetched_data':{}}
        workflow=NS()
        s._complete_empty_reconciliation_date(Mock(),workflow,context,announce=False)
        self.assertIs(json.loads(workflow.context_json).get('empty_day_skipped'),True)
        self.assertEqual(workflow.state,'succeeded')

    def test_report_error_has_batch_scope_and_no_raw_paths(self):
        workflow=NS(context_json=json.dumps({'current_step':'finalize_batch','current_step_label':'生成范围报告'}),stage='completed',owner_id='owner',owner_name='owner',skill_id='ar',skill_name='ar',material_set=None,reconciliation_date='2026-08-31')
        detail=s._workflow_error_detail(workflow,RuntimeError('/private/secret.xlsx missing'))
        public=s._workflow_public_error(workflow,detail)
        self.assertEqual(public['error_type'],'batch_report_failed')
        self.assertIn('批次报告汇总失败',public['message'])
        self.assertNotIn('2026-08-31',public['message'])
        self.assertNotIn('/private',public['message'])

if __name__ == '__main__':
    unittest.main()
