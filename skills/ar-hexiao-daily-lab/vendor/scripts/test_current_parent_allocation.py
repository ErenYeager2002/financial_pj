import unittest
import datetime as dt
import copy
import classify_hexiao as C
import test_recognition_regressions as fixtures

class CurrentParentTest(unittest.TestCase):
    def fixture(self):
        p=fixtures.parent(100);p['arrival_date']=dt.date(2026,8,4)
        p['orders'][1]['delivery_date']=dt.date(2025,6,1)
        rows={2:{'so':'SO_A','sod':'SOD_A','yingshou':40,'jiti':40,'huikuan':40,'jiezhang':'是','shoukuan_time':'2026-08-04','shoukuan_way':'汇'}}
        l=C.LedgerIndex(synthetic={'so':{'SO_A':[2]},'sod':{'SOD_A':[2]},'rows':rows})
        p['_ledger_received_local_by_so']={'SO_A':40};p['_ledger_settled_sos']=['SO_A']
        p['sod_lines']={'SO_A':[{'sod':'SOD_A','deliver':40}],'SO_B':[{'sod':'SOD_B','deliver':60}]}
        return p,l
    def test_current_full_receipt_is_not_blocked_by_missing_history(self):
        import current_parent_allocation as M
        p,l=self.fixture();M.attach(p,{2026:l})
        records=C.expand_payments([p],{})
        self.assertFalse(any(r.get('forced_code')=='E_PARENT_ALLOCATION_HISTORY_MISSING' for r in records))
        self.assertEqual(sum(r.get('amount_local') or 0 for r in records),100)
        result=C.classify_records_by_year(records,{2026:l},{},{})
        self.assertEqual(len(result['auto']),1,result)
        self.assertEqual(result['auto'][0]['so'],'SO_A')
        self.assertEqual([(r['so'],r['code']) for r in result['hold']],[('SO_B','E3')])
    def test_other_day_or_partial_parent_remains_unresolved(self):
        import current_parent_allocation as M
        for mode in ['day','amount','partial']:
            p,l=self.fixture()
            if mode=='day':l.row_snapshot[2]['shoukuan_time']='2026-07-01'
            if mode=='amount':l.row_snapshot[2]['huikuan']=39
            if mode=='partial':p.update(amount_orig=80,amount_local=80,total_amount_orig=80,total_amount_local=80)
            M.attach(p,{2026:l});records=C.expand_payments([p],{})
            self.assertTrue(any(r.get('forced_code')=='E_PARENT_ALLOCATION_HISTORY_MISSING' for r in records),mode)

    def test_competing_parent_cannot_claim_same_current_receipt(self):
        import current_parent_allocation as M
        p,l=self.fixture();other=copy.deepcopy(p);other['ar']='AR_OTHER'
        M.attach(p,{2026:l},payments=[p,other])
        records=C.expand_payments([p],{})
        self.assertTrue(any(r.get('forced_code')=='E_PARENT_ALLOCATION_HISTORY_MISSING' for r in records))
    def test_reservations_only_include_current_unwritten_amount(self):
        import current_parent_allocation as M
        import fallback_sequence as FS
        from collections import defaultdict
        p,l=self.fixture();M.attach(p,{2026:l});C.expand_payments([p],{})
        reservations=defaultdict(list);FS.reserve(p,reservations)
        self.assertEqual(reservations['SO_A'],[])
        self.assertEqual(sum(r[2] for r in reservations['SO_B']),60)
