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
    def test_write_after_review_uses_explicit_current_plan_evidence(self):
        import openpyxl
        import apply_to_copy as W
        import classification_cli as CLI
        import validate_plan as V
        with tempfile.TemporaryDirectory() as tmp:
            ws=Path(tmp);(ws/'02_我的表副本').mkdir();(ws/'03_台账').mkdir();(ws/'04_产出').mkdir()
            ledger=ws/'02_我的表副本'/'ledger.xlsx'
            book=openpyxl.Workbook();sheet=book.active;sheet.title='明细'
            sheet.append(['SO','SOD','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
            sheet.append(['SO_SMALL','SOD_SMALL',987.84,None,None,'否',None,None,None])
            sheet.append(['SO_LARGE','SOD_LARGE',29000,None,None,'否',None,None,None])
            book.save(ledger);book.close()
            fixture=ws/'fixture.json'
            fixture.write_text(json.dumps({'payments':[{
                'ar':'AR_TEST','amount_orig':664.61,'amount_local':664.61,
                'total_amount_orig':664.61,'total_amount_local':664.61,'currency':'CNY',
                'hexiao_date':'2026-09-03','arrival_date':'2026-08-12','status':'手动核销',
                'orders':[{'so':'SO_SMALL','deliver':987.84,'deliver_local':987.84,'currency':'CNY','delivery_date':'2026-05-06'},
                          {'so':'SO_LARGE','deliver':29000,'deliver_local':29000,'currency':'CNY','delivery_date':'2026-04-20'}],
                'writeoffs':{},'writeoffs_local':{}
            }], 'sod_lines':{
                'SO_SMALL':[{'sod':'SOD_SMALL','deliver':987.84,'deliver_local':987.84}],
                'SO_LARGE':[{'sod':'SOD_LARGE','deliver':29000,'deliver_local':29000}]
            }}),encoding='utf-8')
            name_map=ws/'name-map.json';name_map.write_text('[]',encoding='utf-8')
            initial_out=ws/'04_产出'/'initial.json'
            common_args=['--workspace',str(ws),'--fixture',str(fixture),'--hexiao-date','2026-09-03',
                         '--name-map',str(name_map)]
            self.assertEqual(CLI.main([*common_args,'--ledger-year',f'2026={ledger}','--out',str(initial_out)]),0)
            initial=json.loads(initial_out.read_text(encoding='utf-8'))
            self.assertEqual(initial['counts'],{'auto':1,'hold':0,'exception':0,'total':1})
            item=copy.deepcopy(initial['auto'][0]);item['_check']={'verdict':'write','reason':'synthetic verified plan'}
            checked={**initial,'write':[item],'skip':[],'conflict':[],
                     'counts':{'write':1,'skip':0,'conflict':0}}
            after=ws/'02_我的表副本'/'ledger-after.xlsx'
            W.write_plan(ledger,after,checked['write'])
            self.assertEqual(W.verify_written(after,checked['write']),[])
            evidence=ws/'03_台账'/'本次核销计划证据.json';evidence.write_text(json.dumps(checked),encoding='utf-8')
            out=ws/'04_产出'/'repeat.json'
            rc=CLI.main([*common_args,'--ledger-year',f'2026={after}',
                         '--current-run-plan',str(evidence),'--out',str(out)])
            self.assertEqual(rc,0)
            result=json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(result['counts'],{'auto':1,'hold':0,'exception':0,'total':1})
            self.assertEqual((result['auto'][0]['so'],result['auto'][0]['code']),
                             ('SO_SMALL','OK_REGISTERED_RECEIPT_ALREADY_APPLIED'))
            self.assertFalse(any(row.get('so')=='SO_LARGE' for bucket in ('auto','hold','exception') for row in result[bucket]))
            # This focused fixture has no raw writeoff rows, so omit the unrelated
            # duplicate-writeoff audit gate before exercising current-run evidence.
            result.pop('duplicate_writeoff_audits',None)
            result.pop('duplicate_writeoff_audit_sha256',None)
            out.write_text(json.dumps(result),encoding='utf-8')
            rechecked=ws/'04_\u4ea7\u51fa'/'rechecked.json'
            validate_rc=V.main(['--workspace',str(ws),'--plan',str(out),'--ledger-year',f'2026={after}',
                                '--current-run-plan',str(evidence),'--out',str(rechecked)])
            self.assertEqual(validate_rc,0)
            self.assertEqual(json.loads(rechecked.read_text(encoding='utf-8'))['counts'],
                             {'write':0,'skip':1,'conflict':0})

    def test_hold_report_only_contains_current_source_orders(self):
        import rescan_holds as H
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'03_台账').mkdir();H.ledger_path(p).write_bytes(b'corrupt old hold ledger')
            result=p/'result.json';result.write_text(json.dumps({'business_rules':{'decision_basis':M.POLICY},'auto':[],'hold':[],'exception':[]}))
            self.assertEqual(H.main(['--workspace',str(p),'--result',str(result),'--no-reclassify']),0)
            self.assertEqual(H.load_ledger(H.ledger_path(p)),[])
