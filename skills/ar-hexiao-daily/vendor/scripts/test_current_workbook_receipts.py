"""Current workbook must produce the same result regardless of old journals."""
import copy
import unittest
import baseline_receipts as BR
import classify_hexiao as C
import validate_plan as V


def fixture():
    so, sod, day = 'SO_CURRENT', 'SOD_CURRENT', '2026-08-20'
    rows = {2: dict(so=so,sod=sod,yingshou=10,huikuan=10,jiezhang='是',shoukuan_time='2026-09-15',shoukuan_way='汇',jiti=None,chayi=None),
            3: dict(so=so,sod=sod,yingshou=40,huikuan=None,jiezhang='否',shoukuan_time=None,shoukuan_way=None,jiti=None,chayi=None)}
    records=[]
    for n,amount in enumerate([20,30]):
        arrival='2026-06-01' if n==0 else '2026-06-02'
        rows[4+n]=dict(so=so,sod=sod,yingshou=amount,huikuan=amount,jiezhang='是',shoukuan_time=arrival if n==0 else day,shoukuan_way='汇' if n==0 else '冲预收',jiti=None,chayi=None)
        records.append(dict(ar='AR_CURRENT_'+str(n),so=so,sod=sod,amount_orig=amount,amount_local=amount,deliver_orig=100,deliver_local=100,so_delivery_local=100,sod_delivery_local={sod:100},all_sods=[sod],cumulative_received_local=20 if n==0 else 50,currency='CNY',shoukuan_date=arrival,hexiao_date=day,status='正常',writeoff_sequence_key=[day,'HX_'+str(n),'DETAIL_'+str(n)]))
    return records,rows


def ledger(rows):
    by_so={};by_sod={}
    for ref,row in rows.items():
        by_so.setdefault(row['so'],[]).append(ref)
        by_sod.setdefault(row['sod'],[]).append(ref)
    return C.LedgerIndex(synthetic={'so':by_so,'sod':by_sod,'rows':rows})


