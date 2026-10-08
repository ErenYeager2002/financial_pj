"""Exercise the real CLI with identical sources and obsolete audit files."""
import contextlib,copy,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import openpyxl
import classification_cli as CLI
from test_current_source_history import CurrentSourceHistory
from test_writeoff_local_amounts import DAY

class CurrentCLIInputs(unittest.TestCase):
    def test_old_journal_does_not_control_classification_entry(self):
        source=CurrentSourceHistory().build()
        source['orders'][0]['delivery_date']='2026-08-01'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);book=root/'ledger.xlsx';out=root/'result.json'
            wb=openpyxl.Workbook();ws=wb.active;ws.title='明细'
            ws.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
            ws.append(['SO_TEST','SOD_TEST',3000,None,None,'否',None,None,None]);wb.save(book);wb.close()
            journal=root/'03_台账'/'父回款顺序分配台账.json';journal.parent.mkdir()
            results=[]
            for text in (None,'broken old json',json.dumps({'version':3,'parents':{},'baseline_receipts':{}})):
                if text is not None:journal.write_text(text)
                with patch.object(CLI,'load_exports',return_value=[copy.deepcopy(source)]),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                    code=CLI.main(['--workspace',str(root),'--ledger-year','2026='+str(book),'--hexiao-date',DAY.isoformat(),'--out',str(out)])
                self.assertEqual(code,0,text)
                results.append(json.loads(out.read_text()))
            self.assertEqual(results[0],results[1]);self.assertEqual(results[0],results[2])

if __name__=='__main__':unittest.main()
