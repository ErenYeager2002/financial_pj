import unittest
import classify_hexiao as C
import current_receipt_cohort as R
from test_current_receipt_cohort import CurrentCohortTest
class ZeroCohort(unittest.TestCase):
 def test_zero_source_preserved_before_and_after_date_correction(self):
  p,ledger=CurrentCohortTest().fixture();records=C.expand_payments([p],{})
  for rec in records:rec['so_receipt_source']['sod_delivery_local']['SOD_ZERO']=0
  ledger.row_snapshot[5]={'so':'SO_SYNTHETIC','sod':'SOD_ZERO','yingshou':0,'jiti':0,'huikuan':0,'jiezhang':'是','shoukuan_time':'2026-08-25','shoukuan_way':'汇'}
  ledger.so_index['SO_SYNTHETIC'].append(5);ledger.sod_index['SOD_ZERO']=[5]
  for day in ['bad-date','2026-08-25']:
   ledger.row_snapshot[4]['shoukuan_time']=day;result=R.expand(records,ledger)
   self.assertEqual({r['sod'] for r in result},{'SOD_B','SOD_ZERO'})
   zero=next(r for r in result if r['sod']=='SOD_ZERO')
   self.assertEqual((zero['amount_local'],zero['amount_orig'],zero['deliver_local']),(0,0,0))
   self.assertEqual(sum(r['amount_local'] for r in result),40)

 def test_missing_delivery_is_not_treated_as_zero(self):
  p,ledger=CurrentCohortTest().fixture();records=C.expand_payments([p],{})
  for rec in records:rec['so_receipt_source']['sod_delivery_local']['SOD_UNKNOWN']=None
  self.assertNotIn('SOD_UNKNOWN',{r['sod'] for r in R.expand(records,ledger)})
 def test_nonzero_history_for_zero_source_rejects_cohort_shortcut(self):
  p,ledger=CurrentCohortTest().fixture();records=C.expand_payments([p],{})
  for rec in records:rec['so_receipt_source']['sod_delivery_local']['SOD_A']=0
  self.assertEqual(R.expand(records,ledger),records)
