"""Physical lab receipt-count acceptance; uses immutable image business modules."""
import copy
import shutil
import tempfile
import unittest
from pathlib import Path
import openpyxl
import classify_hexiao as C
import validate_plan as V
import apply_to_copy as A
from test_current_workbook_receipts import fixture

class EqualReceiptPipeline(unittest.TestCase):
    def test_equal_events_zero_one_two_existing_rows_and_reordering(self):
        for existing in (0,1,2):
            for reverse in (False,True):
                with self.subTest(existing=existing,reverse=reverse),tempfile.TemporaryDirectory() as tmp:
                    records,rows=fixture()
                    records[1].update(amount_orig=20,amount_local=20,cumulative_received_local=40,shoukuan_date='2026-06-01')
                    rows[5].update(yingshou=20,huikuan=20,shoukuan_time='2026-06-01',shoukuan_way='汇')
                    rows[3]['yingshou']=50+20*(2-existing)
                    for ref in range(4+existing,6):rows.pop(ref)
                    if reverse:
                        records.reverse();rows=dict(reversed(list(rows.items())))
                    wb=openpyxl.Workbook();ws=wb.active;ws.title='明细'
                    ws.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
                    for r in rows.values():ws.append([r.get(k) for k in ('so','sod','yingshou','jiti','huikuan','jiezhang','shoukuan_time','shoukuan_way','chayi')])
                    before=Path(tmp)/'before.xlsx';after=Path(tmp)/'after.xlsx';wb.save(before);wb.close();raw=before.read_bytes()
                    def check(path):
                        return V.validate(C.classify_records(copy.deepcopy(records),C.LedgerIndex(path),{}),A.read_ledger_rows(path))
                    checked=check(before)
                    self.assertEqual(checked['counts'],dict(write=2-existing,skip=existing,conflict=0), C.classify_records(copy.deepcopy(records),C.LedgerIndex(before),{}))
                    if checked['write']:A.write_plan(before,after,checked['write'])
                    else:shutil.copy2(before,after)
                    self.assertEqual(A.verify_written(after,checked['write']),[])
                    actual=A.read_ledger_rows(after)
                    self.assertEqual(sum(r['回款明细'] or 0 for r in actual.values()),50)
                    self.assertEqual([r['回款明细'] for r in actual.values() if str(r['收款时间'])[:10]=='2026-09-15'],[10])
                    self.assertEqual([r['应收金额'] for r in actual.values() if r['是否结账']=='否'],[50])
                    self.assertEqual(check(after)['counts'],dict(write=0,skip=2,conflict=0))
                    self.assertEqual(before.read_bytes(),raw)

    def test_partial_count_proof_rejects_non_equivalent_or_damaged_inputs(self):
        import current_workbook_receipts as W
        import baseline_receipts as BR
        from test_current_workbook_receipts import ledger
        for mode in ('status','arrival','future_equal','broken_capacity','prior_unknown','different_accrual'):
            with self.subTest(mode=mode):
                records,rows=fixture()
                records[1].update(amount_orig=20,amount_local=20,cumulative_received_local=40,shoukuan_date='2026-06-01')
                rows.pop(5);rows[3]['yingshou']=70
                if mode=='status':records[1]['status']='预存部分核销'
                if mode=='arrival':records[1]['shoukuan_date']='2026-06-02'
                if mode=='future_equal':rows[2].update(yingshou=20,huikuan=20);rows[3]['yingshou']=60
                if mode=='broken_capacity':rows[3]['yingshou']=69
                if mode=='prior_unknown':
                    for r in records:r['cumulative_received_local']+=20
                if mode=='different_accrual':
                    rows[5]=copy.deepcopy(rows[4]);rows[5]['jiti']=1;rows[3]['yingshou']=50
                before=copy.deepcopy(rows)
                self.assertIsNone(W.prove(records,BR.ledger_rows(ledger(rows),'SO_CURRENT','SOD_CURRENT')))
                self.assertEqual(rows,before)

if __name__=='__main__':unittest.main()
