import copy
import unittest
import classify_hexiao as C
import validate_plan as V
from test_recognition_regressions import RecognitionTests, ledger_rows

class DeferredHistoryReviewTests(unittest.TestCase):
    def test_existing_split_receipts_keep_so_accrual_deferred_on_recheck(self):
        rec, ledger = RecognitionTests().existing(amount=70, prior=40, arrival='2026-08-04', paid_date='2026-08-04')
        rec.pop('receivable_group_scope')
        paid = copy.deepcopy(ledger.row_snapshot[3])
        paid.update(yingshou=40, huikuan=40, jiti=None)
        second = {**paid, 'sod':'SOD_OTHER', 'yingshou':30, 'huikuan':30}
        unpaid = {**second, 'yingshou':30, 'huikuan':None, 'jiezhang':'否', 'shoukuan_time':None, 'shoukuan_way':''}
        ledger.row_snapshot={3:paid,4:second,5:unpaid}
        ledger.so_index={'SO_TEST':[3,4,5]}
        ledger.sod_index={'SOD_TEST':[3],'SOD_OTHER':[4,5]}
        rec.update(forced_code='E5',default_first_sod=True,default_amount_local=70,default_amount_orig=70,default_cumulative_received_local=70,default_sod_lines=[{'sod':'SOD_TEST','deliver_local':40},{'sod':'SOD_OTHER','deliver_local':60}],all_sods=['SOD_TEST','SOD_OTHER'],sod_delivery_local={'SOD_TEST':40,'SOD_OTHER':60},so_delivery_local=100)
        result=C.classify_records([rec],ledger,{})
        self.assertEqual(len(result['auto']),2)
        for item in result['auto']:
            self.assertIsNone(item['five_cols']['计提'])
            self.assertFalse(item['so_accrual_audit']['all_settled'])
            self.assertEqual(V.check_one(item,ledger_rows(ledger))['verdict'],'skip')
            tampered=copy.deepcopy(item)
            tampered['five_cols']['计提']=40
            self.assertEqual(V.check_one(tampered,ledger_rows(ledger))['verdict'],'conflict')

if __name__=='__main__':unittest.main()
