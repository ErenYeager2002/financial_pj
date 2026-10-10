"""Explicit writeoffs must not inherit conflicting delivery-only estimates."""
import copy
import datetime as dt
from pathlib import Path
import tempfile
import unittest
import openpyxl
import classify_hexiao as C
from classification_exports import reconcile_writeoff_details
from classification_expansion import expand_payments
import validate_plan as V
import apply_to_copy as A

DAY=dt.date(2026,9,29)

def parent(ar, total, amounts):
    return dict(ar=ar, currency='CNY', amount_orig=total, amount_local=total,
        total_amount_orig=total,total_amount_local=total, arrival_date=DAY,
        hexiao_date=DAY,status='手动核销',huikuan_type='整笔回款',fee=0,
        _source_meta={'historical_detail_rows':0},
        orders=[dict(so=so,deliver=value,deliver_local=value,currency='CNY',delivery_date=DAY)
                for so,value in amounts.items()],
        sod_lines={so:[dict(sod='SOD_'+so,deliver=value,currency='CNY')]
                   for so,value in amounts.items()})

def detail(ar, amount):
    return dict(record_id='HX_'+ar,rowid='row_'+ar,ar=ar,so='SO_TEST',date=DAY,
        snapshot_date=DAY,amount=amount,amount_local=amount,currency='CNY',revoked='',source='核销明细')

class InferredSourceConflict(unittest.TestCase):
    def run_case(self, weak=True, extra_explicit=False):
        with tempfile.TemporaryDirectory() as temp:
            before,after=Path(temp)/'before.xlsx',Path(temp)/'after.xlsx'
            wb=openpyxl.Workbook();ws=wb.active;ws.title='明细'
            ws.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
            ws.append(['SO_TEST','SOD_SO_TEST',5100,None,None,'否',None,None,None])
            ws.append(['SO_OTHER','SOD_SO_OTHER',103.79,None,None,'否',None,None,None])
            wb.save(before);wb.close()
            ps=[parent('AR_EXPLICIT',5100,{'SO_TEST':5100})]
            raw=[detail('AR_EXPLICIT',5100)]
            if weak:ps.append(parent('AR_INFERRED',5203.79,{'SO_TEST':5100,'SO_OTHER':103.79}))
            if extra_explicit:
                ps.append(parent('AR_EXPLICIT_2',5100,{'SO_TEST':5100}));raw.append(detail('AR_EXPLICIT_2',5100))
            original=copy.deepcopy(raw)
            reconcile_writeoff_details(ps,{p['ar']:p for p in ps},raw,DAY)
            self.assertEqual(original,raw)
            records=expand_payments(ps,{})
            plan=C.classify_records(records,C.LedgerIndex(before),{})
            checked=V.validate(plan,A.read_ledger_rows(before))
            if not extra_explicit:
                self.assertEqual(checked['counts']['conflict'],0)
                self.assertIn('AR_EXPLICIT',[r['ar'] for r in checked['write']],plan)
                A.write_plan(before,after,checked['write'])
                self.assertEqual(A.verify_written(after,checked['write']),[])
                rows=A.read_ledger_rows(after)
                self.assertEqual(rows[2]['回款明细'],5100)
                again=V.validate(C.classify_records(copy.deepcopy(records),C.LedgerIndex(after),{}),rows)
                self.assertEqual(again['counts']['write'],0)
            return ps,records,plan,checked

    def test_explicit_is_writable_but_conflicting_estimate_keeps_amount_pending(self):
        ps,records,plan,checked=self.run_case()
        held=next(r for r in plan['hold'] if r['ar']=='AR_INFERRED' and r['so']=='SO_TEST')
        self.assertEqual(held['code'],'E_PARENT_ALLOCATION_HISTORY_MISSING')
        self.assertIn('推算',held['reason'])
        self.assertEqual(held['split_payment_source']['amount_local'],5100)
        self.assertFalse(held['flow_source_receipt'])
        self.assertEqual(ps[1]['writeoffs_local']['SO_TEST'],5100)
        explicit=next(r for r in records if r['ar']=='AR_EXPLICIT')
        self.assertEqual(explicit['cumulative_received_local'],5100)
        self.assertEqual([e['ar'] for e in explicit['current_source_history']['events']],['AR_EXPLICIT'])

    def test_closed_so_remains_closed_when_estimate_is_conflicted(self):
        rec=dict(ar='AR_INFERRED',so='SO_TEST',sod='SOD_SO_TEST',currency='CNY',status='手动核销',
            hexiao_date=DAY,shoukuan_date=DAY,amount_orig=5100,amount_local=5100,deliver_local=5100,
            all_sods=['SOD_SO_TEST'],forced_code='E_PARENT_ALLOCATION_HISTORY_MISSING',
            forced_reason='交付额推算与明确核销明细冲突',
            inferred_source_conflict={'basis':'delivery_estimate_conflicts_with_explicit_receipts'})
        rows={2:dict(so='SO_TEST',sod='SOD_SO_TEST',yingshou=5100,jiti=5100,huikuan=5100,
                     jiezhang='是',shoukuan_time='2026-09-08',shoukuan_way='汇',chayi=None)}
        ledger=C.LedgerIndex(synthetic={'rows':rows,'so':{'SO_TEST':[2]},'sod':{'SOD_SO_TEST':[2]}})
        plan=C.classify_records([rec],ledger,{})
        self.assertEqual(plan['counts']['hold'],0)
        self.assertEqual(plan['auto'][0]['code'],'OK_SO_ALREADY_SETTLED')
        self.assertFalse(plan['auto'][0]['flow_source_receipt'])
        self.assertIn('W_SETTLED_SO_SOURCE_DIFFERENCE',plan['auto'][0]['warning_codes'])

    def test_two_explicit_writeoffs_remain_blocked(self):
        ps,records,plan,checked=self.run_case(weak=False,extra_explicit=True)
        self.assertFalse([r for r in checked['write'] if r['so']=='SO_TEST'])
        self.assertEqual(ps[-1]['cumulative_writeoffs_local']['SO_TEST'],10200)

    def test_standalone_delivery_fallback_keeps_legacy_allocation(self):
        p=parent('AR_INFERRED',5203.79,{'SO_TEST':5100,'SO_OTHER':103.79})
        reconcile_writeoff_details([p],{p['ar']:p},[],DAY)
        rs=expand_payments([p],{})
        self.assertEqual(sum(r['amount_local'] for r in rs),5203.79)
        self.assertTrue(all(not r.get('forced_code') for r in rs))

if __name__=='__main__':unittest.main()
