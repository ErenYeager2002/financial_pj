import datetime as dt
import unittest
import openpyxl
from test_flow_monthly import MonthlySafetyTest
import flow_monthly as M
import flow_ledger as L

class CarryLegacyTest(MonthlySafetyTest):
    def test_period_amount_is_not_opening(self):
        def edit(ws):
            ws['A2']=dt.date(2026,9,4);ws['C2']=3950;ws['D2']='冲预收'
            ws['E2']='SXSO26080411 SO26070560';ws['F2']='还剩：8189.21-3950=4239.21-1400=2839.21-56.16=2783.05'
        self.modify(edit)
        wb=openpyxl.load_workbook(self.path);month=M.legacy_month(wb.active,2,{'日期':1,'公司名称':2,'金额':3,'收款形式':4,'单号':5,'预收':6,'是否更新应收款':7})
        self.assertEqual(month['start'],'8189.21');self.assertEqual(month['remaining'],'2783.05');wb.close()

    def test_follow_legacy_period_amount(self):
        def edit(ws):
            ws['A2']=dt.date(2026,6,29);ws['C2']=118650.50;ws['F2']='还剩：113225.18转7月'
            ws.append([dt.date(2026,7,3),'测试甲',108148.97,'冲预收','SO26060098','还剩：113225.18-108148.97=5076.21',None])
        self.modify(edit)
        wb=openpyxl.load_workbook(self.path);chain=M.adopt_chain(wb.active,{'日期':1,'公司名称':2,'金额':3,'收款形式':4,'单号':5,'预收':6,'是否更新应收款':7},{'row_no':2})
        self.assertEqual(len(chain['months']),2);self.assertEqual(chain['months'][-1]['remaining'],'5076.21');wb.close()

    def test_carry_match_requires_source_order_evidence(self):
        def edit(ws):
            ws['A2']=dt.date(2026,5,14);ws['C2']=69.83;ws['D2']='冲预收';ws['E2']='JZSO25120703';ws['F2']='还剩：173.25-69.83=103.42'
        self.modify(edit)
        rec={'ar':'AR_PRIOR','shoukuan_date':'2025-03-01','hexiao_date':'2026-09-17','arrival_total':225.71,'customer':'测试甲','so':'SO26060498',
             'flow_carry_evidence':{'known_sos':['SO25120703'],'opening_limit':225.71}}
        L.annotate_records([rec],L.FlowLedger.from_paths([self.path]))
        self.assertEqual(rec['flow_row_no'],2);self.assertEqual(rec['flow_matched_by'],'同回款历史单号及预收承接')
        rec['flow_carry_evidence']['known_sos']=[]
        L.annotate_records([rec],L.FlowLedger.from_paths([self.path]))
        self.assertIsNone(rec.get('flow_row_no'))

    def test_write_and_repeat_preserves_legacy_amount(self):
        def edit(ws):
            ws['A2']=dt.date(2026,9,4);ws['C2']=3950;ws['D2']='冲预收'
            ws['E2']='SO26080411';ws['F2']='还剩：8189.21-3950=4239.21-1400=2839.21-56.16=2783.05'
        self.modify(edit)
        entry=self.entry(so='SO26090333',amount=2783.05)
        entry['flow_identity']={'date':'2026-09-04','payer':'测试甲','amount':3950}
        changes,errors=self.run_items('2026-09-20',[entry]);self.assertEqual(errors,[])
        self.assertEqual(self.read('C2'),3950)
        self.assertEqual(self.read('F2'),'8189.21-3950-1400-56.16-2783.05=0')
        before=self.path.read_bytes();changes,errors=self.run_items('2026-09-20',[entry])
        self.assertEqual(errors,[]);self.assertEqual(changes,[]);self.assertEqual(self.path.read_bytes(),before)

    def test_ambiguous_carries_do_not_auto_select(self):
        def edit(ws):
            ws['A2']=dt.date(2026,5,14);ws['C2']=69.83;ws['D2']='冲预收';ws['E2']='SO25120703';ws['F2']='173.25-69.83=103.42'
            ws.append([dt.date(2026,5,15),'测试甲',69.83,'冲预收','SO25120703','173.25-69.83=103.42',None])
        self.modify(edit)
        rec={'shoukuan_date':'2025-03-01','hexiao_date':'2026-09-17','arrival_total':225.71,'customer':'测试甲',
             'flow_carry_evidence':{'known_sos':['SO25120703'],'opening_limit':225.71}}
        L.annotate_records([rec],L.FlowLedger.from_paths([self.path]))
        self.assertEqual(rec['flow_hits'],2);self.assertIsNone(rec['flow_row_no'])

    def test_bad_formula_and_normal_receipt_are_not_legacy_period(self):
        for form,formula in [('汇款','173.25-69.83=103.42'),('冲预收','173.25-69.83=100')]:
            self.modify(lambda ws: (setattr(ws['C2'],'value',69.83),setattr(ws['D2'],'value',form),setattr(ws['F2'],'value',formula)))
            wb=openpyxl.load_workbook(self.path)
            with self.assertRaises(ValueError):M.legacy_month(wb.active,2,{'日期':1,'公司名称':2,'金额':3,'收款形式':4,'单号':5,'预收':6,'是否更新应收款':7})
            wb.close()
