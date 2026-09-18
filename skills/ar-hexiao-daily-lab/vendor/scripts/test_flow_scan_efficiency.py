"""Bound full-sheet scans while exercising real history and multi-item validation."""
import copy
import datetime as dt
import unittest
from unittest.mock import patch
import openpyxl
import apply_flow
import build_flow_plan
import flow_monthly
from test_flow_monthly import MonthlySafetyTest as Fixture

class FlowScanEfficiency(unittest.TestCase):
    setUp = Fixture.setUp
    tearDown = Fixture.tearDown
    entry = Fixture.entry
    modify = Fixture.modify
    plans = Fixture.plans

    def history(self):
        self.modify(lambda ws: [ws.append([dt.date(2026,7,27), payer,9000,'汇款','WX',9000,None])
                                for payer in ['测试乙','测试丙']])
        entries=[self.entry('OLD'+str(i),1000,'AR'+str(i),i+2,payer)
                 for i,payer in enumerate(['测试甲','测试乙','测试丙'])]
        plan,checked=self.plans('2026-07-28',entries)
        final=build_flow_plan.finalize_plan_after_ledger(plan,checked)
        self.assertEqual(apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status')[1],[])
        return entries

    def test_validation_scans_once_per_sheet_not_per_history_or_receipt(self):
        self.history()
        entries=[self.entry('NEW'+str(i),500,'AR'+str(i),i+2,payer)
                 for i,payer in enumerate(['测试甲','测试乙','测试丙'])]
        plan,checked=self.plans('2026-07-29',entries)
        final=build_flow_plan.finalize_plan_after_ledger(plan,checked)
        before=self.path.read_bytes()
        with patch.object(flow_monthly,'columns',wraps=flow_monthly.columns) as scans:
            flow_monthly.write_file(self.path,self.path,copy.deepcopy(final['items']),validate_only=True)
        self.assertLessEqual(scans.call_count,1,'full sheet scans grow with history and current receipts')
        self.assertEqual(self.path.read_bytes(),before)

    def test_unrelated_history_is_still_validated(self):
        self.history()
        # Damage a receipt outside the current write selection.
        import xlsx_patch
        changed=self.path.with_name('changed.xlsx')
        xlsx_patch.patch_cells(self.path,changed,'流水',[(4,2,'被修改客户')])
        changed.replace(self.path)
        self.assertEqual(len(flow_monthly.load_state(self.path)['receipts']),3)
        plan,checked=self.plans('2026-07-29',[self.entry('NEW',500,'AR0',2,'测试甲')])
        final=build_flow_plan.finalize_plan_after_ledger(plan,checked)
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):
            flow_monthly.write_file(self.path,self.path,final['items'],validate_only=True)
        self.assertEqual(self.path.read_bytes(),before)

    def test_header_detection_reads_only_existing_search_window(self):
        book=openpyxl.Workbook();sheet=book.active
        for _ in range(7):sheet.append(['标题'])
        sheet.append(['日期','公司名称','金额','收款形式','单号','预收','是否更新应收款'])
        for _ in range(100):sheet.append(['业务行'])
        original=sheet.iter_rows;visited=[]
        def tracked(*args,**kwargs):
            for row in original(*args,**kwargs):
                visited.append(row)
                yield row
        with patch.object(sheet,'iter_rows',side_effect=tracked):
            cols=flow_monthly.columns(sheet)
        self.assertEqual(cols['日期'],1);self.assertEqual(cols['单号'],5)
        self.assertLessEqual(len(visited),8,'header detection reads unused business rows')
        book.close()

    def test_separate_workbooks_keep_independent_column_maps(self):
        books=[]
        try:
            for header,wanted in [(['日期','公司名称','金额','收款形式','单号','预收','是否更新应收款'],5),
                                   (['单号','金额','公司名称','日期','预收','收款形式','是否更新应收款'],1)]:
                book=openpyxl.Workbook();books.append(book);book.active.title='流水';book.active.append(header)
                self.assertEqual(flow_monthly.columns(book.active)['单号'],wanted)
        finally:
            for book in books:book.close()
