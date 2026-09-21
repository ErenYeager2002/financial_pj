import tempfile,unittest
from pathlib import Path
import openpyxl
import classify_hexiao as C
import validate_plan as V
import apply_to_copy as W
import fallback_allocation_ledger as F

class SplitBaselineTest(unittest.TestCase):
    def test_missing_historical_cent_does_not_reduce_original_receivable(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/'ledger.xlsx';out=root/'out.xlsx'
            book=openpyxl.Workbook();sheet=book.active;sheet.title='明细'
            sheet.append(['SO','SOD','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
            sheet.append(['SO_TEST','SOD_TEST',469.33,None,None,'否',None,None,None])
            sheet.append(['SO_TEST','SOD_TEST',69.85,None,69.85,'是','2026-08-28','汇',None])
            book.save(src);book.close()
            records=[]
            for ar,num,amount,cumulative in [('AR_FIRST','HX_FIRST',424.71,494.57),('AR_SECOND','HX_SECOND',44.61,539.18)]:
                records.append({'ar':ar,'so':'SO_TEST','sod':'SOD_TEST','amount_orig':amount,'amount_local':amount,'currency':'CNY','deliver_local':539.18,'cumulative_received_local':cumulative,'shoukuan_date':'2026-07-01','hexiao_date':'2026-09-17','status':'已核销','writeoff_sequence_key':['2026-09-17',num,num]})
            plan=C.classify_records(records,C.LedgerIndex(src),{})
            checked=V.validate(plan,W.read_ledger_rows(src))
            self.assertEqual(len(checked['write']),2)
            operation=checked['write'][0]['row_operation']
            self.assertEqual([step['receivable'] for step in operation['steps']],[424.71,44.62])
            W.write_plan(src,out,checked['write'])
            self.assertEqual(W.verify_written(out,checked['write']),[])
            rows=[r for r in W.read_ledger_rows(out).values() if r['SO']=='SO_TEST']
            self.assertAlmostEqual(sum(row[2] or 0 for row in openpyxl.load_workbook(out,read_only=True).active.iter_rows(min_row=2,values_only=True) if row[0]=='SO_TEST'),539.18,places=2)
            self.assertAlmostEqual(sum(r['回款明细'] or 0 for r in rows),539.17,places=2)
            self.assertIn(69.85,[r['回款明细'] for r in rows])
            repeated=C.classify_records(records,C.LedgerIndex(out),{})
            second=V.validate(repeated,W.read_ledger_rows(out))
            self.assertEqual(second["write"],[])
            self.assertEqual(second["conflict"],[])
