"""Acceptance of SO-level settlement tails through classification and workbook writes."""
import copy
import datetime as dt
from pathlib import Path
import tempfile
import unittest
import openpyxl
import classify_hexiao as C
import validate_plan as V
import apply_to_copy as A

class MultiSodSettlementTail(unittest.TestCase):
    def test_two_cent_tail_writes_actual_money_and_repeats_without_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            before,after=Path(temp)/'before.xlsx',Path(temp)/'after.xlsx'
            wb=openpyxl.Workbook();ws=wb.active;ws.title='明细'
            ws.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
            ws.append(['SO_TAIL','SOD_A',155.70,None,None,'否',None,None,None])
            ws.append(['SO_TAIL','SOD_B',1646.28,None,None,'否',None,None,None])
            wb.save(before);wb.close();original=before.read_bytes()
            amounts={'SOD_A':155.70,'SOD_B':1646.28}
            rec=dict(ar='AR_TAIL',so='SO_TAIL',sod='',currency='CNY',status='手动核销',
                huikuan_type='整笔回款',shoukuan_date=dt.date(2026,9,29),hexiao_date=dt.date(2026,9,29),
                delivery_date=dt.date(2026,9,1),target_ledger_year=2026,target_ledger_path=str(before),
                default_first_sod=True,default_amount_local=1802.0,default_amount_orig=1802.0,
                default_sod_lines=[dict(sod=s,deliver_local=a,currency='CNY') for s,a in amounts.items()],
                so_delivery_local=1801.98,sod_delivery_local=amounts,all_sods=list(amounts))
            plan=C.classify_records([copy.deepcopy(rec)],C.LedgerIndex(before),{})
            self.assertEqual(plan['counts'],{'auto':2,'hold':0,'exception':0,'total':2},
                [(r['code'],r['reason']) for k in ['hold','exception'] for r in plan[k]])
            checked=V.validate(plan,A.read_ledger_rows(before))
            self.assertEqual(checked['counts'],{'write':2,'skip':0,'conflict':0})
            A.write_plan(before,after,checked['write'])
            self.assertEqual(A.verify_written(after,checked['write']),[])
            rows=A.read_ledger_rows(after)
            self.assertEqual(round(sum(r['回款明细'] or 0 for r in rows.values()),2),1802.0)
            self.assertEqual(round(sum(r['应收金额'] or 0 for r in rows.values()),2),1801.98)
            self.assertEqual(round(sum(r['计提'] or 0 for r in rows.values()),2),1801.98)
            self.assertTrue(all(r['是否结账']=='是' for r in rows.values()))
            repeated=C.classify_records([copy.deepcopy(rec)],C.LedgerIndex(after),{})
            again=V.validate(repeated,rows)
            self.assertEqual(again['counts']['write'],0)
            self.assertEqual(again['counts']['conflict'],0)
            self.assertEqual(before.read_bytes(),original)

    def test_tail_does_not_hide_overreceived_closed_sod(self):
        rows={2:dict(so='SO_TAIL',sod='SOD_A',yingshou=155.7,jiti=None,huikuan=165.7,
                     jiezhang='是',shoukuan_time='2026-09-01',shoukuan_way='汇',chayi=None),
              3:dict(so='SO_TAIL',sod='SOD_B',yingshou=1646.28,jiti=None,huikuan=None,
                     jiezhang='否',shoukuan_time=None,shoukuan_way='',chayi=None)}
        ledger=C.LedgerIndex(synthetic={'rows':rows,'so':{'SO_TAIL':[2,3]},'sod':{'SOD_A':[2],'SOD_B':[3]}})
        rec=dict(ar='AR_TAIL',so='SO_TAIL',sod='',currency='CNY',status='手动核销',
            shoukuan_date=dt.date(2026,9,29),hexiao_date=dt.date(2026,9,29),
            default_first_sod=True,default_amount_local=1646.3,default_amount_orig=1646.3,
            default_sod_lines=[dict(sod='SOD_A',deliver_local=155.7),dict(sod='SOD_B',deliver_local=1646.28)],
            so_delivery_local=1801.98,sod_delivery_local={'SOD_A':155.7,'SOD_B':1646.28},all_sods=['SOD_A','SOD_B'])
        before=copy.deepcopy(rows);plan=C.classify_records([rec],ledger,{})
        self.assertFalse(plan['auto'])
        self.assertTrue(plan['hold'] or plan['exception'])
        self.assertEqual(ledger.row_snapshot,before)

    def test_business_tail_limit_does_not_relax_coverage_or_baseline_guards(self):
        for amount,baseline,missing,allowed in [(1802.98,1801.98,False,True),
                (1802.99,1801.98,False,False),(1802,1791.98,False,False),
                (1802,1801.98,True,False)]:
            with self.subTest(amount=amount,baseline=baseline,missing=missing), tempfile.TemporaryDirectory() as temp:
                path=Path(temp)/'before.xlsx'
                wb=openpyxl.Workbook();ws=wb.active;ws.title='明细'
                ws.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
                ws.append(['SO_TAIL','SOD_A',155.70,None,None,'否',None,None,None])
                ws.append(['SO_TAIL','SOD_B',baseline-155.70,None,None,'否',None,None,None])
                wb.save(path);wb.close()
                amounts={'SOD_A':155.70,'SOD_B':1646.28}
                rec=dict(ar='AR_TAIL',so='SO_TAIL',sod='',currency='CNY',status='手动核销',
                    shoukuan_date=dt.date(2026,9,29),hexiao_date=dt.date(2026,9,29),
                    delivery_date=dt.date(2026,9,1),target_ledger_year=2026,
                    default_first_sod=True,default_amount_local=amount,default_amount_orig=amount,
                    default_sod_lines=[dict(sod=s,deliver_local=a,currency='CNY') for s,a in amounts.items()
                                       if not missing or s!='SOD_A'],
                    so_delivery_local=1801.98,sod_delivery_local=amounts,all_sods=list(amounts))
                before=path.read_bytes();plan=C.classify_records([rec],C.LedgerIndex(path),{})
                checked=V.validate(plan,A.read_ledger_rows(path))
                self.assertEqual(bool(checked['write']),allowed,plan['counts'])
                if allowed:
                    after=path.with_name('after.xlsx');A.write_plan(path,after,checked['write'])
                    self.assertEqual(A.verify_written(after,checked['write']),[])
                    self.assertEqual(round(sum(r['回款明细'] or 0 for r in A.read_ledger_rows(after).values()),2),amount)
                else:self.assertTrue(plan['hold'] or plan['exception'])
                self.assertEqual(path.read_bytes(),before)

if __name__=='__main__':unittest.main()
