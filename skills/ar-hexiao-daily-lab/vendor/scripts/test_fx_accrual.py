"""Business examples for final-day original-currency accrual."""
import unittest
import fx_accrual as FX

class ForeignAccrualTests(unittest.TestCase):
    def source(self):
        return {"currency":"USD", "so_delivery_orig":10, "sod_delivery_orig":{"SOD1":10},
            "reconciliation_date":"2026-09-20", "quote":{
                "schema":"boc_spot_buying_v1", "currency":"USD", "rate_type":"现汇买入价", "quoted_unit":100,
                "buying_price_per_100":"2000", "rate_cny_per_unit":"20", "published_at":"2026-09-20T19:00:00",
                "timezone":"Asia/Shanghai", "reconciliation_date":"2026-09-20",
                "selection":"same_date_latest", "source":{"name":"中国银行","kind":"imported_workbook",
                "reference":"rates.xlsx#中行历史牌价", "sha256":"a"*64,"row":2}}}
    def test_whole_original_at_final_day_not_zhiyun_local(self):
        record={"sod":"SOD1","fx_accrual_source":self.source()}
        self.assertEqual(200, FX.accrual_amount(record,1000))
    def test_missing_quote_must_not_use_local_amount(self):
        source=self.source();source.pop("quote")
        with self.assertRaises(FX.FxAccrualError): FX.accrual_amount({"fx_accrual_source":source},1000)
    def test_future_quote_rejected(self):
        source=self.source();source["quote"]["published_at"]="2026-09-21T00:00:00"
        with self.assertRaises(FX.FxAccrualError): FX.accrual_amount({"fx_accrual_source":source},1000)
    def test_no_silent_rate_or_currency_tamper(self):
        source=self.source();source["quote"]["rate_cny_per_unit"]="100"
        with self.assertRaises(FX.FxAccrualError): FX.accrual_amount({"fx_accrual_source":source},1000)
    def test_whole_order_or_sod_original_currency_amount(self):
        source=self.source();source["so_delivery_orig"]=100;source["sod_delivery_orig"]={"SOD1":40,"SOD2":60}
        record={"sod":"SOD1","fx_accrual_source":source}
        self.assertEqual(800, FX.accrual_amount(record,4000))
        self.assertEqual(1200, FX.accrual_amount(record,6000,sod="SOD2"))
        self.assertEqual(2000, FX.accrual_amount(record,10000,whole_order=True))
    def test_sod_rounding_reconciles_to_whole_order_value(self):
        source=self.source();source["so_delivery_orig"]=2.02;source["sod_delivery_orig"]={"SOD1":1.01,"SOD2":1.01}
        source["quote"].update(buying_price_per_100="711.23",rate_cny_per_unit="7.1123")
        record={"sod":"SOD1","fx_accrual_source":source}
        self.assertEqual(7.18, FX.accrual_amount(record,100))
        self.assertEqual(7.19, FX.accrual_amount(record,100,sod="SOD2"))
        self.assertEqual(14.37, FX.accrual_amount(record,200,whole_order=True))
    def test_many_small_sods_never_get_negative_accrual(self):
        source=self.source();source["currency"]="JPY";source["so_delivery_orig"]=14
        source["sod_delivery_orig"]={f"SOD{i:02}":1 for i in range(14)}
        source["quote"].update(currency="JPY",buying_price_per_100="4.6",rate_cny_per_unit="0.046")
        record={"sod":"SOD00","fx_accrual_source":source}
        amounts=[FX.accrual_amount(record,1,sod=s) for s in source["sod_delivery_orig"]]
        self.assertEqual(0.64,round(sum(amounts),2))
        self.assertTrue(all(a>=0 for a in amounts))
    def test_legacy_frozen_plan_keeps_existing_behavior(self):
        self.assertEqual(1000, FX.accrual_amount({"currency":"USD"},1000))

if __name__=="__main__": unittest.main()
