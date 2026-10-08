import copy
import datetime as dt
import unittest
import flow_monthly as F
import flow_source_receipts as S

DAY=dt.date(2026,8,14)

def source(so,amount):
    return dict(ar='ARTEST',so=so,date=DAY.isoformat(),amount=str(amount),amount_orig=str(amount),currency='CNY',basis='current_source_so_receipt',event=[DAY.isoformat(),'HX'+so,'R'+so])

def row(so,sod,amount):
    return dict(ar='ARTEST',so=so,sod=sod,case_id='ARTEST|'+so+'|'+sod,bucket='auto',split_payment_source={'amount_local':amount},write_currency_audit={'currency':'CNY','amount_local':amount})

class CurrentFlowCoverage(unittest.TestCase):
    def fixture(self):
        item=dict(ar='ARTEST',identity={'amount':100},source_receipts=[source('SOA',60),source('SOB',40),source('SOZERO',0)],so_list=['SOA','SOB','SOZERO'],so_outcomes=[])
        rows=[row('SOA','SODA',20),row('SOA','SODB',40),row('SOB','SODC',40),row('SOZERO','SODZ',0)]
        checked=dict(hexiao_date=DAY.isoformat(),write=rows,skip=[],conflict=[])
        return item,rows,checked,S.allocations(item,DAY)

    def test_zero_source_does_not_invalidate_positive_allocations(self):
        item,rows,checked,entries=self.fixture()
        self.assertEqual(len(entries),2)
        proof=F.current_source_balance_candidate(item,entries,DAY)
        self.assertIsNotNone(proof)
        self.assertEqual(sum(F.money(e['amount']) for e in proof['entries']),100)

    def test_sod_evidence_is_aggregated_by_so_with_amounts_checked(self):
        item,rows,checked,entries=self.fixture()
        proof=F.complete_current_history(item,checked,[('write',r) for r in rows],entries,[])
        self.assertIsNotNone(proof)
        self.assertEqual(proof['opening'],'100')

    def test_same_total_wrong_so_amounts_are_rejected(self):
        item,rows,checked,entries=self.fixture()
        rows[0]['split_payment_source']['amount_local']=10
        rows[2]['split_payment_source']['amount_local']=50
        self.assertIsNone(F.complete_current_history(item,checked,[('write',r) for r in rows],entries,[]))

    def test_unverified_or_duplicate_sod_evidence_cannot_fill_gap(self):
        item,rows,checked,entries=self.fixture()
        for selected in [rows[1:],rows+[rows[0]]]:
            with self.subTest(size=len(selected)):
                self.assertIsNone(F.complete_current_history(item,checked,[('write',r) for r in selected],entries,[]))

    def test_candidate_rejects_tampered_missing_and_duplicate_entries(self):
        item,rows,checked,entries=self.fixture()
        bad=copy.deepcopy(entries);bad[0]['amount']='59';bad[1]['amount']='41'
        for values in [bad,entries[:1],entries+[entries[0]]]:
            self.assertIsNone(F.current_source_balance_candidate(item,values,DAY))

    def test_invalid_zero_source_still_rejects(self):
        for key,value in [('ar','OTHER'),('date','2026-08-15'),('amount','-1')]:
            item,rows,checked,entries=self.fixture();item['source_receipts'][-1][key]=value
            self.assertIsNone(F.current_source_balance_candidate(item,entries,DAY))

class PhysicalCurrentCoverage(unittest.TestCase):
    def test_multi_sod_and_zero_source_write_once_and_preserve_other_cells(self):
        import tempfile
        from pathlib import Path
        import openpyxl
        import build_flow_plan as B
        import test_flow_monthly as T
        f=T.MonthlySafetyTest();f.setUp()
        try:
            def prepare(ws):
                ws['C2']=100;ws['E2']='WX SOA SOB SOZERO';ws['F2']=None
                ws['H2']='=C2';ws['I2']='keep'
            f.modify(prepare)
            records=[]
            for so,sod,amount in [('SOA','SODA',20),('SOA','SODB',40),('SOB','SODC',40),('SOZERO','SODZ',0)]:
                r=f.entry(so,amount);r.update(sod=sod,case_id='AR1|'+so+'|'+sod)
                r['flow_identity']['amount']=100
                src=source(so,60 if so=='SOA' else amount)
                src.update(ar='AR1',date='2026-07-28',event=['2026-07-28','HX'+so,'R'+so])
                r['flow_source_receipt']=src;records.append(r)
            checked=dict(hexiao_date='2026-07-28',write=records,skip=[],conflict=[])
            def plan():return B.finalize_plan_after_ledger(B.build_plan({'auto':records,'hexiao_date':'2026-07-28'}),checked,workspace=f.root)
            result=plan();self.assertEqual(result['manual_items'],[])
            changes,errors=F.write(f.root,result['items'],in_place=True,phase='status')
            self.assertFalse(errors);self.assertEqual(len(changes),1)
            self.assertEqual(f.read('F2'),'100-60-40=0')
            self.assertEqual(f.read('H2'),'=C2');self.assertEqual(f.read('I2'),'keep')
            after=f.path.read_bytes()
            self.assertEqual(F.write(f.root,plan()['items'],in_place=True,phase='status'),([],[]))
            self.assertEqual(f.path.read_bytes(),after)
        finally:f.tearDown()
