import unittest
import classify_hexiao as C

class IdentityMatchTest(unittest.TestCase):
    def ledger(self, mixed=False):
        rows={2:{'so':'SO_OTHER','sod':'SOD_TEST','yingshou':100,'jiezhang':'否'}}
        if mixed:rows[3]={'so':'SO_TEST','sod':'SOD_TEST','yingshou':200,'jiezhang':'否'}
        return C.LedgerIndex(synthetic={'so':{'SO_OTHER':[2],**({'SO_TEST':[3]} if mixed else {})},
            'sod':{'SOD_TEST':list(rows)},'rows':rows})
    def record(self):
        return {'ar':'AR_TEST','so':'SO_TEST','sod':'SOD_TEST','amount_orig':100,'amount_local':100,
                'currency':'CNY','deliver_local':100,'so_delivery_local':100,'all_sods':['SOD_TEST'],
                'sod_delivery_local':{'SOD_TEST':100},'shoukuan_date':'2026-09-20','hexiao_date':'2026-09-20','status':'已核销'}
    def test_other_so_cannot_supply_row(self):
        row,how,candidates=self.ledger().match('SO_TEST','SOD_TEST',100)
        self.assertIsNone(row)
        self.assertEqual(how,'E_SO_SOD_MISMATCH')
        self.assertEqual(candidates,[2])
    def test_cross_so_conflict_is_held_before_plan(self):
        plan=C.classify_records([self.record()],self.ledger(),{})
        self.assertFalse(plan['auto'])
        self.assertEqual(plan['hold'][0]['code'],'E_SO_SOD_MISMATCH')
    def test_shared_sod_is_resolved_with_so(self):
        row,how,candidates=self.ledger(True).match('SO_TEST','SOD_TEST',100)
        self.assertEqual(row,3)
        self.assertEqual(candidates,[3])
    def test_sod_only_match_stays_available_without_so(self):
        self.assertEqual(self.ledger().match('','SOD_TEST',100)[0],2)
