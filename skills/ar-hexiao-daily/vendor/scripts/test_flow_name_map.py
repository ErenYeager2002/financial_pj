import datetime as dt
import unittest
from flow_ledger import FlowLedger,normalize_name,formula_original_amount

class ExplicitNameMapTest(unittest.TestCase):
    def flow(self,form='星展',copies=1):
        row={'date':dt.date(2026,8,1),'amount':100,'company_name':'付款别名','payer':'付款别名','form':form,'formula_orig_amount':None}
        flow=FlowLedger([dict(row,row_no=i+2) for i in range(copies)])
        flow.name_map[normalize_name('付款别名')]={'系统客户甲'}
        return flow
    def match(self,flow,customer='系统客户甲',sales_name=''):
        return flow.match(dt.date(2026,8,1),100,customer=customer,sales_name=sales_name)
    def test_explicit_alias_applies_to_receipt_channels(self):
        for channel in ['星展','汇款','甲骨易支付宝','PayPal','美元户']:
            with self.subTest(channel=channel):
                result=self.match(self.flow(channel))
                self.assertEqual(result['hits'],1)
                self.assertEqual(result['matched_by'],'三键(中英文对照)')
    def test_ambiguous_alias_cannot_authorize_name_match(self):
        flow=self.flow();flow.name_map[normalize_name('付款别名')].add('系统客户乙')
        self.assertEqual(self.match(flow)['matched_by'],'日期+金额(名字不符)')
    def test_alias_does_not_disambiguate_identical_rows(self):
        result=self.match(self.flow(copies=2));self.assertEqual(result['hits'],2)
    def test_customer_alias_is_not_sales_alias_or_fx_permission(self):
        self.assertEqual(self.match(self.flow(),customer='另一客户',sales_name='系统客户甲')['matched_by'],'日期+金额(名字不符)')
        self.assertEqual(formula_original_amount('=100*7','星展'),(None,None))
