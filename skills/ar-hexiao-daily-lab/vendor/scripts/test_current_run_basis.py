"""Current material decisions must be independent of earlier platform runs."""
import copy,json,tempfile,unittest
from pathlib import Path
import current_run_basis as M
import fallback_allocation_ledger as F
import classification_runner as R
from classification_ledger import LedgerIndex

class CurrentRunBasisTest(unittest.TestCase):
    def test_closed_delivery_is_not_vetoed_by_old_receivable_journal(self):
        rows={2:dict(so='SO_TEST',sod='SOD_TEST',yingshou=10,jiti=100,huikuan=10,jiezhang='是',shoukuan_time='2026-09-08',shoukuan_way='汇'),
              3:dict(so='SO_TEST',sod='SOD_TEST',yingshou=100,jiti=None,huikuan=90,jiezhang='是',shoukuan_time='2026-09-07',shoukuan_way='汇')}
        ledger=LedgerIndex(synthetic={'so':{'SO_TEST':[2,3]},'sod':{'SOD_TEST':[2,3]},'rows':rows})
        ledger.baseline_receipt_state={'old':{'receivable_group_scope':{'so':'SO_TEST','ledger_sod':'SOD_TEST','source_sods':['SOD_TEST'],'baseline_receivable':100}}}
        original=copy.deepcopy(rows)
        M.initialize([ledger])
        rec=dict(ar='AR_TEST',so='SO_TEST',sod='SOD_TEST',amount_orig=10,amount_local=10,deliver_orig=100,deliver_local=100,currency='CNY',hexiao_date='2026-09-08',shoukuan_date='2026-09-08',status='已核销',cumulative_received_local=100,writeoff_sequence_key=['2026-09-08','HX_TEST','ROW_TEST'],so_receipt_source={'all_sods':['SOD_TEST'],'delivery_local':100,'sod_delivery_local':{'SOD_TEST':100},'amount_local':10,'amount_orig':10,'cumulative_local':100,'currency':'CNY'})
        out=R.classify_records([rec],ledger,{})
        self.assertFalse(out['hold'],out)
        self.assertEqual(out['auto'][0]['code'],'OK_SO_ALREADY_SETTLED')
        self.assertEqual(rows,original)
    def test_current_preflight_ignores_missing_corrupt_or_conflicting_past_file(self):
        plan={'business_rules':{'decision_basis':M.POLICY},'write':[],'skip':[],'parent_fallback_allocations':{}}
        for raw in ['bad json',json.dumps({'version':999,'parents':{'OLD':{}}})]:
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp);q=p/'03_台账';q.mkdir();f=q/F.LEDGER_NAME;f.write_text(raw)
                F.preflight(p,plan)
                self.assertEqual(f.read_text(),raw)
    def test_audit_result_is_independent_of_old_entries(self):
        plan={'business_rules':{'decision_basis':M.POLICY},'write':[],'skip':[]}
        old={'parents':{'OLD':{'bad':'history'}},'baseline_receipts':{'bad':{}}}
        before=copy.deepcopy(old);a,_=F.prepare_commit(old,plan);b,_=F.prepare_commit({},plan)
        self.assertEqual(a,b);self.assertEqual(old,before)
    def test_legacy_plans_retain_their_bound_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'03_台账').mkdir();(p/'03_台账'/F.LEDGER_NAME).write_text('bad json')
            with self.assertRaises(ValueError):F.preflight(p,{'write':[],'skip':[]})

    def test_completion_uses_current_audit_even_with_corrupt_old_journals(self):
        import complete_execution as E
        import batch_ledger as B
        import rescan_holds as H
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'03_台账').mkdir()
            for name in [F.LEDGER_NAME,B.LEDGER_NAME]:(p/'03_台账'/name).write_text('corrupt old audit')
            H.save_ledger(H.ledger_path(p),[])
            plan={'business_rules':{'decision_basis':M.POLICY},'hexiao_date':'2026-09-08','write':[],'skip':[]}
            checked=p/'checked.json';checked.write_text(json.dumps(plan))
            publication={'reconciliation_date':'2026-09-08','schema_version':'ar-publication-v1','material_set_id':'synthetic','files':['synthetic'],'written':0,'material_version':1,'workflow_id':'synthetic'}
            artifact=E.build(p,checked,publication,'abc123')
            saved=json.loads(artifact.read_text())['json_ledgers']
            self.assertEqual(saved[F.LEDGER_NAME]['parents'],{})
            self.assertEqual((p/'03_台账'/F.LEDGER_NAME).read_text(),'corrupt old audit')
    def test_hold_report_only_contains_current_source_orders(self):
        import rescan_holds as H
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'03_台账').mkdir();H.ledger_path(p).write_bytes(b'corrupt old hold ledger')
            result=p/'result.json';result.write_text(json.dumps({'business_rules':{'decision_basis':M.POLICY},'auto':[],'hold':[],'exception':[]}))
            self.assertEqual(H.main(['--workspace',str(p),'--result',str(result),'--no-reclassify']),0)
            self.assertEqual(H.load_ledger(H.ledger_path(p)),[])
