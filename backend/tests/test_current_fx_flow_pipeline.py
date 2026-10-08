"""Physical flow conversion uses its workbook rate, preserving source amounts."""
import copy
import unittest
import flow_monthly
from test_flow_source_receipts import SourceReceiptFlow

class ForeignFlowPipeline(unittest.TestCase):
    setUp=SourceReceiptFlow.setUp
    tearDown=SourceReceiptFlow.tearDown
    entry=SourceReceiptFlow.entry
    read=SourceReceiptFlow.read
    modify=SourceReceiptFlow.modify
    row=SourceReceiptFlow.row
    run_rows=SourceReceiptFlow.run_rows

    def test_formula_rate_full_write_and_repeat(self):
        def setup(ws):
            ws['C2']='=100*7';ws['F2']=700;ws['D2']='PayPal'
        self.modify(setup)
        # openpyxl does not calculate formulas. Supply the cached value that
        # exists in an Excel-saved business workbook; do not alter the formula.
        import io,zipfile,re
        archive=io.BytesIO()
        with zipfile.ZipFile(self.path) as source,zipfile.ZipFile(archive,'w') as target:
            for info in source.infolist():
                data=source.read(info.filename)
                if info.filename=='xl/worksheets/sheet1.xml':
                    data,count=re.subn(rb'<c r="C2"[^>]*>.*?</c>',
                        lambda m:re.sub(rb'<v\s*/>|<v>.*?</v>',b'<v>700</v>',m[0],flags=re.S),data,flags=re.S)
                    assert count==1
                target.writestr(info,data)
        self.path.write_bytes(archive.getvalue())
        rows=[]
        for so,original,local in [('SO1',60,450),('SO2',40,300)]:
            r=self.row(so,local)
            r.update(shoukuan_date='2026-07-27',hexiao_date='2026-07-28',arrival_total=100,
                     business_arrival_total=100,sales_name='测试甲')
            r['write_currency_audit'].update(currency='美元USD',amount_orig=original)
            r['flow_source_receipt'].update(currency='美元USD',amount_orig=str(original))
            rows.append(r)
        from flow_ledger import FlowLedger,annotate_records
        annotate_records(rows,FlowLedger.from_paths([self.path]))
        self.assertTrue(all(r['flow_hits']==1 and '原币公式' in r['flow_matched_by'] for r in rows))
        self.assertTrue(all(r['flow_identity']['amount']==700 for r in rows))
        before=copy.deepcopy(rows)
        changed,errors=self.run_rows(rows)
        self.assertEqual(errors,[])
        self.assertTrue(changed)
        self.assertEqual(self.read('C2'),'=100*7')
        self.assertEqual(self.read('F2'),'700-420-280=0')
        self.assertFalse(self.read('G2'))  # P&L was held; flow deduction is independent.
        self.assertEqual(rows,before)     # Source local amounts remain 450 and 300.
        raw=self.path.read_bytes()
        self.assertEqual(self.run_rows(rows),([],[]))
        self.assertEqual(self.path.read_bytes(),raw)

if __name__=='__main__':unittest.main()
