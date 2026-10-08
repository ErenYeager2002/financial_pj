"""Channel-only gross receipt fallback with strict identity and amount gates."""
import copy
import datetime as dt
import unittest
from flow_ledger import FlowLedger, annotate_records
from build_flow_plan import AUTO_MATCH_BASES

class ChannelGrossTest(unittest.TestCase):
    def row(self, **changes):
        r=dict(file='flow.xlsx',sheet='明细',row_no=2,date=dt.date(2026,7,21),
               company_name='王雄',remitter='王雄',payer='王雄',amount=500,
               form='甲骨易支付宝',order_cell='WXSO26070387',prepayment=None)
        r.update(changes);return r

    def match(self, rows, **changes):
        args=dict(arrival_date='2026-07-21',amount_net=497,amount_total=500,fee=3,
                  sales_name='王雄',order_sos=['SO26070387'])
        args.update(changes)
        return FlowLedger(rows).match(**args)

    def test_channel_and_identity_gates(self):
        for channel in ('甲骨易微信','甲骨易支付宝'):
            for sales,order in [('王雄',''),('','WXSO26070387')]:
                with self.subTest(channel=channel,sales=sales):
                    row=self.row(form=channel,order_cell=order)
                    before=copy.deepcopy(row)
                    hit=self.match([row],sales_name=sales)
                    self.assertEqual(hit['hits'],1)
                    self.assertIn(hit['matched_by'],AUTO_MATCH_BASES)
                    self.assertEqual(row,before)
        for changes,args in [({'form':'汇款'},{}),({'form':'星展'},{}),
                             ({'date':dt.date(2026,7,20)},{}),
                             ({'company_name':'客户','payer':'客户','remitter':'客户','order_cell':'WX'}, {'sales_name':'王雄','customer':'客户'}),
                             ({},{'amount_total':496}),({},{'amount_total':None})]:
            with self.subTest(changes=changes,args=args):
                self.assertEqual(self.match([self.row(**changes)],**args)['hits'],0)

    def test_channel_total_precedes_wrong_net_row(self):
        net=self.row(row_no=3,amount=497,payer='其他',remitter='其他',company_name='其他',order_cell='')
        hit=self.match([self.row(),net]);self.assertEqual(hit['rows'],[self.row()])
        self.assertIn('总到账金额',hit['matched_by'])
        self.assertEqual(self.match([net])['hits'],0)

    def test_explicit_total_does_not_require_fee_to_explain_tax(self):
        for fee in (0,2,3):
            self.assertEqual(self.match([self.row()],fee=fee)['rows'],[self.row()])
        bank=self.row(form='星展',amount=497)
        self.assertEqual(self.match([bank])['rows'],[bank])
        self.assertEqual(self.match([self.row(form='星展')])['hits'],0)

    def test_bank_net_and_channel_total_both_identified_are_ambiguous(self):
        bank=self.row(row_no=3,form='汇款',amount=497)
        self.assertEqual(self.match([self.row(),bank])['hits'],2)
        self.assertEqual(self.match([self.row()],fee=0,amount_net=500)['hits'],1)

    def test_two_identified_candidates_stay_ambiguous(self):
        self.assertEqual(self.match([self.row(),self.row(row_no=3)])['hits'],2)
        self.assertEqual(self.match([self.row(order_cell='WX'),self.row(row_no=3,order_cell='WX')])['hits'],2)

    def test_existing_so_disambiguates_same_sales_blank_row(self):
        row=self.row();hit=self.match([row,self.row(row_no=3,order_cell='WX')])
        self.assertEqual(hit['rows'],[row])

    def test_same_receipt_uses_all_so_and_cache_separates_different_receipts(self):
        rows=[self.row(order_cell='WXSO26070387\nSO26070388'),self.row(row_no=3,order_cell='WXSO26070389')]
        base=dict(shoukuan_date='2026-07-21',hexiao_date='2026-08-02',arrival_total=497,
                  business_arrival_total=500,fee=3,sales_name='王雄',customer='客户')
        recs=[dict(base,ar='AR_A',so='SO26070387'),dict(base,ar='AR_A',so='SO26070388'),dict(base,ar='AR_B',so='SO26070389')]
        annotate_records(recs,FlowLedger(rows))
        self.assertEqual([r['flow_row_no'] for r in recs],[2,2,3])
        self.assertTrue(all(r['flow_identity']['amount']==500 for r in recs))
        self.assertTrue(all(r['arrival_total']==497 and r['business_arrival_total']==500 for r in recs))

    def test_gross_match_writes_preserves_receipt_values_and_repeats(self):
        from test_flow_monthly import MonthlySafetyTest
        for day,target in [('2026-07-28','F2'),('2026-08-01','F3')]:
            with self.subTest(day=day):
                book=MonthlySafetyTest();book.setUp()
                try:
                    book.modify(lambda ws:setattr(ws['D2'],'value','甲骨易微信'))
                    rec=book.entry();rec.update(shoukuan_date='2026-07-27',hexiao_date=day,
                        arrival_total=8997,business_arrival_total=9000,fee=3,sales_name='测试甲')
                    annotate_records([rec],FlowLedger.from_paths([book.path]))
                    self.assertEqual(rec['flow_hits'],1)
                    self.assertIn('总到账金额',rec['flow_matched_by'])
                    changes,errors=book.run_items(day,[rec])
                    self.assertFalse(errors);self.assertTrue(changes)
                    self.assertEqual(book.read(target),'9000-1000=8000')
                    self.assertEqual(book.read('C2'),9000)
                    self.assertEqual(rec['arrival_total'],8997)
                    before=book.path.read_bytes()
                    self.assertEqual(book.run_items(day,[rec]),([],[]))
                    self.assertEqual(book.path.read_bytes(),before)
                finally:book.tearDown()

if __name__=='__main__':unittest.main()
