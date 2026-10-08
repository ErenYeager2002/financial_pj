import copy,datetime as dt,unittest
from types import SimpleNamespace
import flow_date_identity as D

class DateIdentity(unittest.TestCase):
    def fixture(self):
        row={'date':dt.date(2026,7,1),'form':'甲骨易支付宝','order_cell':'WXSO1','payer':'销售甲','amount':2000}
        rec={'ar':'AR1','so':'SO1','shoukuan_date':'2026-07-02','hexiao_date':'2026-08-09','currency':'人民币CNY',
             'business_arrival_total':2000,'arrival_total':1988,'so_delivery_local':2000,'sales_name':'销售甲',
             'duplicate_writeoff_audit':{'status':'single_order_parent','is_whole_payment':True,'order_count':1},
             'current_source_history':{'basis':'audited_current_exports','identity_fields_complete':True,'events':[
                 {'ar':'AR1','so':'SO1','arrival_date':'2026-07-02','posting_date':'2026-08-09','record_id':'R1','amount_orig':2000}]}}
        return SimpleNamespace(rows=[row]),rec
    def test_unique_current_whole_receipt_matches_without_modifying_date(self):
        flow,rec=self.fixture();before=copy.deepcopy(flow.rows)
        self.assertEqual(D.match(flow,rec)['hits'],1);self.assertEqual(flow.rows,before)
    def test_incomplete_conflicting_and_multiple_candidates_are_not_bound(self):
        for mode in ['two_rows','two_receipts','missing_identity','different_so','other_name','wrong_amount','other_month','foreign','partial']:
            flow,rec=self.fixture()
            if mode=='two_rows':flow.rows.append(copy.deepcopy(flow.rows[0]))
            if mode=='two_receipts':rec['current_source_history']['events'].append(dict(rec['current_source_history']['events'][0],ar='AR2'))
            if mode=='missing_identity':rec['current_source_history']['identity_fields_complete']=False
            if mode=='different_so':flow.rows[0]['order_cell']='SO2'
            if mode=='other_name':flow.rows[0]['payer']='其他人'
            if mode=='wrong_amount':flow.rows[0]['amount']=1988
            if mode=='other_month':flow.rows[0]['date']=dt.date(2026,6,30)
            if mode=='foreign':rec['currency']='美元USD'
            if mode=='partial':rec['so_delivery_local']=3000
            with self.subTest(mode=mode):self.assertEqual(D.match(flow,rec)['hits'],0)

    def test_transferred_root_requires_one_proved_posting(self):
        flow,rec=self.fixture();root=flow.rows[0]
        root.update(order_cell='WX转8月',file='flow.xlsx',sheet='明细')
        carry=dict(root,date=dt.date(2026,8,9),form='冲预收',order_cell='WXSO1 2000',prepayment='2000-2000=0')
        flow.match_existing_posting=lambda _: {'hits':1,'rows':[carry]}
        self.assertEqual(D.match(flow,rec)['rows'],[root])
        carry['amount']=1000
        self.assertEqual(D.match(flow,rec)['hits'],0)
