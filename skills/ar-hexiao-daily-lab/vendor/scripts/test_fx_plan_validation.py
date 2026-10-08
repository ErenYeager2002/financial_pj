"""FX accrual uses final-day BOC buying while receipts keep source local values."""
import copy
import tempfile
import unittest
from pathlib import Path
import openpyxl
import classify_hexiao as C
import validate_plan as V
import apply_to_copy as W


def fx_source(original=10, rate=20, sods=None):
    return {"currency": "USD", "so_delivery_orig": original,
            "sod_delivery_orig": sods or {"SOD_FX": original},
            "reconciliation_date": "2026-09-20",
            "quote": {"schema": "boc_spot_buying_v1", "currency": "USD",
                      "rate_type": "现汇买入价", "quoted_unit": 100,
                      "buying_price_per_100": str(rate * 100), "rate_cny_per_unit": str(rate),
                      "published_at": "2026-09-20T16:00:00", "timezone": "Asia/Shanghai",
                      "reconciliation_date": "2026-09-20", "selection": "same_date_latest",
                      "source": {"name": "中国银行", "kind": "imported_workbook",
                                 "reference": "rates.xlsx#中行历史牌价", "sha256": "a" * 64, "row": 2}}}


class FxPlanValidationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.src = self.root / "ledger.xlsx"
        book = openpyxl.Workbook(); sheet = book.active; sheet.title = "明细"
        sheet.append(["SO", "SOD", "应收金额", "计提", "回款明细", "是否结账", "收款时间", "收款方式(支/汇/现)", "差异"])
        sheet.append(["SO_FX", "SOD_FX", 1000, None, None, "否", None, None, None])
        book.save(self.src); book.close()

    def tearDown(self):
        self.temp.cleanup()

    def record(self, amount=1000, cumulative=1000, ar="AR_FX", num="HX_FX"):
        return {"ar": ar, "so": "SO_FX", "sod": "SOD_FX",
                "currency": "USD", "amount_orig": amount / 100,
                "amount_local": amount, "deliver_local": 1000,
                "so_delivery_local": 1000, "cumulative_received_local": cumulative,
                "hexiao_date": "2026-09-20", "shoukuan_date": "2026-09-20",
                "status": "已核销", "writeoff_sequence_key": ["2026-09-20", num, num],
                "fx_accrual_source": fx_source()}

    def test_final_accrual_revalues_original_not_receipt(self):
        rec = self.record()
        plan = C.classify_records([rec], C.LedgerIndex(self.src), {})
        self.assertEqual(len(plan["auto"]), 1, plan)
        item = plan["auto"][0]
        self.assertEqual(item["five_cols"]["计提"], 200)
        self.assertEqual(item["five_cols"]["回款明细"], 1000)
        self.assertEqual(item["derived_cols"]["差异"], 800)
        checked = V.validate(plan, W.read_ledger_rows(self.src))
        self.assertFalse(checked["conflict"], checked)
        self.assertEqual(len(checked["write"]), 1)
        out = self.root / "written.xlsx"
        W.write_plan(self.src, out, checked["write"])
        self.assertEqual(W.verify_written(out, checked["write"]), [])
        self.assertEqual(V.check_one(item, W.read_ledger_rows(out))["verdict"], "skip")

    def test_installments_accrue_whole_original_only_on_final_row(self):
        first = self.record(400, 400, "AR_FIRST", "HX_FIRST")
        last = self.record(600, 1000, "AR_LAST", "HX_LAST")
        plan = C.classify_records([first, last], C.LedgerIndex(self.src), {})
        self.assertEqual(len(plan["auto"]), 2, plan)
        checked = V.validate(plan, W.read_ledger_rows(self.src))
        self.assertFalse(checked["conflict"], checked)
        self.assertEqual(len(checked["write"]), 2)
        operation = checked["write"][0]["row_operation"]
        self.assertEqual([step["five_cols"]["计提"] for step in operation["steps"]], [None, 200])
        self.assertEqual([step["five_cols"]["回款明细"] for step in operation["steps"]], [400, 600])
        self.assertEqual(operation["steps"][-1]["derived_cols"]["差异"], 800)
        out = self.root / "installments.xlsx"
        W.write_plan(self.src, out, checked["write"])
        self.assertEqual(W.verify_written(out, checked["write"]), [])
        repeated = C.classify_records([first, last], C.LedgerIndex(out), {})
        second = V.validate(repeated, W.read_ledger_rows(out))
        self.assertFalse(second["write"], second)
        self.assertFalse(second["conflict"], second)

    def test_complete_multiple_sods_use_each_original_amount(self):
        book = openpyxl.load_workbook(self.src)
        book["明细"].cell(2, 2, "SOD_A"); book["明细"].cell(2, 3, 400)
        book["明细"].append(["SO_FX", "SOD_B", 600, None, None, "否", None, None, None])
        book.save(self.src); book.close()
        records = []
        for sod, amount in [("SOD_A", 400), ("SOD_B", 600)]:
            rec = self.record(amount, amount)
            rec.update(sod=sod, deliver_local=amount, all_sods=["SOD_A", "SOD_B"],
                       sod_delivery_local={"SOD_A": 400, "SOD_B": 600},
                       fx_accrual_source=fx_source(sods={"SOD_A": 4, "SOD_B": 6}))
            records.append(rec)
        plan = C.classify_records(records, C.LedgerIndex(self.src), {})
        self.assertFalse(plan["hold"], plan)
        self.assertFalse(plan["exception"], plan)
        checked = V.validate(plan, W.read_ledger_rows(self.src))
        self.assertFalse(checked["conflict"], checked)
        self.assertEqual(len(checked["write"]), 2, checked)
        self.assertEqual(sorted(item["five_cols"]["计提"] for item in checked["write"]), [80, 120])
        self.assertEqual(sum(item["five_cols"]["回款明细"] for item in checked["write"]), 1000)
        self.assertEqual(sum(item["derived_cols"]["差异"] for item in checked["write"]), 800)

    def test_fx_accrual_tampering_is_rejected_before_write(self):
        plan = C.classify_records([self.record()], C.LedgerIndex(self.src), {})
        bad = copy.deepcopy(plan)
        bad["auto"][0]["five_cols"]["计提"] = 201
        checked = V.validate(bad, W.read_ledger_rows(self.src))
        self.assertFalse(checked["write"], checked)
        self.assertEqual(len(checked["conflict"]), 1, checked)
        missing = copy.deepcopy(plan)
        missing["auto"][0]["fx_accrual_source"]["quote"] = {}
        missing["auto"][0]["split_payment_source"]["fx_accrual_source"]["quote"] = {}
        checked = V.validate(missing, W.read_ledger_rows(self.src))
        self.assertFalse(checked["write"], checked)
        self.assertEqual(len(checked["conflict"]), 1, checked)

    def test_prior_sod_backfill_uses_final_whole_order_date(self):
        book = openpyxl.load_workbook(self.src); sheet = book["明细"]
        sheet.cell(2, 2, "SOD_A"); sheet.cell(2, 3, 400)
        sheet.cell(2, 5, 400); sheet.cell(2, 6, "是")
        sheet.cell(2, 7, "2026-09-01"); sheet.cell(2, 8, "汇")
        sheet.append(["SO_FX", "SOD_B", 600, None, None, "否", None, None, None])
        book.save(self.src); book.close()
        rec = self.record(600, 600)
        rec.update(sod="SOD_B", deliver_local=600, all_sods=["SOD_A", "SOD_B"],
                   sod_delivery_local={"SOD_A": 400, "SOD_B": 600},
                   fx_accrual_source=fx_source(sods={"SOD_A": 4, "SOD_B": 6}))
        plan = C.classify_records([rec], C.LedgerIndex(self.src), {})
        checked = V.validate(plan, W.read_ledger_rows(self.src))
        self.assertFalse(checked["conflict"], checked)
        self.assertEqual(len(checked["write"]), 1, checked)
        item = checked["write"][0]
        self.assertEqual(item["five_cols"]["计提"], 120)
        self.assertEqual(item["so_accrual_backfills"][0]["accrual"], 80)
        self.assertEqual(item["so_accrual_backfills"][0]["difference"], 320)
        out = self.root / "backfill.xlsx"
        W.write_plan(self.src, out, checked["write"])
        self.assertEqual(W.verify_written(out, checked["write"]), [])
        tampered = copy.deepcopy(plan)
        tampered["auto"][0]["so_accrual_backfills"][0]["accrual"] = 81
        tampered["auto"][0]["so_accrual_backfills"][0]["difference"] = 319
        rejected = V.validate(tampered, W.read_ledger_rows(self.src))
        self.assertFalse(rejected["write"], rejected)
        self.assertEqual(len(rejected["conflict"]), 1, rejected)


if __name__ == "__main__": unittest.main()
