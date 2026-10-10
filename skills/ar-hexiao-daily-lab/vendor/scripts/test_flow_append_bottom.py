import datetime as dt
import unittest
from test_flow_monthly import MonthlySafetyTest
import openpyxl

class AppendBottom(MonthlySafetyTest):
    def test_carry_appends_and_keeps_other_receipts_in_place(self):
        def tail(ws):
            ws.append([dt.date(2026,7,28),'其他客户',200,'汇款','OTHER',200,None])
            ws.cell(2,8,'=C2*2')
            ws.auto_filter.ref='A1:H3'
        self.modify(tail)
        changes,errors=self.run_items('2026-08-01',[self.entry()])
        self.assertEqual(errors,[])
        self.assertEqual(self.read('B3'),'其他客户')
        self.assertEqual(self.read('B4'),'测试甲')
        self.assertEqual(self.read('H4'),'=C4*2')
        self.assertEqual(changes[0]['行号'],4)
        self.assertEqual(self.read('F4'),'9000-1000=8000')
        changes,errors=self.run_items('2026-08-02',[self.entry('SO2',500)])
        self.assertEqual(errors,[])
        self.assertEqual(self.read('F4'),'9000-1000-500=7500')
        before=self.path.read_bytes()
        changes,errors=self.run_items('2026-08-02',[self.entry('SO2',500)])
        self.assertEqual(errors,[]);self.assertEqual(changes,[])
        self.assertEqual(self.path.read_bytes(),before)

    def test_filtered_tail_is_visible_and_append_ignores_format_only_rows(self):
        from openpyxl.worksheet.filters import FilterColumn, Filters
        def filtered(ws):
            ws.append([dt.date(2026,7,28),'其他客户',200,'汇款','OTHER',200,None])
            ws.cell(2,8,'=C2*2')
            ws.auto_filter.ref='A1:H3'
            ws.auto_filter.filterColumn=[FilterColumn(colId=1,filters=Filters(filter=['测试甲']))]
            ws.sheet_properties.filterMode=True
            ws.row_dimensions[3].hidden=True
            ws.cell(12,8).number_format='0.00'
        self.modify(filtered)
        changes,errors=self.run_items('2026-08-01',[self.entry()])
        self.assertEqual(errors,[])
        self.assertEqual(changes[0]['行号'],4)
        self.assertEqual(self.read('B3'),'其他客户')
        self.assertEqual(self.read('B4'),'测试甲')
        self.assertEqual(self.read('H4'),'=C4*2')
        wb=openpyxl.load_workbook(self.path);ws=wb['流水']
        self.assertFalse(ws.row_dimensions[3].hidden)
        self.assertFalse(ws.sheet_properties.filterMode)
        self.assertEqual(ws.auto_filter.filterColumn,[])
        self.assertEqual(ws.auto_filter.ref,'A1:H4')
        self.assertEqual(ws.cell(12,8).number_format,'0.00')
        wb.close()
        before=self.path.read_bytes()
        self.assertEqual(self.run_items('2026-08-01',[self.entry()]),([],[]))
        self.assertEqual(self.path.read_bytes(),before)

    def test_table_filters_clear_and_only_receipt_table_extends(self):
        from openpyxl.worksheet.table import Table
        from openpyxl.worksheet.filters import FilterColumn, Filters
        def tables(ws):
            ws.append([dt.date(2026,7,28),'其他客户',200,'汇款','OTHER',200,None])
            ws.add_table(Table(displayName='Receipts',ref='A1:G3'))
            for row,values in enumerate([['附表甲','附表乙','附表丙'],['A',1,2],['B',3,4]],1):
                for col,value in enumerate(values,10):ws.cell(row,col,value)
            ws.add_table(Table(displayName='OtherData',ref='J1:L3'))
        self.modify(tables)
        def filter_tables(ws):
            for table in ws.tables.values():
                table.autoFilter.filterColumn=[FilterColumn(colId=0,filters=Filters(filter=['A']))]
            ws.row_dimensions[3].hidden=True
        self.modify(filter_tables)
        # The existing high-level table guard remains; verify the copying
        # boundary itself does not extend an unrelated table or retain filters.
        import flow_append_rows
        after=self.root/'copied.xlsx'
        flow_append_rows.copy_rows(self.path,after,'流水',[(2,4,{col:None for col in range(1,8)})])
        wb=openpyxl.load_workbook(after);ws=wb['流水']
        self.assertEqual(ws.tables['Receipts'].ref,'A1:G4')
        self.assertEqual(ws.tables['OtherData'].ref,'J1:L3')
        self.assertTrue(all(not t.autoFilter.filterColumn for t in ws.tables.values()))
        self.assertFalse(ws.row_dimensions[3].hidden)
        self.assertEqual(ws.cell(3,10).value,'B')
        wb.close()

if __name__=='__main__':unittest.main()
