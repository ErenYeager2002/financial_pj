import unittest
import copy
import test_receipt_history as fixtures
import receipt_history as H
import baseline_receipts as BR
import validate_plan as V
from classify_hexiao import classify_one

class CurrentReceiptEvidenceTest(unittest.TestCase):
    def fixture(self, tiny=False):
        rec, ledger=fixtures.HistoryTest().make(paid_date='2026-08-04')
        if tiny:
            rec.update(amount_local=19.8, amount_orig=19.8, cumulative_received_local=19.8, deliver_local=20, deliver_orig=20, so_delivery_local=20, sod_delivery_local={'SOD_TEST':20})
            rec['receivable_group_scope']['baseline_receivable']=20
            ledger.row_snapshot.pop(2)
            ledger.so_index['SO_TEST']=[3];ledger.sod_index['SOD_TEST']=[3]
            ledger.row_snapshot[3].update(shoukuan_time='2026-08-05',jiti=20)
        journal={'baseline_receivable':20 if tiny else 100,'scope_only':True,'events':{},'ordinary_events':{BR.event_key(rec):{'signature':[rec['amount_local'],'2026-08-05','冲预收']}}}
        ledger.baseline_receipt_state={BR.group_key('SO_TEST','SOD_TEST'):journal}
        return rec,ledger,journal

    def test_current_unique_conserved_receipt_can_correct_date_despite_old_journal(self):
        rec,ledger,_=self.fixture()
        item=classify_one(rec,ledger,{},.01,2026)
        self.assertEqual(item.get('receipt_correction',{}).get('kind'),'existing')
        self.assertEqual(item['ledger_row_ref'],3)
        self.assertFalse(item.get('row_operation'))
        rows={int(k):v for k,v in BR.ledger_rows(ledger,'SO_TEST','SOD_TEST').items()}
        self.assertEqual(V.check_one(item,rows)['verdict'],'write')
        rows[3].update(item['five_cols'])
        self.assertEqual(V.check_one(item,rows)['verdict'],'skip')
        self.assertEqual(sum(r['回款明细'] or 0 for r in rows.values()),20)

    def test_current_unique_small_tail_correction_not_blocked_by_journal(self):
        rec,ledger,_=self.fixture(tiny=True)
        item=H.candidate(rec,{},ledger)
        self.assertIsNotNone(item)
        self.assertEqual(item['five_cols']['回款明细'],19.8)
        self.assertFalse(item.get('row_operation'))

    def test_changed_identity_amount_and_other_event_ownership_still_rejected(self):
        for mode in ['changed','other','unconserved','multiple']:
            rec,ledger,journal=self.fixture()
            if mode=='changed':journal['ordinary_events'][BR.event_key(rec)]['signature'][0]=21
            if mode=='other':journal['ordinary_events']['OTHER']={'signature':[20,'2026-08-04','汇']}
            if mode=='unconserved':ledger.row_snapshot[2]['yingshou']=79
            if mode=='multiple':
                ledger.row_snapshot[4]=copy.deepcopy(ledger.row_snapshot[3]);ledger.so_index['SO_TEST'].append(4);ledger.sod_index['SOD_TEST'].append(4);ledger.row_snapshot[2]['yingshou']=60
            self.assertIsNone(H.candidate(rec,{},ledger),mode)
