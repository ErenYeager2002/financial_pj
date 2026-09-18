import unittest
import copy
import datetime as dt
import classify_hexiao as C
import baseline_receipts as BR
import validate_plan as V
import test_full_receipt_cumulative as fixtures

class CurrentCohortTest(unittest.TestCase):
    def fixture(self):
        p=fixtures.FullReceiptCumulativeTest().payment()
        p.update(amount_orig=40,amount_local=40,total_amount_orig=40,total_amount_local=40)
        p['writeoffs']={'SO_SYNTHETIC':40};p['writeoffs_local']={'SO_SYNTHETIC':40}
        # The naive delivery subset picks A=40. Current rows prove the receipt is B=40.
        raw={2:{'so':'SO_SYNTHETIC','sod':'SOD_A','yingshou':40,'jiti':40,'huikuan':40,'jiezhang':'是','shoukuan_time':'2026-06-23','shoukuan_way':'汇'},
             3:{'so':'SO_SYNTHETIC','sod':'SOD_B','yingshou':20,'jiti':20,'huikuan':20,'jiezhang':'是','shoukuan_time':'2026-06-23','shoukuan_way':'汇'},
             4:{'so':'SO_SYNTHETIC','sod':'SOD_B','yingshou':40,'jiti':40,'huikuan':40,'jiezhang':'是','shoukuan_time':'bad-date','shoukuan_way':'汇'}}
        l=C.LedgerIndex(synthetic={'so':{'SO_SYNTHETIC':[2,3,4]},'sod':{'SOD_A':[2],'SOD_B':[3,4]},'rows':raw})
        return p,l
    def test_current_receipt_cohort_precedes_delivery_subset(self):
        p,l=self.fixture();result=C.classify_records(C.expand_payments([p],{}),l,{})
        self.assertEqual(len(result['auto']),1,result)
        item=result['auto'][0];self.assertEqual(item['sod'],'SOD_B');self.assertEqual(item['ledger_row_ref'],4);self.assertFalse(item.get('row_operation'))
        rows={int(k):{**r,'_差异列存在':True} for sod in l.sod_index for k,r in BR.ledger_rows(l,'SO_SYNTHETIC',sod).items()}
        self.assertEqual(V.check_one(item,rows)['verdict'],'write')
        rows[4].update(item['five_cols']);self.assertEqual(V.check_one(item,rows)['verdict'],'skip')
        self.assertEqual(rows[2]['收款时间'],'2026-06-23');self.assertEqual(sum(r['回款明细'] for r in rows.values()),100)
    def test_unknown_totals_or_multiple_rows_per_sod_do_not_rebind(self):
        import current_receipt_cohort as R
        for mode in ['extra','duplicate','later']:
            p,l=self.fixture()
            if mode=='extra':l.row_snapshot[3]['huikuan']=21
            if mode=='later':l.row_snapshot[3]['shoukuan_time']='2026-09-01'
            if mode=='duplicate':l.row_snapshot[3]['shoukuan_time']='bad-date';l.row_snapshot[3]['huikuan']=20;l.row_snapshot[4]['huikuan']=20
            records=C.expand_payments([p],{})
            self.assertEqual(R.expand(records,l),records,mode)

    def test_write_readback_repeat_and_changed_group(self):
        import tempfile
        from pathlib import Path
        import openpyxl
        import apply_to_copy as A
        p,l=self.fixture();result=C.classify_records(C.expand_payments([p],{}),l,{})
        item=result['auto'][0]
        with tempfile.TemporaryDirectory() as temp:
            src,out=Path(temp)/'source.xlsx',Path(temp)/'result.xlsx'
            book=openpyxl.Workbook();sheet=book.active;sheet.title='明细'
            sheet.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
            for row in l.row_snapshot.values():sheet.append([row.get(k) for k in ['so','sod','yingshou','jiti','huikuan','jiezhang','shoukuan_time','shoukuan_way','chayi']])
            book.save(src);book.close();original=src.read_bytes();rows=A.read_ledger_rows(src)
            changed=copy.deepcopy(rows);changed[2]['回款明细']=39
            self.assertEqual(V.check_one(item,changed)['verdict'],'conflict')
            self.assertEqual(V.check_one(item,rows)['verdict'],'write')
            A.write_plan(src,out,[item]);self.assertEqual(A.verify_written(out,[item]),[])
            after=A.read_ledger_rows(out);self.assertEqual(V.check_one(item,after)['verdict'],'skip')
            self.assertEqual(sum(r['回款明细'] for r in after.values()),100)
            self.assertEqual(str(after[2]['收款时间'])[:10],'2026-06-23')
            self.assertEqual(src.read_bytes(),original)

    def test_completed_date_correction_preserves_source_sod(self):
        import current_receipt_cohort as R
        p, ledger = self.fixture()
        records = C.expand_payments([p], {})
        self.assertEqual([r['sod'] for r in R.expand(records, ledger)], ['SOD_B'])
        item = C.classify_records(records, ledger, {})['auto'][0]
        ledger.row_snapshot[4]['shoukuan_time'] = item['five_cols']['收款时间']
        after = R.expand(records, ledger)
        self.assertEqual([r['sod'] for r in after], ['SOD_B'])
        self.assertEqual([r['amount_local'] for r in after], [40])
        self.assertEqual([r['cumulative_received_local'] for r in after], [60])
        final = C.classify_records(records, ledger, {})
        self.assertEqual([r['sod'] for r in final['auto']], ['SOD_B'])
        self.assertTrue(all(not r.get('row_operation') for r in final['auto']))

    def test_dated_cohort_keeps_amount_and_uniqueness_guards(self):
        import current_receipt_cohort as R
        for mode in ['wrong_total', 'wrong_cumulative', 'duplicate_sod', 'missing_method']:
            with self.subTest(mode=mode):
                p, ledger = self.fixture()
                ledger.row_snapshot[4]['shoukuan_time'] = '2026-08-25'
                records = C.expand_payments([p], {})
                if mode == 'wrong_total': ledger.row_snapshot[4]['huikuan'] = 39
                if mode == 'wrong_cumulative': ledger.row_snapshot[2]['huikuan'] = 39
                if mode == 'duplicate_sod':
                    ledger.row_snapshot[3]['shoukuan_time'] = '2026-08-25'
                    ledger.row_snapshot[4]['huikuan'] = 20
                if mode == 'missing_method': ledger.row_snapshot[4]['shoukuan_way'] = None
                self.assertEqual(R.expand(records, ledger), records)
