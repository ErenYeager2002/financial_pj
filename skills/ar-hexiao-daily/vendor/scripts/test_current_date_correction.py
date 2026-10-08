import copy,tempfile,unittest
from pathlib import Path
import openpyxl
import classify_hexiao as C,validate_plan as V,apply_to_copy as A
from test_current_workbook_receipts import fixture,ledger
import baseline_receipts as BR

class CurrentDateCorrection(unittest.TestCase):
    def test_complete_unique_group_corrects_dates_and_preserves_financial_cells(self):
        records,rows=fixture();rows.pop(2);rows.pop(3)
        records[1].update(amount_orig=80,amount_local=80,cumulative_received_local=100)
        rows[4].update(shoukuan_time='2026-08-11',shoukuan_way='冲预收')
        rows[5].update(yingshou=80,huikuan=80,shoukuan_time='2026-08-30',jiti=80)
        with tempfile.TemporaryDirectory() as temp:
            wb=openpyxl.Workbook();ws=wb.active;ws.title='明细'
            ws.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
            for r in rows.values():ws.append([r.get(k) for k in ('so','sod','yingshou','jiti','huikuan','jiezhang','shoukuan_time','shoukuan_way','chayi')])
            before,after=Path(temp)/'before.xlsx',Path(temp)/'after.xlsx';wb.save(before);wb.close()
            prior=A.read_ledger_rows(before)
            plan=C.classify_records(copy.deepcopy(records),C.LedgerIndex(before),{})
            checked=V.validate(plan,prior)
            self.assertEqual(checked['counts'],{'write':2,'skip':0,'conflict':0},plan)
            self.assertTrue(all(r.get('current_workbook_receipts',{}).get('date_corrections') for r in checked['write']))
            A.write_plan(before,after,checked['write']);self.assertEqual(A.verify_written(after,checked['write']),[])
            actual=A.read_ledger_rows(after)
            for ref,r in prior.items():
                for k in ('应收金额','回款明细','计提','是否结账','差异'):self.assertEqual(actual[ref][k],r[k])
            repeat=C.classify_records(copy.deepcopy(records),C.LedgerIndex(after),{})
            self.assertEqual(V.validate(repeat,actual)['counts'],{'write':0,'skip':2,'conflict':0},repeat)

    def test_correction_rejects_incomplete_or_ambiguous_financial_groups(self):
        import current_date_correction as D
        records,rows=fixture();rows.pop(2);rows.pop(3)
        records[1].update(amount_orig=80,amount_local=80,cumulative_received_local=100)
        rows[4].update(shoukuan_time='2026-08-11',shoukuan_way='冲预收')
        rows[5].update(yingshou=80,huikuan=80,shoukuan_time='2026-08-30',jiti=80)
        def normalized(rs):return BR.ledger_rows(ledger(rs),'SO_CURRENT','SOD_CURRENT')
        before=copy.deepcopy(rows)
        self.assertIsNotNone(D.prove(records,normalized(rows)))
        self.assertEqual(rows,before)
        self.assertIsNone(D.prove(records[:1],normalized(rows)))
        for field,value in [('huikuan',79),('yingshou',79),('jiezhang','否'),('shoukuan_way','现')]:
            changed=copy.deepcopy(rows);changed[5][field]=value
            with self.subTest(field=field):self.assertIsNone(D.prove(records,normalized(changed)))
        equal=copy.deepcopy(records);equal[0].update(amount_orig=50,amount_local=50,cumulative_received_local=50)
        equal[1].update(amount_orig=50,amount_local=50)
        equal_rows=copy.deepcopy(rows)
        for row in equal_rows.values():row.update(yingshou=50,huikuan=50)
        self.assertIsNone(D.prove(equal,normalized(equal_rows)))

    def test_correction_plan_rejects_extra_financial_write_or_changed_material(self):
        records,rows=fixture();rows.pop(2);rows.pop(3)
        records[1].update(amount_orig=80,amount_local=80,cumulative_received_local=100)
        rows[4].update(shoukuan_time='2026-08-11',shoukuan_way='冲预收')
        rows[5].update(yingshou=80,huikuan=80,shoukuan_time='2026-08-30',jiti=80)
        current=ledger(rows)
        plan=C.classify_records(copy.deepcopy(records),current,{})
        before={int(k):v for k,v in BR.ledger_rows(current,'SO_CURRENT','SOD_CURRENT').items()}
        self.assertEqual(V.validate(plan,before)['counts']['write'],2)
        for field,value in [('计提',999),('回款明细',999),('差异',999)]:
            changed=copy.deepcopy(plan);changed['auto'][0]['five_cols'][field]=value
            with self.subTest(field=field):self.assertGreater(V.validate(changed,before)['counts']['conflict'],0)
        changed=copy.deepcopy(before);changed[4]['收款时间']='2026-08-12'
        self.assertGreater(V.validate(plan,changed)['counts']['conflict'],0)

if __name__=='__main__':unittest.main()
