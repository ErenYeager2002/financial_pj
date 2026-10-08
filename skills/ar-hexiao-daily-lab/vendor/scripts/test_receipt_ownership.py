"""Acceptance for two distinct source receipts with identical workbook values."""
import copy,tempfile,unittest
from pathlib import Path
import openpyxl
import classify_hexiao as C
import validate_plan as V
import apply_to_copy as W
import fallback_allocation_ledger as F

class ReceiptOwnershipTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.path=self.root/'ledger.xlsx'
        wb=openpyxl.Workbook();ws=wb.active;ws.title='明细'
        ws.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
        ws.append(['SO_TEST','SOD_TEST',1000,None,None,'否',None,None,None]);wb.save(self.path);wb.close()
    def tearDown(self):self.tmp.cleanup()
    def rec(self, ar, cumulative):
        return {'ar':ar,'so':'SO_TEST','sod':'SOD_TEST','amount_orig':500,'amount_local':500,
                'currency':'CNY','deliver_local':1000,'cumulative_received_local':cumulative,
                'shoukuan_date':'2026-09-20','hexiao_date':'2026-09-20','status':'已核销',
                'writeoff_sequence_key':['2026-09-20','HX_'+ar,'DETAIL_'+ar]}
    def plan(self, record):
        ledger=C.LedgerIndex(self.path)
        ledger.baseline_receipt_state=F.load(self.root).get('baseline_receipts',{})
        result=C.classify_records([record],ledger,{})
        result['hexiao_date']=record['hexiao_date']
        checked=V.validate(result,W.read_ledger_rows(self.path))
        checked['hexiao_date']='2026-09-20'
        return result,checked
    def apply(self,checked):
        before=self.path.read_bytes()
        if checked['write']:
            out=self.root/'next.xlsx';W.write_plan(self.path,out,checked['write'])
            self.assertEqual(W.verify_written(out,checked['write']),[])
            self.assertEqual(self.path.read_bytes(),before)
            out.replace(self.path)
        F.commit(self.root,checked)
    def test_two_equal_receipts_both_register_and_both_repeats_skip(self):
        a=self.rec('AR_FIRST',500);b=self.rec('AR_SECOND',1000)
        _,first=self.plan(a);self.assertEqual(len(first['write']),1);self.apply(first)
        _,repeat=self.plan(a);self.assertFalse(repeat['write']);self.assertEqual(len(repeat['skip']),1)
        result,second=self.plan(b)
        self.assertEqual(len(second['write']),1,{k:[(r.get('code'),r.get('reason')) for r in result.get(k,[])] for k in ['auto','hold','exception']})
        self.apply(second)
        wb=openpyxl.load_workbook(self.path,data_only=True)
        self.assertEqual(sum(float(row[0] or 0) for row in wb['明细'].iter_rows(min_row=2,min_col=5,max_col=5,values_only=True)),1000);wb.close()
        for rec in [a,b]:
            _,checked=self.plan(rec)
            self.assertFalse(checked['write']);self.assertEqual(len(checked['skip']),1)
    def test_verified_ordinary_write_preserves_source_identity(self):
        import baseline_receipts as BR
        rec=self.rec('AR_FIRST',500)
        _,checked=self.plan(rec)
        self.assertEqual(len(checked['write']),1)
        self.apply(checked)
        groups=F.load(self.root).get('baseline_receipts',{})
        group=groups.get(BR.group_key(rec['so'],rec['sod']),{})
        identities=set(group.get('events',{})) | set(group.get('ordinary_events',{}))
        self.assertIn(BR.event_key(rec),identities,
                      'successful write/readback must retain source receipt identity')
    def test_legacy_unattributed_row_does_not_prove_current_event(self):
        _,first=self.plan(self.rec('AR_FIRST',500));self.apply(first)
        # This emulates an uploaded historical workbook without its event journal.
        journal=self.root/'03_台账'/'父回款顺序分配台账.json'
        if journal.exists():journal.unlink()
        _,checked=self.plan(self.rec('AR_SECOND',1000))
        self.assertFalse(checked['skip'],'same visible values cannot prove current AR ownership')
    def test_equal_receipts_in_one_batch_keep_two_identities(self):
        import baseline_receipts as BR
        a=self.rec('AR_FIRST',500);b=self.rec('AR_SECOND',1000)
        result=C.classify_records([a,b],C.LedgerIndex(self.path),{})
        result['hexiao_date']=a['hexiao_date']
        checked=V.validate(result,W.read_ledger_rows(self.path))
        self.assertEqual(len(checked['write']),2)
        self.apply(checked)
        group=F.load(self.root)['baseline_receipts'][BR.group_key(a['so'],a['sod'])]
        self.assertEqual(len(group['ordinary_events']),2)
        self.assertEqual({e.get('signature_index') for e in group['ordinary_events'].values()},{0,1})
        for rec in (a,b):
            _,again=self.plan(rec)
            self.assertFalse(again['write'])
            self.assertEqual(len(again['skip']),1)

    def test_registered_source_amount_change_is_not_silently_skipped(self):
        rec=self.rec('AR_FIRST',500)
        _,checked=self.plan(rec);self.apply(checked)
        changed={**rec,'amount_local':501,'amount_orig':501,'cumulative_received_local':501}
        result,checked=self.plan(changed)
        self.assertFalse(checked['write']);self.assertFalse(checked['skip'])
        self.assertEqual(result['hold'][0]['code'],'E_RECEIPT_OWNERSHIP_UNRESOLVED')

    def test_reuploaded_material_restores_one_missing_registered_receipt(self):
        # Two older installments remain visible; only this event disappeared
        # from the uploaded workbook, leaving one uniquely matching blank row.
        wb=openpyxl.load_workbook(self.path);ws=wb['明细']
        ws.cell(2,3,9101.59)
        for amount in (405.41,752.10):
            ws.append(['SO_TEST','SOD_TEST',amount,None,amount,'是','2026-07-10','冲预收',None])
        wb.save(self.path);wb.close()
        rec=self.rec('AR_FIRST',10259.10)
        rec.update(amount_orig=9101.59,amount_local=9101.59,deliver_local=10259.10)
        _,first=self.plan(rec);self.assertEqual(len(first['write']),1);self.apply(first)
        wb=openpyxl.load_workbook(self.path);ws=wb['明细']
        for col in (4,5,7,8,9):ws.cell(2,col).value=None
        ws.cell(2,6).value='否'
        wb.save(self.path);wb.close()
        result,restored=self.plan(rec)
        self.assertEqual(len(restored['write']),1,
                         {k:[(r.get('code'),r.get('reason')) for r in result.get(k,[])]
                          for k in ('auto','hold','exception')})
        self.assertEqual(restored['write'][0]['ledger_row_ref'],2)
        self.apply(restored)
        rows=W.read_ledger_rows(self.path)
        self.assertEqual(rows[2]['回款明细'],9101.59)
        _,repeat=self.plan(rec)
        self.assertFalse(repeat['write']);self.assertEqual(len(repeat['skip']),1)

    def test_reuploaded_material_restores_registered_partial_receipt_by_split(self):
        # The verified receipt disappeared with an uploaded workbook. Its
        # uncollected row is larger than this installment and must be split.
        prior = [40500, 22800, 38774.30, 42322.50, 52650, 24300, 21600, 20250]
        wb = openpyxl.load_workbook(self.path)
        ws = wb['明细']
        ws.cell(2, 3, 17603.20)
        for amount in prior:
            ws.append(['SO_TEST', 'SOD_TEST', amount, None, amount, '是',
                       '2026-06-30', '汇', None])
        wb.save(self.path)
        wb.close()
        uploaded = self.path.read_bytes()
        rec = self.rec('AR_FIRST', 273321.80)
        rec.update(amount_orig=10125, amount_local=10125, deliver_local=280800,
                   shoukuan_date='2026-09-15', hexiao_date='2026-09-21')
        _, first = self.plan(rec)
        self.assertEqual(len(first['write']), 1)
        self.apply(first)
        self.path.write_bytes(uploaded)
        result, restored = self.plan(rec)
        self.assertEqual(len(restored['write']), 1,
                         {k: [(r.get('code'), r.get('reason')) for r in result.get(k, [])]
                          for k in ('auto', 'hold', 'exception')})
        self.assertEqual(restored['write'][0]['ledger_row_ref'], 2)
        self.apply(restored)
        rows = W.read_ledger_rows(self.path)
        self.assertAlmostEqual(sum(float(row['回款明细'] or 0) for row in rows.values()),
                               273321.80, places=2)
        self.assertEqual([round(float(row['应收金额']), 2) for row in rows.values()
                          if row['是否结账'] != '是'], [7478.20])
        _, repeat = self.plan(rec)
        self.assertFalse(repeat['write'])
        self.assertEqual(len(repeat['skip']), 1)

    def test_missing_identical_receipt_occurrence_is_not_skipped(self):
        for rec in (self.rec('AR_FIRST',500),self.rec('AR_SECOND',1000)):
            _,checked=self.plan(rec);self.apply(checked)
        wb=openpyxl.load_workbook(self.path);wb['明细'].delete_rows(3);wb.save(self.path);wb.close()
        result,checked=self.plan(self.rec('AR_SECOND',1000))
        self.assertFalse(checked['write']);self.assertFalse(checked['skip'])
        self.assertEqual(result['hold'][0]['code'],'E_RECEIPT_OWNERSHIP_UNRESOLVED')

    def test_registration_tampering_fails_before_commit(self):
        result,checked=self.plan(self.rec('AR_FIRST',500))
        changed=copy.deepcopy(result)
        changed['auto'][0]['ordinary_receipt_registration']['baseline_receivable']=999
        self.assertEqual(len(V.validate(changed,W.read_ledger_rows(self.path))['conflict']),1)
        changed=copy.deepcopy(checked)
        changed['write'][0]['ordinary_receipt_registration']['event_key']='other'
        with self.assertRaises(ValueError):F.preflight(self.root,changed)
        self.assertEqual(F.load(self.root).get('baseline_receipts',{}),{})

    def test_registered_repeat_checks_material_and_flow_proof(self):
        import flow_monthly, datetime
        rec=self.rec('AR_FIRST',500)
        _,first=self.plan(rec);self.apply(first)
        result,again=self.plan(rec)
        self.assertEqual(len(again['skip']),1)
        self.assertTrue(flow_monthly.valid_receipt_proof(again['skip'][0],datetime.date(2026,9,20)))
        rows=W.read_ledger_rows(self.path);rows[2]['回款明细']=499
        checked=V.validate(result,rows)
        self.assertEqual(len(checked['conflict']),1)
    def test_repeating_both_equal_events_in_one_batch_does_not_regroup(self):
        records=[self.rec('AR_FIRST',500),self.rec('AR_SECOND',1000)]
        for rec in records:
            _,checked=self.plan(rec);self.apply(checked)
        ledger=C.LedgerIndex(self.path)
        ledger.baseline_receipt_state=F.load(self.root)['baseline_receipts']
        result=C.classify_records(records,ledger,{})
        result['hexiao_date']=records[0]['hexiao_date']
        checked=V.validate(result,W.read_ledger_rows(self.path))
        self.assertEqual(len(checked['skip']),2)
        self.assertFalse(checked['write']);self.assertFalse(checked['conflict'])
        before=self.path.read_bytes();self.apply(checked)
        self.assertEqual(self.path.read_bytes(),before)

    def test_two_sods_each_keep_equal_receipts_distinct(self):
        wb=openpyxl.load_workbook(self.path)
        wb['明细'].append(['SO_TEST','SOD_OTHER',1000,None,None,'否',None,None,None])
        wb.save(self.path);wb.close()
        records=[]
        for cumulative,ar in [(500,'AR_FIRST'),(1000,'AR_SECOND')]:
            batch=[]
            for sod in ['SOD_TEST','SOD_OTHER']:
                rec={**self.rec(ar,cumulative),'sod':sod,'all_sods':['SOD_TEST','SOD_OTHER'],
                     'so_delivery_local':2000,'sod_delivery_local':{'SOD_TEST':1000,'SOD_OTHER':1000}}
                batch.append(rec);records.append(rec)
            ledger=C.LedgerIndex(self.path)
            ledger.baseline_receipt_state=F.load(self.root).get('baseline_receipts',{})
            result=C.classify_records(batch,ledger,{})
            checked=V.validate(result,W.read_ledger_rows(self.path))
            self.assertEqual(len(checked['write']),2,result)
            self.assertFalse(checked['conflict']);self.apply(checked)
        rows=W.read_ledger_rows(self.path)
        self.assertEqual(sum(row['回款明细'] or 0 for row in rows.values()),2000)
        for rec in records:
            _,again=self.plan(rec)
            self.assertFalse(again['write']);self.assertEqual(len(again['skip']),1)
    def test_registered_identity_still_allows_missing_accrual_repair(self):
        rec={**self.rec('AR_FIRST',1000),'amount_local':1000,'amount_orig':1000}
        _,checked=self.plan(rec);self.apply(checked)
        wb=openpyxl.load_workbook(self.path);wb['明细']['D2']=None;wb.save(self.path);wb.close()
        _,checked=self.plan(rec)
        self.assertEqual(len(checked['write']),1)
        self.assertEqual(checked['write'][0]['five_cols']['计提'],1000)
        self.apply(checked)
        _,again=self.plan(rec)
        self.assertFalse(again['write']);self.assertEqual(len(again['skip']),1)

    def test_published_parent_identity_survives_later_receipts(self):
        import baseline_receipts as BR
        rec=self.rec('AR_FIRST',500)
        _,checked=self.plan(rec);self.apply(checked)
        wb=openpyxl.load_workbook(self.path)
        wb['明细'].cell(3,3,300);wb['明细'].cell(3,5,300);wb['明细'].cell(3,6,'是')
        wb['明细'].cell(3,7,'2026-09-20');wb['明细'].cell(3,8,'汇')
        wb['明细'].append(['SO_TEST','SOD_TEST',200,None,None,'否',None,None,None])
        wb.save(self.path);wb.close()
        F.ledger_path(self.root).unlink()
        rec.pop('writeoff_sequence_key')
        rec['fallback_allocation_reused']=True
        rec['parent_allocation_audit']={'ar':'AR_FIRST','so':'SO_TEST','reused':True,'applied':True,
            'applied_cases':{'AR_FIRST|SO_TEST|SOD_TEST':{'so':'SO_TEST','sod':'SOD_TEST','amount_local':500}}}
        _,again=self.plan(rec)
        self.assertFalse(again['write']);self.assertEqual(len(again['skip']),1)

    def test_partly_registered_complete_group_can_still_repair_other_events(self):
        import baseline_receipts as BR
        from test_current_receipt_group import CurrentGroupTest
        records,ledger=CurrentGroupTest().fixture()
        ledger.row_snapshot[3].update(shoukuan_time='2026-08-20',shoukuan_way='冲预收')
        ledger.baseline_receipt_state={BR.group_key('SO_GROUP','SOD_GROUP'):{
            'baseline_receivable':200,'scope_only':True,'events':{},'ordinary_events':{
                BR.event_key(records[0]):{'signature':[20,'2026-08-20','冲预收']}}}}
        result=C.classify_records(records,ledger,{})
        self.assertEqual(len(result['auto']),6)
        rows={int(k):v for k,v in BR.ledger_rows(ledger,'SO_GROUP','SOD_GROUP').items()}
        checked=V.validate(result,rows)
        self.assertFalse(checked['conflict'])
        self.assertTrue(checked['write'])
        self.assertTrue(all(x.get('current_receipt_group') for x in result['auto']))
    def test_first_write_into_blank_sod_keeps_source_identity(self):
        import baseline_receipts as BR
        wb=openpyxl.load_workbook(self.path);wb['明细']['B2']=None;wb.save(self.path);wb.close()
        rec={**self.rec('AR_FIRST',500),'deliver_orig':1000,'all_sods':['SOD_TEST']}
        result,checked=self.plan(rec)
        self.assertEqual(len(checked['write']),1, {'classification':[(r.get('code'),r.get('reason')) for k in ['auto','hold','exception'] for r in result.get(k,[])], 'conflicts':[r.get('_check') for r in checked['conflict']]})
        self.apply(checked)
        group=F.load(self.root)['baseline_receipts'][BR.group_key(rec['so'],rec['sod'])]
        self.assertIn(BR.event_key(rec),group['ordinary_events'])
        _,again=self.plan(rec)
        self.assertFalse(again['write']);self.assertEqual(len(again['skip']),1)
    def test_blank_sod_first_write_rejects_extra_rows_and_source_sods(self):
        wb=openpyxl.load_workbook(self.path);wb['明细']['B2']=None;wb.save(self.path);wb.close()
        rec={**self.rec('AR_FIRST',500),'deliver_orig':1000,'all_sods':['SOD_TEST']}
        result,_=self.plan(rec);rows=W.read_ledger_rows(self.path)
        changed=copy.deepcopy(rows);changed[3]=copy.deepcopy(rows[2])
        self.assertEqual(len(V.validate(result,changed)['conflict']),1)
        changed=copy.deepcopy(result)
        changed['auto'][0]['split_payment_source']['all_sods'].append('SOD_OTHER')
        self.assertEqual(len(V.validate(changed,rows)['conflict']),1)
    def test_journal_version_changes_only_for_repeated_signature(self):
        _,first=self.plan(self.rec('AR_FIRST',500));self.apply(first)
        self.assertEqual(F.load(self.root)['version'],2)
        _,second=self.plan(self.rec('AR_SECOND',1000));self.apply(second)
        state=F.load(self.root)
        self.assertEqual(state['version'],3)
        state['parents']['AR_OLD']={'allocations':[],'applied_cases':{},'applied_sos':[]}
        after,_=F.prepare_commit(state,{'write':[],'skip':[]})
        self.assertEqual(after['version'],3)

    def test_legacy_versions_load_without_rewriting_files(self):
        import json
        for version in (1,2):
            path=F.ledger_path(self.root)
            path.write_text(json.dumps({'version':version,'parents':{}}))
            before=path.read_bytes()
            self.assertEqual(F.load(self.root)['version'],version)
            self.assertEqual(path.read_bytes(),before)
if __name__=='__main__':unittest.main()
