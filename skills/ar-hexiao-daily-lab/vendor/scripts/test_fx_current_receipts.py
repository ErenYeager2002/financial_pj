"""Foreign accrual retains current-table receipt and repeat guarantees."""
import copy
import tempfile
import unittest
from pathlib import Path

import classify_hexiao as C
import validate_plan as V
import apply_to_copy as A
import test_delivery_above_receivable as fixtures


def foreign(rec, original=150, rate=7):
    rec = copy.deepcopy(rec)
    rec.update(currency='USD', amount_orig=rec['amount_local']/10)
    rec['fx_accrual_source'] = {
        'currency': 'USD', 'so_delivery_orig': original,
        'sod_delivery_orig': {rec['sod']: original},
        'reconciliation_date': rec['hexiao_date'],
        'quote': {'schema':'boc_spot_buying_v1','currency':'USD',
                  'rate_type':'现汇买入价','quoted_unit':100,
                  'buying_price_per_100':str(rate*100),'rate_cny_per_unit':str(rate),
                  'published_at':rec['hexiao_date']+'T18:00:00',
                  'timezone':'Asia/Shanghai','reconciliation_date':rec['hexiao_date'],
                  'selection':'same_date_latest',
                  'source':{'name':'中国银行','kind':'imported_workbook',
                            'reference':'rates.xlsx#中行历史牌价','sha256':'a'*64,'row':2}},
    }
    return rec


