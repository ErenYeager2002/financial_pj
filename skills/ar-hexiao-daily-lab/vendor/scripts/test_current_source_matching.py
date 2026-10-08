"""Cross-day matching must use current exports and current rows, not journals."""
import copy
import common
import unittest
import baseline_receipts as BR
import current_workbook_receipts as W
import classify_hexiao as C
import validate_plan as V
from test_current_workbook_receipts import fixture, ledger


def fixture_crossday(present):
    records,rows=fixture()
    records=records[:1]
    rec=records[0]
    rec.update(shoukuan_date='2026-06-01',cumulative_received_local=40)
    rows.pop(5)
    rows[4].update(shoukuan_time='2026-06-01')
    rows[3]['yingshou']=70
    if present:
        rows[5]=copy.deepcopy(rows[4]);rows[5].update(shoukuan_time='2026-08-20',shoukuan_way='冲预收')
        rows[3]['yingshou']=50
    events=[]
    for n,(ar,posting) in enumerate([('AR_PRIOR','2026-07-20'),(rec['ar'],rec['hexiao_date'])]):
        events.append(dict(ar=ar,so=rec['so'],record_id='HX'+str(n),rowid='D'+str(n),
            posting_date=posting,arrival_date='2026-06-01',amount_orig=20,amount_local=20,
            currency='CNY',status='正常',missing_fields=[]))
    rec['current_source_history']=dict(basis='audited_current_exports',as_of_date=rec['hexiao_date'],
        events=events,unresolved_parent_ars=[],identity_fields_complete=True)
    return records,rows

