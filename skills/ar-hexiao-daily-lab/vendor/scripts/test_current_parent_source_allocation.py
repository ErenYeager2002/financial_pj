import copy,datetime as dt,unittest
import classify_hexiao as C,baseline_receipts as BR,validate_plan as V
import current_parent_allocation as M
import test_recognition_regressions as fixtures

class CurrentParentSourceAllocation(unittest.TestCase):
    def fixture(self,present):
        p=fixtures.parent(70);p['arrival_date']=dt.date(2026,8,4)
        p['sod_lines']={'SO_A':[{'sod':'SOD_A','deliver':40}],'SO_B':[{'sod':'SOD_B','deliver':60}]}
        p['cumulative_writeoffs']={'SO_A':10};p['cumulative_writeoffs_local']={'SO_A':10}
        event=dict(ar='AR_PRIOR',so='SO_A',record_id='HX_PRIOR',rowid='D1',posting_date='2026-07-01',arrival_date='2026-07-01',amount_orig=10,amount_local=10,currency='CNY',status='已核销',missing_fields=[])
        p['_current_source_history_by_so']={'SO_A':dict(basis='audited_current_exports',as_of_date='2026-08-05',events=[event],unresolved_parent_ars=[],identity_fields_complete=True)}
        rows={2:dict(so='SO_A',sod='SOD_A',yingshou=10,huikuan=10,jiti=None,jiezhang='是',shoukuan_time='2026-07-01',shoukuan_way='汇'),
              3:dict(so='SO_A',sod='SOD_A',yingshou=30,huikuan=30 if present else None,jiti=None,jiezhang='是' if present else '否',shoukuan_time='2026-08-04' if present else None,shoukuan_way='汇' if present else None),
              4:dict(so='SO_B',sod='SOD_B',yingshou=40 if present else 60,huikuan=40 if present else None,jiti=None,jiezhang='是' if present else '否',shoukuan_time='2026-08-04' if present else None,shoukuan_way='汇' if present else None)}
        if present:rows[5]=dict(so='SO_B',sod='SOD_B',yingshou=20,huikuan=None,jiti=None,jiezhang='否',shoukuan_time=None,shoukuan_way=None)
        by_so={};by_sod={}
        for ref,r in rows.items():by_so.setdefault(r['so'],[]).append(ref);by_sod.setdefault(r['sod'],[]).append(ref)
        ledger=C.LedgerIndex(synthetic={'so':by_so,'sod':by_sod,'rows':rows})
        p['_ledger_received_local_by_so']={'SO_A':40 if present else 10,'SO_B':40 if present else 0}
        p['_ledger_settled_sos']=['SO_A'] if present else []
        M.attach(p,{2026:ledger});return p,ledger

    def test_current_verified_source_history_beats_stale_parent_allocation(self):
        for present in (False,True):
            for old in ({},{'parents':{'AR_TEST':{'basis':'local','parent_amount':999,'allocations':[]}}}):
                with self.subTest(present=present,old=bool(old)):
                    p,l=self.fixture(present);p['_fallback_allocation_state']=old
                    records=C.expand_payments([p],{})
                    self.assertFalse(any(r.get('forced_code') for r in records),records)
                    self.assertEqual({r['so']:r['amount_local'] for r in records},{'SO_A':30,'SO_B':40})
                    self.assertEqual({r['so']:r['cumulative_received_local'] for r in records},{'SO_A':40,'SO_B':40})
                    self.assertTrue(p['_parent_fallback_allocation'].get('current_source_history_evidence'))
                    plan=C.classify_records(records,l,{})
                    rows={int(k):v for so,sod in [('SO_A','SOD_A'),('SO_B','SOD_B')] for k,v in BR.ledger_rows(l,so,sod).items()}
                    checked=V.validate(plan,rows)
                    self.assertEqual(checked['counts'],{'write':0 if present else 2,'skip':2 if present else 0,'conflict':0},plan)

    def test_source_prefix_or_row_disagreement_is_not_reconstructed(self):
        for mode in ('missing','wrong_date','revoked','wrong_amount'):
            p,l=self.fixture(True)
            event=p['_current_source_history_by_so']['SO_A']['events'][0]
            if mode=='missing':p['_current_source_history_by_so']['SO_A']['events']=[]
            if mode=='wrong_date':event['arrival_date']=event['posting_date']='2026-07-02'
            if mode=='revoked':event['status']='已作废'
            if mode=='wrong_amount':event['amount_orig']=event['amount_local']=9
            C.expand_payments([p],{})
            self.assertFalse((p.get('_parent_fallback_allocation') or {}).get('current_source_history_evidence'),mode)

    def test_current_parent_history_write_readback_and_repeat(self):
        import tempfile,openpyxl
        from pathlib import Path
        import apply_to_copy as A
        with tempfile.TemporaryDirectory() as temp:
            p,l=self.fixture(False)
            wb=openpyxl.Workbook();ws=wb.active;ws.title='明细'
            ws.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
            for row in l.row_snapshot.values():ws.append([row.get(k) for k in ('so','sod','yingshou','jiti','huikuan','jiezhang','shoukuan_time','shoukuan_way','chayi')])
            before,after=Path(temp)/'before.xlsx',Path(temp)/'after.xlsx';wb.save(before);wb.close();original=before.read_bytes()
            current=C.LedgerIndex(before);M.attach(p,{2026:current})
            plan=C.classify_records(C.expand_payments([p],{}),current,{})
            checked=V.validate(plan,A.read_ledger_rows(before))
            self.assertEqual(checked['counts'],{'write':2,'skip':0,'conflict':0})
            A.write_plan(before,after,checked['write']);self.assertEqual(A.verify_written(after,checked['write']),[])
            actual=A.read_ledger_rows(after)
            self.assertEqual(sum(r['回款明细'] or 0 for r in actual.values()),80)
            self.assertEqual(sum(r['应收金额'] or 0 for r in actual.values()),100)
            self.assertEqual([(r['SO'],r['应收金额']) for r in actual.values() if r['是否结账']=='否'],[('SO_B',20)])
            next_payment,_=self.fixture(True);current=C.LedgerIndex(after);M.attach(next_payment,{2026:current})
            repeat=C.classify_records(C.expand_payments([next_payment],{}),current,{})
            self.assertEqual(V.validate(repeat,actual)['counts'],{'write':0,'skip':2,'conflict':0},repeat)
            self.assertEqual(before.read_bytes(),original)

    def test_historical_fully_paid_so_gets_zero_and_parent_goes_to_next_order(self):
        p,l=self.fixture(False)
        p.update(amount_orig=30,amount_local=30,total_amount_orig=30,total_amount_local=30)
        p['cumulative_writeoffs']=p['cumulative_writeoffs_local']={'SO_A':40}
        event=p['_current_source_history_by_so']['SO_A']['events'][0]
        event.update(amount_orig=40,amount_local=40)
        l.row_snapshot[2].update(yingshou=40,huikuan=40,jiti=40)
        l.row_snapshot.pop(3);l.so_index['SO_A']=[2];l.sod_index['SOD_A']=[2]
        p['_ledger_settled_sos']=['SO_A'];p['_ledger_received_local_by_so']['SO_A']=40
        p['_fallback_allocation_state']={'parents':{'AR_TEST':{'parent_amount':999}}}
        M.attach(p,{2026:l});records=C.expand_payments([p],{})
        self.assertTrue(p['_parent_fallback_allocation'].get('current_source_history_evidence'))
        allocated={r['so']:r['allocated_local'] for r in p['_parent_fallback_allocation']['allocations']}
        self.assertEqual(allocated,{'SO_A':0,'SO_B':30})
        self.assertEqual(sum(r.get('amount_local') or 0 for r in records),30)
        self.assertFalse(any(r.get('forced_code')=='E_PARENT_ALLOCATION_HISTORY_MISSING' for r in records),records)

    def test_exhausted_parent_keeps_later_so_zero(self):
        p,l=self.fixture(False)
        p.update(amount_orig=20,amount_local=20,total_amount_orig=20,total_amount_local=20)
        p['_fallback_allocation_state']={'parents':{'AR_TEST':{'parent_amount':999}}}
        M.attach(p,{2026:l});records=C.expand_payments([p],{})
        audit=p['_parent_fallback_allocation']
        self.assertTrue(audit.get('current_source_history_evidence'))
        self.assertEqual({r['so']:r['allocated_local'] for r in audit['allocations']},{'SO_A':20,'SO_B':0})
        self.assertEqual(audit['zero_sos'],['SO_B'])
        self.assertEqual(sum(r.get('amount_local') or 0 for r in records),20)

    def test_foreign_prior_uses_its_explicit_original_and_local_amounts(self):
        p,l=self.fixture(False)
        p.update(currency='USD',amount_orig=7,total_amount_orig=7)
        for order in p['orders']:
            order['currency']='USD';order['deliver']/=10
        for lines in p['sod_lines'].values():
            for line in lines:line['deliver']/=10;line['currency']='USD'
        event=p['_current_source_history_by_so']['SO_A']['events'][0]
        event.update(currency='USD',amount_orig=1.25,amount_local=10)
        p['cumulative_writeoffs']={'SO_A':1.25}
        p['_fallback_allocation_state']={'parents':{'AR_TEST':{'parent_amount':999}}}
        M.attach(p,{2026:l});records=C.expand_payments([p],{})
        self.assertFalse(any(r.get('forced_code') for r in records),records)
        audit=p['_parent_fallback_allocation']
        self.assertTrue(audit.get('current_source_history_evidence'))
        self.assertEqual({a['so']:a['allocated_local'] for a in audit['allocations']},{'SO_A':30,'SO_B':40})
        self.assertEqual({a['so']:a['allocated_orig'] for a in audit['allocations']},{'SO_A':3,'SO_B':4})
        self.assertEqual(audit['allocations'][0]['historical_received_orig'],1.25)
        self.assertEqual(audit['allocations'][0]['historical_received_local'],10)
        self.assertEqual(p['_fallback_cumulative_orig_by_so']['SO_A'],4.25)

if __name__=='__main__':unittest.main()