class ForeignCurrentReceipts(unittest.TestCase):
    def test_preserved_receivable_installments_value_original_order_at_final_rate(self):
        helper = fixtures.DeliveryAboveReceivable()
        with tempfile.TemporaryDirectory() as temp:
            path = helper.create(temp)
            for index, amount, total in [(1,200,200), (2,1300,1500)]:
                rec = foreign(helper.record(index,amount,total))
                if index==1:
                    rec['fx_accrual_source'].pop('quote')
                before = A.read_ledger_rows(path)
                plan = C.classify_records([copy.deepcopy(rec)],C.LedgerIndex(path),{})
                checked = V.validate(plan,before)
                self.assertEqual(checked['counts'],{'write':1,'skip':0,'conflict':0},plan)
                dst = Path(temp)/f'after{index}.xlsx'
                A.write_plan(path,dst,checked['write'])
                self.assertEqual(A.verify_written(dst,checked['write']),[])
                after = A.read_ledger_rows(dst)
                self.assertEqual(sum(r['回款明细'] or 0 for r in after.values()),total)
                self.assertEqual(sum(r['计提'] or 0 for r in after.values()),1050 if index==2 else 0)
                self.assertEqual(sum(r['差异'] or 0 for r in after.values()),-50 if index==2 else 0)
                repeated = C.classify_records([copy.deepcopy(rec)],C.LedgerIndex(dst),{})
                self.assertEqual(V.validate(repeated,after)['counts'],{'write':0,'skip':1,'conflict':0},repeated)
                self.assertTrue(repeated['auto'][0].get('current_workbook_receipts'),repeated)
                if index==2:
                    another_quote=foreign(rec,rate=9)
                    another_quote['fx_accrual_source'].pop('quote')
                    preserved=C.classify_records([another_quote],C.LedgerIndex(dst),{})
                    self.assertEqual(V.validate(preserved,after)['counts'],{'write':0,'skip':1,'conflict':0},preserved)
                    self.assertEqual(sum(r['计提'] or 0 for r in A.read_ledger_rows(dst).values()),1050)
                path = dst


    def test_ordinary_foreign_write_has_difference_and_repeats_without_revaluation(self):
        helper=fixtures.DeliveryAboveReceivable()
        with tempfile.TemporaryDirectory() as temp:
            path=helper.create(temp)
            rec=helper.record(1,1000,1000)
            rec.update(deliver_local=1000,so_delivery_local=1000,sod_delivery_local={'SOD_A':1000})
            rec=foreign(rec,original=100)
            before=A.read_ledger_rows(path)
            checked=V.validate(C.classify_records([rec],C.LedgerIndex(path),{}),before)
            self.assertEqual(checked['counts'],{'write':1,'skip':0,'conflict':0},checked)
            self.assertEqual(checked['write'][0]['five_cols']['计提'],700)
            self.assertEqual(checked['write'][0]['derived_cols'],{'差异':300})
            altered=copy.deepcopy(checked['write'][0])
            altered['five_cols']['计提']=701
            self.assertEqual(V.check_one(altered,before)['verdict'],'conflict')
            altered=copy.deepcopy(checked['write'][0])
            altered['fx_accrual_source']['quote'].update(buying_price_per_100='800',rate_cny_per_unit='8')
            self.assertEqual(V.check_one(altered,before)['verdict'],'conflict')
            dst=Path(temp)/'ordinary.xlsx'
            A.write_plan(path,dst,checked['write'])
            self.assertEqual(A.verify_written(dst,checked['write']),[])
            after=A.read_ledger_rows(dst)
            rec['fx_accrual_source'].pop('quote')
            repeated=C.classify_records([rec],C.LedgerIndex(dst),{})
            self.assertEqual(V.validate(repeated,after)['counts'],{'write':0,'skip':1,'conflict':0},repeated)
            self.assertTrue(repeated['auto'][0].get('current_workbook_receipts'),repeated)
            self.assertEqual(repeated['auto'][0]['five_cols']['计提'],700)


    def test_multiple_sods_share_last_order_reconciliation_rate(self):
        helper=fixtures.DeliveryAboveReceivable()
        with tempfile.TemporaryDirectory() as temp:
            path=helper.create(temp,True)
            for index,sod,amount,total in [(1,'SOD_A',200,200),(2,'SOD_A',1300,1500),(3,'SOD_B',100,100)]:
                rec=foreign(helper.record(index,amount,total,sod,True),original=160,rate=5 if index<3 else 7)
                rec['fx_accrual_source']['sod_delivery_orig']={'SOD_A':150,'SOD_B':10}
                if index==2:
                    rec['fx_accrual_source'].pop('quote')
                before=A.read_ledger_rows(path)
                plan=C.classify_records([copy.deepcopy(rec)],C.LedgerIndex(path),{})
                checked=V.validate(plan,before)
                self.assertEqual(checked['counts'],{'write':1,'skip':0,'conflict':0},plan)
                dst=Path(temp)/f'multi{index}.xlsx'
                A.write_plan(path,dst,checked['write'])
                self.assertEqual(A.verify_written(dst,checked['write']),[])
                after=A.read_ledger_rows(dst)
                self.assertEqual(sum(r['计提'] or 0 for r in after.values()),1120 if index==3 else 0)
                self.assertEqual(sum(r['差异'] or 0 for r in after.values()),-20 if index==3 else 0)
                repeated=C.classify_records([copy.deepcopy(rec)],C.LedgerIndex(dst),{})
                self.assertEqual(V.validate(repeated,after)['counts'],{'write':0,'skip':1,'conflict':0},repeated)
                path=dst


    def test_final_missing_quote_reports_hold_without_financial_write(self):
        helper=fixtures.DeliveryAboveReceivable()
        with tempfile.TemporaryDirectory() as temp:
            path=helper.create(temp)
            original=path.read_bytes()
            rec=foreign(helper.record(1,1500,1500))
            rec['fx_accrual_source'].pop('quote')
            plan=C.classify_records([rec],C.LedgerIndex(path),{})
            checked=V.validate(plan,A.read_ledger_rows(path))
            self.assertEqual(checked['counts']['write'],0,plan)
            self.assertEqual(len(plan['hold']),1,plan)
            self.assertEqual(plan['hold'][0]['code'],'E_FX_ACCRUAL')
            self.assertEqual(path.read_bytes(),original)


if __name__ == '__main__':
    unittest.main()
