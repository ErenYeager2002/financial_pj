"""Current visible carry conflicts stay concrete without selecting a candidate."""
import copy
import datetime as dt
import tempfile
import unittest
from pathlib import Path

import openpyxl
import flow_monthly as M


class CarryDiagnostics(unittest.TestCase):
    def fixture(self, path, extra=True):
        wb=openpyxl.Workbook();ws=wb.active;ws.title='流水'
        ws.append(['日期','公司名称','金额','收款形式','单号','预收','是否更新应收款'])
        ws.append([dt.date(2026,7,1),'合成客户',1000,'汇款','WXSO1 400 转8月','1000-400=600',None])
        ws.append([dt.date(2026,8,29),'合成客户',600,'冲预收','WXSO2 100','600-100=500',None])
        cols=M.columns(ws)
        chain=M.adopt_chain(ws,cols,{'row_no':2})
        if extra:
            ws.append([dt.date(2026,8,11),'合成客户',500,'冲预收','WXSO1 500 追加SO2 100','600-500=100-100=0','是'])
        wb.save(path);wb.close()
        M.save_state(path,{'schema':M.SCHEMA,'receipts':{'AR_TEST':chain}})
        return chain

    def test_visible_candidates_and_stored_chain_diagnostic(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'flow.xlsx';chain=self.fixture(path);before=copy.deepcopy(chain)
            wb=openpyxl.load_workbook(path);ws=wb.active;cols=M.columns(ws)
            item={'row_no':2,'monthly_receipt_history':{'periods':{}}}
            diagnostics=[]
            returned=M.refresh_current_chain(ws,cols,item,chain,diagnostics=diagnostics)
            self.assertEqual(returned,before);self.assertEqual(chain,before)
            self.assertEqual(len(diagnostics),1)
            for token in ('2个候选','流水','第3行','2026-08-29','金额600','第4行','2026-08-11','金额500','600-500=100-100=0'):
                self.assertIn(token,diagnostics[0])
            wb.close()

    def test_actual_write_boundary_retains_conflict_and_original_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'flow.xlsx';out=Path(d)/'out.xlsx';self.fixture(path)
            before=path.read_bytes()
            item={'ar':'AR_TEST','sheet':'流水','row_no':2,'monthly_date':'2026-08-11',
                  'monthly_receipt_history':{'periods':{}},
                  'monthly_entries':[{'key':'new-current','so':'SO1','date':'2026-08-11','amount':'500'}]}
            for validate_only in (True,False):
                with self.assertRaisesRegex(ValueError,'当前表重新核对失败') as caught:
                    M.write_file(path,out,[item],validate_only=validate_only)
                message=str(caught.exception)
                self.assertIn('第3行',message);self.assertIn('第4行',message)
                self.assertIn('不重复扣减',message)
                self.assertEqual(path.read_bytes(),before);self.assertFalse(out.exists())
                self.assertNotIn('diagnostics',str(M.load_state(path)))

    def test_unique_carry_has_no_spurious_diagnostic(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'flow.xlsx';chain=self.fixture(path,extra=False)
            wb=openpyxl.load_workbook(path);ws=wb.active;diagnostics=[]
            result=M.refresh_current_chain(ws,M.columns(ws),{'row_no':2,'monthly_receipt_history':{'periods':{}}},chain,diagnostics=diagnostics)
            self.assertEqual(diagnostics,[]);self.assertEqual(result,chain);wb.close()
