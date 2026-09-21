import unittest
from writeoff_duplicate_audit import audit_parent_writeoffs

class OrderDuplicateTest(unittest.TestCase):
    def payment(self,delivery=133.14):
        return {'ar':'AR_TEST','currency':'CNY','amount_local':12051.3,'amount_orig':12051.3,'huikuan_type':'预存回款','orders':[{'so':'SO_TEST','deliver_local':delivery,'deliver':delivery,'currency':'CNY'}]}
    def rows(self):
        return [{'ar':'AR_TEST','so':'SO_TEST','record_id':num,'rowid':num,'date':'2026-09-17','amount':133.14,'amount_local':133.14,'currency':'CNY'} for num in ['HX_FIRST','HX_SECOND']]
    def test_order_excess_detected_with_parent_balance_remaining(self):
        rows,audit=audit_parent_writeoffs(self.payment(),self.rows())
        self.assertEqual(len(rows),1)
        self.assertEqual(audit['ignored_record_count'],1)
        self.assertEqual(audit['logical_total'],133.14)
    def test_equal_genuine_installments_are_kept(self):
        rows,audit=audit_parent_writeoffs(self.payment(266.28),self.rows())
        self.assertEqual(len(rows),2)
        self.assertEqual(audit['ignored_record_count'],0)
    def test_distinct_dates_are_not_automatically_folded(self):
        raw=self.rows();raw[1]['date']='2026-09-16'
        rows,audit=audit_parent_writeoffs(self.payment(),raw)
        self.assertEqual(len(rows),2)
    def test_missing_delivery_does_not_guess_duplicates(self):
        payment=self.payment();payment['orders']=[]
        self.assertEqual(len(audit_parent_writeoffs(payment,self.rows())[0]),2)
    def test_missing_identity_does_not_remove_a_record(self):
        raw=self.rows();raw[1]['record_id']=''
        rows,audit=audit_parent_writeoffs(self.payment(),raw)
        self.assertFalse(audit['ignored_record_count'])
    def test_other_so_equal_rows_remain_independent(self):
        raw=self.rows()+[{**r,'so':'SO_OTHER','record_id':r['record_id']+'_OTHER'} for r in self.rows()]
        rows,audit=audit_parent_writeoffs(self.payment(),raw)
        self.assertEqual(len(rows),3)
        self.assertEqual(sum(r['so']=='SO_OTHER' for r in rows),2)
