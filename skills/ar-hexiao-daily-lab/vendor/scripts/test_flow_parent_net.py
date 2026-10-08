import copy
import unittest
import datetime as dt
import zipfile
import openpyxl
import build_flow_plan as B
import flow_monthly as F
import flow_parent_net as N
import test_flow_monthly as T

class ParentNet(unittest.TestCase):
    def setUp(self):
        self.f=T.MonthlySafetyTest();self.f.setUp()
        self.f.modify(lambda ws:setattr(ws['C2'],'value',100))
        self.f.modify(lambda ws:setattr(ws['F2'],'value',100))
    def tearDown(self):self.f.tearDown()
    def records(self,day='2026-07-28'):
        audit=dict(ar='AR1',status='delivery_fallback',is_whole_payment=True,raw_record_count=0,records=[],
                   order_count=3,parent_net_local=100,parent_net_orig=100,parent_total_local=103,
                   parent_total_orig=103,parent_charge_local=3,parent_charge_orig=3,
                   order_records=[dict(so=so,amount=amt,amount_local=amt,source='delivery_fallback')
                                  for so,amt in [('SO1',60),('SO2',42.8),('SOZERO',0)]])
        rows=[]
        for r in audit['order_records']:
            row=self.f.entry(r['so'],r['amount']);row['flow_identity']['amount']=100
            row['duplicate_writeoff_audit']=copy.deepcopy(audit)
            row['flow_source_receipt']=dict(ar='AR1',so=r['so'],date=day,amount=r['amount'],amount_orig=r['amount'],
                currency='CNY',basis='current_source_so_receipt',event=[day,'DELIVERY_FALLBACK|AR1|'+r['so'],''])
            rows.append(row)
        return rows
    def plan(self,day='2026-07-28',rows=None,hold=False):
        rows=rows or self.records(day)
        checked=dict(hexiao_date=day,write=rows,skip=[],conflict=[])
        if hold:
            rows[-2]['bucket']='hold';rows[-2]['code']='E3'
            checked['write']=[r for r in rows if r['bucket']=='auto']
        classified={'auto':[r for r in rows if r['bucket']=='auto'],
                    'hold':[r for r in rows if r['bucket']=='hold'],'hexiao_date':day}
        return B.finalize_plan_after_ledger(B.build_plan(classified),checked,workspace=self.f.root)
    def write(self,plan):return F.write(self.f.root,plan['items'],in_place=True,phase='status')
    def test_one_net_deduction_no_so_allocation_and_repeat(self):
        rows=self.records();before=copy.deepcopy(rows)
        plan=self.plan(rows=rows)
        self.assertFalse(plan['manual_items']);self.assertEqual(rows,before)
        entries=plan['items'][0]['monthly_entries']
        self.assertEqual(len(entries),1);self.assertEqual(entries[0]['amount'],'100')
        changes,errors=self.write(plan);self.assertFalse(errors);self.assertEqual(len(changes),1)
        self.assertEqual(self.f.read('F2'),'100-100=0')
        text=self.f.read('E2');self.assertIn('SOZERO',text);self.assertNotIn('60.00',text)
        self.assertIn('本次整笔净到账核销合计 100.00',text)
        before=self.f.path.read_bytes();self.assertEqual(self.write(self.plan()),([],[]))
        self.assertEqual(self.f.path.read_bytes(),before)
    def test_cross_month_and_repeat(self):
        changes,errors=self.write(self.plan('2026-08-14'))
        self.assertFalse(errors);self.assertEqual(len(changes),1)
        self.assertEqual(self.f.read('F3'),'100-100=0');self.assertEqual(self.f.read('D3'),'冲预收')
        self.assertEqual(self.f.read('F2'),100)
        before=self.f.path.read_bytes();self.assertEqual(self.write(self.plan('2026-08-14')),([],[]))
        self.assertEqual(before,self.f.path.read_bytes())
    def test_current_visible_table_without_metadata_prevents_repeat(self):
        self.assertFalse(self.write(self.plan())[1])
        wb=openpyxl.load_workbook(self.f.path,rich_text=True);wb.save(self.f.path);wb.close()
        plan=self.plan();self.assertFalse(plan['manual_items'])
        self.assertFalse(self.write(plan)[1]);self.assertEqual(self.f.read('F2'),'100-100=0')
        self.assertEqual(str(self.f.read('E2')).count('本次整笔净到账核销合计'),1)
    def test_pl_hold_does_not_block_receipt_deduction_and_stays_red(self):
        changes,errors=self.write(self.plan(hold=True));self.assertFalse(errors)
        self.assertEqual(self.f.read('F2'),'100-100=0');self.assertEqual(self.f.read('G2'),'部分')
        from apply_flow import _line_colors
        wb=openpyxl.load_workbook(self.f.path,rich_text=True)
        colors=_line_colors(wb['流水']['E2'].value);wb.close()
        self.assertTrue(colors['SO2'].endswith('FF0000'))
    def test_old_unrelated_so_preserved_with_clear_error(self):
        self.f.modify(lambda ws:(setattr(ws['E2'],'value','WX SOOTHER'),setattr(ws['F2'],'value',None)))
        before=self.f.path.read_bytes();plan=self.plan()
        self.assertTrue(plan['manual_items']);self.assertIn('SOOTHER',str(plan['manual_items']))
        self.assertEqual(self.f.path.read_bytes(),before)
    def test_partial_prior_deduction_not_overwritten(self):
        self.f.modify(lambda ws:(setattr(ws['E2'],'value','WX SO1'),setattr(ws['F2'],'value','100-60=40')))
        before=self.f.path.read_bytes();plan=self.plan();self.assertTrue(plan['manual_items'])
        self.assertEqual(before,self.f.path.read_bytes())
    def test_invalid_or_incomplete_audit_is_not_delivery_fallback(self):
        for defect in ('net','missing','duplicate','raw','date','negative','audit_mismatch'):
            rows=self.records()
            if defect=='net':
                for r in rows:r['duplicate_writeoff_audit']['parent_net_local']=99
            elif defect=='missing':rows.pop()
            elif defect=='duplicate':
                for r in rows:r['duplicate_writeoff_audit']['order_records'].append(copy.deepcopy(r['duplicate_writeoff_audit']['order_records'][0]))
            elif defect=='raw':
                for r in rows:r['duplicate_writeoff_audit']['raw_record_count']=1
            elif defect=='date':rows[0]['flow_source_receipt']['date']='2026-07-29'
            elif defect=='negative':rows[-1]['flow_source_receipt']['amount']=-1
            else:rows[0]['duplicate_writeoff_audit']['parent_net_orig']=99
            with self.subTest(defect=defect):self.assertTrue(self.plan(rows=rows)['manual_items'])
    def test_real_itemized_sources_are_unchanged(self):
        rows=self.records()
        for r in rows:
            r['duplicate_writeoff_audit']={'status':'normal'}
            r['flow_source_receipt']['event'][1]='HX'+r['so']
        item=B.build_plan({'auto':rows,'hexiao_date':'2026-07-28'})['items'][0]
        self.assertIsNone(N.bind(item,dt.date(2026,7,28)))
    def test_changed_parent_date_is_not_charged_again(self):
        self.assertFalse(self.write(self.plan())[1])
        before=self.f.path.read_bytes();plan=self.plan('2026-07-29');self.assertTrue(plan['manual_items'])
        self.assertEqual(before,self.f.path.read_bytes())

    def test_later_pl_completion_only_changes_status_and_colors(self):
        self.assertFalse(self.write(self.plan(hold=True))[1])
        changes,errors=self.write(self.plan());self.assertFalse(errors)
        self.assertEqual(self.f.read('G2'),'是');self.assertEqual(self.f.read('F2'),'100-100=0')
        self.assertEqual(str(self.f.read('E2')).count('本次整笔净到账核销合计'),1)
        from apply_flow import _line_colors
        wb=openpyxl.load_workbook(self.f.path,rich_text=True)
        self.assertFalse(_line_colors(wb['流水']['E2'].value).get('SO2','').endswith('FF0000'));wb.close()
    def test_fx_uses_original_net_and_workbook_rate_once(self):
        rows=self.records()
        for row in rows:
            row['flow_source_receipt']['currency']='美元USD'
            row['flow_matched_by']='三键(原币公式)'
            row['flow_identity'].update(amount=700,formula_orig_amount=100,formula_rate=7)
            audit=row['duplicate_writeoff_audit']
            audit.update(parent_net_local=720,parent_total_local=741.6,parent_charge_local=21.6)
            for record in audit['order_records']:record['amount_local']=round(record['amount']*7.2,2)
            row['flow_source_receipt']['amount']=round(row['flow_source_receipt']['amount_orig']*7.2,2)
        item=B.build_plan({'auto':rows,'hexiao_date':'2026-07-28'})['items'][0]
        entry=N.bind(item,dt.date(2026,7,28));self.assertEqual(entry['amount'],'700')
    def test_gross_channel_retains_existing_rule(self):
        rows=self.records()
        for row in rows:row['flow_matched_by']='微信支付宝到账日+总到账金额+销售或已有SO'
        item=B.build_plan({'auto':rows,'hexiao_date':'2026-07-28'})['items'][0]
        self.assertIsNone(N.bind(item,dt.date(2026,7,28)))

    def test_missing_all_or_all_but_one_source_cannot_revert_to_delivery(self):
        for remaining in (0,1):
            rows=self.records()
            for row in rows[remaining:]:row.pop('flow_source_receipt')
            with self.subTest(remaining=remaining):self.assertTrue(self.plan(rows=rows)['manual_items'])
