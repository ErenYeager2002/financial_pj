import unittest
import classify_hexiao as C

class UnprovenPositionTest(unittest.TestCase):
    def fixture(self, deliveries, known=False):
        rows={2:{'so':'SO_TEST','sod':'SOD_B' if known else '', 'yingshou':100,'huikuan':None,'jiezhang':'否'},
              3:{'so':'SO_TEST','sod':'SOD_A' if known else '', 'yingshou':100,'huikuan':None,'jiezhang':'否'}}
        ledger=C.LedgerIndex(synthetic={'so':{'SO_TEST':[2,3]},'sod':{'SOD_A':[3],'SOD_B':[2]} if known else {},'rows':rows})
        rec={'ar':'AR_TEST','so':'SO_TEST','sod':'SOD_A','amount_orig':deliveries[1],'amount_local':deliveries[1],
             'currency':'CNY','deliver_local':deliveries[1],'so_delivery_local':sum(deliveries),
             'so_all_lines':[{'sod':'SOD_B','deliver':deliveries[0]},{'sod':'SOD_A','deliver':deliveries[1]}],
             'all_sods':['SOD_A','SOD_B'],'sod_delivery_local':{'SOD_B':deliveries[0],'SOD_A':deliveries[1]},
             'shoukuan_date':'2026-09-20','hexiao_date':'2026-09-20','status':'已核销'}
        return rec,ledger
    def test_equal_amounts_do_not_prove_order(self):
        rec,ledger=self.fixture([100,100]);plan=C.classify_records([rec],ledger,{})
        self.assertFalse(plan['auto'],plan)
        self.assertEqual(plan['hold'][0]['code'],'E8')
    def test_proportional_amounts_do_not_prove_order(self):
        rec,ledger=self.fixture([90,90]);plan=C.classify_records([rec],ledger,{})
        self.assertFalse(plan['auto'],plan)
        self.assertEqual(plan['hold'][0]['code'],'E8')
    def test_one_changed_amount_is_not_systematic_ratio_proof(self):
        rec,ledger=self.fixture([100,90]);plan=C.classify_records([rec],ledger,{})
        self.assertFalse(plan['auto'],plan)
        self.assertEqual(plan['hold'][0]['code'],'E8')
    def test_existing_unique_sod_remains_usable(self):
        rec,ledger=self.fixture([100,100],known=True);plan=C.classify_records([rec],ledger,{})
        self.assertEqual(len(plan['auto']),1,plan)
        self.assertEqual(plan['auto'][0]['ledger_row_ref'],3)
