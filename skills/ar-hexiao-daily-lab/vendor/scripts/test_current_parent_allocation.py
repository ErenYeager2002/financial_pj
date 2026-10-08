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
        for mode in ['day','amount']:
            p,l=self.fixture()
            if mode=='day':l.row_snapshot[2]['shoukuan_time']='2026-07-01'
            if mode=='amount':l.row_snapshot[2]['huikuan']=39
            M.attach(p,{2026:l});records=C.expand_payments([p],{})
            self.assertTrue(any(r.get('forced_code')=='E_PARENT_ALLOCATION_HISTORY_MISSING' for r in records),mode)
            reasons=' '.join(r.get('forced_reason','') for r in records)
            self.assertNotIn('恢复',reasons)
            if mode=='day':
                self.assertIn('2026-07-01',reasons);self.assertIn('2026-08-04',reasons)
                self.assertIn('当前表行2',reasons)
            else:
                self.assertIn('已收39.00',reasons);self.assertIn('应分配40.00',reasons)
                self.assertIn('差额-1.00',reasons)

    def test_competing_parent_cannot_claim_same_current_receipt(self):
        import current_parent_allocation as M
        p,l=self.fixture();other=copy.deepcopy(p);other['ar']='AR_OTHER'
        M.attach(p,{2026:l},payments=[p,other])
        records=C.expand_payments([p],{})
        self.assertTrue(any(r.get('forced_code')=='E_PARENT_ALLOCATION_HISTORY_MISSING' for r in records))
        reasons=' '.join(r.get('forced_reason','') for r in records)
        self.assertIn('AR_OTHER',reasons);self.assertIn('多个父回款',reasons)
        self.assertNotIn('恢复',reasons)
    def test_reservations_only_include_current_unwritten_amount(self):
        import current_parent_allocation as M
        import fallback_sequence as FS
        from collections import defaultdict
        p,l=self.fixture();M.attach(p,{2026:l});C.expand_payments([p],{})
        reservations=defaultdict(list);FS.reserve(p,reservations)
        self.assertEqual(reservations['SO_A'],[])
        self.assertEqual(sum(r[2] for r in reservations['SO_B']),60)


class CurrentParentDiagnosticTest(unittest.TestCase):
    fixture = CurrentParentTest.fixture
    def test_reconstruction_structure_diagnostics(self):
        import current_parent_allocation as M
        for mode,expected in [('delivery','应收合计41.00'),('settlement','结账标记'),('duplicate','同一SOD'),('partial_accrual','计提')]:
            with self.subTest(mode=mode):
                p,l=self.fixture()
                p['_ledger_settled_sos']=[]
                if mode=='delivery':l.row_snapshot[2]['yingshou']=41
                if mode=='settlement':l.row_snapshot[2]['jiezhang']='否'
                if mode=='duplicate':
                    l.row_snapshot[2].update(yingshou=20,huikuan=20)
                    l.row_snapshot[3]=copy.deepcopy(l.row_snapshot[2])
                    l.so_index['SO_A'].append(3);l.sod_index['SOD_A'].append(3)
                if mode=='partial_accrual':
                    p.update(amount_orig=20,amount_local=20,total_amount_orig=20,total_amount_local=20)
                    l.row_snapshot[2].update(yingshou=20,huikuan=20,jiti=1)
                    l.row_snapshot[3]=dict(so='SO_A',sod='SOD_A',yingshou=20,huikuan=None,jiti=None,jiezhang='否',shoukuan_time=None,shoukuan_way=None)
                    l.so_index['SO_A'].append(3);l.sod_index['SOD_A'].append(3)
                    p['_ledger_received_local_by_so']['SO_A']=20
                M.attach(p,{2026:l})
                before=copy.deepcopy(p['_current_parent_rows'])
                records=C.expand_payments([p],{})
                reasons=' '.join(r.get('forced_reason','') for r in records)
                self.assertTrue(any(r.get('forced_code')=='E_PARENT_ALLOCATION_HISTORY_MISSING' for r in records))
                self.assertIn(expected,reasons)
                self.assertIn('SO_A',reasons)
                self.assertNotIn('恢复',reasons)
                self.assertEqual(before,p['_current_parent_rows'])


class CurrentParentMissingPrefixDiagnostic(unittest.TestCase):
    def test_current_prefix_gap_lists_actual_rows_not_restore_old_journal(self):
        import current_parent_allocation as M
        p,l=CurrentParentTest().fixture()
        p['cumulative_writeoffs']={'SO_A':1}
        p['cumulative_writeoffs_local']={'SO_A':1}
        M.attach(p,{2026:l})
        records=C.expand_payments([p],{})
        reasons=' '.join(r.get('forced_reason','') for r in records)
        self.assertTrue(any(r.get('forced_code')=='E_PARENT_ALLOCATION_HISTORY_MISSING' for r in records))
        for text in ['SO_A','39.00','2026-08-04','行2','逐笔']:
            self.assertIn(text,reasons)
        self.assertNotIn('恢复',reasons)
