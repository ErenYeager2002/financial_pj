"""One-yuan cumulative boundaries through classification, write and readback."""
import unittest,tempfile,datetime as dt
from pathlib import Path
import openpyxl
import classify_hexiao as C
import validate_plan as V
import apply_to_copy as W

class SettlementBoundaryTest(unittest.TestCase):
    def fixture(self, delta, previous=0):
        current=round(1000+delta-previous,2)
        base={'so':'SO_TEST','sod':'SOD_TEST','yingshou':1000-previous,'jiti':None,'huikuan':None,
              'jiezhang':'否','shoukuan_time':None,'shoukuan_way':None,'chayi':None}
        rows={2:base}
        if previous:
            rows={2:{**base,'yingshou':previous,'huikuan':previous,'jiezhang':'是','shoukuan_time':'2026-09-19','shoukuan_way':'汇'},3:base}
        ledger=C.LedgerIndex(synthetic={'so':{'SO_TEST':list(rows)},'sod':{'SOD_TEST':list(rows)},'rows':rows})
        rec={'ar':'AR_TEST','so':'SO_TEST','sod':'SOD_TEST','amount_orig':current,'amount_local':current,
             'deliver_local':1000,'deliver_orig':1000,'currency':'CNY','cumulative_received_local':1000+delta,
             'hexiao_date':'2026-09-20','shoukuan_date':'2026-09-20','status':'已核销',
             'writeoff_sequence_key':['2026-09-20','HX_TEST','DETAIL_TEST']}
        return rec,ledger,rows
    def test_first_and_later_boundaries_write_readback_and_repeat(self):
        for previous in [0,500]:
            for delta in [-1,-0.6,0,0.6,1]:
                with self.subTest(previous=previous,delta=delta),tempfile.TemporaryDirectory() as tmp:
                    rec,ledger,rows=self.fixture(delta,previous)
                    result=C.classify_records([rec],ledger,{})
                    self.assertEqual(len(result['auto']),1,{k:[(x.get('code'),x.get('reason')) for x in result.get(k,[])] for k in ['auto','hold','exception']})
                    item=result['auto'][0]
                    self.assertEqual(item['five_cols']['回款明细'],rec['amount_local'])
                    self.assertFalse(item.get('row_operation'))
                    src=Path(tmp)/'before.xlsx';out=Path(tmp)/'after.xlsx'
                    wb=openpyxl.Workbook();ws=wb.active;ws.title='明细'
                    ws.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
                    for row in rows.values():ws.append([row[k] for k in ['so','sod','yingshou','jiti','huikuan','jiezhang','shoukuan_time','shoukuan_way','chayi']])
                    wb.create_sheet('保留')['A1']='不改';wb.save(src);wb.close();before=src.read_bytes()
                    self.assertEqual(V.check_one(item,W.read_ledger_rows(src))['verdict'],'write')
                    W.write_plan(src,out,[item])
                    self.assertEqual(W.verify_written(out,[item]),[])
                    self.assertEqual(V.check_one(item,W.read_ledger_rows(out))['verdict'],'skip')
                    self.assertEqual(src.read_bytes(),before)
                    wb=openpyxl.load_workbook(out,data_only=True);ws=wb['明细']
                    self.assertAlmostEqual(sum(float(ws.cell(r,5).value or 0) for r in range(2,ws.max_row+1)),1000+delta)
                    self.assertEqual(wb['保留']['A1'].value,'不改');wb.close()
    def test_more_than_one_overpayment_is_rejected(self):
        for previous in [0,500]:
            rec,ledger,_=self.fixture(1.01,previous)
            result=C.classify_records([rec],ledger,{})
            self.assertFalse(result['auto'])
    def test_more_than_one_underpayment_remains_unpaid(self):
        for previous in [0,500]:
            rec,ledger,_=self.fixture(-1.01,previous)
            result=C.classify_records([rec],ledger,{})
            self.assertEqual(len(result['auto']),1)
            item=result['auto'][0]
            self.assertEqual(item['row_operation']['type'],'split_below')
            self.assertEqual(item['row_operation']['unpaid_receivable'],1.01)
    def test_prior_tail_does_not_grant_another_yuan(self):
        rec,ledger,_=self.fixture(1.2,500.6)
        self.assertAlmostEqual(rec['amount_local'],500.6)
        self.assertFalse(C.classify_records([rec],ledger,{})['auto'])
if __name__=='__main__':unittest.main()