class CrossdaySourceMatching(unittest.TestCase):
    def test_equal_prior_and_missing_current_are_distinct(self):
        records,rows=fixture_crossday(False)
        for journal in ({},{'stale':{'ordinary_events':{'bad':{}}}}):
            current=ledger(rows);current.baseline_receipt_state=journal
            plan=C.classify_records(copy.deepcopy(records),current,{})
            checked=V.validate(plan,{int(k):v for k,v in BR.ledger_rows(current,'SO_CURRENT','SOD_CURRENT').items()})
            self.assertEqual(checked['counts'],{'write':1,'skip':0,'conflict':0},plan)
            proof=checked['write'][0]['current_workbook_receipts']
            self.assertEqual(proof['protected_prior_rows'],['4'])
            self.assertEqual(checked['write'][0]['row_operation']['unpaid_receivable'],50)

    def test_equal_prior_and_present_current_do_not_repeat(self):
        records,rows=fixture_crossday(True)
        proof=W.prove(records,BR.ledger_rows(ledger(rows),'SO_CURRENT','SOD_CURRENT'))
        self.assertIsNotNone(proof)
        self.assertEqual(proof['event_rows'][BR.event_key(records[0])],['5'])
        self.assertEqual(proof['protected_prior_rows'],['4'])

    def test_missing_or_invalid_history_cannot_be_used_as_complete_evidence(self):
        records,rows=fixture_crossday(False)
        for mutation in ('missing_prior','wrong_current','wrong_arrival','duplicate','revoked','foreign_so'):
            with self.subTest(mutation=mutation):
                changed=copy.deepcopy(records);events=changed[0]['current_source_history']['events']
                if mutation=='missing_prior':events.pop(0)
                if mutation=='wrong_current':events[-1]['amount_local']=19
                if mutation=='wrong_arrival':events[0]['arrival_date']='2026-07-02'
                if mutation=='duplicate':events.append(copy.deepcopy(events[0]))
                if mutation=='revoked':events[0]['status']='已作废'
                if mutation=='foreign_so':events[0]['so']='OTHER'
                self.assertIsNone(W.prove(changed,BR.ledger_rows(ledger(rows),'SO_CURRENT','SOD_CURRENT')))

    def test_indistinguishable_prior_and_current_rows_remain_ambiguous(self):
        records,rows=fixture_crossday(True)
        rows[5].update(shoukuan_time='2026-06-01',shoukuan_way='汇')
        self.assertIsNone(W.prove(records,BR.ledger_rows(ledger(rows),'SO_CURRENT','SOD_CURRENT')))

    def test_crossday_missing_write_readback_and_repeat_without_journal(self):
        import tempfile
        from pathlib import Path
        import openpyxl
        import apply_to_copy as A
        records,rows=fixture_crossday(False)
        with tempfile.TemporaryDirectory() as temp:
            before,after=Path(temp)/'before.xlsx',Path(temp)/'after.xlsx'
            wb=openpyxl.Workbook();ws=wb.active;ws.title='明细'
            ws.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
            for r in rows.values():ws.append([r.get(k) for k in ('so','sod','yingshou','jiti','huikuan','jiezhang','shoukuan_time','shoukuan_way','chayi')])
            wb.save(before);wb.close();original=before.read_bytes()
            plan=C.classify_records(copy.deepcopy(records),C.LedgerIndex(before),{})
            checked=V.validate(plan,A.read_ledger_rows(before))
            self.assertEqual(checked['counts'],{'write':1,'skip':0,'conflict':0})
            A.write_plan(before,after,checked['write'])
            self.assertEqual(A.verify_written(after,checked['write']),[])
            actual=A.read_ledger_rows(after)
            self.assertEqual(sorted((common.norm_date(r['收款时间']).isoformat(),r['回款明细']) for r in actual.values() if r['回款明细']),[('2026-06-01',20),('2026-08-20',20),('2026-09-15',10)])
            self.assertEqual([r['应收金额'] for r in actual.values() if r['是否结账']=='否'],[50])
            repeat=C.classify_records(copy.deepcopy(records),C.LedgerIndex(after),{})
            self.assertEqual(V.validate(repeat,actual)['counts'],{'write':0,'skip':1,'conflict':0})
            self.assertEqual(before.read_bytes(),original)

    def test_matching_solver_preserves_mandatory_history_for_all_small_graphs(self):
        import itertools
        from current_source_matching import _matching
        refs=['2','3']
        for bits in itertools.product((False,True),repeat=6):
            edges=[[ref for j,ref in enumerate(refs) if bits[2*i+j]] for i in range(3)]
            for mask in itertools.product((False,True),repeat=3):
                required={i for i,yes in enumerate(mask) if yes}
                for forced in [None]+[(i,ref) for i in range(3) for ref in edges[i]]:
                    allowed=[]
                    for owners in itertools.permutations(range(3),2):
                        if not required.issubset(owners):continue
                        if any(ref not in edges[owners[j]] for j,ref in enumerate(refs)):continue
                        if forced and owners[refs.index(forced[1])]!=forced[0]:continue
                        allowed.append(dict(zip(refs,owners)))
                    result=_matching(edges,required,refs,forced)
                    self.assertEqual(result is not None,bool(allowed),(edges,required,forced,result))
                    if result is not None:self.assertIn(result,allowed)

    def test_fragmented_current_receipt_is_proven_as_a_whole(self):
        records,rows=fixture_crossday(True)
        rows[5].update(yingshou=8,huikuan=8)
        rows[6]=copy.deepcopy(rows[5]);rows[6].update(yingshou=12,huikuan=12)
        current=ledger(rows)
        plan=C.classify_records(records,current,{})
        checked=V.validate(plan,{int(k):v for k,v in BR.ledger_rows(current,'SO_CURRENT','SOD_CURRENT').items()})
        self.assertEqual(checked['counts'],{'write':0,'skip':1,'conflict':0},plan)
        proof=checked['skip'][0]['current_workbook_receipts']
        self.assertEqual(proof['event_rows'][BR.event_key(records[0])],['5','6'])
        import flow_monthly as F
        flow=F.checked_receipt_proof(checked['skip'][0],{int(k):v for k,v in proof['before_rows'].items()},'2026-08-20',{})
        self.assertEqual(float(flow['amount']),20)
        altered=copy.deepcopy(rows);altered[6]['huikuan']=11
        self.assertEqual(V.validate(plan,{int(k):v for k,v in BR.ledger_rows(ledger(altered),'SO_CURRENT','SOD_CURRENT').items()})['counts']['conflict'],1)

    def test_fragmented_prior_does_not_block_missing_current(self):
        records,rows=fixture_crossday(False)
        rows[4].update(yingshou=8,huikuan=8)
        rows[6]=copy.deepcopy(rows[4]);rows[6].update(yingshou=12,huikuan=12)
        proof=W.prove(records,BR.ledger_rows(ledger(rows),'SO_CURRENT','SOD_CURRENT'))
        self.assertIsNotNone(proof)
        self.assertEqual(proof['protected_prior_rows'],['4','6'])
        self.assertEqual(proof['missing_events'],[BR.event_key(records[0])])

    def test_fragmented_assignment_cannot_borrow_from_another_event(self):
        records,rows=fixture_crossday(True)
        # Two source events share arrival dates. Several subsets can each make
        # 20, so the table cannot identify which belonged to the earlier posting.
        for ref in (4,5):rows[ref].update(yingshou=10,huikuan=10,shoukuan_time='2026-06-01',shoukuan_way='汇')
        rows[6]=copy.deepcopy(rows[4]);rows[7]=copy.deepcopy(rows[4])
        self.assertIsNone(W.prove(records,BR.ledger_rows(ledger(rows),'SO_CURRENT','SOD_CURRENT')))

    def test_unproven_source_ownership_cannot_fall_back_to_old_date_repair(self):
        records,rows=fixture_crossday(True)
        rows[5].update(shoukuan_time='2026-06-01',shoukuan_way='汇')
        for journal in ({},{BR.group_key('SO_CURRENT','SOD_CURRENT'):{'scope_only':True,'ordinary_events':{}}}):
            current=ledger(rows);current.baseline_receipt_state=journal
            plan=C.classify_records(copy.deepcopy(records),current,{})
            self.assertEqual(plan['counts']['auto'],0,plan)
            self.assertEqual(plan['counts']['hold'],1,plan)
            self.assertEqual(plan['hold'][0]['code'],'E_CURRENT_SOURCE_ROW_BINDING')
            self.assertTrue(plan['hold'][0]['current_workbook_conflict']['rows'])

if __name__=='__main__':unittest.main()
