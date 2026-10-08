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
    def test_blank_balance_explains_unmatched_source_and_actual_difference(self):
        def existing(ws):
            ws['C2']=100.43;ws['E2']='WX SO1 SO2';ws['F2']=None
        self.modify(existing)
        row=self.row('SO1',100);row['flow_identity']['amount']=100.43
        before=self.path.read_bytes()
        flow=build_flow_plan.build_plan({'hold':[row],'hexiao_date':'2026-07-28'})
        final=build_flow_plan.finalize_plan_after_ledger(flow,{'hexiao_date':'2026-07-28','write':[],'skip':[],'conflict':[]},workspace=self.root)
        reason=' '.join(r['reason'] for r in final['manual_items'])
        for expected in ('100.43','100.00','0.43','SO2'):
            self.assertIn(expected,reason)
        self.assertEqual(self.path.read_bytes(),before)

    def test_same_month_existing_explicit_deduction_does_not_require_same_day(self):
        def existing(ws):
            ws['E2']='WX SO1 1000\nSO2 2000'
            ws['F2']='9000-1000-2000=6000'
        self.modify(existing)
        row=self.row('SO1',1000,day='2026-07-29')
        flow=build_flow_plan.build_plan({'hold':[row],'hexiao_date':'2026-07-29'})
        checked={'hexiao_date':'2026-07-29','write':[],'skip':[],'conflict':[]}
        final=build_flow_plan.finalize_plan_after_ledger(flow,checked,workspace=self.root)
        self.assertEqual(final['manual_items'],[])
        changes,errors=flow_monthly.write(self.root,final['items'],in_place=True,phase='status')
        self.assertEqual(errors,[])
        self.assertEqual(self.read('F2'),'9000-1000-2000=6000')
        repeated=build_flow_plan.finalize_plan_after_ledger(flow,checked,workspace=self.root)
        self.assertEqual(flow_monthly.write(self.root,repeated['items'],in_place=True,phase='status'),([],[]))

    def test_adoption_rejects_substring_amount_and_different_month(self):
        for shown,day in [('11000','2026-07-29'),('1000','2026-08-01')]:
            with self.subTest(shown=shown,day=day):
                def existing(ws):
                    ws['E2']='WX SO1 '+shown+'\nSO2 2000'
                    ws['F2']='9000-1000-2000=6000'
                self.modify(existing)
                before=self.path.read_bytes()
                row=self.row('SO1',1000,day=day)
                flow=build_flow_plan.build_plan({'hold':[row],'hexiao_date':day})
                final=build_flow_plan.finalize_plan_after_ledger(flow,{'hexiao_date':day,'write':[],'skip':[],'conflict':[]},workspace=self.root)
                self.assertTrue(final['manual_items'])
                self.assertEqual(self.path.read_bytes(),before)

    def test_current_fetch_prefix_recovers_existing_balance_without_charging_prior_again(self):
        def existing(ws):
            ws['E2']='WX SO1 SO2';ws['F2']=None
        self.modify(existing)
        row=self.row('SO2',2000,day='2026-07-29')
        row['flow_source_receipt']['event']=['2026-07-29','HX2','R2','AR1','SO2']
        def event(so,amount,day,ident):
            return dict(ar='AR1',so=so,amount=amount,amount_local=amount,currency='CNY',date=day,record_id='HX'+ident,rowid='R'+ident,disposition='kept',revoked=False)
        row['duplicate_writeoff_audit']={'status':'normal','records':[event('SO1',7000,'2026-07-28','1'),event('SO2',2000,'2026-07-29','2')]}
        checked={'hexiao_date':'2026-07-29','write':[],'skip':[],'conflict':[]}
        def finalize(record):
            flow=build_flow_plan.build_plan({'hold':[record],'hexiao_date':'2026-07-29'})
            self.assertEqual(len(flow['items'][0]['source_receipts']),1)
            return build_flow_plan.finalize_plan_after_ledger(flow,checked,workspace=self.root)
        future=copy.deepcopy(row);future['duplicate_writeoff_audit']['records'][0]['date']='2026-07-30'
        self.assertTrue(finalize(future)['manual_items'])
        changed=copy.deepcopy(row);changed['duplicate_writeoff_audit']['records'][1]['amount_local']=2001
        self.assertTrue(finalize(changed)['manual_items'])
        final=finalize(row);self.assertEqual(final['manual_items'],[])
        self.assertEqual(flow_monthly.write(self.root,final['items'],in_place=True,phase='status')[1],[])
        self.assertEqual(self.read('F2'),'9000-7000-2000=0')
        final=finalize(row)
        self.assertEqual(flow_monthly.write(self.root,final['items'],in_place=True,phase='status'),([],[]))

    def test_visible_running_balance_prefix_preserves_unassigned_later_deduction(self):
        row=self.row('SO2',1000,day='2026-07-29')
        row['flow_source_receipt']['event']=['2026-07-29','HX2','R2','AR1','SO2']
        row['duplicate_writeoff_audit']={'status':'normal','records':[
            dict(ar='AR1',so='SO1',amount=7000,amount_local=7000,currency='CNY',date='2026-07-28',record_id='HX1',rowid='R1',disposition='kept'),
            dict(ar='AR1',so='SO2',amount=1000,amount_local=1000,currency='CNY',date='2026-07-29',record_id='HX2',rowid='R2',disposition='kept')]}
        checked={'hexiao_date':'2026-07-29','write':[],'skip':[],'conflict':[]}
        def final():return build_flow_plan.finalize_plan_after_ledger(build_flow_plan.build_plan({'hold':[row],'hexiao_date':'2026-07-29'}),checked,workspace=self.root)
        def initial(ws):ws['E2']='WX SO1 SO2 追加 SO3';ws['F2']='1000-999=1'
        self.modify(initial)
        plan=final();self.assertEqual(plan['manual_items'],[])
        self.assertEqual(flow_monthly.write(self.root,plan['items'],in_place=True,phase='status')[1],[])
        self.assertEqual(self.read('F2'),'1000-999=1')
        self.assertIn('SO3',str(self.read('E2')))
        self.assertEqual(flow_monthly.write(self.root,final()['items'],in_place=True,phase='status'),([],[]))
        self.modify(lambda ws:None)
        self.assertEqual(final()['manual_items'],[])
        self.assertEqual(flow_monthly.write(self.root,final()['items'],in_place=True,phase='status')[1],[])
        # The next date supplies the previously anonymous final deduction.
        later=self.row('SO3',999,day='2026-07-30')
        later['flow_source_receipt']['event']=['2026-07-30','HX3','R3','AR1','SO3']
        later['duplicate_writeoff_audit']=copy.deepcopy(row['duplicate_writeoff_audit'])
        later['duplicate_writeoff_audit']['records'].append(dict(ar='AR1',so='SO3',amount=999,amount_local=999,currency='CNY',date='2026-07-30',record_id='HX3',rowid='R3',disposition='kept'))
        later_flow=build_flow_plan.build_plan({'hold':[later],'hexiao_date':'2026-07-30'})
        later_checked={'hexiao_date':'2026-07-30','write':[],'skip':[],'conflict':[]}
        changed=copy.deepcopy(later)
        for field in ('amount','amount_local'):
            changed['duplicate_writeoff_audit']['records'][0][field]=6999
            changed['duplicate_writeoff_audit']['records'][1][field]=1001
        before=self.path.read_bytes()
        changed_final=build_flow_plan.finalize_plan_after_ledger(build_flow_plan.build_plan({'hold':[changed],'hexiao_date':'2026-07-30'}),later_checked,workspace=self.root)
        self.assertTrue(changed_final['manual_items'])
        self.assertEqual(self.path.read_bytes(),before)
        later_final=build_flow_plan.finalize_plan_after_ledger(later_flow,later_checked,workspace=self.root)
        self.assertEqual(later_final['manual_items'],[])
        self.assertEqual(flow_monthly.write(self.root,later_final['items'],in_place=True,phase='status')[1],[])
        self.assertEqual(flow_monthly.parsed_balance(self.read('F2'))['remaining'],flow_monthly.money(1))
        self.modify(lambda ws:None) # saved output without metadata must still match
        later_repeat=build_flow_plan.finalize_plan_after_ledger(later_flow,later_checked,workspace=self.root)
        self.assertEqual(later_repeat['manual_items'],[])
        self.assertEqual(flow_monthly.write(self.root,later_repeat['items'],in_place=True,phase='status')[1],[])
        self.assertEqual(flow_monthly.parsed_balance(self.read('F2'))['remaining'],flow_monthly.money(1))
        for text,balance in [('WX SO1 SO2 追加 SO3','1100-1099=1'),('WX SO1 SO2 SO2 追加 SO3','1000-999=1')]:
            def invalid(ws):ws['E2']=text;ws['F2']=balance
            self.modify(invalid);before=self.path.read_bytes()
            self.assertTrue(final()['manual_items']);self.assertEqual(self.path.read_bytes(),before)

    def test_partial_prefix_requires_visible_exact_balance_and_survives_metadata_loss(self):
        row=self.row('SO2',1998.92,day='2026-07-29')
        row['flow_source_receipt']['event']=['2026-07-29','HX2','R2','AR1','SO2']
        row['duplicate_writeoff_audit']={'status':'normal','records':[
            dict(ar='AR1',so='SO1',amount=7000,amount_local=7000,currency='CNY',date='2026-07-28',record_id='HX1',rowid='R1',disposition='kept'),
            dict(ar='AR1',so='SO2',amount=1998.92,amount_local=1998.92,currency='CNY',date='2026-07-29',record_id='HX2',rowid='R2',disposition='kept')]}
        checked={'hexiao_date':'2026-07-29','write':[],'skip':[],'conflict':[]}
        def final():
            return build_flow_plan.finalize_plan_after_ledger(build_flow_plan.build_plan({'hold':[row],'hexiao_date':'2026-07-29'}),checked,workspace=self.root)
        for raw in (None,'2000-1998=2'):
            def invalid(ws):ws['E2']='WX SO1 SO2';ws['F2']=raw
            self.modify(invalid)
            before=self.path.read_bytes()
            self.assertTrue(final()['manual_items'])
            self.assertEqual(self.path.read_bytes(),before)
        def valid(ws):ws['E2']='WX SO1 SO2';ws['F2']='2000-1998.92=1.08'
        self.modify(valid)
        plan=final();self.assertEqual(plan['manual_items'],[])
        self.assertEqual(flow_monthly.write(self.root,plan['items'],in_place=True,phase='status')[1],[])
        self.assertEqual(flow_monthly.parsed_balance(self.read('F2'))['remaining'],flow_monthly.money('1.08'))
        self.modify(lambda ws:None)
        plan=final();self.assertEqual(plan['manual_items'],[])
        self.assertEqual(flow_monthly.write(self.root,plan['items'],in_place=True,phase='status')[1],[])
        self.assertEqual(flow_monthly.parsed_balance(self.read('F2'))['remaining'],flow_monthly.money('1.08'))
        self.assertEqual(flow_monthly.write(self.root,final()['items'],in_place=True,phase='status'),([],[]))

    def test_same_so_multiple_source_events_survive_workbook_without_metadata(self):
        def existing(ws):ws['E2']='WX SO1';ws['F2']=None
        self.modify(existing)
        row=self.row('SO1',2000,day='2026-07-29')
        row['flow_source_receipt']['event']=['2026-07-29','HX2','R2','AR1','SO1']
        row['duplicate_writeoff_audit']={'status':'normal','records':[
            dict(ar='AR1',so='SO1',amount=7000,amount_local=7000,currency='CNY',date='2026-07-28',record_id='HX1',rowid='R1',disposition='kept'),
            dict(ar='AR1',so='SO1',amount=2000,amount_local=2000,currency='CNY',date='2026-07-29',record_id='HX2',rowid='R2',disposition='kept')]}
        checked={'hexiao_date':'2026-07-29','write':[],'skip':[],'conflict':[]}
        def final():return build_flow_plan.finalize_plan_after_ledger(build_flow_plan.build_plan({'hold':[row],'hexiao_date':'2026-07-29'}),checked,workspace=self.root)
        plan=final();self.assertEqual(plan['manual_items'],[])
        self.assertEqual(flow_monthly.write(self.root,plan['items'],in_place=True,phase='status')[1],[])
        self.assertEqual(self.read('F2'),'9000-7000-2000=0')
        self.modify(lambda ws:None) # Excel-style save discards unsupported custom XML.
        import zipfile
        with zipfile.ZipFile(self.path) as archive:self.assertNotIn(flow_monthly.PART,archive.namelist())
        plan=final();self.assertEqual(plan['manual_items'],[])
        self.assertEqual(flow_monthly.write(self.root,plan['items'],in_place=True,phase='status')[1],[])
        self.assertEqual(self.read('F2'),'9000-7000-2000=0')

    def test_cross_month_existing_chain_uses_source_periods_without_rededucting(self):
        def existing(ws):
            ws['E2']='WX SO1 1000 转8月';ws['F2']='9000-1000=8000'
            ws.append(['2026-08-01','测试甲',8000,'冲预收','WX SO2 3000 SO3 5000','8000-3000-5000=0',None])
        self.modify(existing)
        row=self.row('SO3',5000,day='2026-08-02')
        row['flow_source_receipt']['event']=['2026-08-02','HX3','R3','AR1','SO3']
        raw=[]
        for so,amount,day,ident in [('SO1',1000,'2026-07-28','1'),('SO2',3000,'2026-08-01','2'),('SO3',5000,'2026-08-02','3')]:
            raw.append(dict(ar='AR1',so=so,amount=amount,amount_local=amount,currency='CNY',date=day,record_id='HX'+ident,rowid='R'+ident,disposition='kept'))
        row['duplicate_writeoff_audit']={'status':'normal','records':raw}
        checked={'hexiao_date':'2026-08-02','write':[],'skip':[],'conflict':[]}
        flow=build_flow_plan.build_plan({'hold':[row],'hexiao_date':'2026-08-02'})
        self.modify(lambda ws:setattr(ws['F2'],'value','9000-900=8100'))
        before=self.path.read_bytes()
        invalid=build_flow_plan.finalize_plan_after_ledger(flow,checked,workspace=self.root)
        self.assertTrue(invalid['manual_items'])
        self.assertEqual(self.path.read_bytes(),before)
        self.modify(lambda ws:setattr(ws['F2'],'value','9000-1000=8000'))
        final=build_flow_plan.finalize_plan_after_ledger(flow,checked,workspace=self.root)
        self.assertEqual(final['manual_items'],[])
        self.assertEqual(flow_monthly.write(self.root,final['items'],in_place=True,phase='status')[1],[])
        self.assertEqual(self.read('F2'),'9000-1000=8000');self.assertEqual(self.read('F3'),'8000-3000-5000=0')
        repeat=build_flow_plan.finalize_plan_after_ledger(flow,checked,workspace=self.root)
        self.assertEqual(flow_monthly.write(self.root,repeat['items'],in_place=True,phase='status'),([],[]))

    def test_missing_ledger_deducts_and_replay_does_not(self):
        rows=[self.row()];changes,errors=self.run_rows(rows)
        self.assertEqual(errors,[]);self.assertTrue(changes)
        self.assertEqual(self.read('F2'),'9000-1000=8000');self.assertFalse(self.read('G2'))
        before=self.path.read_bytes();self.assertEqual(self.run_rows(rows),([],[]));self.assertEqual(before,self.path.read_bytes())
    def test_multiple_sod_views_deduct_so_once(self):
        a=self.row();b=copy.deepcopy(a);b['sod']='OTHER';b['case_id']+='OTHER'
        self.assertEqual(self.run_rows([a,b])[1],[]);self.assertEqual(self.read('F2'),'9000-1000=8000')
    def test_repeated_sod_views_recover_blank_balance_once(self):
        def existing(ws):
            ws['C2'] = 3000
            ws['E2'] = 'WX\nSO1\nSO2'
            ws['F2'] = None
        self.modify(existing)
        first = self.row('SO1', 1000)
        duplicate = copy.deepcopy(first)
        duplicate['sod'] = 'OTHER'
        duplicate['case_id'] += 'OTHER'
        second = self.row('SO2', 2000)
        rows = [first, duplicate, second]
        for row in rows:
            row['flow_identity']['amount'] = 3000
        plan = build_flow_plan.build_plan({'hold': rows, 'hexiao_date': '2026-07-28'})
        self.assertEqual(len(plan['items'][0]['source_receipts']), 2)
        changes, errors = self.run_rows(rows)
        self.assertEqual(errors, [])
        self.assertTrue(changes)
        self.assertEqual(self.read('F2'), '3000-1000-2000=0')

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
    def test_fx_receipt_uses_flow_formula_rate_and_preserves_original_amount(self):
        import datetime as dt, flow_source_receipts
        rec = {'ar': 'AR1', 'so': 'SO1', 'hexiao_date': '2026-07-28', 'status': '自动核销',
               'so_receipt_source': {'amount_orig': 60, 'amount_local': 450,
                                     'currency': '美元USD',
                                     'writeoff_sequence_key': ['2026-07-28', 'HX1', 'R1']}}
        proof = flow_source_receipts.proof(rec)
        self.assertEqual(proof['amount_orig'], '60')
        second = {**proof, 'so': 'SO2', 'amount_orig': '40', 'amount': '300',
                  'event': ['2026-07-28', 'HX2', 'R2']}
        item = {'ar': 'AR1', 'matched_by': '三键(原币公式)',
                'identity': {'amount': 700, 'formula_orig_amount': 100, 'formula_rate': 7},
                'source_receipts': [proof, second]}
        entries = flow_source_receipts.allocations(item, dt.date(2026, 7, 28))
        self.assertEqual([entry['amount'] for entry in entries], ['420', '280'])
        self.assertIsNotNone(flow_monthly.current_source_balance_candidate(
            item, entries, dt.date(2026, 7, 28)))

    def test_current_balance_reconciles_existing_source_receipts(self):
        def existing(ws):
            ws['E2'] = 'WX\nSO1\nSO2'
            ws['F2'] = '还剩：6000'
            ws['G2'] = '是'
        self.modify(existing)
        rows = [self.row('SO1', 1000), self.row('SO2', 2000)]
        changes, errors = self.run_rows(rows)
        self.assertEqual(errors, [])
        self.assertEqual(self.read('F2'), '9000-1000-2000=6000')
        before = self.path.read_bytes()
        self.assertEqual(self.run_rows(rows), ([], []))
        self.assertEqual(self.path.read_bytes(), before)

    def test_blank_balance_rebuilds_fully_covered_source_receipts(self):
        def existing(ws):
            ws['C2'] = 3000
            ws['E2'] = 'WX\nSO1\nSO2'
            ws['F2'] = None
            ws['G2'] = '是'
        self.modify(existing)
        rows = [self.row('SO1', 1000), self.row('SO2', 2000)]
        for row in rows:
            row['flow_identity']['amount'] = 3000
        changes, errors = self.run_rows(rows)
        self.assertEqual(errors, [])
        self.assertEqual(self.read('F2'), '3000-1000-2000=0')

    def test_full_source_receipt_with_extra_delivery_text_registers_same_month(self):
        def existing(ws):
            ws['C2'] = 3000
            ws['E2'] = 'WX\nSO1\nSO9'
            ws['F2'] = None
        self.modify(existing)
        row = self.row('SO1', 3000)
        row['flow_identity']['amount'] = 3000
        changes, errors = self.run_rows([row])
        self.assertEqual(errors, [])
        self.assertTrue(changes)
        self.assertEqual(self.read('F2'), '3000-3000=0')
        self.assertIn('SO9', self.read('E2'))
        self.assertIn('SO1  3,000.00', self.read('E2'))

    def test_full_source_receipt_cross_month_keeps_unrelated_order_text(self):
        def existing(ws):
            ws['C2'] = 3000
            ws['E2'] = 'WXSO9 SO1'
            ws['F2'] = None
        self.modify(existing)
        row = self.row('SO1', 3000, day='2026-08-01')
        row['flow_identity']['amount'] = 3000
        changes, errors = self.run_rows([row], day='2026-08-01')
        self.assertEqual(errors, [])
        self.assertTrue(changes)
        self.assertIn('SO9', self.read('E2'))
        self.assertEqual(self.read('F3'), '3000-3000=0')
        self.assertIn('SO1  3,000.00', self.read('E3'))

    def test_legacy_deduction_matching_source_is_moved_to_posting_month(self):
        def existing(ws):
            ws['E2'] = 'WX\nSO1\nSO2\nSO2'
            ws['F2'] = '还剩：6000'
        self.modify(existing)
        rows = [self.row('SO1', 1000, day='2026-08-01'),
                self.row('SO2', 2000, day='2026-08-01')]
        changes, errors = self.run_rows(rows, day='2026-08-01')
        self.assertEqual(errors, [])
        self.assertTrue(changes)
        self.assertEqual(self.read('F2'), '9000=9000')
        self.assertNotIn('SO1', self.read('E2'))
        self.assertEqual(self.read('C3'), 9000)
        self.assertEqual(self.read('F3'), '9000-1000-2000=6000')
        self.assertIn('SO1  1,000.00', self.read('E3'))
        self.assertIn('SO2  2,000.00', self.read('E3'))
        before = self.path.read_bytes()
        self.assertEqual(self.run_rows(rows, day='2026-08-01'), ([], []))
        self.assertEqual(self.path.read_bytes(), before)

    def test_unreconciled_balance_keeps_manual_guard(self):
        def existing(ws):
            ws['E2'] = 'WX\nSO1\nSO2'
            ws['F2'] = '还剩：6100'
        self.modify(existing)
        before = self.path.read_bytes()
        changes, errors = self.run_rows([self.row('SO1', 1000), self.row('SO2', 2000)])
        self.assertEqual(changes, [])
        self.assertTrue(errors)
        self.assertEqual(self.path.read_bytes(), before)

    def test_blank_balance_with_incomplete_source_stays_manual(self):
        def existing(ws):
            ws['E2'] = 'WX\nSO1'
            ws['F2'] = None
        self.modify(existing)
        before = self.path.read_bytes()
        changes, errors = self.run_rows([self.row('SO1', 1000)])
        self.assertEqual(changes, [])
        self.assertTrue(errors)
        self.assertEqual(self.path.read_bytes(), before)

    def test_unlisted_source_so_cannot_adopt_existing_balance(self):
        def existing(ws):
            ws['E2'] = 'WX\nSO1\nSO3'
            ws['F2'] = '还剩：6000'
        self.modify(existing)
        before = self.path.read_bytes()
        changes, errors = self.run_rows([self.row('SO1', 1000), self.row('SO2', 2000)])
        self.assertEqual(changes, [])
        self.assertTrue(errors)
        self.assertEqual(self.path.read_bytes(), before)

if __name__=='__main__':unittest.main()



