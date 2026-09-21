import copy, tempfile, unittest
from pathlib import Path
import openpyxl
import classify_hexiao as C, validate_plan as V, apply_to_copy as W
import baseline_receipts as BR

class DeliveryAboveReceivable(unittest.TestCase):
    def create(self, folder, extra=False):
        p=Path(folder)/'initial.xlsx';b=openpyxl.Workbook();w=b.active;w.title='明细'
        w.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
        w.append(['SO_TEST','SOD_A',1000,None,None,'否',None,None,None])
        if extra:w.append(['SO_TEST','SOD_B',100,None,None,'否',None,None,None])
        b.save(p);b.close();return p
    def record(self,index,amount,cumulative,sod='SOD_A',extra=False):
        deliveries={'SOD_A':1500.,**({'SOD_B':100.} if extra else {})}
        return {'ar':f'AR_{index}','so':'SO_TEST','sod':sod,'amount_orig':amount,'amount_local':amount,'currency':'CNY','deliver_local':deliveries[sod],'so_delivery_local':sum(deliveries.values()),'cumulative_received_local':cumulative,'itemized_cumulative_authoritative':True,'all_sods':list(deliveries),'sod_delivery_local':deliveries,'shoukuan_date':f'2026-09-{index:02d}','hexiao_date':f'2026-09-{index:02d}','status':'已核销','writeoff_sequence_key':[f'2026-09-{index:02d}',f'HX_{index}',f'ROW_{index}']}
    def step(self,src,rec,journal):
        original=src.read_bytes();ledger=C.LedgerIndex(src);ledger.baseline_receipt_state=journal
        plan=C.classify_records([copy.deepcopy(rec)],ledger,{})
        checked=V.validate(plan,W.read_ledger_rows(src))
        self.assertEqual(checked['counts'],{'write':1,'skip':0,'conflict':0},plan)
        dst=src.with_name('step-'+rec['ar']+'.xlsx');W.write_plan(src,dst,checked['write'])
        self.assertEqual(W.verify_written(dst,checked['write']),[])
        self.assertEqual(src.read_bytes(),original)
        updated=BR.merge_journal(journal,checked);BR.validate_journal(updated)
        rows=W.read_ledger_rows(dst)
        after=C.LedgerIndex(dst);after.baseline_receipt_state=updated
        repeated=C.classify_records([copy.deepcopy(rec)],after,{})
        self.assertEqual(V.validate(repeated,rows)['counts'],{'write':0,'skip':1,'conflict':0},repeated)
        return dst,updated,rows
    def test_first_and_later_installments_leave_receivable_blank(self):
        with tempfile.TemporaryDirectory() as temp:
            p=self.create(temp);journal={};total=0
            for i,amount in enumerate((200,300,1000),1):
                total+=amount;p,journal,rows=self.step(p,self.record(i,amount,total),journal)
                self.assertEqual([r['应收金额'] for r in rows.values()],[1000]+[None]*i)
                self.assertEqual(sum(r['回款明细'] or 0 for r in rows.values()),total)
                self.assertEqual(sum(r['计提'] or 0 for r in rows.values()),1500 if i==3 else 0)
    def test_accrual_waits_for_other_sod(self):
        with tempfile.TemporaryDirectory() as temp:
            p=self.create(temp,True);journal={}
            for i,amount,cumulative in ((1,200,200),(2,1300,1500)):
                p,journal,rows=self.step(p,self.record(i,amount,cumulative,extra=True),journal)
                self.assertEqual(sum(r['计提'] or 0 for r in rows.values()),0)
            p,journal,rows=self.step(p,self.record(3,100,100,'SOD_B',True),journal)
            self.assertEqual(sum(r['计提'] or 0 for r in rows.values()),1600)
    def test_fully_settled_so_stays_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            p=self.create(temp);journal={}
            for i,amount,cumulative in ((1,200,200),(2,1300,1500)):
                p,journal,rows=self.step(p,self.record(i,amount,cumulative),journal)
            ledger=C.LedgerIndex(p);ledger.baseline_receipt_state=journal
            plan=C.classify_records([self.record(3,200,1700)],ledger,{})
            self.assertEqual(V.validate(plan,rows)['counts'],{'write':0,'skip':1,'conflict':0},plan)
            self.assertFalse(plan.get('hold'),plan)