class CurrentWorkbookRegression(unittest.TestCase):
    def test_exact_existing_receipt_does_not_require_unrelated_rows_in_source_prefix(self):
        records,rows=fixture();records=records[1:]
        records[0]['cumulative_received_local']=30
        current=ledger(rows)
        plan=C.classify_records(copy.deepcopy(records),current,{})
        checked=V.validate(plan,{int(k):v for k,v in BR.ledger_rows(current,'SO_CURRENT','SOD_CURRENT').items()})
        self.assertEqual(checked['counts'],{'write':0,'skip':1,'conflict':0},plan)
        self.assertTrue(checked['skip'][0]['current_workbook_receipts']['read_only_subset'])
        self.assertEqual(rows[4]['huikuan'],20)
        altered=copy.deepcopy(rows);altered[5]['shoukuan_time']='2026-01-01'
        self.assertEqual(V.validate(plan,{int(k):v for k,v in BR.ledger_rows(ledger(altered),'SO_CURRENT','SOD_CURRENT').items()})['counts']['conflict'],1)

    def test_multiple_source_receipts_already_aggregated_in_one_row(self):
        records,rows=fixture()
        rows[4].update(yingshou=50,huikuan=50,shoukuan_time='2026-08-20',shoukuan_way='冲预收')
        rows.pop(5)
        current=ledger(rows)
        plan=C.classify_records(copy.deepcopy(records),current,{})
        checked=V.validate(plan,{int(k):v for k,v in BR.ledger_rows(current,'SO_CURRENT','SOD_CURRENT').items()})
        self.assertEqual(checked['counts'],{'write':0,'skip':2,'conflict':0},plan)
        proof=checked['skip'][0]['current_workbook_receipts']
        self.assertEqual(len(proof['aggregate_groups']),1)
        self.assertEqual(set(proof['aggregate_groups'][0]['events']),{BR.event_key(r) for r in records})
        incomplete=copy.deepcopy(plan);incomplete['auto'].pop()
        self.assertEqual(V.validate(incomplete,{int(k):v for k,v in proof['before_rows'].items()})['counts']['conflict'],1)

    def test_existing_group_does_not_depend_on_old_event_markers(self):
        records,rows=fixture()
        states=[{}, {'future':{'signature':[10,'2026-09-15','汇']}},
                {'future':{'signature':[10,'2026-09-15','汇']},BR.event_key(records[1]):{'signature':[30,'2026-08-20','冲预收']}},
                {'stale':{'signature':[999,'2025-01-01','汇']}}]
        for events in states:
            with self.subTest(events=events):
                current=ledger(copy.deepcopy(rows))
                current.baseline_receipt_state={BR.group_key('SO_CURRENT','SOD_CURRENT'):{'baseline_receivable':100,'scope_only':True,'events':{},'ordinary_events':events}} if events else {}
                plan=C.classify_records(copy.deepcopy(records),current,{})
                self.assertEqual(plan['counts']['hold'],0,[(r['ar'],r['reason']) for r in plan['hold']])
                checked=V.validate(plan,{int(k):v for k,v in BR.ledger_rows(current,'SO_CURRENT','SOD_CURRENT').items()})
                self.assertEqual(checked['counts'],{'write':0,'skip':2,'conflict':0})
                self.assertEqual(current.row_snapshot[3]['huikuan'],None)


    def test_proof_rejects_incomplete_sources_and_reused_rows(self):
        import current_workbook_receipts as W
        records, rows = fixture()
        before = BR.ledger_rows(ledger(rows), 'SO_CURRENT', 'SOD_CURRENT')
        self.assertIsNone(W.prove(records[:1], before))
        changed = copy.deepcopy(records)
        changed[1]['cumulative_received_local'] = 49
        self.assertIsNone(W.prove(changed, before))
        changed = copy.deepcopy(before)
        changed['4']['SO'] = 'OTHER'
        self.assertIsNone(W.prove(records, changed))
        changed = copy.deepcopy(before)
        changed['3']['应收金额'] = 39
        self.assertIsNone(W.prove(records, changed))

    def test_current_proof_preserves_values_and_rejects_stale_plan_or_extra_write(self):
        records, rows = fixture()
        original = copy.deepcopy(rows)
        current = ledger(rows)
        plan = C.classify_records(records,current,{})
        self.assertEqual(rows, original)
        before = {int(k):v for k,v in BR.ledger_rows(current,'SO_CURRENT','SOD_CURRENT').items()}
        changed = copy.deepcopy(before)
        changed[3]['应收金额'] = 39
        self.assertEqual(V.validate(plan,changed)['counts']['conflict'],2)
        changed_plan = copy.deepcopy(plan)
        changed_plan['auto'][0]['five_cols']['计提'] = 100
        self.assertGreater(V.validate(changed_plan,before)['counts']['conflict'],0)
        reordered = {ref+10:row for ref,row in reversed(list(rows.items()))}
        other = ledger(reordered)
        rebuilt = C.classify_records(records,other,{})
        self.assertEqual(V.validate(rebuilt,{int(k):v for k,v in BR.ledger_rows(other,'SO_CURRENT','SOD_CURRENT').items()})['counts'],{'write':0,'skip':2,'conflict':0})

    def test_group_evidence_cannot_drop_a_source_member(self):
        records, rows = fixture()
        current = ledger(rows)
        plan = C.classify_records(records,current,{})
        plan['auto'] = plan['auto'][:1]
        before = {int(k):v for k,v in BR.ledger_rows(current,'SO_CURRENT','SOD_CURRENT').items()}
        self.assertEqual(V.validate(plan,before)['counts']['conflict'],1)


    def test_missing_prefix_event_is_filled_once_from_current_unpaid_capacity(self):
        records, rows = fixture()
        del rows[4]
        rows[3]['yingshou'] += 20
        current = ledger(rows)
        current.baseline_receipt_state = {BR.group_key('SO_CURRENT','SOD_CURRENT'):{'baseline_receivable':100,'scope_only':True,'events':{},'ordinary_events':{BR.event_key(records[0]):{'signature':[20,'2026-08-20','冲预收']}}}}
        plan = C.classify_records(records,current,{})
        before = {int(k):v for k,v in BR.ledger_rows(current,'SO_CURRENT','SOD_CURRENT').items()}
        checked = V.validate(plan,before)
        self.assertEqual(checked['counts'],{'write':1,'skip':1,'conflict':0},plan)
        item=checked['write'][0]
        self.assertEqual(item['ar'],records[0]['ar'])
        self.assertEqual(item['five_cols']['回款明细'],20)
        self.assertEqual(item['row_operation']['unpaid_receivable'],40)
        self.assertTrue(item.get('current_workbook_receipts'))


    def test_missing_one_and_multiple_events_write_readback_repeat(self):
        import tempfile, zipfile
        from pathlib import Path
        import openpyxl
        import apply_to_copy as A
        for missing_refs in ([4], [4,5]):
            with self.subTest(missing=missing_refs), tempfile.TemporaryDirectory() as tmp:
                records, rows = fixture()
                for ref in missing_refs:
                    rows[3]['yingshou'] += rows.pop(ref)['huikuan']
                book = openpyxl.Workbook();sheet=book.active;sheet.title='明细'
                sheet.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异','备注'])
                for row in rows.values():
                    sheet.append([row.get(k) for k in ('so','sod','yingshou','jiti','huikuan','jiezhang','shoukuan_time','shoukuan_way','chayi')]+['KEEP'])
                book.create_sheet('保留')['A1']='=1+2'
                before,after=Path(tmp)/'before.xlsx',Path(tmp)/'after.xlsx'
                book.save(before);book.close()
                original=before.read_bytes()
                plan=C.classify_records(records,C.LedgerIndex(before),{})
                checked=V.validate(plan,A.read_ledger_rows(before))
                self.assertEqual(checked['counts'],{'write':len(missing_refs),'skip':2-len(missing_refs),'conflict':0},checked)
                A.write_plan(before,after,checked['write'])
                self.assertEqual(A.verify_written(after,checked['write']),[])
                actual=A.read_ledger_rows(after)
                self.assertEqual(sum(r['回款明细'] or 0 for r in actual.values()),60)
                self.assertEqual(sum(r['应收金额'] for r in actual.values()),100)
                unpaid=[r for r in actual.values() if r['是否结账']=='否']
                self.assertEqual([r['应收金额'] for r in unpaid],[40])
                self.assertEqual([r['回款明细'] for r in actual.values() if r['收款时间']=='2026-09-15'],[10])
                repeated=C.classify_records(records,C.LedgerIndex(after),{})
                self.assertEqual(V.validate(repeated,actual)['counts'],{'write':0,'skip':2,'conflict':0},repeated)
                self.assertEqual(before.read_bytes(),original)
                with zipfile.ZipFile(before) as b,zipfile.ZipFile(after) as a:
                    self.assertEqual(b.read('xl/worksheets/sheet2.xml'),a.read('xl/worksheets/sheet2.xml'))


    def test_equal_complete_events_keep_occurrence_count(self):
        records,rows=fixture()
        rows[5].update(yingshou=20,huikuan=20,shoukuan_time='2026-06-01',shoukuan_way='汇')
        rows[3]['yingshou']=50
        records[1].update(amount_orig=20,amount_local=20,cumulative_received_local=40,shoukuan_date='2026-06-01')
        current=ledger(rows)
        plan=C.classify_records(records,current,{})
        checked=V.validate(plan,{int(k):v for k,v in BR.ledger_rows(current,'SO_CURRENT','SOD_CURRENT').items()})
        self.assertEqual(checked['counts'],{'write':0,'skip':2,'conflict':0},plan)
        self.assertEqual(len({r['ledger_row_ref'] for r in checked['skip']}),2)

    def test_crossday_prefix_uses_current_prior_rows_not_old_journal(self):
        records,rows=fixture()
        rows[6]=dict(so='SO_CURRENT',sod='SOD_CURRENT',yingshou=5,huikuan=5,jiezhang='是',shoukuan_time='2026-05-01',shoukuan_way='汇',jiti=None,chayi=None)
        rows[3]['yingshou']-=5
        for rec in records:rec['cumulative_received_local']+=5
        current=ledger(rows)
        plan=C.classify_records(records,current,{})
        checked=V.validate(plan,{int(k):v for k,v in BR.ledger_rows(current,'SO_CURRENT','SOD_CURRENT').items()})
        self.assertEqual(checked['counts'],{'write':0,'skip':2,'conflict':0},plan)
        self.assertTrue(all(r.get('current_workbook_receipts') for r in checked['skip']))

    def test_foreign_receipts_use_explicit_local_amount_for_profit_ledger(self):
        records,rows=fixture()
        for r in records:r.update(currency='美元USD',amount_orig=r['amount_local']/7)
        current=ledger(rows)
        plan=C.classify_records(records,current,{})
        checked=V.validate(plan,{int(k):v for k,v in BR.ledger_rows(current,'SO_CURRENT','SOD_CURRENT').items()})
        self.assertEqual(checked['counts'],{'write':0,'skip':2,'conflict':0},plan)
        self.assertTrue(all(r.get('current_workbook_receipts') for r in checked['skip']))


    def test_missing_final_receipts_settle_once_with_one_accrual(self):
        import tempfile
        from pathlib import Path
        import openpyxl
        import apply_to_copy as A
        for keep_first in (True,False):
            with self.subTest(keep_first=keep_first),tempfile.TemporaryDirectory() as tmp:
                records,rows=fixture()
                del rows[2];del rows[5]
                records[1].update(amount_local=80,amount_orig=80,cumulative_received_local=100)
                rows[3]['yingshou']=80
                if not keep_first:
                    del rows[4];rows[3]['yingshou']=100
                wb=openpyxl.Workbook();ws=wb.active;ws.title='明细'
                ws.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
                for r in rows.values():ws.append([r.get(k) for k in ('so','sod','yingshou','jiti','huikuan','jiezhang','shoukuan_time','shoukuan_way','chayi')])
                before,after=Path(tmp)/'before.xlsx',Path(tmp)/'after.xlsx'
                wb.save(before);wb.close()
                plan=C.classify_records(records,C.LedgerIndex(before),{})
                checked=V.validate(plan,A.read_ledger_rows(before))
                self.assertEqual(checked['counts'],{'write':1 if keep_first else 2,'skip':1 if keep_first else 0,'conflict':0},checked)
                self.assertTrue(all(i.get('current_workbook_receipts') for i in checked['write']))
                A.write_plan(before,after,checked['write'])
                self.assertEqual(A.verify_written(after,checked['write']),[])
                actual=A.read_ledger_rows(after)
                self.assertEqual(sum(r['回款明细'] or 0 for r in actual.values()),100)
                self.assertEqual(sum(r['计提'] or 0 for r in actual.values()),100)
                self.assertTrue(all(r['是否结账']=='是' for r in actual.values()))
                repeat=C.classify_records(records,C.LedgerIndex(after),{})
                self.assertEqual(V.validate(repeat,actual)['counts'],{'write':0,'skip':2,'conflict':0})


    def test_multisod_existing_proof_does_not_clear_accrual_or_close_sibling(self):
        records,rows=fixture()
        rows[4]['jiti']=100
        rows[7]=dict(so='SO_CURRENT',sod='SOD_OTHER',yingshou=50,huikuan=None,jiezhang='否',shoukuan_time=None,shoukuan_way=None,jiti=None,chayi=None)
        for r in records:
            r['all_sods']=['SOD_CURRENT','SOD_OTHER']
            r['sod_delivery_local']={'SOD_CURRENT':100,'SOD_OTHER':50}
            r['so_delivery_local']=150
        current=ledger(rows)
        plan=C.classify_records(records,current,{})
        all_rows={}
        for sod in ['SOD_CURRENT','SOD_OTHER']:all_rows.update({int(k):v for k,v in BR.ledger_rows(current,'SO_CURRENT',sod).items()})
        checked=V.validate(plan,all_rows)
        self.assertEqual(checked['counts'],{'write':0,'skip':2,'conflict':0},plan)
        self.assertTrue(all(i.get('current_workbook_receipts') for i in checked['skip']))
        self.assertTrue(all(not i.get('so_accrual_backfills') for i in checked['skip']))
        self.assertTrue(all(not i['so_accrual_audit']['all_settled'] for i in checked['skip']))
        self.assertEqual(next(i for i in checked['skip'] if i['ledger_row_ref']==4)['five_cols']['计提'],100)


    def test_multisod_writes_gate_accrual_and_repeat(self):
        import tempfile
        from pathlib import Path
        import openpyxl
        import apply_to_copy as A
        for second_amount,first_present in ((50,False),(20,False),(50,True)):
            with self.subTest(second=second_amount,first_present=first_present),tempfile.TemporaryDirectory() as tmp:
                records=[]
                for i,(sod,delivery,amount) in enumerate([('SOD_A',100,100),('SOD_B',50,second_amount)]):
                    records.append(dict(ar='AR_MULTI_'+str(i),so='SO_MULTI',sod=sod,amount_orig=amount,amount_local=amount,
                        deliver_orig=delivery,deliver_local=delivery,so_delivery_local=150,currency='CNY',
                        all_sods=['SOD_A','SOD_B'],sod_delivery_local={'SOD_A':100,'SOD_B':50},
                        cumulative_received_local=amount,shoukuan_date='2026-08-01',hexiao_date='2026-08-20',
                        status='正常',writeoff_sequence_key=['2026-08-20','HX_MULTI_'+str(i),'DETAIL_'+str(i)]))
                wb=openpyxl.Workbook();ws=wb.active;ws.title='明细'
                ws.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
                ws.append(['SO_MULTI','SOD_A',100,None,100 if first_present else None,'是' if first_present else '否','2026-08-01' if first_present else None,'汇' if first_present else None,None])
                ws.append(['SO_MULTI','SOD_B',50,None,None,'否',None,None,None])
                before,after=Path(tmp)/'before.xlsx',Path(tmp)/'after.xlsx'
                wb.save(before);wb.close()
                plan=C.classify_records(records,C.LedgerIndex(before),{})
                checked=V.validate(plan,A.read_ledger_rows(before))
                self.assertEqual(checked['counts'],{'write':1 if first_present else 2,'skip':1 if first_present else 0,'conflict':0},checked)
                self.assertTrue(all(r.get('current_workbook_receipts') for r in checked['write']))
                A.write_plan(before,after,checked['write'])
                self.assertEqual(A.verify_written(after,checked['write']),[])
                actual=A.read_ledger_rows(after)
                self.assertEqual(sum(r['计提'] or 0 for r in actual.values()),150 if second_amount==50 else 0)
                self.assertEqual(sum(r['回款明细'] or 0 for r in actual.values()),100+second_amount)
                repeated=C.classify_records(records,C.LedgerIndex(after),{})
                self.assertEqual(V.validate(repeated,actual)['counts'],{'write':0,'skip':2,'conflict':0},repeated)
                dropped=copy.deepcopy(plan);dropped['auto']=dropped['auto'][:1]
                self.assertEqual(V.validate(dropped,A.read_ledger_rows(before))['counts']['conflict'],1)

if __name__=='__main__':unittest.main()
