"""Exercise completion through plan, workbook write/readback, and repeat."""
import unittest
from test_flow_monthly import MonthlySafetyTest
import build_flow_plan,apply_flow

class CompletionTest(MonthlySafetyTest):
    # Inherit only fixture methods, not the existing acceptance tests twice.
    def final(self, good, pending, kind='hold', code='E5', skip=False):
        p=dict(pending,bucket=kind,code=code)
        result={'auto':[good],'hexiao_date':'2026-07-28',kind:[p]}
        checked={'hexiao_date':'2026-07-28','write':[good],'skip':[],'conflict':[]}
        if kind=='auto':
            result['auto']=[good,p]
            if skip:checked['skip']=[p]
            else:checked['conflict']=[p]
        flow=build_flow_plan.build_plan(result)
        return build_flow_plan.finalize_plan_after_ledger(flow,checked)
    def test_partial_failure_codes_plan_and_workbook_agree(self):
        for code in ['E2','E3','E5','E8']:
            with self.subTest(code=code):
                # Use a separate workbook for each branch.
                self.tearDown();self.setUp()
                final=self.final(self.entry(),self.entry('SO2',2000),code=code)
                self.assertEqual(final['items'][0]['updated_suggest'],'部分')
                changes,errors=apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status')
                self.assertFalse(errors);self.assertTrue(changes)
                self.assertEqual(self.read('G2'),'部分')
                self.assertEqual(self.read('F2'),'9000-1000=8000')
                before=self.path.read_bytes()
                self.assertEqual(apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status'),([],[]))
                self.assertEqual(before,self.path.read_bytes())
    def test_conflicting_second_case_remains_partial(self):
        final=self.final(self.entry(),self.entry('SO2',2000),kind='auto')
        self.assertEqual(final['items'][0]['updated_suggest'],'部分')
        changes,errors=apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status')
        self.assertFalse(errors);self.assertEqual(self.read('G2'),'部分')
    def test_unattributed_skip_does_not_claim_completed(self):
        final=self.final(self.entry(),self.entry('SO2',2000),kind='auto',code='OK_SO_ALREADY_SETTLED',skip=True)
        self.assertEqual(final['items'][0]['updated_suggest'],'部分')
        changes,errors=apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status')
        self.assertFalse(errors);self.assertEqual(self.read('G2'),'部分')
        self.assertEqual(self.read('F2'),'9000-1000=8000')
    def test_later_completion_only_adds_unwritten_amount(self):
        a,b=self.entry(),self.entry('SO2',2000)
        final=self.final(a,b)
        self.assertFalse(apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status')[1])
        flow=build_flow_plan.build_plan({'auto':[a,b],'hexiao_date':'2026-07-28'})
        a['_check']={'reason':'已经填过且与本次一致（幂等跳过）'}
        final=build_flow_plan.finalize_plan_after_ledger(flow,{'hexiao_date':'2026-07-28','write':[b],'skip':[a],'conflict':[]})
        self.assertEqual(final['items'][0]['updated_suggest'],'是')
        self.assertFalse(apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status')[1])
        self.assertEqual(self.read('G2'),'是');self.assertEqual(self.read('F2'),'9000-1000-2000=6000')

    def test_independent_review_checks_status_and_all_workbook_parts(self):
        import json,shutil
        from verify_execution_write import verify_flow
        baseline=self.root/'baseline'
        shutil.copytree(self.root/'02_我的表副本',baseline/'02_我的表副本')
        a=self.entry();b=dict(self.entry('SO2',2000),bucket='hold',code='E5')
        flow=build_flow_plan.build_plan({'auto':[a],'hold':[b],'hexiao_date':'2026-07-28'})
        checked={'hexiao_date':'2026-07-28','write':[a],'skip':[],'conflict':[]}
        pre,errors=apply_flow.write_flow_items(self.root,flow['items'],in_place=True,phase='prefill')
        self.assertFalse(errors)
        final=build_flow_plan.finalize_plan_after_ledger(flow,checked,workspace=self.root)
        made,errors=apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status')
        self.assertFalse(errors)
        result={'flow_written':True,'manual_items':final['manual_items'],'manual_count':len(final['manual_items']),
                'phases':{'prefill':{'state':'verified','changed_count':len(pre)},'status':{'state':'verified','changed_count':len(made)}}}
        for name,data in [('流转写入计划_校验后.json',flow),('流转阶段执行结果.json',result)]:
            (self.root/'04_产出'/name).write_text(json.dumps(data),encoding='utf-8')
        self.assertGreater(verify_flow(self.root,baseline,self.path,checked)['parts_checked'],0)
        self.modify(lambda ws:setattr(ws['G2'],'value','是'))
        with self.assertRaises(ValueError):verify_flow(self.root,baseline,self.path,checked)

# Reuse fixture helpers without rerunning inherited test cases in this module.
for name in list(MonthlySafetyTest.__dict__):
    if name.startswith('test_') and name not in CompletionTest.__dict__:
        setattr(CompletionTest,name,None)
if __name__=='__main__':unittest.main()
