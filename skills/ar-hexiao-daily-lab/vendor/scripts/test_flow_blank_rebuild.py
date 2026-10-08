"""Complete fetched SO coverage permits a positive blank-balance rebuild."""
import copy
import unittest
import build_flow_plan
import flow_monthly
from test_flow_source_receipts import SourceReceiptFlow

class BlankRebuild(unittest.TestCase):
    setUp=SourceReceiptFlow.setUp
    tearDown=SourceReceiptFlow.tearDown
    entry=SourceReceiptFlow.entry
    row=SourceReceiptFlow.row
    read=SourceReceiptFlow.read
    modify=SourceReceiptFlow.modify

    def setup_case(self, cross=True):
        day='2026-08-05' if cross else '2026-07-31'
        def initial(ws):
            ws['A2']='2026-07-30';ws['C2']=18807.85;ws['E2']='JZ SO1 SO2 SO3';ws['F2']=None
        self.modify(initial)
        row=self.row('SO3',1850.43,day=day)
        row['flow_identity'].update(amount=18807.85,date='2026-07-30')
        row['flow_source_receipt']['event']=[day,'HX3','R3','AR1','SO3']
        row['duplicate_writeoff_audit']={'status':'normal','records':[
            dict(ar='AR1',so=so,amount=amount,amount_local=amount,currency='CNY',date=date,
                 record_id='HX'+i,rowid='R'+i,disposition='kept')
            for so,amount,date,i in [('SO1',16417,'2026-07-30','1'),('SO2',540.21,'2026-07-30','2'),('SO3',1850.43,day,'3')]]}
        return row,day

    def final(self,row,day):
        return build_flow_plan.finalize_plan_after_ledger(
            build_flow_plan.build_plan({'hold':[row],'hexiao_date':day}),
            {'hexiao_date':day,'write':[],'skip':[],'conflict':[]},workspace=self.root)

    def test_cross_month_positive_remainder_and_repeat(self):
        row,day=self.setup_case()
        final=self.final(row,day);self.assertEqual(final['manual_items'],[])
        self.assertEqual(flow_monthly.write(self.root,final['items'],in_place=True,phase='status')[1],[])
        self.assertEqual(self.read('F2'),'18807.85-16417-540.21=1850.64')
        self.assertEqual(self.read('F3'),'1850.64-1850.43=0.21')
        self.assertEqual(self.read('C3'),1850.64)
        self.assertNotIn('SO3',str(self.read('E2')))
        self.assertIn('SO1',str(self.read('E2')))
        self.assertIn('SO3',str(self.read('E3')))
        for discard_metadata in (False,True):
            if discard_metadata:self.modify(lambda ws:None)
            again=self.final(row,day);self.assertEqual(again['manual_items'],[])
            self.assertEqual(flow_monthly.write(self.root,again['items'],in_place=True,phase='status')[1],[])
            self.assertEqual(self.read('F3'),'1850.64-1850.43=0.21')
            self.assertIsNone(self.read('C4'))

    def test_same_month_positive_remainder(self):
        row,day=self.setup_case(False)
        final=self.final(row,day);self.assertEqual(final['manual_items'],[])
        self.assertEqual(flow_monthly.write(self.root,final['items'],in_place=True,phase='status')[1],[])
        self.assertEqual(self.read('F2'),'18807.85-16417-540.21-1850.43=0.21')
        self.assertEqual(flow_monthly.write(self.root,self.final(row,day)['items'],in_place=True,phase='status'),([],[]))

    def test_incomplete_future_conflicting_or_intermediate_sources_preserve_workbook(self):
        for kind in ('missing','future','conflict','intermediate','extra_so','overdraw'):
            with self.subTest(kind=kind):
                row,day=self.setup_case()
                records=row['duplicate_writeoff_audit']['records']
                if kind=='missing':records.pop(0)
                if kind=='future':records[0]['date']='2026-08-06'
                if kind=='conflict':records.append({**records[0],'amount_local':16416})
                if kind=='intermediate':records[1]['date']='2026-08-01'
                if kind=='extra_so':self.modify(lambda ws:setattr(ws['E2'],'value','JZ SO1 SO2 SO3 SO4'))
                if kind=='overdraw':records[0]['amount_local']=19000
                before=self.path.read_bytes()
                self.assertTrue(self.final(row,day)['manual_items'])
                self.assertEqual(self.path.read_bytes(),before)

    def test_full_source_does_not_claim_unrelated_future_same_amount_carry(self):
        def initial(ws):
            ws['E2']='WX SO1';ws['F2']=None
            ws.append(['2026-09-07','测试甲',9000,'冲预收','WX SOOTHER 9000','9000-9000=0',None])
        self.modify(initial)
        row=self.row('SO1',9000,day='2026-08-05')
        row['flow_source_receipt']['event']=['2026-08-05','HX1','R1','AR1','SO1']
        row['duplicate_writeoff_audit']={'status':'normal','records':[
            dict(ar='AR1',so='SO1',amount=9000,amount_local=9000,currency='CNY',
                 date='2026-08-05',record_id='HX1',rowid='R1',disposition='kept')]}
        final=self.final(row,'2026-08-05');self.assertEqual(final['manual_items'],[])
        self.assertEqual(flow_monthly.write(self.root,final['items'],in_place=True,phase='status')[1],[])
        self.assertEqual(self.read('F3'),'9000-9000=0')
        self.assertIn('SO1',str(self.read('E3')))
        self.assertEqual(self.read('E4'),'WX SOOTHER 9000')
        self.assertEqual(self.read('F4'),'9000-9000=0')
        self.modify(lambda ws:None)
        final=self.final(row,'2026-08-05');self.assertEqual(final['manual_items'],[])
        self.assertEqual(flow_monthly.write(self.root,final['items'],in_place=True,phase='status')[1],[])
        self.assertIsNone(self.read('F5'))

    def test_future_carry_not_excluded_without_complete_disjoint_source_proof(self):
        for mode in ('same_order','partial','no_audit','explicit_transfer'):
            with self.subTest(mode=mode):
                def initial(ws):
                    ws['E2']='WX SO1'+(' 转9月' if mode=='explicit_transfer' else '')
                    ws['F2']=None
                    ws.append(['2026-09-07','测试甲',9000,'冲预收',
                               'WX SO1 9000' if mode=='same_order' else 'WX SOOTHER 9000','9000-9000=0',None])
                # Reset workbook between variants, not append to a previous case.
                self.tearDown();self.setUp();self.modify(initial)
                amount=8000 if mode=='partial' else 9000
                row=self.row('SO1',amount,day='2026-08-05')
                row['flow_source_receipt']['event']=['2026-08-05','HX1','R1','AR1','SO1']
                if mode!='no_audit':
                    row['duplicate_writeoff_audit']={'status':'normal','records':[
                        dict(ar='AR1',so='SO1',amount=amount,amount_local=amount,currency='CNY',
                             date='2026-08-05',record_id='HX1',rowid='R1',disposition='kept')]}
                before=self.path.read_bytes()
                self.assertTrue(self.final(row,'2026-08-05')['manual_items'])
                self.assertEqual(self.path.read_bytes(),before)

    def test_month_only_note_uses_complete_source_date_and_preserves_audit(self):
        for note in ('核销在7月','核销在6月'):
            self.tearDown();self.setUp()
            self.modify(lambda ws:(setattr(ws['E2'],'value','WX SO1'),setattr(ws['F2'],'value',note)))
            row=self.row('SO1',9000,day='2026-08-05')
            row['flow_source_receipt']['event']=['2026-08-05','HX1','R1','AR1','SO1']
            row['duplicate_writeoff_audit']={'status':'normal','records':[
                dict(ar='AR1',so='SO1',amount=9000,amount_local=9000,currency='CNY',
                     date='2026-08-05',record_id='HX1',rowid='R1',disposition='kept')]}
            plan=self.final(row,'2026-08-05');self.assertEqual(plan['manual_items'],[])
            changes,errors=flow_monthly.write(self.root,plan['items'],in_place=True,phase='status')
            self.assertEqual(errors,[]);self.assertEqual(changes[0]['原预收备注'],note)
            self.assertEqual(self.read('F3'),'9000-9000=0')
            self.assertNotIn('核销在',str(self.read('F2')))
            self.assertEqual(str(self.read('A3'))[:10],'2026-08-05')
            self.assertEqual(flow_monthly.write(self.root,self.final(row,'2026-08-05')['items'],in_place=True,phase='status'),([],[]))

    def test_note_requires_exact_full_source_and_recognized_text(self):
        for mode in ('unrecognized','partial','no_audit','unmatched_so'):
            self.tearDown();self.setUp()
            note='已转7月待核' if mode=='unrecognized' else '核销在7月'
            self.modify(lambda ws:(setattr(ws['E2'],'value','WX SO1 SO2' if mode=='unmatched_so' else 'WX SO1'),setattr(ws['F2'],'value',note)))
            amount=8999 if mode=='partial' else 9000
            row=self.row('SO1',amount,day='2026-08-05')
            row['flow_source_receipt']['event']=['2026-08-05','HX1','R1','AR1','SO1']
            if mode!='no_audit':
                row['duplicate_writeoff_audit']={'status':'normal','records':[
                    dict(ar='AR1',so='SO1',amount=amount,amount_local=amount,currency='CNY',
                         date='2026-08-05',record_id='HX1',rowid='R1',disposition='kept')]}
            before=self.path.read_bytes()
            self.assertTrue(self.final(row,'2026-08-05')['manual_items'])
            self.assertEqual(self.path.read_bytes(),before)

    def test_month_note_accepts_whole_single_parent_without_raw_hx(self):
        self.modify(lambda ws:(setattr(ws['E2'],'value','WX SO1'),setattr(ws['F2'],'value','核销在7月')))
        row=self.row('SO1',9000,day='2026-08-05')
        row['flow_source_receipt']['event']=['2026-08-05','SINGLE_ORDER_PARENT|AR1|SO1','','AR1','SO1']
        row.pop('duplicate_writeoff_audit',None)
        plan=self.final(row,'2026-08-05');self.assertEqual(plan['manual_items'],[])
        changes,errors=flow_monthly.write(self.root,plan['items'],in_place=True,phase='status')
        self.assertEqual(errors,[]);self.assertEqual(self.read('F3'),'9000-9000=0')
        self.assertEqual(flow_monthly.write(self.root,self.final(row,'2026-08-05')['items'],in_place=True,phase='status'),([],[]))

    def test_month_note_does_not_accept_delivery_estimate_as_explicit_parent(self):
        self.modify(lambda ws:(setattr(ws['E2'],'value','WX SO1'),setattr(ws['F2'],'value','核销在7月')))
        row=self.row('SO1',9000,day='2026-08-05')
        row['flow_source_receipt']['event']=['2026-08-05','DELIVERY_FALLBACK|AR1|SO1','','AR1','SO1']
        row.pop('duplicate_writeoff_audit',None)
        before=self.path.read_bytes();self.assertTrue(self.final(row,'2026-08-05')['manual_items'])
        self.assertEqual(self.path.read_bytes(),before)
