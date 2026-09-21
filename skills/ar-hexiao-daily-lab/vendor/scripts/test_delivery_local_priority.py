import copy
import unittest
from classification_expansion import expand_payment
from classification_amounts import _order_delivery_local

class DeliveryLocalPriorityTest(unittest.TestCase):
    def payment(self, current=100, local=700, itemized=True, rate=None, multi=False):
        order={'so':'SO_LOCAL','deliver':100,'deliver_local':700,'currency':'USD'}
        if rate is not None: order['rate']=rate
        p={'ar':'AR_LOCAL','currency':'USD','amount_orig':current,'amount_local':local,
           'arrival_date':'2026-09-01','hexiao_date':'2026-09-01',
           'orders':[order], 'sod_lines':{'SO_LOCAL':[{'sod':'SOD_LOCAL','deliver':100}]}}
        if itemized:
            p.update(writeoffs={'SO_LOCAL':current},writeoffs_local={'SO_LOCAL':local},
                     cumulative_writeoffs={'SO_LOCAL':current},cumulative_writeoffs_local={'SO_LOCAL':local})
        if multi:p['sod_lines']['SO_LOCAL']=[{'sod':'SOD_A','deliver':40},{'sod':'SOD_B','deliver':60}]
        return p
    def test_order_local_without_rate(self):
        p=self.payment()
        self.assertEqual(_order_delivery_local(100,p,{},p['orders'][0]),(700,None))
    def test_delivery_local_beats_order_rate(self):
        p=self.payment(rate=7.2)
        self.assertEqual(_order_delivery_local(100,p,{},p['orders'][0]),(700,None))
    def test_parent_partial_retains_local_allocation(self):
        r=expand_payment(self.payment(40,280,False),{})
        self.assertEqual(len(r),1)
        self.assertEqual((r[0]['amount_local'],r[0]['deliver_local'],r[0]['so_delivery_local']),(280,700,700))
    def test_receipt_local_does_not_revalue_delivery(self):
        r=expand_payment(self.payment(40,288,True,7.2),{})[0]
        self.assertEqual((r['amount_local'],r['cumulative_received_local'],r['deliver_local']),(288,288,700))
    def test_multi_sod_uses_delivery_ratio_once(self):
        r=expand_payment(self.payment(100,720,True,7.2,True),{})
        self.assertEqual({x['sod']:x['deliver_local'] for x in r},{'SOD_A':280,'SOD_B':420})
        self.assertEqual(sum(x['amount_local'] for x in r),720)
        self.assertTrue(all(x['so_delivery_local']==700 for x in r))
    def test_order_rate_still_used_without_local(self):
        p=self.payment(rate=7.2);p['orders'][0].pop('deliver_local')
        self.assertEqual(_order_delivery_local(100,p,{},p['orders'][0]),(720,None))

    def test_delivery_discrepancy_is_reported(self):
        r=expand_payment(self.payment(rate=7.2),{})[0]
        self.assertIn('W_DELIVERY_LOCAL_RATE_DIFFERENCE',r['warning_codes'])
    def test_delivery_fallback_uses_order_local(self):
        p=self.payment();p.pop('writeoffs_local')
        p['duplicate_writeoff_audit']={'comparison_basis':'delivery_fallback_local'}
        r=expand_payment(p,{})[0]
        self.assertNotEqual(r.get('forced_code'),'E6')
        self.assertEqual((r['amount_local'],r['deliver_local']),(700,700))

    def test_local_delivery_write_readback_and_repeat(self):
        import openpyxl
        import test_receipt_ownership as fixtures
        import classify_hexiao as C
        import validate_plan as V
        import apply_to_copy as W
        import fallback_allocation_ledger as F
        helper=fixtures.ReceiptOwnershipTest();helper.setUp()
        try:
            wb=openpyxl.load_workbook(helper.path);ws=wb['明细']
            ws.cell(2,1,'SO_LOCAL');ws.cell(2,2,'SOD_LOCAL');ws.cell(2,3,700)
            wb.save(helper.path);wb.close()
            p=self.payment(rate=7.2);p['status']='已核销'
            rec=expand_payment(p,{})[0]
            for repeat in [False,True]:
                ledger=C.LedgerIndex(helper.path)
                ledger.baseline_receipt_state=F.load(helper.root).get('baseline_receipts',{})
                plan=C.classify_records([rec],ledger,{})
                plan['hexiao_date']=p['hexiao_date']
                checked=V.validate(plan,W.read_ledger_rows(helper.path))
                checked['hexiao_date']=p['hexiao_date']
                self.assertFalse(checked['conflict'],checked)
                self.assertEqual(len(checked['write']),0 if repeat else 1,plan)
                if repeat:self.assertEqual(len(checked['skip']),1,checked)
                else:
                    self.assertEqual(checked['write'][0]['five_cols']['回款明细'],700)
                    helper.apply(checked)
            wb=openpyxl.load_workbook(helper.path,data_only=True)
            self.assertEqual(wb['明细'].cell(2,5).value,700);wb.close()
        finally:helper.tearDown()

    def test_new_snapshot_does_not_inherit_old_delivery_local(self):
        import datetime as dt
        import tempfile
        from pathlib import Path
        import openpyxl
        from classification_exports import load_exports
        day=dt.date(2026,9,1)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);out=root/'01_智云导出';out.mkdir()
            def save(name,headers,rows):
                wb=openpyxl.Workbook();ws=wb.active;ws.append(headers)
                for row in rows:ws.append(row)
                wb.save(out/name);wb.close()
            save('回款记录_20260901.xlsx',['AR','核销日期','到账日期','到账金额原币','到账金额本币','原币币种'],[['AR_LOCAL',day,day,100,700,'USD']])
            headers=['AR','SO','交付额原币','交付额本币','汇率','币种','项目交付日期']
            save('订单交付_20260901.xlsx',headers,[['AR_LOCAL','SO_LOCAL',100,700,7, 'USD',day]])
            save('订单交付_20260902.xlsx',headers,[['AR_LOCAL','SO_LOCAL',200,None,7.3,'USD',day]])
            order=load_exports(root,day)[0]['orders'][0]
            self.assertEqual(order['deliver'],200)
            self.assertIsNone(order['deliver_local'],'new original must not pair with stale local')
            self.assertEqual(_order_delivery_local(200,{}, {},order),(1460,None))
