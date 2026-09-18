"""Pending SO display is independent of financial allocation."""
import copy,unittest
import openpyxl
import apply_flow,build_flow_plan,flow_monthly
from test_flow_monthly import MonthlySafetyTest as Fixture
class PendingOrders(unittest.TestCase):
 setUp=Fixture.setUp
 tearDown=Fixture.tearDown
 entry=Fixture.entry
 read=Fixture.read
 modify=Fixture.modify
 def pending(self,so='SO1',amount=1000):
  row=self.entry(so,amount);row.update(bucket='hold',code='E2')
  row['split_payment_source']['so_delivery_local']=amount
  return row
 def run_pending(self,rows,phase='status'):
  plan=build_flow_plan.build_plan({'hold':rows,'hexiao_date':'2026-07-28'})
  if phase=='status':plan=build_flow_plan.finalize_plan_after_ledger(plan,{'hexiao_date':'2026-07-28','write':[],'skip':[],'conflict':[]})
  return apply_flow.write_flow_items(self.root,plan['items'],in_place=True,phase=phase)
 def test_append_keeps_history_and_blank_balance(self):
  self.modify(lambda ws:(setattr(ws['E2'],'value','SXSO0  5,425.32'),setattr(ws['F2'],'value',None),setattr(ws['G2'],'value','是')))
  changes,errors=self.run_pending([self.pending(),self.pending('SO2',126.72)])
  self.assertEqual(errors,[]);self.assertTrue(changes)
  self.assertEqual(self.read('E2'),'SXSO0  5,425.32\nSO1  1,000.00\nSO2  126.72')
  self.assertIsNone(self.read('F2'));self.assertEqual(self.read('G2'),'是')
  self.assertEqual(flow_monthly.load_state(self.path)['receipts'],{})
  before=self.path.read_bytes();self.assertEqual(self.run_pending([self.pending(),self.pending('SO2',126.72)]),([],[]));self.assertEqual(self.path.read_bytes(),before)
 def test_prefill_phase_is_not_silent_noop(self):
  changes,errors=self.run_pending([self.pending()],phase='prefill')
  self.assertEqual(errors,[]);self.assertTrue(changes);self.assertEqual(self.read('F2'),9000);self.assertIsNone(self.read('G2'))
 def test_changed_amount_rejected(self):
  self.assertEqual(self.run_pending([self.pending()])[1],[]);before=self.path.read_bytes()
  self.assertTrue(self.run_pending([self.pending(amount=1200)])[1]);self.assertEqual(self.path.read_bytes(),before)
 def test_existing_conflicting_amount_rejected(self):
  self.modify(lambda ws:setattr(ws['E2'],'value','SO1  2000'));before=self.path.read_bytes()
  self.assertTrue(self.run_pending([self.pending()])[1]);self.assertEqual(self.path.read_bytes(),before)
 def test_unknown_amount_rejected(self):
  row=self.pending();row['split_payment_source'].pop('so_delivery_local');before=self.path.read_bytes()
  self.assertTrue(self.run_pending([row])[1]);self.assertEqual(self.path.read_bytes(),before)
 def test_verified_completion_after_prefill(self):
  self.modify(lambda ws:setattr(ws['F2'],'value',None))
  self.assertEqual(self.run_pending([self.pending()])[1],[])
  ready=self.entry();ready['split_payment_source']['so_delivery_local']=1000
  plan=build_flow_plan.build_plan({'auto':[ready],'hexiao_date':'2026-07-28'})
  final=build_flow_plan.finalize_plan_after_ledger(plan,{'hexiao_date':'2026-07-28','write':[ready]})
  self.assertEqual(apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status')[1],[])
  self.assertEqual(self.read('F2'),'9000-1000=8000');self.assertEqual(self.read('G2'),'是')
  self.assertEqual(self.read('E2').count('SO1'),1)
 def test_history_unknown_does_not_become_fake_allocation(self):
  self.modify(lambda ws:(setattr(ws['E2'],'value','SO0  2000'),setattr(ws['F2'],'value',None)))
  self.assertEqual(self.run_pending([self.pending()])[1],[]);before=self.path.read_bytes()
  ready=self.entry();plan=build_flow_plan.build_plan({'auto':[ready],'hexiao_date':'2026-07-28'})
  final=build_flow_plan.finalize_plan_after_ledger(plan,{'hexiao_date':'2026-07-28','write':[ready]})
  self.assertTrue(apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status')[1]);self.assertEqual(self.path.read_bytes(),before)
 def test_ambiguous_match_stays_manual(self):
  row=self.pending();row['flow_hits']=2;before=self.path.read_bytes()
  self.assertEqual(self.run_pending([row]),([],[]));self.assertEqual(self.path.read_bytes(),before)
 def test_conflicting_source_amounts_rejected(self):
  a=self.pending();b=self.pending(amount=1200);b['case_id']+='other'
  before=self.path.read_bytes();self.assertTrue(self.run_pending([a,b])[1]);self.assertEqual(self.path.read_bytes(),before)
 def test_duplicate_case_conflicting_amount_rejected(self):
  before=self.path.read_bytes();self.assertTrue(self.run_pending([self.pending(),self.pending(amount=1200)])[1]);self.assertEqual(self.path.read_bytes(),before)
 def test_changed_basis_at_completion_rejected(self):
  self.assertEqual(self.run_pending([self.pending()])[1],[]);before=self.path.read_bytes()
  ready=self.entry(amount=1200);ready['split_payment_source']['so_delivery_local']=1200
  plan=build_flow_plan.build_plan({'auto':[ready],'hexiao_date':'2026-07-28'})
  final=build_flow_plan.finalize_plan_after_ledger(plan,{'hexiao_date':'2026-07-28','write':[ready]})
  self.assertTrue(apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status')[1]);self.assertEqual(self.path.read_bytes(),before)
 def test_same_so_partial_cases_keep_pending(self):
  self.assertEqual(self.run_pending([self.pending()])[1],[])
  ready=self.entry(amount=500);ready['split_payment_source']['so_delivery_local']=1000
  missing=self.pending();missing['case_id']+='missing';missing['sod']='MISSING'
  plan=build_flow_plan.build_plan({'auto':[ready],'hold':[missing],'hexiao_date':'2026-07-28'})
  final=build_flow_plan.finalize_plan_after_ledger(plan,{'hexiao_date':'2026-07-28','write':[ready]})
  changes,errors=apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status')
  self.assertEqual(errors,[]);self.assertEqual(self.read('G2'),'部分');self.assertEqual(changes[0]['是否更新应收款'],'部分')
  self.assertIn('SO1',flow_monthly.load_state(self.path)['order_prefills']['AR1']['pending'])
 def test_other_ar_cannot_prefill_owned_row(self):
  ready=self.entry();flow=build_flow_plan.build_plan({'auto':[ready],'hexiao_date':'2026-07-28'})
  final=build_flow_plan.finalize_plan_after_ledger(flow,{'hexiao_date':'2026-07-28','write':[ready]})
  self.assertEqual(apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status')[1],[])
  row=self.pending('SO2');row['ar']='OTHER';before=self.path.read_bytes()
  self.assertTrue(self.run_pending([row])[1]);self.assertEqual(self.path.read_bytes(),before)
 def test_pending_row_moves_after_other_receipt_insertion(self):
  import datetime as dt
  self.modify(lambda ws:ws.append([dt.date(2026,7,27),'测试乙',9000,'汇款','YX',9000,None]))
  ready=self.entry();pending=self.pending('SO2');pending.update(ar='AR2',flow_row_no=3)
  pending['flow_identity']['payer']='测试乙'
  flow=build_flow_plan.build_plan({'auto':[ready],'hold':[pending],'hexiao_date':'2026-08-01'})
  final=build_flow_plan.finalize_plan_after_ledger(flow,{'hexiao_date':'2026-08-01','write':[ready]})
  changes,errors=apply_flow.write_flow_items(self.root,final['items'],in_place=True,phase='status')
  self.assertEqual(errors,[]);self.assertIn('SO2',self.read('E4'));self.assertEqual(self.read('F4'),9000)
  self.assertEqual(next(c['行号'] for c in changes if c['AR']=='AR2'),4)
 def test_rich_history_is_preserved(self):
  from openpyxl.cell.rich_text import CellRichText,TextBlock
  from openpyxl.cell.text import InlineFont
  self.modify(lambda ws:setattr(ws['E2'],'value',CellRichText('SX',TextBlock(InlineFont(color='FFFF0000'),'SO0  100.00'))))
  self.assertEqual(self.run_pending([self.pending()])[1],[])
  wb=openpyxl.load_workbook(self.path,rich_text=True)
  self.assertEqual(apply_flow._line_colors(wb['流水']['E2'].value)['SO0'],'FFFF0000');wb.close()
 def test_full_stage_and_independent_replay(self):
  import json,shutil
  import execution_flow_stage,verify_execution_write
  baseline=self.root/'before';relative=self.path.relative_to(self.root)
  (baseline/relative).parent.mkdir(parents=True);shutil.copy2(self.path,baseline/relative)
  out=self.root/'04_产出';out.mkdir(exist_ok=True)
  checked={'hexiao_date':'2026-07-28','write':[],'skip':[],'conflict':[]}
  checkpath=out/'checked.json';checkpath.write_text(json.dumps(checked))
  flow=build_flow_plan.build_plan({'hold':[self.pending()],'hexiao_date':'2026-07-28'})
  (out/'流转写入计划_校验后.json').write_text(json.dumps(flow))
  result=execution_flow_stage.run(self.root,checkpath)
  self.assertTrue(result['flow_written']);self.assertTrue(result['phases']['prefill']['applicable'])
  self.assertEqual(result['phases']['prefill']['unchanged_count'],0)
  (out/'流转阶段执行结果.json').write_text(json.dumps(result))
  verified=verify_execution_write.verify_flow(self.root,baseline,self.path,checked)
  self.assertEqual(verified['mode'],'approved_patch_all_parts')
if __name__=='__main__':unittest.main()
