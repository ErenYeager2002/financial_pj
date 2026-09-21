import unittest,tempfile,copy
from pathlib import Path
import openpyxl
import classify_hexiao as C,validate_plan as V,apply_to_copy as W

class SourceHistoryGap(unittest.TestCase):
 def plan(self,current=400,prior=0):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  p=Path(self.tmp.name)/'ledger.xlsx';w=openpyxl.Workbook();s=w.active;s.title='明细'
  s.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
  if prior:s.append(['SO_TEST','SOD_TEST',prior,None,prior,'是','2026-09-01','汇',None])
  s.append(['SO_TEST','SOD_TEST',1000-prior,None,None,'否',None,None,None]);w.save(p);w.close()
  rec={'ar':'AR_TEST','so':'SO_TEST','sod':'SOD_TEST','amount_orig':current,'amount_local':current,'currency':'CNY','deliver_local':1000,'so_delivery_local':1000,'cumulative_received_local':1000,'itemized_cumulative_authoritative':True,'all_sods':['SOD_TEST'],'sod_delivery_local':{'SOD_TEST':1000},'shoukuan_date':'2026-09-20','hexiao_date':'2026-09-20','status':'已核销'}
  plan=C.classify_records([rec],C.LedgerIndex(p),{});plan['hexiao_date']='2026-09-20'
  return p,plan,W.read_ledger_rows(p),rec
 def test_missing_history_does_not_write(self):
  p,plan,rows,_=self.plan();checked=V.validate(plan,rows)
  self.assertEqual(checked['write'],[])
  self.assertEqual(len(checked['skip']),1)
  self.assertEqual(checked['skip'][0]['source_business_status'],'settled')
  self.assertEqual(checked['skip'][0]['material_registration_status'],'incomplete')
 def test_valid_controls_write_and_readback(self):
  for amount,prior in [(1000,0),(400,600)]:
   with self.subTest(amount=amount):
    p,plan,rows,_=self.plan(amount,prior);checked=V.validate(plan,rows)
    self.assertEqual(len(checked['write']),1)
    out=p.with_name('out.xlsx');W.write_plan(p,out,checked['write']);self.assertEqual(W.verify_written(out,checked['write']),[])
 def test_gap_skip_cannot_carry_write(self):
  p,plan,rows,_=self.plan();plan['auto'][0]['five_cols']={'回款明细':400}
  checked=V.validate(plan,rows);self.assertEqual(len(checked['conflict']),1)
 def test_gap_material_changed_requires_recheck(self):
  p,plan,rows,_=self.plan();rows[2]['回款明细']=600
  checked=V.validate(plan,rows);self.assertEqual(len(checked['conflict']),1)
 def test_no_applied_allocation_proof(self):
  import fallback_allocation_ledger as F
  p,plan,rows,_=self.plan();checked=V.validate(plan,rows)
  self.assertEqual(F._successful_pairs(checked),set())

 def test_same_batch_history_is_not_missing(self):
  p,_,rows,rec=self.plan()
  first={**rec,'ar':'AR_FIRST','amount_orig':400,'amount_local':400,'cumulative_received_local':400,'writeoff_sequence_key':['2026-09-20','W1',1]}
  second={**rec,'ar':'AR_SECOND','amount_orig':600,'amount_local':600,'writeoff_sequence_key':['2026-09-20','W2',2]}
  plan=C.classify_records([first,second],C.LedgerIndex(p),{});checked=V.validate(plan,rows)
  self.assertEqual(checked['conflict'],[])
  self.assertEqual(len(checked['write']),2)
  out=p.with_name('batch.xlsx');W.write_plan(p,out,checked['write']);self.assertEqual(W.verify_written(out,checked['write']),[])
 def test_skip_cannot_complete_flow(self):
  import flow_monthly as F
  p,plan,rows,_=self.plan();checked=V.validate(plan,rows)
  # Even accidentally attached proof cannot turn this business status into a receipt write.
  checked['skip'][0]['flow_receipt_proof']={'valid':True}
  item={'ar':'AR_TEST','monthly_schema':F.SCHEMA,'verdict':'write','monthly_receipts':[]}
  F.finalize([item],checked)
  self.assertFalse(item.get('monthly_receipts'))
 def test_validator_rejects_old_unsafe_plan(self):
  p,plan,rows,_=self.plan();item=plan['auto'][0]
  item.pop('source_history_gap',None);item['code']='';item['five_cols']={'回款明细':400,'计提':1000,'是否结账':'是','收款时间':'2026-09-20','收款方式':'汇','实收SOD':'SOD_TEST'}
  checked=V.validate(plan,rows);self.assertEqual(len(checked['conflict']),1)

 def test_gap_between_batch_events_is_detected(self):
  import source_history_gap as G
  sources=[{'split_payment_source':{'amount_local':400,'cumulative_local':400,'delivery_local':1000}},
           {'split_payment_source':{'amount_local':200,'cumulative_local':1000,'delivery_local':1000}}]
  proof=G.inspect(sources,{'2':{'回款明细':None}})
  self.assertEqual(proof['missing_prior_local'],400)
