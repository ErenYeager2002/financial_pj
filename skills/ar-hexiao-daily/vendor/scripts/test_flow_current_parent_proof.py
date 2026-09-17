import copy
import unittest
import datetime as dt
import baseline_receipts as BR
import current_parent_allocation as M
import flow_monthly as F
import build_flow_plan
import test_flow_monthly as T

class CurrentParentFlowProofTest(unittest.TestCase):
    def setup_case(self):
        fixture=T.MonthlySafetyTest();fixture.setUp();self.addCleanup(fixture.tearDown)
        fixture.modify(lambda w:(setattr(w['E2'],'value','WXSO1 20000'),setattr(w['F2'],'value',None)))
        row=fixture.entry(amount=9000)
        row.update(code='OK_SO_ALREADY_SETTLED',status='手动核销',_check={'verdict':'skip','reason':'整单已结账'})
        row['source_lineage']={'source':{'ar':'AR1','so':'SO1','reconciliation_date':'2026-07-28','parent_amount_local':9000,'order_writeoff_local':None}}
        row['split_payment_source']['so_delivery_local']=9000
        current={2:{'SO':'SO1','SOD':'SO1D','应收金额':9000,'计提':9000,'回款明细':9000,'是否结账':'是','收款时间':dt.date(2026,7,27),'收款方式':'汇','差异':None}}
        payment={'ar':'AR1','arrival_date':dt.date(2026,7,27),'hexiao_date':dt.date(2026,7,28),'amount_local':9000,'status':'手动核销','_current_parent_rows':{'SO1':{'2':BR.normalized(current[2])}}}
        audit=M.reconstruct(payment,{'SO1':{'deliver_local':9000,'deliver_orig':9000}},'local',9000)[2]
        return fixture,row,current,{'AR1':audit}
    def test_current_parent_can_recover_without_historical_journal(self):
        fixture,row,current,parents=self.setup_case()
        proof=F.checked_receipt_proof(row,current,'2026-07-28',parents)
        self.assertEqual(proof.get('basis'),'current_material_parent_case')
        row['flow_receipt_proof']=proof
        flow=build_flow_plan.build_plan({'auto':[row],'hexiao_date':'2026-07-28'})
        checked={'hexiao_date':'2026-07-28','write':[],'skip':[row],'conflict':[],'parent_fallback_allocations':parents}
        final=build_flow_plan.finalize_plan_after_ledger(flow,checked,workspace=fixture.root)
        self.assertEqual(final['items'][0]['verdict'],'write')
        import apply_flow
        changed,errors=apply_flow.write_flow_items(fixture.root,final['items'],in_place=True,phase='status')
        self.assertEqual(errors,[]);self.assertEqual(len(changed),1)
        self.assertEqual(fixture.read('F2'),'9000-9000=0')
        before=fixture.path.read_bytes()
        self.assertEqual(apply_flow.write_flow_items(fixture.root,final['items'],in_place=True,phase='status'),([],[]))
        self.assertEqual(fixture.path.read_bytes(),before)
    def test_changed_current_receipt_is_not_accepted(self):
        _,row,current,parents=self.setup_case();current[2]['回款明细']=8000
        self.assertEqual(F.checked_receipt_proof(row,current,'2026-07-28',parents),{})
    def test_same_amount_without_parent_evidence_is_not_accepted(self):
        _,row,current,_=self.setup_case()
        self.assertEqual(F.checked_receipt_proof(row,current,'2026-07-28',{}),{})
    def test_wrong_parent_total_date_or_extra_current_row_is_rejected(self):
        _,row,current,parents=self.setup_case()
        for mutate in [lambda p:p['AR1'].update(parent_amount=10000),lambda p:p['AR1'].update(hexiao_date='2026-07-29')]:
            p=copy.deepcopy(parents);mutate(p)
            self.assertEqual(F.checked_receipt_proof(row,current,'2026-07-28',p),{})
        extra=copy.deepcopy(current);extra[3]=copy.deepcopy(current[2])
        self.assertEqual(F.checked_receipt_proof(row,extra,'2026-07-28',parents),{})
