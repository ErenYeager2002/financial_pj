"""Unmatched diagnostics expose current evidence without choosing a write row."""
import copy
import datetime as dt
import unittest
from flow_ledger import FlowLedger, annotate_records

class UnmatchedEvidenceTest(unittest.TestCase):
    def row(self, **changes):
        row=dict(file='flow.xlsx',sheet='明细',row_no=7,date=dt.date(2026,7,2),
            amount=103,form='星展',payer='甲公司',company_name='甲公司',remitter='',
            order_cell='SO26070001',prepayment=None)
        row.update(changes);return row

    def match(self,rows,**changes):
        args=dict(arrival_date='2026-07-02',amount_net=100,amount_total=106,
            customer='甲公司',order_sos=['SO26070001'])
        args.update(changes);return FlowLedger(rows).match(**args)

    def test_bank_amount_difference_is_explicit_but_never_a_match(self):
        rows=[self.row()];before=copy.deepcopy(rows);hit=self.match(rows)
        self.assertEqual(hit['hits'],0);self.assertEqual(hit['rows'],[])
        for value in ('第7行','2026-07-02','净到账','100.00','103.00','3.00'):
            self.assertIn(value,hit['diagnostic'])
        self.assertEqual(rows,before)

    def test_channel_date_difference_uses_total(self):
        hit=self.match([self.row(date=dt.date(2026,7,1),form='支付宝',amount=106)])
        self.assertEqual(hit['hits'],0)
        for value in ('2026-07-01','2026-07-02','总到账','106.00','日期不同'):
            self.assertIn(value,hit['diagnostic'])

    def test_unrelated_rows_are_not_presented_as_candidates(self):
        hit=self.match([self.row(order_cell='SO26079999',payer='其他',company_name='其他')])
        self.assertEqual(hit['hits'],0)
        self.assertNotIn('第7行',hit['diagnostic'])
        self.assertNotIn('可能缺',hit['diagnostic'])

    def test_candidate_limit_keeps_total_count(self):
        hit=self.match([self.row(row_no=i) for i in range(2,14)])
        self.assertIn('12行',hit['diagnostic']);self.assertIn('前8行',hit['diagnostic'])
        self.assertNotIn('第10行',hit['diagnostic'])

    def test_annotation_keeps_explanation_without_write_coordinates(self):
        rec=dict(ar='receipt',so='SO26070001',shoukuan_date='2026-07-02',
            hexiao_date='2026-08-02',arrival_total=100,business_arrival_total=106,customer='甲公司')
        annotate_records([rec],FlowLedger([self.row()]))
        self.assertIn('103.00',rec['flow_matched_by'])
        self.assertIsNone(rec['flow_hits']);self.assertIsNone(rec['flow_row_no'])
        self.assertFalse(rec['flow_file'])
        from build_flow_plan import plan_item_for_ar
        plan=plan_item_for_ar(rec['ar'],[rec],None)
        self.assertEqual(plan['verdict'],'hand')
        self.assertIn('103.00',plan['reason'])
        self.assertIsNone(plan['row_no'])

if __name__=='__main__':unittest.main()
