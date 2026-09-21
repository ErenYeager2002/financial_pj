import unittest,copy,json,shutil
import build_flow_plan,flow_monthly,execution_flow_stage,verify_execution_write
from test_flow_monthly import MonthlySafetyTest as Fixture

class SourceReceiptFlow(unittest.TestCase):
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    entry=Fixture.entry
    read=Fixture.read
    modify=Fixture.modify
    def row(self,so='SO1',amount=1000,day='2026-07-28',code='E2'):
        r=self.entry(so,amount);r.update(bucket='hold',code=code)
        r['flow_source_receipt']={'ar':r['ar'],'so':so,'date':day,'amount':str(amount),'currency':'CNY','event':[],'basis':'current_source_so_receipt'}
        return r
    def run_rows(self,rows,day='2026-07-28',written=()):
        p=build_flow_plan.build_plan({'hold':[r for r in rows if r['bucket']=='hold'],'auto':[r for r in rows if r['bucket']=='auto'],'hexiao_date':day})
        checked={'hexiao_date':day,'write':list(written),'skip':[],'conflict':[]}
        f=build_flow_plan.finalize_plan_after_ledger(p,checked)
        return flow_monthly.write(self.root,f['items'],in_place=True,phase='status')
    def test_missing_ledger_deducts_and_replay_does_not(self):
        rows=[self.row()];changes,errors=self.run_rows(rows)
        self.assertEqual(errors,[]);self.assertTrue(changes)
        self.assertEqual(self.read('F2'),'9000-1000=8000');self.assertFalse(self.read('G2'))
        before=self.path.read_bytes();self.assertEqual(self.run_rows(rows),([],[]));self.assertEqual(before,self.path.read_bytes())
    def test_multiple_sod_views_deduct_so_once(self):
        a=self.row();b=copy.deepcopy(a);b['sod']='OTHER';b['case_id']+='OTHER'
        self.assertEqual(self.run_rows([a,b])[1],[]);self.assertEqual(self.read('F2'),'9000-1000=8000')
    def test_cross_month_and_next_day(self):
        self.assertEqual(self.run_rows([self.row()])[1],[])
        self.assertEqual(self.run_rows([self.row('SO2',3000,'2026-08-01')],'2026-08-01')[1],[])
        self.assertEqual(self.run_rows([self.row('SO3',5000,'2026-08-02',code='E3')],'2026-08-02')[1],[])
        self.assertEqual(self.read('C3'),8000);self.assertEqual(self.read('F3'),'8000-3000-5000=0');self.assertFalse(self.read('G3'))
    def test_later_ledger_completion_only_updates_status(self):
        row=self.row();self.assertEqual(self.run_rows([row])[1],[])
        row.update(bucket='auto',code='')
        self.assertEqual(self.run_rows([row],written=[row])[1],[])
        self.assertEqual(self.read('F2'),'9000-1000=8000');self.assertEqual(self.read('G2'),'是')
    def test_previous_case_allocation_is_not_deducted_again(self):
        old=self.entry();flow=build_flow_plan.build_plan({'auto':[old],'hexiao_date':'2026-07-28'})
        final=build_flow_plan.finalize_plan_after_ledger(flow,{'hexiao_date':'2026-07-28','write':[old]})
        self.assertEqual(flow_monthly.write(self.root,final['items'],in_place=True,phase='status')[1],[])
        self.assertEqual(self.run_rows([self.row()])[1],[])
        self.assertEqual(self.read('F2'),'9000-1000=8000');self.assertEqual(self.read('G2'),'是')
    def test_conflicting_source_total_does_not_write(self):
        before=self.path.read_bytes();_,errors=self.run_rows([self.row(),self.row(amount=2000)])
        self.assertEqual(self.path.read_bytes(),before)
    def test_full_stage_and_independent_readback(self):
        baseline=self.root/'before';rel=self.path.relative_to(self.root);(baseline/rel).parent.mkdir(parents=True);shutil.copy2(self.path,baseline/rel)
        out=self.root/'04_产出';checked={'hexiao_date':'2026-07-28','write':[],'skip':[],'conflict':[]}
        cp=out/'checked.json';cp.write_text(json.dumps(checked))
        flow=build_flow_plan.build_plan({'hold':[self.row()],'hexiao_date':'2026-07-28'})
        (out/'流转写入计划_校验后.json').write_text(json.dumps(flow))
        result=execution_flow_stage.run(self.root,cp);self.assertTrue(result['flow_written']);self.assertEqual(self.read('F2'),'9000-1000=8000')
        (out/'流转阶段执行结果.json').write_text(json.dumps(result))
        self.assertEqual(verify_execution_write.verify_flow(self.root,baseline,self.path,checked)['mode'],'approved_patch_all_parts')

    def test_classification_retains_source_even_without_ledger(self):
        import classification_decision
        rec={'ar':'AR1','so':'SO1','sod':'','hexiao_date':'2026-07-28','status':'正常',
             'forced_code':'E5','_missing_from_provided_ledgers':True,
             'so_receipt_source':{'amount_local':1000,'currency':'CNY','writeoff_sequence_key':[]}}
        result=classification_decision.classify_one(rec,None,{},1,2026)
        self.assertEqual(result['code'],'E2');self.assertEqual(result['flow_source_receipt']['amount'],'1000')
        for forced in ('E7','E_PARENT_WRITEOFF_MISMATCH','E_SYSTEM_OVER_WRITEOFF_UNRESOLVED'):
            rec['forced_code']=forced
            self.assertFalse(classification_decision.classify_one(rec,None,{},1,2026)['flow_source_receipt'])
    def test_source_ledger_conflict_still_deducts(self):
        row=self.row(code='E8')
        self.assertEqual(self.run_rows([row])[1],[]);self.assertEqual(self.read('F2'),'9000-1000=8000')
    def test_amount_change_does_not_deduct_again(self):
        self.run_rows([self.row()]);before=self.path.read_bytes()
        self.assertTrue(self.run_rows([self.row(amount=2000)])[1]);self.assertEqual(before,self.path.read_bytes())
    def test_legacy_partial_cases_only_deduct_remaining_source_amount(self):
        row=self.entry(amount=400)
        flow=build_flow_plan.build_plan({'auto':[row],'hexiao_date':'2026-07-28'})
        final=build_flow_plan.finalize_plan_after_ledger(flow,{'hexiao_date':'2026-07-28','write':[row]})
        flow_monthly.write(self.root,final['items'],in_place=True,phase='status')
        self.assertEqual(self.run_rows([self.row()])[1],[]);self.assertEqual(self.read('F2'),'9000-400-600=8000')
        before=self.path.read_bytes();self.assertEqual(self.run_rows([self.row()]),([],[]));self.assertEqual(before,self.path.read_bytes())

    def test_later_completion_updates_original_month_without_backdated_deduction(self):
        row=self.row();self.run_rows([row])
        self.run_rows([self.row('SO2',2000,'2026-08-01')],'2026-08-01')
        row.update(bucket='auto',code='')
        self.assertEqual(self.run_rows([row],written=[row])[1],[])
        self.assertEqual(self.read('G2'),'是');self.assertFalse(self.read('G3'))
        self.assertEqual(self.read('F2'),'9000-1000=8000');self.assertEqual(self.read('F3'),'8000-2000=6000')
    def test_old_prefill_then_deduction_then_ledger_completion(self):
        from test_flow_order_prefill import PendingOrders
        legacy=self.entry();legacy.update(bucket='hold',code='E2')
        legacy['split_payment_source']['so_delivery_local']=5000
        flow=build_flow_plan.build_plan({'hold':[legacy],'hexiao_date':'2026-07-28'})
        self.assertEqual(flow_monthly.write(self.root,flow['items'],in_place=True,phase='prefill')[1],[])
        row=self.row();self.assertEqual(self.run_rows([row])[1],[])
        self.assertEqual(self.read('F2'),'9000-1000=8000');self.assertNotIn('5,000',self.read('E2'))
        row.update(bucket='auto',code='');self.assertEqual(self.run_rows([row],written=[row])[1],[])
        self.assertEqual(self.read('G2'),'是');self.assertEqual(self.read('F2'),'9000-1000=8000')

    def test_source_expansion_and_missing_delivery_date_route(self):
        import classification_expansion as E,classification_runner as R
        payment={'ar':'AR1','amount_orig':9000,'amount_local':9000,'hexiao_date':'2026-07-28','arrival_date':'2026-07-27','currency':'CNY','status':'已核销','writeoffs':{'SO1':1000},'writeoffs_local':{'SO1':1000},'orders':[{'so':'SO1','deliver':5000,'currency':'CNY'}],'sod_lines':{'SO1':[{'sod':'SOD1','deliver':5000}]}}
        rows=E.expand_payment(payment,{})
        for r in rows:r.update(flow_hits=1,flow_file='flow.xlsx',flow_sheet='流水',flow_row_no=2,flow_matched_by='三键',flow_identity={'date':'2026-07-27','payer':'测试甲','amount':9000})
        result=R.classify_records_by_year(rows,{});result['hexiao_date']='2026-07-28'
        final=build_flow_plan.finalize_plan_after_ledger(build_flow_plan.build_plan(result),{'hexiao_date':'2026-07-28','write':[],'skip':[],'conflict':[]})
        self.assertEqual(flow_monthly.write(self.root,final['items'],in_place=True,phase='status')[1],[])
        self.assertEqual(self.read('F2'),'9000-1000=8000');self.assertFalse(self.read('G2'))
if __name__=='__main__':unittest.main()



