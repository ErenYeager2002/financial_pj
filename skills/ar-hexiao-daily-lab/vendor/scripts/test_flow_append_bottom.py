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

if __name__=='__main__':unittest.main()
