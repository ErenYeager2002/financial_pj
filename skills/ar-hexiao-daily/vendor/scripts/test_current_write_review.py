"""Physical write verification must not depend on obsolete allocation journals."""
import contextlib,io,json,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import openpyxl
import verify_execution_write as E

class CurrentWriteReview(unittest.TestCase):
    def test_unchanged_material_passes_without_committing_old_review_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);before=root/'baseline';stage=root/'stage'
            for p in (before,stage):(p/'02_我的表副本').mkdir(parents=True)
            name='2026年盈亏核算表.xlsx';book=before/'02_我的表副本'/name
            wb=openpyxl.Workbook();wb.active.title='明细';wb.active.append(['新智云单号']);wb.save(book);wb.close()
            target=stage/'02_我的表副本'/name;shutil.copy2(book,target)
            (stage/'04_产出').mkdir();review=stage/'execution-review'/'03_台账';review.mkdir(parents=True)
            journal=review/'父回款顺序分配台账.json';journal.write_text('obsolete invalid audit')
            flow=stage/'flow.xlsx';flow.write_bytes(b'flow verification tested independently')
            checked=stage/'checked.json';checked.write_text(json.dumps({'hexiao_date':'2026-08-20','write':[]}))
            args=['--workspace',str(stage),'--baseline',str(before),'--checked',str(checked),'--flow-file',str(flow),'--ledger-year','2026='+str(target)]
            with patch.object(E,'verify_flow',return_value={'mode':'isolated_flow_boundary'}),patch('fallback_allocation_ledger.commit',side_effect=ValueError('old journal')) as commit,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(E.main(args),0)
                commit.assert_not_called()
                self.assertEqual(journal.read_text(),'obsolete invalid audit')
                target.write_bytes(b'changed outside approved plan')
                with self.assertRaisesRegex(ValueError,'无写入计划'):
                    E.main(args)

if __name__=='__main__':unittest.main()
