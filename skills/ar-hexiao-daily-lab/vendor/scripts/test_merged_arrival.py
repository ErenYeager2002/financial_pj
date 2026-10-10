"""Merged bank arrivals retain each AR while updating one flow row."""
import copy
import datetime as dt
from pathlib import Path
import tempfile
import unittest
import openpyxl
import apply_flow
import build_flow_plan as B
import flow_ledger as F
import flow_monthly

DAY=dt.date(2026,9,29)
ARRIVAL=dt.date(2026,9,18)

class MergedArrival(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'02_我的表副本').mkdir()
        self.path=self.root/'02_我的表副本'/'flow.xlsx'
        wb=openpyxl.Workbook();ws=wb.active;ws.title='明细'
        ws.append(['日期','公司名称','金额','收款形式','单号','预收','是否更新应收款'])
        ws.append([ARRIVAL,'合成客户',1686.68,'汇款','ZG',None,None]);wb.save(self.path);wb.close()
    def tearDown(self):self.temp.cleanup()
    def records(self):
        return [dict(ar=ar,so=so,sod=so+'D',customer='合成客户',sales_name='',currency='CNY',fee=0,
            shoukuan_date=ARRIVAL,hexiao_date=DAY,arrival_total=total,business_arrival_total=total,
            amount_local=amount,amount_orig=amount,status='手动核销',
            so_receipt_source=dict(amount_local=amount,amount_orig=amount,delivery_local=amount,
                currency='CNY',writeoff_sequence_key=[DAY.isoformat(),'HX_'+ar+'_'+so,'row_'+so,ar,so]))
            for ar,so,amount,total in [('AR1','SO1',206.36,837.44),('AR1','SO2',631.08,837.44),('AR2','SO3',849.24,849.24)]]
    def plans(self,records):
        import flow_source_receipts
        F.annotate_records(records,F.FlowLedger.from_paths([self.path]))
        rows=[]
        for r in records:
            row={**r,'bucket':'auto','case_id':r['ar']+'|'+r['so']+'|'+r['sod'],
                'split_payment_source':{'amount_local':r['amount_local'],'so_delivery_local':r['amount_local']},
                'write_currency_audit':{'currency':'CNY','amount_local':r['amount_local']},
                'flow_source_receipt':flow_source_receipts.proof(r)}
            rows.append(row)
        plan=B.build_plan({'auto':rows,'hexiao_date':DAY.isoformat()})
        final=B.finalize_plan_after_ledger(plan,{'hexiao_date':DAY.isoformat(),'write':rows,'skip':[],'conflict':[]},workspace=self.root)
        return final,rows
    def test_unique_group_writes_once_and_repeat_is_byte_identical(self):
        final,rows=self.plans(self.records())
        self.assertEqual(final['counts'],{'write':1,'hand':0,'skip':0},final['manual_items'])
        item=final['items'][0]
        self.assertEqual([m['ar'] for m in item['receipt_group']['members']],['AR1','AR2'])
        self.assertEqual({e['case_id'].split('|')[0] for e in item['monthly_entries']},{'AR1','AR2'})
        changes,errors=apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status')
        self.assertEqual(errors,[]);self.assertEqual(len(changes),1)
        wb=openpyxl.load_workbook(self.path,rich_text=True);ws=wb['明细']
        self.assertEqual(ws['F2'].value,'1686.68-206.36-631.08-849.24=0')
        self.assertEqual(ws['G2'].value,'是')
        for so in ['SO1','SO2','SO3']:self.assertIn(so,str(ws['E2'].value))
        self.assertTrue(str(ws['E2'].value).startswith('ZG'));wb.close()
        before=self.path.read_bytes()
        self.assertEqual(apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status'),([],[]))
        self.assertEqual(self.path.read_bytes(),before)
        state=flow_monthly.load_state(self.path)
        self.assertEqual(len(state['receipts']),1)
        # A later partial run cannot reclaim the same bank row under one AR.
        partial=copy.deepcopy(item);partial.pop('receipt_group');partial['source_receipts']=partial['source_receipts'][:2]
        changes,errors=apply_flow.write_flow_items(self.root,[partial],in_place=True,phase='status')
        self.assertEqual(changes,[]);self.assertTrue(errors)
        self.assertEqual(self.path.read_bytes(),before)
    def test_subset_solver_never_reuses_one_ar(self):
        from flow_merged_receipts import subsets
        self.assertEqual(subsets([('AR1',100),('AR2',100)],200),[('AR1','AR2')])

    def test_group_source_change_is_rejected_before_any_write(self):
        final,_=self.plans(self.records())
        item=copy.deepcopy(final['items'][0]);item['source_receipts'][-1]['amount']='900'
        before=self.path.read_bytes()
        changes,errors=apply_flow.write_flow_items(self.root,[item],in_place=True,phase='status')
        self.assertEqual(changes,[]);self.assertTrue(errors);self.assertEqual(self.path.read_bytes(),before)

    def test_ambiguous_member_combinations_remain_manual(self):
        records=self.records()
        for old in list(records)[2:]:
            other=copy.deepcopy(old);other['ar']='AR3';other['so']='SO4';other['sod']='SO4D';records.append(other)
        F.annotate_records(records,F.FlowLedger.from_paths([self.path]))
        self.assertTrue(all(r.get('flow_hits')!=1 for r in records))
    def test_existing_single_match_is_reserved(self):
        records=self.records();other=copy.deepcopy(records[-1])
        other.update(ar='AR3',arrival_total=1686.68,business_arrival_total=1686.68)
        records.append(other);F.annotate_records(records,F.FlowLedger.from_paths([self.path]))
        self.assertEqual(records[-1]['flow_hits'],1)
        self.assertTrue(all(r.get('flow_hits')!=1 for r in records[:-1]))

    def test_partial_ledger_completion_is_not_marked_complete(self):
        final,rows=self.plans(self.records())
        plan=B.build_plan({'auto':rows[:2],'hold':[{**rows[2],'bucket':'hold','code':'E2'}],
                           'hexiao_date':DAY.isoformat()})
        final=B.finalize_plan_after_ledger(plan,{'hexiao_date':DAY.isoformat(),'write':rows[:2],
                                              'skip':[],'conflict':[]},workspace=self.root)
        self.assertEqual(final['counts']['write'],1)
        self.assertEqual(final['items'][0]['updated_suggest'],'部分')
        self.assertEqual(final['items'][0]['red_sos'],['SO3'])

    def test_foreign_or_fee_group_is_not_implicitly_converted(self):
        for field,value in [('currency','USD'),('fee',1)]:
            records=self.records();records[-1][field]=value
            F.annotate_records(records,F.FlowLedger.from_paths([self.path]))
            self.assertTrue(all(r.get('flow_hits')!=1 for r in records))

if __name__=='__main__':unittest.main()
