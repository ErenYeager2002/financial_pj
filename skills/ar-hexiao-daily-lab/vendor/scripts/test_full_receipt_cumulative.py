import unittest
import datetime as dt
import classify_hexiao as C
import baseline_receipts as BR
import validate_plan as V

class FullReceiptCumulativeTest(unittest.TestCase):
    def payment(self, cumulative=100):
        return {'ar':'AR_SYNTHETIC','amount_orig':100.,'amount_local':100.,'total_amount_orig':100.,'total_amount_local':100.,'currency':'CNY','arrival_date':dt.date(2026,8,25),'hexiao_date':dt.date(2026,8,25),'status':'核销成功','huikuan_type':'预存回款','orders':[{'so':'SO_SYNTHETIC','deliver':100.,'deliver_local':100.,'currency':'CNY','delivery_date':dt.date(2026,6,1)}],'writeoffs':{'SO_SYNTHETIC':100.},'writeoffs_local':{'SO_SYNTHETIC':100.},'cumulative_writeoffs':{'SO_SYNTHETIC':cumulative},'cumulative_writeoffs_local':{'SO_SYNTHETIC':cumulative},'_writeoff_sequence_key_by_so':{'SO_SYNTHETIC':['2026-08-25','HX_SYNTHETIC','DETAIL_SYNTHETIC']},'sod_lines':{'SO_SYNTHETIC':[{'sod':'SOD_A','deliver':40.},{'sod':'SOD_B','deliver':60.}]}}
    def test_single_current_event_supplies_per_sod_cumulative(self):
        rows=C.expand_payments([self.payment()],{})
        self.assertEqual([r['cumulative_received_local'] for r in rows],[40.,60.])
        self.assertTrue(all(r['itemized_cumulative_authoritative'] for r in rows))
    def test_other_receipts_do_not_get_assigned_to_each_sod(self):
        rows=C.expand_payments([self.payment(120)],{})
        self.assertTrue(all(r.get('cumulative_received_local') is None for r in rows))
    def test_invalid_dates_correct_without_adding_money(self):
        raw={2:{'so':'SO_SYNTHETIC','sod':'SOD_A','yingshou':40,'jiti':40,'huikuan':40,'jiezhang':'是','shoukuan_time':'20626-8-25','shoukuan_way':'汇'},3:{'so':'SO_SYNTHETIC','sod':'SOD_B','yingshou':60,'jiti':60,'huikuan':60,'jiezhang':'是','shoukuan_time':'20626-8-25','shoukuan_way':'汇'}}
        ledger=C.LedgerIndex(synthetic={'so':{'SO_SYNTHETIC':[2,3]},'sod':{'SOD_A':[2],'SOD_B':[3]},'rows':raw})
        result=C.classify_records(C.expand_payments([self.payment()],{}),ledger,{})
        self.assertEqual(len(result['auto']),2,result)
        actual={int(k):{**r,'_差异列存在':True} for sod in ['SOD_A','SOD_B'] for k,r in BR.ledger_rows(ledger,'SO_SYNTHETIC',sod).items()}
        for item in result['auto']:
            self.assertTrue(item.get('receipt_correction'))
            self.assertFalse(item.get('row_operation'))
            self.assertEqual(V.check_one(item,actual)['verdict'],'write')
            actual[item['ledger_row_ref']].update(item['five_cols'])
            self.assertEqual(V.check_one(item,actual)['verdict'],'skip')
        self.assertEqual(sum(r['回款明细'] for r in actual.values()),100)
