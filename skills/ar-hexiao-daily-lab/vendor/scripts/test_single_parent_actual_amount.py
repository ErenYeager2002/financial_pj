import copy,unittest
from writeoff_duplicate_audit import audit_parent_writeoffs as audit

class SingleParentActual(unittest.TestCase):
    def payment(self,total=147,delivery=146.7):
        return {'ar':'AR_TEST','currency':'CNY','huikuan_type':'整笔回款','hexiao_date':'2026-08-11',
                'amount_orig':total,'amount_local':total,'total_amount_orig':total,'total_amount_local':total,
                'orders':[{'so':'SO_TEST','deliver':delivery,'deliver_local':delivery,'currency':'CNY'}]}
    def test_actual_parent_used_on_both_sides_of_subyuan_difference(self):
        for total in [145.7,146.7,147,147.7]:
            p=self.payment(total);before=copy.deepcopy(p);rows,a=audit(p,[])
            self.assertEqual(p,before);self.assertEqual(a['status'],'single_order_parent')
            self.assertEqual(rows[0]['amount'],total);self.assertEqual(rows[0]['amount_local'],total)
            self.assertEqual(a['unallocated_parent_amount'],0)
    def test_over_limit_foreign_multiple_and_inconsistent_currency_not_promoted(self):
        for mode in ['large','foreign','multiple','conflict','zero']:
            p=self.payment()
            if mode=='large':p=self.payment(147.71)
            if mode=='foreign':p['currency']='USD';p['orders'][0]['currency']='USD'
            if mode=='multiple':p['orders'].append(dict(p['orders'][0],so='SO_OTHER'))
            if mode=='conflict':p['total_amount_local']=148
            if mode=='zero':p=self.payment(0.5,0)
            with self.subTest(mode=mode):self.assertNotEqual(audit(p,[])[1]['status'],'single_order_parent')
    def test_explicit_detail_is_not_replaced_by_parent_total(self):
        raw=[{'ar':'AR_TEST','so':'SO_TEST','record_id':'HX1','date':'2026-08-11','amount':146.7,'amount_local':146.7,'currency':'CNY'}]
        rows,a=audit(self.payment(),raw)
        self.assertEqual(rows[0]['amount'],146.7);self.assertNotEqual(a['status'],'single_order_parent')
