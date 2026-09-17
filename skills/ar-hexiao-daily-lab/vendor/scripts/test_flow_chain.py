import unittest
import datetime as dt
import openpyxl
import flow_monthly as F

class FlowChainTest(unittest.TestCase):
    def book(self):
        b=openpyxl.Workbook();w=b.active;w.title='流水'
        w.append(['日期','公司名称','金额','收款形式','单号','预收','是否更新应收款'])
        w.append([dt.date(2026,7,1),'合成客户',9000,'汇款','WXSOOLD 转8月','9000-1000=8000',None])
        w.append([dt.date(2026,7,2),'其他',15,'汇款','',15,None])
        w.append([dt.date(2026,8,1),'合成客户',8000,'冲预收','SOSECOND','8000-3000=5000',None])
        w.append([dt.date(2026,8,2),'其他',15,'汇款','',15,None])
        w.append([dt.date(2026,9,1),'合成客户',5000,'冲预收','',5000,None])
        return b,w
    def test_unique_nonadjacent_chain_is_adopted(self):
        b,w=self.book();chain=F.adopt_chain(w,F.columns(w),{'row_no':2});b.close()
        self.assertEqual([m['row'] for m in chain['months']],[2,4,6])
        self.assertEqual([m['remaining'] for m in chain['months']],['8000','5000','5000'])
    def test_earlier_same_amount_row_is_not_a_successor(self):
        b,w=self.book();w.delete_rows(4,3);w['E2']='WX';w['F2']=9000
        w.append([dt.date(2026,6,1),'合成客户',9000,'冲预收','SOOTHER',0,None])
        chain=F.adopt_chain(w,F.columns(w),{'row_no':2});b.close()
        self.assertEqual(len(chain['months']),1)
    def test_ambiguous_successors_still_require_review(self):
        b,w=self.book();w.append([dt.date(2026,8,3),'合成客户',8000,'冲预收','',8000,None])
        with self.assertRaises(ValueError):F.adopt_chain(w,F.columns(w),{'row_no':2})
        b.close()
    def test_explicit_month_cannot_be_silently_ignored(self):
        b,w=self.book();w['E2']='WX转10月'
        with self.assertRaises(ValueError):F.adopt_chain(w,F.columns(w),{'row_no':2})
        b.close()

    def test_nonadjacent_write_readback_and_idempotence(self):
        import test_flow_monthly as T
        fixture=T.MonthlySafetyTest();fixture.setUp()
        try:
            def setup(w):
                w['E2']='WX\nSO0 1000\nWX转8月';w['F2']='9000-1000=8000'
                w.append([dt.date(2026,7,28),'其他客户',10,'汇款','WX',10,None])
                w.append([dt.date(2026,8,1),'测试甲',8000,'冲预收','SO1 3000','8000-3000=5000',None])
            fixture.modify(setup)
            entry=fixture.entry('SO2',5000)
            changes,errors=fixture.run_items('2026-08-02',[entry])
            self.assertEqual(errors,[]);self.assertEqual(len(changes),1)
            self.assertEqual(fixture.read('F4'),'8000-3000-5000=0')
            self.assertEqual(fixture.read('F3'),10)
            before=fixture.path.read_bytes()
            self.assertEqual(fixture.run_items('2026-08-02',[entry]),([],[]))
            self.assertEqual(fixture.path.read_bytes(),before)
            item={'ar':'AROTHER','sheet':'流水','row_no':4,'monthly_date':'2026-08-03','monthly_entries':[]}
            with self.assertRaisesRegex(ValueError,'另一笔到账'):
                F.write_file(fixture.path,fixture.path,[item],validate_only=True)
            self.assertEqual(fixture.path.read_bytes(),before)
        finally:fixture.tearDown()
