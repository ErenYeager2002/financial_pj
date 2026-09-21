import tempfile,unittest
from pathlib import Path
import openpyxl
from classification_ledger import LedgerIndex
from classification_decision import classify_one

class MissingOrderPriorityTest(unittest.TestCase):
    def decide(self,*,present=False,year=2026,code="E5",no_ledger=False,unrouted=False):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'ledger.xlsx';book=openpyxl.Workbook();ws=book.active;ws.title='明细'
            ws.append(['SO','SOD','应收金额','计提','回款明细','是否结账','收款时间','收款方式'])
            ws.append(['SO_TARGET' if present else 'SO_OTHER','SOD_ONE',100,None,None,'否',None,None])
            book.save(p);book.close()
            rec={'ar':'AR_TEST','so':'SO_TARGET','sod':'','amount_orig':99.91,'amount_local':99.91,'currency':'CNY','forced_code':code,'forced_reason':'SOD金额无法唯一匹配','target_ledger_year':year,'status':'已核销'}
            ledger=None if no_ledger else LedgerIndex(p)
            if unrouted:
                from classification_runner import classify_records_by_year
                result=classify_records_by_year([rec],{2026:ledger} if ledger else {})
                return next(r for bucket in ['hold','auto','exception'] for r in result[bucket])
            return classify_one(rec,ledger,{},0.01,2026)

    def test_missing_current_order_precedes_sod_ambiguity(self):
        r=self.decide();self.assertEqual(r['code'],'E2');self.assertEqual(r['bucket'],'hold')
        self.assertIn('未包含这张订单',r['reason']);self.assertEqual(r['five_cols'],{})

    def test_missing_prior_order_keeps_year_specific_reason(self):
        r=self.decide(year=2025);self.assertEqual(r['code'],'E3');self.assertIn('2025',r['reason'])

    def test_missing_workbook_precedes_sod_ambiguity(self):
        for year,expected in [(2026,'E2'),(2025,'E3')]:
            with self.subTest(year=year):self.assertEqual(self.decide(year=year,no_ledger=True)['code'],expected)

    def test_present_order_keeps_sod_decision(self):
        self.assertEqual(self.decide(present=True)['code'],'E5')

    def test_parent_and_amount_safety_failures_keep_priority(self):
        for code in ['E_PARENT_WRITEOFF_MISMATCH','E_SYSTEM_OVER_WRITEOFF_UNRESOLVED','E4','E7']:
            with self.subTest(code=code):self.assertEqual(self.decide(code=code)['code'],code)

    def test_unrouted_ambiguity_checks_provided_workbooks(self):
        r=self.decide(unrouted=True)
        self.assertEqual(r['code'],'E2')
        self.assertIn('未包含这张订单',r['reason'])

    def test_unrouted_existing_order_is_not_reported_missing(self):
        self.assertEqual(self.decide(unrouted=True,present=True)['code'],'E5')
