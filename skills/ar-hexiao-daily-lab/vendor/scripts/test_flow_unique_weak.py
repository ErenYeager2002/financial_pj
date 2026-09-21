"""Unique date/amount matches may write despite a different payer name."""
import unittest
import apply_flow
import build_flow_plan
import flow_ledger
from test_flow_monthly import MonthlySafetyTest

class UniqueWeakFlowTest(unittest.TestCase):
    def setUp(self):
        self.book = MonthlySafetyTest()
        self.book.setUp()
    def tearDown(self):
        self.book.tearDown()
    def entry(self):
        row = self.book.entry()
        row.update(shoukuan_date='2026-07-27', arrival_total=9000,
                   customer='不同客户乙', sales_name='不同销售', fee=0)
        flow = flow_ledger.FlowLedger.from_paths([self.book.path])
        flow_ledger.annotate_records([row], flow)
        return row
    def test_unique_weak_match_writes_carry_and_is_idempotent(self):
        row = self.entry()
        self.assertEqual(row['flow_matched_by'], '日期+金额(名字不符)')
        plan, checked = self.book.plans('2026-08-01', [row])
        self.assertEqual(plan['items'][0]['verdict'], 'write')
        final = build_flow_plan.finalize_plan_after_ledger(plan, checked)
        changes, errors = apply_flow.write_flow_items(self.book.root, final['items'], in_place=True, phase='status')
        self.assertEqual(errors, [])
        self.assertEqual(len(changes), 1)
        self.assertEqual(self.book.read('F3'), '9000-1000=8000')
        self.assertEqual(self.book.read('B3'), '测试甲')
        before = self.book.path.read_bytes()
        self.assertEqual(apply_flow.write_flow_items(self.book.root, final['items'], in_place=True, phase='status'), ([], []))
        self.assertEqual(self.book.path.read_bytes(), before)
    def test_two_weak_candidates_stay_manual(self):
        self.book.modify(lambda ws: ws.append([ws['A2'].value, '另一汇款人', 9000, '汇款', 'WX', 9000, None]))
        row = self.entry()
        self.assertEqual(row['flow_hits'], 2)
        self.assertEqual(self.book.plans('2026-07-28', [row])[0]['items'][0]['verdict'], 'hand')
    def test_unknown_basis_and_missing_location_stay_manual(self):
        for patch in ({'flow_matched_by':'日期+金额(名字不符)-unknown'}, {'flow_row_no':None, 'flow_locate':''}, {'flow_hits':0}):
            with self.subTest(patch=patch):
                row=self.entry();row.update(patch)
                self.assertEqual(self.book.plans('2026-07-28',[row])[0]['items'][0]['verdict'],'hand')
    def test_changed_identity_is_not_written(self):
        row=self.entry();plan,checked=self.book.plans('2026-07-28',[row])
        self.assertEqual(plan['items'][0]['verdict'],'write')
        final=build_flow_plan.finalize_plan_after_ledger(plan,checked)
        self.book.modify(lambda ws:setattr(ws['B2'],'value','已换另一付款方'))
        before=self.book.path.read_bytes()
        changes,errors=apply_flow.write_flow_items(self.book.root,final['items'],in_place=True,phase='status')
        self.assertFalse(changes);self.assertTrue(errors)
        self.assertEqual(self.book.path.read_bytes(),before)
    def test_missing_annual_ledger_prefills_without_marking_complete(self):
        row=self.entry();row.update(bucket='hold',code='E3')
        plan=build_flow_plan.build_plan({'hold':[row],'hexiao_date':'2026-07-28'})
        self.assertEqual(plan['items'][0]['verdict'],'write')
        final=build_flow_plan.finalize_plan_after_ledger(plan,{'hexiao_date':'2026-07-28','write':[],'skip':[],'conflict':[]})
        changes,errors=apply_flow.write_flow_items(self.book.root,final['items'],in_place=True,phase='status')
        self.assertFalse(errors);self.assertTrue(changes)
        self.assertIn('SO1',self.book.read('E2'))
        self.assertEqual(self.book.read('F2'),9000)
        self.assertIsNone(self.book.read('G2'))
