import copy
import datetime as dt
import unittest
import classify_hexiao as C
import current_parent_allocation as P
import current_parent_rows_allocation as R
import baseline_receipts as BR
import validate_plan as V
from test_recognition_regressions import parent


class CurrentRows(unittest.TestCase):
    def fixture(self,amount=15,arrival='2026-08-04'):
        p=parent(amount);p['arrival_date']=dt.date.fromisoformat(arrival)
        p['sod_lines']={'SO_A':[dict(sod='SOD_A',deliver=40)],'SO_B':[dict(sod='SOD_B',deliver=60)]}
        rows={2:dict(so='SO_A',sod='SOD_A',yingshou=40,huikuan=40,jiezhang='是',jiti=40,shoukuan_time='2026-08-01',shoukuan_way='汇'),
              3:dict(so='SO_B',sod='SOD_B',yingshou=10,huikuan=10,jiezhang='是',shoukuan_time='2026-08-02',shoukuan_way='汇'),
              4:dict(so='SO_B',sod='SOD_B',yingshou=15,huikuan=15,jiezhang='是',shoukuan_time='2026-08-04',shoukuan_way='汇'),
              5:dict(so='SO_B',sod='SOD_B',yingshou=35,huikuan=None,jiezhang='否')}
        l=C.LedgerIndex(synthetic={'so':{'SO_A':[2],'SO_B':[3,4,5]},'sod':{'SOD_A':[2],'SOD_B':[3,4,5]},'rows':rows})
        return p,l

    def run_plan(self,p,l,others=()):
        payments=[p,*others]
        for item in payments:
            P.attach(item,{2026:l},payments=payments)
            item['_ledger_received_local_by_so']={so:l.so_totals(so)[1] for so in l.so_index}
            item['_ledger_settled_sos']=['SO_A']
        records=C.expand_payments(payments,{})
        plan=C.classify_records(records,l,{})
        rows={int(ref):row for so,sod in [('SO_A','SOD_A'),('SO_B','SOD_B')] for ref,row in BR.ledger_rows(l,so,sod).items()}
        return plan,V.validate(plan,rows)

    def test_existing_amount_is_not_compared_with_cumulative(self):
        p,l=self.fixture();before=copy.deepcopy(l.row_snapshot)
        plan,checked=self.run_plan(p,l)
        self.assertFalse(plan['hold']);self.assertEqual(checked['counts'],dict(write=0,skip=2,conflict=0))
        self.assertEqual(l.row_snapshot,before)
        self.assertEqual(p['_parent_fallback_allocation']['current_workbook_balance_basis'],'unique_receipt_rows')

    def test_same_day_distinct_amount_is_not_automatically_ambiguous(self):
        p,l=self.fixture();other=copy.deepcopy(p);other['ar']='AR_OTHER'
        for key in ('amount_orig','amount_local','total_amount_orig','total_amount_local'):other[key]=10
        l.row_snapshot[3]['shoukuan_time']='2026-08-04'
        plan,checked=self.run_plan(p,l,[other])
        self.assertFalse(plan['hold']);self.assertEqual(checked['counts']['write'],0);self.assertEqual(checked['counts']['conflict'],0)

    def test_competing_parent_cannot_reuse_same_rows(self):
        p,l=self.fixture();other=copy.deepcopy(p);other['ar']='AR_OTHER'
        plan,checked=self.run_plan(p,l,[other])
        self.assertTrue(plan['hold']);self.assertEqual(checked['counts']['write'],0)

    def test_new_receipt_uses_current_paid_balance_and_reservations(self):
        p,l=self.fixture(7,'2026-08-05');other=copy.deepcopy(p);other['ar']='AR_OTHER'
        plan,checked=self.run_plan(p,l,[other])
        self.assertFalse(plan['hold']);self.assertEqual(checked['counts'],dict(write=2,skip=2,conflict=0))
        amounts=[a for a in p['_parent_fallback_allocation']['allocations'] if a['so']=='SO_B']
        self.assertEqual(amounts[0]['historical_received_local'],32)
        self.assertEqual(amounts[0]['cumulative_after'],39)

    def test_same_day_unmatched_paid_row_not_assumed_previous(self):
        p,l=self.fixture(7)
        plan,checked=self.run_plan(p,l)
        self.assertTrue(plan['hold']);self.assertEqual(checked['counts']['write'],0)

    def test_insufficient_remaining_does_not_over_allocate(self):
        p,l=self.fixture(36,'2026-08-05')
        plan,checked=self.run_plan(p,l)
        self.assertTrue(plan['hold']);self.assertEqual(checked['counts']['write'],0)

    def test_one_physical_row_cannot_be_counted_twice(self):
        identity=dict(amount=30,sos=['S'],day='2026-08-04',way='汇')
        rows={str(i):dict(SO='S',收款时间='2026-08-04',收款方式='汇',回款明细=10) for i in range(2)}
        self.assertEqual(R.matches(identity,rows),[])

    def test_subset_solver_preserves_ambiguity(self):
        identity=dict(amount=30,sos=['S'],day='2026-08-04',way='汇')
        rows={str(i):dict(SO='S',收款时间='2026-08-04',收款方式='汇',回款明细=a) for i,a in enumerate([10,20,30])}
        self.assertEqual(len(R.matches(identity,rows)),2)


if __name__=='__main__':unittest.main()
