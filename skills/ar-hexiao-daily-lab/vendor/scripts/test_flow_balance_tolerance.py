import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
import openpyxl
import flow_monthly as M


class BalanceTolerance(unittest.TestCase):
    def item(self,amount,opening):
        e={'key':'source|'+json.dumps(['AR_TEST','SO1','2026-08-03',['HX1','R1']]),'case_id':'AR_TEST|SO1','so':'SO1','date':'2026-08-03','amount':str(amount)}
        return {'ar':'AR_TEST','row_no':2,'sheet':'流水','monthly_date':'2026-08-03','monthly_entries':[e],
                'monthly_receipt_history':{'basis':'current_source_reconcile','date':'2026-08-03','opening':str(opening),'entries':[e],'known_sos':['SO1']},
                'so_outcomes':[{'so':'SO1','completed':True}]}

    def book(self,path,opening,balance,form='汇款'):
        w=openpyxl.Workbook();s=w.active;s.title='流水'
        s.append(['日期','公司名称','金额','收款形式','单号','预收','是否更新应收款'])
        s.append([dt.date(2026,8,3),'合成客户',opening,form,'WXSO1',balance,'是'])
        w.save(path);w.close()

    def test_balance_restores_exact_current_amount_and_repeats_without_deduction(self):
        for source,previous,expected in [(90.03,10,'100-90.03=9.97'),(89.97,10,'100-89.97=10.03'),(91,10,'100-91=9')]:
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/'flow.xlsx';out=Path(d)/'out.xlsx';self.book(p,100,previous)
                item=self.item(source,100);unchanged=copy.deepcopy(item)
                changes=M.write_file(p,out,[item]);self.assertEqual(item,unchanged)
                self.assertEqual(changes[0]['核销事项'],[]);self.assertIn('已确认一元内尾差',changes[0])
                p.write_bytes(out.read_bytes());w=openpyxl.load_workbook(p)
                self.assertEqual(w.active['F2'].value,expected);self.assertEqual(w.active['C2'].value,100);w.close()
                before=p.read_bytes();self.assertEqual(M.write_file(p,out,[item]),[]);self.assertEqual(p.read_bytes(),before)

    def test_small_carry_amount_typo_uses_existing_equation_and_current_source(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'flow.xlsx';out=Path(d)/'out.xlsx';self.book(p,33.36,'33.6-33.6=0','冲预收')
            item=self.item(33.6,33.36);changes=M.write_file(p,out,[item])
            self.assertEqual(changes[0]['核销事项'],[])
            p.write_bytes(out.read_bytes());w=openpyxl.load_workbook(p)
            self.assertEqual(w.active['C2'].value,33.36);self.assertEqual(w.active['F2'].value,'33.6-33.6=0');w.close()
            self.assertEqual(M.write_file(p,out,[item]),[])

    def test_large_difference_missing_so_future_and_invalid_equation_stay_rejected(self):
        for mode in ['large','missing','future','invalid','negative']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                p=Path(d)/'flow.xlsx';out=Path(d)/'out.xlsx';self.book(p,100,10)
                item=self.item(91.01 if mode=='large' else 90.03,100)
                w=openpyxl.load_workbook(p)
                if mode=='missing':w.active['E2']='WXSO1 SO2'
                if mode=='future':item['monthly_receipt_history']['entries'][0]['date']='2026-08-04'
                if mode=='invalid':w.active['F2']='100-90=9'
                if mode=='negative':item=self.item(100.5,100);w.active['F2']=0
                w.save(p);w.close();before=p.read_bytes()
                with self.assertRaises(ValueError):M.write_file(p,out,[item])
                self.assertEqual(p.read_bytes(),before);self.assertFalse(out.exists())
