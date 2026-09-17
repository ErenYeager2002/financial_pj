import unittest
import datetime as dt
import tempfile
from pathlib import Path
import openpyxl
import flow_monthly as F
import xlsx_patch as X

class FlowCurrentBalanceTest(unittest.TestCase):
    def book(self):
        b=openpyxl.Workbook();w=b.active;w.title='流水'
        w.append(['日期','公司名称','金额','收款形式','单号','预收','是否更新应收款'])
        w.append([dt.date(2026,8,1),'合成客户',9000,'汇款','WXSOOLD','还剩：1000-100=900',None])
        return b,w
    def test_rolling_balance_keeps_full_conservation(self):
        b,w=self.book();m=F.legacy_month(w,2,F.columns(w));b.close()
        self.assertEqual(F.formula(m['start'],m['entries']),'9000-8000-100=900')
        self.assertEqual(m['remaining'],'900')
        self.assertTrue(all(not e['so'] for e in m['entries']))
    def test_rolling_balance_cannot_exceed_receipt(self):
        b,w=self.book();w['F2']='10000-9100=900'
        with self.assertRaises(ValueError):F.legacy_month(w,2,F.columns(w))
        b.close()
    def test_fixed_lookup_table_above_insertion_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            src,out=Path(tmp)/'in.xlsx',Path(tmp)/'out.xlsx';b,w=self.book()
            w['A4']=dt.date(2026,8,2);w['B4']='其他';w['C4']=10
            w['J4']='=VLOOKUP(C4,$T$1:$W$2,2,0)';w['T1']=10;w['U1']=7;b.save(src);b.close()
            F.insertion_guard(src,'流水',2)
            X.patch_cells(src,out,'流水',[],insertions=[(2,{})])
            b=openpyxl.load_workbook(out);self.assertEqual(b['流水']['J5'].value,'=VLOOKUP(C5,$T$1:$W$2,2,0)');b.close()
    def test_references_that_copy_translation_would_break_remain_rejected(self):
        for formula in ['=$T$5','=$T$1+T1','=INDIRECT("A"&1)','=OFFSET(A4,1,0)']:
            with self.subTest(formula=formula),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'in.xlsx';b,w=self.book();w['J4']=formula;b.save(path);b.close()
                with self.assertRaises(ValueError):F.insertion_guard(path,'流水',2)

    def test_source_formula_pointing_below_insertion_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'in.xlsx';b,w=self.book();w['J2']='=C4';b.save(path);b.close()
            with self.assertRaises(ValueError):F.insertion_guard(path,'流水',2)

    def test_print_title_above_insert_is_unaffected(self):
        for title,blocked in [('1:1',False),('4:4',True)]:
            with self.subTest(title=title),tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'in.xlsx';b,w=self.book();w.print_title_rows=title;b.save(path);b.close()
                if blocked:
                    with self.assertRaises(ValueError):F.insertion_guard(path,'流水',2)
                else:F.insertion_guard(path,'流水',2)
