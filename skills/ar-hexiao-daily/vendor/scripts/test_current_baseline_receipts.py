import copy,tempfile,unittest
from pathlib import Path
import classify_hexiao as C,validate_plan as V,apply_to_copy as A
import baseline_receipts as BR
from test_delivery_above_receivable import DeliveryAboveReceivable

class CurrentBaselineReceipts(unittest.TestCase):
    def test_changed_delivery_uses_current_rows_across_installments_without_journal(self):
        helper=DeliveryAboveReceivable()
        with tempfile.TemporaryDirectory() as temp:
            path=helper.create(temp);cumulative=0
            for index,amount in enumerate([200,300,1000],1):
                cumulative+=amount;rec=helper.record(index,amount,cumulative)
                rows=A.read_ledger_rows(path)
                for journal in ({},{BR.group_key('SO_TEST','SOD_A'):{'baseline_receivable':999,'scope_only':False,'events':{'stale':{'回款明细':999}}}}):
                    ledger=C.LedgerIndex(path);ledger.baseline_receipt_state=journal
                    plan=C.classify_records([copy.deepcopy(rec)],ledger,{})
                    checked=V.validate(plan,rows)
                    self.assertEqual(checked['counts'],{'write':1,'skip':0,'conflict':0},plan)
                    self.assertTrue(checked['write'][0].get('current_workbook_receipts'))
                dst=Path(temp)/f'after{index}.xlsx'
                A.write_plan(path,dst,checked['write'])
                self.assertEqual(A.verify_written(dst,checked['write']),[])
                after=A.read_ledger_rows(dst)
                self.assertEqual([r['应收金额'] for r in after.values()],[1000]+[None]*index)
                self.assertEqual(sum(r['回款明细'] or 0 for r in after.values()),cumulative)
                self.assertEqual(sum(r['计提'] or 0 for r in after.values()),1500 if index==3 else 0)
                self.assertEqual(sum(r['差异'] or 0 for r in after.values()),-500 if index==3 else 0)
                repeat=C.classify_records([copy.deepcopy(rec)],C.LedgerIndex(dst),{})
                self.assertEqual(V.validate(repeat,after)['counts'],{'write':0,'skip':1,'conflict':0},repeat)
                self.assertTrue(repeat['auto'][0].get('current_workbook_receipts'))
                path=dst

    def test_same_day_missing_chain_and_stale_plan_are_checked(self):
        helper=DeliveryAboveReceivable()
        with tempfile.TemporaryDirectory() as temp:
            path=helper.create(temp)
            records=[helper.record(1,200,200),helper.record(2,300,500)]
            for rec in records:rec['hexiao_date']='2026-09-20';rec['writeoff_sequence_key'][0]='2026-09-20'
            before=A.read_ledger_rows(path)
            plan=C.classify_records(copy.deepcopy(records),C.LedgerIndex(path),{})
            checked=V.validate(plan,before)
            self.assertEqual(checked['counts'],{'write':2,'skip':0,'conflict':0},plan)
            altered=copy.deepcopy(before);altered[2]['应收金额']=999
            self.assertEqual(V.validate(plan,altered)['counts']['conflict'],2)
            dst=Path(temp)/'chain.xlsx';A.write_plan(path,dst,checked['write'])
            self.assertEqual(A.verify_written(dst,checked['write']),[])
            after=A.read_ledger_rows(dst)
            self.assertEqual([r['应收金额'] for r in after.values()],[1000,None,None])
            repeat=C.classify_records(copy.deepcopy(records),C.LedgerIndex(dst),{})
            self.assertEqual(V.validate(repeat,after)['counts'],{'write':0,'skip':2,'conflict':0},repeat)

    def test_decreased_delivery_keeps_existing_blank_installment_layout(self):
        helper=DeliveryAboveReceivable()
        with tempfile.TemporaryDirectory() as temp:
            path=helper.create(temp)
            first=helper.record(1,200,200)
            checked=V.validate(C.classify_records([first],C.LedgerIndex(path),{}),A.read_ledger_rows(path))
            dst=Path(temp)/'first.xlsx';A.write_plan(path,dst,checked['write'])
            last=helper.record(2,600,800)
            last.update(deliver_local=800,so_delivery_local=800,sod_delivery_local={'SOD_A':800})
            checked=V.validate(C.classify_records([last],C.LedgerIndex(dst),{}),A.read_ledger_rows(dst))
            self.assertEqual(checked['counts'],{'write':1,'skip':0,'conflict':0})
            final=Path(temp)/'final.xlsx';A.write_plan(dst,final,checked['write'])
            after=A.read_ledger_rows(final)
            self.assertEqual([r['应收金额'] for r in after.values()],[1000,None,None])
            self.assertEqual(sum(r['计提'] or 0 for r in after.values()),800)
            self.assertEqual(sum(r['差异'] or 0 for r in after.values()),200)
            repeat=C.classify_records([last],C.LedgerIndex(final),{})
            self.assertEqual(V.validate(repeat,after)['counts'],{'write':0,'skip':1,'conflict':0},repeat)

    def test_multiple_sods_wait_for_whole_so_with_current_proofs(self):
        helper=DeliveryAboveReceivable()
        with tempfile.TemporaryDirectory() as temp:
            path=helper.create(temp,True)
            for index,(sod,amount,total) in enumerate([('SOD_A',200,200),('SOD_A',1300,1500),('SOD_B',100,100)],1):
                rec=helper.record(index,amount,total,sod,True)
                plan=C.classify_records([copy.deepcopy(rec)],C.LedgerIndex(path),{})
                checked=V.validate(plan,A.read_ledger_rows(path))
                self.assertEqual(checked['counts'],{'write':1,'skip':0,'conflict':0},plan)
                self.assertTrue(checked['write'][0].get('current_workbook_receipts'))
                dst=Path(temp)/f'multi{index}.xlsx';A.write_plan(path,dst,checked['write'])
                self.assertEqual(A.verify_written(dst,checked['write']),[])
                after=A.read_ledger_rows(dst)
                self.assertEqual(sum(r['计提'] or 0 for r in after.values()),1600 if index==3 else 0)
                repeated=C.classify_records([copy.deepcopy(rec)],C.LedgerIndex(dst),{})
                self.assertEqual(V.validate(repeated,after)['counts'],{'write':0,'skip':1,'conflict':0},repeated)
                self.assertTrue(repeated['auto'][0].get('current_workbook_receipts'))
                path=dst

if __name__=='__main__':unittest.main()
