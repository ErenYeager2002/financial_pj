"""Import → immutable task quote → source-bound original delivery → write gate."""
import copy
import tempfile
import unittest
from pathlib import Path
import openpyxl
import fx_accrual as FX
import fx_accrual_sources as S
import test_fx_plan_validation as P
import classify_hexiao as C
import validate_plan as V
import apply_to_copy as A

class FxQuoteWorkflow(unittest.TestCase):
    def test_import_latest_and_readback_reuses_frozen_quote(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/"ledger.xlsx"
            book=openpyxl.Workbook();sheet=book.active;sheet.title="中行历史牌价"
            sheet.append(["货币名称","现汇买入价","发布时间"])
            sheet.append(["美元",1900,"2026-09-20 09:00:00"])
            sheet.append(["美元",2000,"2026-09-20 18:00:00"])
            book.save(path);book.close()
            payments=[{"ar":"AR1","currency":"美元USD","hexiao_date":"2026-09-20",
                "orders":[{"so":"SO1","currency":"美元USD","deliver":10}],
                "sod_lines":{"SO1":[{"sod":"SOD1","currency":"USD","deliver":10}]}}]
            S.prepare_quotes(payments,{2026:path},root)
            record={"so":"SO1","sod":"SOD1","currency":"美元USD","hexiao_date":"2026-09-20","amount_orig":4}
            S.attach_source(payments[0],record)
            self.assertEqual(FX.accrual_amount(record,1000),200)
            quote=record["fx_accrual_source"]["quote"]
            self.assertEqual(quote["published_at"],"2026-09-20T18:00:00")
            self.assertEqual(quote["rate_cny_per_unit"],"20")
            path.unlink() # staged review must not fetch a newer quote or re-read changed materials
            again=copy.deepcopy(payments);S.prepare_quotes(again,{2026:path},root)
            self.assertEqual(again[0]["_boc_fx_quotes"],payments[0]["_boc_fx_quotes"])
            snapshot=root/"03_台账"/S.SNAPSHOT
            snapshot.write_text(snapshot.read_text().replace('"20"','"21"'))
            with self.assertRaises(ValueError):S.prepare_quotes(again,{2026:path},root)
    def test_missing_final_quote_holds_only_affected_order(self):
        helper=P.FxPlanValidationTest();helper.setUp()
        try:
            book=openpyxl.load_workbook(helper.src);book["明细"].append(["SO_CNY","SOD_CNY",1000,None,None,"否",None,None,None]);book.save(helper.src);book.close()
            foreign=helper.record();foreign["fx_accrual_source"].pop("quote")
            domestic=helper.record(ar="AR_CNY",num="HX_CNY")
            domestic.update(so="SO_CNY",sod="SOD_CNY",currency="CNY",amount_orig=1000)
            domestic.pop("fx_accrual_source")
            result=C.classify_records([foreign,domestic],C.LedgerIndex(helper.src),{})
            self.assertEqual(result["counts"],{"auto":1,"hold":1,"exception":0,"total":2})
            self.assertEqual(result["hold"][0]["code"],"E_FX_ACCRUAL")
            checked=V.validate(result,A.read_ledger_rows(helper.src))
            self.assertEqual(checked["counts"],{"write":1,"skip":0,"conflict":0})
        finally:helper.tearDown()
    def test_sod_cent_allocation_survives_backfill_write_and_readback(self):
        helper=P.FxPlanValidationTest();helper.setUp()
        try:
            book=openpyxl.load_workbook(helper.src);sheet=book["明细"]
            sheet.cell(2,2,"SOD_A");sheet.cell(2,3,101);sheet.cell(2,5,101);sheet.cell(2,6,"是")
            sheet.cell(2,7,"2026-09-01");sheet.cell(2,8,"汇")
            sheet.append(["SO_FX","SOD_B",101,None,None,"否",None,None,None]);book.save(helper.src);book.close()
            rec=helper.record(101,101);rec.update(sod="SOD_B",amount_orig=1.01,deliver_local=101,so_delivery_local=202,
                all_sods=["SOD_A","SOD_B"],sod_delivery_local={"SOD_A":101,"SOD_B":101},
                fx_accrual_source=P.fx_source(original=2.02,rate=7.1123,sods={"SOD_A":1.01,"SOD_B":1.01}))
            # Exact strings model the official decimal quotation.
            rec["fx_accrual_source"]["quote"].update(buying_price_per_100="711.23",rate_cny_per_unit="7.1123")
            checked=V.validate(C.classify_records([rec],C.LedgerIndex(helper.src),{}),A.read_ledger_rows(helper.src))
            self.assertFalse(checked["conflict"],checked)
            output=helper.root/"cents.xlsx";A.write_plan(helper.src,output,checked["write"])
            self.assertEqual(A.verify_written(output,checked["write"]),[])
            rows=A.read_ledger_rows(output)
            self.assertEqual(sorted(r["计提"] for r in rows.values()),[7.18,7.19])
            self.assertEqual(round(sum(r["计提"] for r in rows.values()),2),14.37)
            self.assertEqual(round(sum(r["差异"] for r in rows.values()),2),187.63)
            self.assertEqual(V.validate(C.classify_records([rec],C.LedgerIndex(output),{}),rows)["counts"],{"write":0,"skip":1,"conflict":0})
        finally:helper.tearDown()
    def test_different_order_and_sod_currency_cannot_value_whole_order(self):
        p={"_boc_fx_quotes":{},"currency":"USD","hexiao_date":"2026-09-20",
           "orders":[{"so":"SO1","currency":"EUR","deliver":10}],
           "sod_lines":{"SO1":[{"sod":"SOD1","currency":"USD","deliver":10}]}}
        rec={"so":"SO1","sod":"SOD1","currency":"USD","hexiao_date":"2026-09-20"}
        S.attach_source(p,rec)
        with self.assertRaises(FX.FxAccrualError):FX.accrual_amount(rec,1000)

if __name__=="__main__":unittest.main()
