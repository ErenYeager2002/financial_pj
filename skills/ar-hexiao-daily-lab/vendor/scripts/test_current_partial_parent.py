import copy,unittest
import classify_hexiao as C
import current_parent_allocation as M
import test_recognition_regressions as fixtures
from test_current_parent_allocation import CurrentParentTest

class PartialParentCurrentMaterial(unittest.TestCase):
    def test_current_partial_parent_rebuilds_original_allocation_before_missing_year(self):
        p,l=CurrentParentTest().fixture()
        p.update(amount_orig=80,amount_local=80,total_amount_orig=80,total_amount_local=80)
        for journal in ({},{'parents':{p['ar']:{'parent_amount':999,'basis':'local','allocations':[]}}}):
            current=copy.deepcopy(p);current['_fallback_allocation_state']=journal
            M.attach(current,{2026:l})
            records=C.expand_payments([current],{})
            self.assertFalse(any(r.get('forced_code') for r in records),records)
            self.assertEqual({r['so']:r['amount_local'] for r in records},{'SO_A':40,'SO_B':40})
            self.assertTrue(current['_parent_fallback_allocation']['reconstructed_from_current_material'])
            result=C.classify_records_by_year(records,{2026:l},{},{})
            self.assertEqual([(r['so'],r['code']) for r in result['hold']],[('SO_B','E3')])
            self.assertEqual(len(result['auto']),1)

    def test_partially_paid_second_order_is_not_allocated_again(self):
        import datetime as dt
        import baseline_receipts as BR
        import validate_plan as V
        p,l=CurrentParentTest().fixture()
        p.update(amount_orig=70,amount_local=70,total_amount_orig=70,total_amount_local=70)
        p['orders'][1]['delivery_date']=dt.date(2026,6,1)
        l.row_snapshot[3]=dict(so='SO_B',sod='SOD_B',yingshou=30,huikuan=30,jiti=None,jiezhang='是',shoukuan_time='2026-08-04',shoukuan_way='汇')
        l.row_snapshot[4]=dict(so='SO_B',sod='SOD_B',yingshou=30,huikuan=None,jiti=None,jiezhang='否',shoukuan_time=None,shoukuan_way=None)
        l.so_index['SO_B']=[3,4];l.sod_index['SOD_B']=[3,4]
        p['_ledger_received_local_by_so']['SO_B']=30
        M.attach(p,{2026:l})
        records=C.expand_payments([p],{})
        self.assertEqual({r['so']:r['amount_local'] for r in records},{'SO_A':40,'SO_B':30})
        plan=C.classify_records(records,l,{})
        rows={int(k):v for so,sod in [('SO_A','SOD_A'),('SO_B','SOD_B')] for k,v in BR.ledger_rows(l,so,sod).items()}
        checked=V.validate(plan,rows)
        self.assertEqual(checked['counts'],{'write':0,'skip':2,'conflict':0},plan)

    def test_same_posting_date_other_parent_is_not_ignored(self):
        import datetime as dt
        p,l=CurrentParentTest().fixture()
        l.row_snapshot[2]['shoukuan_time']='2026-08-05'
        l.row_snapshot[2]['shoukuan_way']='汇'
        other=copy.deepcopy(p);other['ar']='OTHER';other['arrival_date']=dt.date(2026,8,3)
        M.attach(p,{2026:l},payments=[p,other])
        self.assertIn('SO_A',p['_current_parent_ambiguous_sos'])
        records=C.expand_payments([p],{})
        self.assertTrue(any(r.get('forced_code')=='E_PARENT_ALLOCATION_HISTORY_MISSING' for r in records))

if __name__=='__main__':unittest.main()
