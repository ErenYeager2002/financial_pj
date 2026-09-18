import copy
import unittest
import classify_hexiao as C
import baseline_receipts as BR
import validate_plan as V

class CurrentGroupTest(unittest.TestCase):
    def fixture(self):
        amounts=[20,110,30,30,8,2]
        days=['2026-02-01','2026-04-01','2026-05-01','2026-05-01','2026-05-02','2026-06-01']
        records=[];total=0
        for i,(amount,day) in enumerate(zip(amounts,days)):
            total+=amount
            records.append(dict(ar=f'AR_GROUP_{i}',so='SO_GROUP',sod='SOD_GROUP',amount_local=amount,amount_orig=amount,deliver_local=200,so_delivery_local=200,deliver_orig=200,currency='CNY',cumulative_received_local=total,shoukuan_date=day,hexiao_date='2026-08-20',delivery_date='2026-01-04',writeoff_sequence_key=['2026-08-20',f'HX_GROUP_{i}',f'DETAIL_{i}'],status='正常',all_sods=['SOD_GROUP'],sod_delivery_local={'SOD_GROUP':200}))
        values=[(7,None,'否',None,None),(20,20,'是',days[1],'汇'),(102,102,'是',days[1],'汇'),(30,30,'是',days[2],'汇'),(30,30,'是',days[3],'汇'),(8,8,'是',days[4],'汇'),(2,2,'是',days[5],'汇'),(1,1,'否',None,None)]
        raw={i+2:dict(so='SO_GROUP',sod='SOD_GROUP',yingshou=a,huikuan=p,jiezhang=s,shoukuan_time=d,shoukuan_way=w,jiti=None,chayi=None) for i,(a,p,s,d,w) in enumerate(values)}
        ledger=C.LedgerIndex(synthetic={'so':{'SO_GROUP':list(raw)},'sod':{'SOD_GROUP':list(raw)},'rows':raw})
        return records,ledger

    def test_complete_source_group_resolves_fragmented_and_equal_receipts(self):
        records,ledger=self.fixture()
        plan=C.classify_records(records,ledger,{})
        self.assertEqual(plan['counts'],{'auto':6,'hold':0,'exception':0,'total':6})
        rows={int(k):v for k,v in BR.ledger_rows(ledger,'SO_GROUP','SOD_GROUP').items()}
        checked=V.validate(plan,rows)
        self.assertEqual(checked['counts']['conflict'],0)
        self.assertEqual(len(checked['write']),6)
        group=plan['auto'][1]['current_receipt_group']
        self.assertEqual(sum(row['应收金额'] for row in group['after_rows'].values()),200)
        self.assertEqual(sum(row['回款明细'] for row in group['after_rows'].values()),200)
        self.assertEqual(group['event_rows'][BR.event_key(records[1])],['2','4','9'])

    def test_write_readback_and_repeat_preserve_original_rows_and_other_parts(self):
        import tempfile,zipfile
        from pathlib import Path
        import openpyxl
        import apply_to_copy as A
        records,ledger=self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            before,after=Path(tmp)/'before.xlsx',Path(tmp)/'after.xlsx'
            book=openpyxl.Workbook();sheet=book.active;sheet.title='明细'
            sheet.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异','备注'])
            for ref,row in ledger.row_snapshot.items():sheet.append([row.get(k) for k in ('so','sod','yingshou','jiti','huikuan','jiezhang','shoukuan_time','shoukuan_way','chayi')]+[f'keep-{ref}'])
            book.create_sheet('保留')['A1']='=1+2';book.save(before);book.close();original=before.read_bytes()
            plan=C.classify_records(records,C.LedgerIndex(before),{})
            checked=V.validate(plan,A.read_ledger_rows(before))
            self.assertEqual(checked['counts']['conflict'],0)
            items=checked['write'];changes,patch=A.write_plan(before,after,items,return_patch_result=True)
            A.write_change_report(changes,Path(tmp)/'changes.xlsx')
            report=openpyxl.load_workbook(Path(tmp)/'changes.xlsx')
            self.assertTrue(all(row[5].value is None for row in list(report.active)[1:]))
            report.close()
            self.assertEqual(A.verify_written(after,items),[])
            rows=A.read_ledger_rows(after)
            self.assertEqual(len(rows),8)
            self.assertEqual([r['应收金额'] for r in rows.values()],[7,20,102,30,30,8,2,1])
            self.assertEqual(sum(r['回款明细'] or 0 for r in rows.values()),200)
            self.assertEqual(sum(r['计提'] or 0 for r in rows.values()),200)
            for item in items:self.assertEqual(V.check_one(item,rows)['verdict'],'skip')
            repeated=C.classify_records(records,C.LedgerIndex(after),{})
            again=V.validate(repeated,rows)
            self.assertEqual((len(again['write']),len(again['skip']),len(again['conflict'])),(0,6,0))
            with zipfile.ZipFile(before) as b,zipfile.ZipFile(after) as a:
                self.assertEqual(b.namelist(),a.namelist())
                for name in b.namelist():
                    if name not in ('xl/worksheets/sheet1.xml','xl/styles.xml','xl/workbook.xml'):self.assertEqual(b.read(name),a.read(name),name)
                from xml.etree import ElementTree as ET
                old,new=ET.fromstring(b.read('xl/workbook.xml')),ET.fromstring(a.read('xl/workbook.xml'))
                for tree in (old,new):
                    for child in list(tree):
                        if child.tag.endswith('}calcPr'):tree.remove(child)
                self.assertEqual(ET.tostring(old),ET.tostring(new))
                old,new=ET.fromstring(b.read('xl/styles.xml')),ET.fromstring(a.read('xl/styles.xml'))
                ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                old_xfs=old.find('s:cellXfs',ns);new_xfs=new.find('s:cellXfs',ns)
                self.assertEqual([ET.tostring(x) for x in old_xfs],[ET.tostring(x) for x in list(new_xfs)[:len(old_xfs)]])
            book=openpyxl.load_workbook(after);self.assertEqual([book['明细'].cell(r,10).value for r in range(2,10)],[f'keep-{r}' for r in range(2,10)]);book.close()
            import workbook_finalize
            workbook_finalize.finalize_workbook(after,{"明细":patch})
            self.assertEqual(A.verify_written(after,items),[])
            difference=A.build_order_difference(items,after,hexiao_date="2026-08-20")
            self.assertEqual(difference["difference_count"],0)
            import verify_execution_write as E
            self.assertGreater(E.verify_package(before,after,checked['write'],Path(tmp)/'expected.xlsx')['parts_checked'],0)
            from flow_monthly import checked_receipt_proof,valid_receipt_proof,actual_amount
            import datetime as dt
            for item in again['skip']:
                item['flow_receipt_proof']=checked_receipt_proof(item,rows,'2026-08-20',{})
                self.assertTrue(valid_receipt_proof(item,dt.date(2026,8,20)))
            self.assertEqual(actual_amount(again['skip'][1]),110)
            self.assertEqual(before.read_bytes(),original)
            from unittest.mock import patch
            with patch.object(A, 'write_change_report', side_effect=OSError('report destination unavailable')):
                rc=A._apply_in_place(before,Path(tmp)/'failed-report.xlsx',Path(tmp)/'diff.xlsx',copy.deepcopy(checked['write']),hexiao_date='2026-08-20')
            self.assertEqual(rc,2)
            self.assertEqual(before.read_bytes(),original)
            self.assertFalse((Path(tmp)/'failed-report.xlsx').exists())
            self.assertFalse((Path(tmp)/'diff.xlsx').exists())
            report_path=Path(tmp)/'old-report.xlsx';diff_path=Path(tmp)/'old-diff.xlsx'
            report_path.write_bytes(b'previous report');diff_path.write_bytes(b'previous difference')
            replace=Path.replace
            def reject_ledger(source,target):
                if Path(target)==before:raise OSError('ledger replacement unavailable')
                return replace(source,target)
            with patch.object(Path,'replace',reject_ledger):
                rc=A._apply_in_place(before,report_path,diff_path,copy.deepcopy(checked['write']),hexiao_date='2026-08-20')
            self.assertEqual(rc,2)
            self.assertEqual(before.read_bytes(),original)
            self.assertEqual(report_path.read_bytes(),b'previous report')
            self.assertEqual(diff_path.read_bytes(),b'previous difference')
            portable=A.workbook_finalize.portable_path_for(before);portable.write_bytes(b'previous portable')
            finalize=A._finalize_output
            def portable_result(source,patch_result,portable_tmp,**kwargs):
                result,_=finalize(source,patch_result,portable_tmp,**kwargs)
                portable_tmp.write_bytes(b'new portable')
                return result,(portable_tmp,{})
            def reject_report(source,target):
                if Path(target)==report_path:raise OSError('report replacement unavailable')
                return replace(source,target)
            with patch.object(A,'_finalize_output',portable_result),patch.object(Path,'replace',reject_report):
                rc=A._apply_in_place(before,report_path,diff_path,copy.deepcopy(checked['write']),hexiao_date='2026-08-20')
            self.assertEqual(rc,2)
            self.assertEqual(before.read_bytes(),original)
            self.assertEqual(portable.read_bytes(),b'previous portable')




    def test_incomplete_source_or_nonconserved_group_is_not_reconstructed(self):
        import current_receipt_group as G
        records,ledger=self.fixture();rows=BR.ledger_rows(ledger,'SO_GROUP','SOD_GROUP')
        self.assertIsNone(G.build(records[1:],rows))
        changed=copy.deepcopy(records);changed[1]['cumulative_received_local']+=1
        self.assertIsNone(G.build(changed,rows))
        changed=copy.deepcopy(rows);changed['2']['应收金额']+=1
        self.assertIsNone(G.build(records,changed))
        changed=copy.deepcopy(rows);changed['4']['回款明细']-=1
        self.assertIsNone(G.build(records,changed))
        changed=copy.deepcopy(rows);changed['9']['收款时间']='2026-03-01'
        self.assertIsNone(G.build(records,changed))

    def test_partial_group_tampered_source_and_postplan_edits_rejected(self):
        records,ledger=self.fixture();plan=C.classify_records(records,ledger,{})
        rows={int(k):v for k,v in BR.ledger_rows(ledger,'SO_GROUP','SOD_GROUP').items()}
        partial=copy.deepcopy(plan);partial['auto'].pop()
        self.assertEqual(len(V.validate(partial,rows)['write']),0)
        changed=copy.deepcopy(plan);changed['auto'][1]['split_payment_source']['amount_local']+=1
        self.assertEqual(len(V.validate(changed,rows)['write']),0)
        changed=copy.deepcopy(rows);changed[2]['回款明细']=1
        self.assertEqual(len(V.validate(plan,changed)['write']),0)

    def test_different_equal_amount_receipts_are_not_assigned_by_row_order(self):
        import current_receipt_group as G
        records,ledger=self.fixture();rows=BR.ledger_rows(ledger,'SO_GROUP','SOD_GROUP')
        rows['6']['收款方式']='现'
        self.assertIsNone(G.build(records,rows))

    def test_serialized_plan_and_hard_source_gate(self):
        import json
        records,ledger=self.fixture();rows={int(k):v for k,v in BR.ledger_rows(ledger,'SO_GROUP','SOD_GROUP').items()}
        plan=json.loads(json.dumps(C.classify_records(records,ledger,{}),default=str))
        self.assertEqual(len(V.validate(plan,rows)['write']),6)
        records[0]['forced_code']='E_PARENT_WRITEOFF_MISMATCH'
        records[0]['forced_reason']='source total conflict'
        guarded=C.classify_records(records,ledger,{})
        self.assertFalse(any(r.get('current_receipt_group') for key in ('auto','hold','exception') for r in guarded[key]))

if __name__=='__main__':unittest.main()
