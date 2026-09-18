import copy
import unittest
import flow_monthly
from test_flow_monthly import MonthlySafetyTest

class OrderOnlyTest(MonthlySafetyTest):
    def pending(self):
        row=self.entry();row.update(bucket='hold',code='E2')
        import build_flow_plan
        plan=build_flow_plan.build_plan({'hold':[row],'hexiao_date':'2026-07-28'})
        return flow_monthly.finalize(plan['items'],{'hexiao_date':'2026-07-28','write':[],'skip':[],'conflict':[]})

    def test_prefill_preserves_balance_status_and_later_posting(self):
        items=self.pending()
        self.assertTrue(items[0]['order_only'])
        self.assertEqual(items[0]['verdict'],'write')
        before=[self.read(c) for c in ('A2','B2','C2','D2','F2','G2')]
        changes,errors=flow_monthly.write(self.root,items,in_place=True,phase='status')
        self.assertEqual(errors,[]);self.assertEqual(len(changes),1)
        self.assertIn('SO1',self.read('E2'))
        self.assertEqual([self.read(c) for c in ('A2','B2','C2','D2','F2','G2')],before)
        data=self.path.read_bytes()
        self.assertEqual(flow_monthly.write(self.root,items,in_place=True,phase='status'),([],[]))
        self.assertEqual(self.path.read_bytes(),data)
        changes,errors=self.run_items('2026-07-29',[self.entry(amount=1000)])
        self.assertEqual(errors,[]);self.assertTrue(changes)
        self.assertEqual(self.read('F2'),'9000-1000=8000')
        self.assertEqual(self.read('G2'),'是')

    def test_blank_balance_stays_blank_until_posting(self):
        self.modify(lambda ws:setattr(ws['F2'],'value',None))
        self.assertEqual(flow_monthly.write(self.root,self.pending(),in_place=True,phase='status')[1],[])
        self.assertIsNone(self.read('F2'));self.assertIsNone(self.read('G2'))
        self.assertEqual(self.run_items('2026-07-29',[self.entry(amount=1000)])[1],[])
        self.assertEqual(self.read('F2'),'9000-1000=8000')

    def test_existing_completed_status_is_not_overwritten(self):
        self.modify(lambda ws:setattr(ws['G2'],'value','是'))
        before=self.path.read_bytes()
        changes,errors=flow_monthly.write(self.root,self.pending(),in_place=True,phase='status')
        self.assertFalse(changes);self.assertTrue(errors);self.assertEqual(self.path.read_bytes(),before)

    def test_other_holds_are_not_prefilled(self):
        items=self.pending();items[0]['so_outcomes'][0]['codes']=['E7']
        flow_monthly.finalize(items,{'hexiao_date':'2026-07-28','write':[],'skip':[],'conflict':[]})
        self.assertEqual(items[0]['verdict'],'skip');self.assertNotIn('order_only',items[0])
