import copy,tempfile,unittest
from pathlib import Path
import openpyxl
import classify_hexiao as C,validate_plan as V,apply_to_copy as A
from test_current_workbook_receipts import fixture

class CurrentTailReceipts(unittest.TestCase):
    def test_tail_settlement_preserves_actual_amount_and_receivable(self):
        for delta in (-1,-.5,.01,.5,1):
            for chain in (False,True):
                with self.subTest(delta=delta,chain=chain),tempfile.TemporaryDirectory() as temp:
                    records,rows=fixture();records=records if chain else records[:1]
                    first=20 if chain else 100+delta
                    records[0].update(amount_orig=first,amount_local=first,cumulative_received_local=first)
                    if chain:records[1].update(amount_orig=80+delta,amount_local=80+delta,cumulative_received_local=100+delta)
                    wb=openpyxl.Workbook();ws=wb.active;ws.title='明细'
                    ws.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
                    ws.append(['SO_CURRENT','SOD_CURRENT',100,None,None,'否',None,None,None])
                    before,after=Path(temp)/'before.xlsx',Path(temp)/'after.xlsx';wb.save(before);wb.close()
                    plan=C.classify_records(copy.deepcopy(records),C.LedgerIndex(before),{})
                    checked=V.validate(plan,A.read_ledger_rows(before))
                    self.assertEqual(checked['counts'],{'write':len(records),'skip':0,'conflict':0},plan)
                    self.assertTrue(all(r.get('current_workbook_receipts') for r in checked['write']))
                    A.write_plan(before,after,checked['write'])
                    self.assertEqual(A.verify_written(after,checked['write']),[])
                    actual=A.read_ledger_rows(after)
                    self.assertEqual(sum(r['应收金额'] or 0 for r in actual.values()),100)
                    self.assertAlmostEqual(sum(r['回款明细'] or 0 for r in actual.values()),100+delta)
                    self.assertEqual(sum(r['计提'] or 0 for r in actual.values()),100)
                    self.assertTrue(all(r['是否结账']=='是' for r in actual.values()))
                    repeat=C.classify_records(copy.deepcopy(records),C.LedgerIndex(after),{})
                    self.assertEqual(V.validate(repeat,actual)['counts'],{'write':0,'skip':len(records),'conflict':0},repeat)
                    self.assertTrue(all(r.get('current_workbook_receipts') for r in repeat['auto']))

    def test_preserved_receivable_tail_settlement_keeps_delivery_basis(self):
        import test_delivery_above_receivable as T
        helper=T.DeliveryAboveReceivable()
        for delta in (-1,.5,1):
            with self.subTest(delta=delta),tempfile.TemporaryDirectory() as temp:
                path=helper.create(temp)
                first=helper.record(1,200,200)
                checked=V.validate(C.classify_records([first],C.LedgerIndex(path),{}),A.read_ledger_rows(path))
                mid=Path(temp)/'mid.xlsx';A.write_plan(path,mid,checked['write'])
                final=helper.record(2,1300+delta,1500+delta)
                checked=V.validate(C.classify_records([final],C.LedgerIndex(mid),{}),A.read_ledger_rows(mid))
                self.assertEqual(checked['counts'],{'write':1,'skip':0,'conflict':0})
                self.assertTrue(checked['write'][0].get('current_workbook_receipts'))
                after=Path(temp)/'after.xlsx';A.write_plan(mid,after,checked['write'])
                self.assertEqual(A.verify_written(after,checked['write']),[])
                rows=A.read_ledger_rows(after)
                self.assertEqual(sum(r['应收金额'] or 0 for r in rows.values()),1000)
                self.assertEqual(sum(r['计提'] or 0 for r in rows.values()),1500)
                self.assertEqual(sum(r['差异'] or 0 for r in rows.values()),-500)
                self.assertAlmostEqual(sum(r['回款明细'] or 0 for r in rows.values()),1500+delta)
                repeat=C.classify_records([final],C.LedgerIndex(after),{})
                self.assertEqual(V.validate(repeat,rows)['counts'],{'write':0,'skip':1,'conflict':0},repeat)
                self.assertTrue(repeat['auto'][0].get('current_workbook_receipts'))

    def test_tail_rule_does_not_round_source_matching_or_settle_early(self):
        import current_workbook_receipts as W
        from test_current_workbook_receipts import ledger
        import baseline_receipts as BR
        records,rows=fixture()
        rows={3:rows[3]};rows[3]['yingshou']=100
        records[0].update(amount_orig=99.5,amount_local=99.5,cumulative_received_local=99.5)
        records[1].update(amount_orig=.5,amount_local=.5,cumulative_received_local=100)
        plan=C.classify_records(copy.deepcopy(records),ledger(rows),{})
        self.assertFalse(plan['auto'][0].get('settlement_tolerance_audit'))
        self.assertIsNone(plan['auto'][0]['five_cols']['计提'])
        self.assertEqual(plan['auto'][1]['five_cols']['计提'],100)
        for amount,expected in [(98.99,1.01),(101.01,None)]:
            rec=copy.deepcopy(records[0]);rec.update(amount_orig=amount,amount_local=amount,cumulative_received_local=amount)
            current=ledger(rows);proof=W.prove([rec],BR.ledger_rows(current,'SO_CURRENT','SOD_CURRENT'))
            if expected is None:self.assertIsNone(proof)
            else:
                self.assertIsNotNone(proof)
                action=W.action(proof,BR.event_key(rec))
                self.assertIsNone(action['five_cols']['计提'])
                self.assertEqual(action['row_operation']['unpaid_receivable'],expected)

if __name__=='__main__':unittest.main()
