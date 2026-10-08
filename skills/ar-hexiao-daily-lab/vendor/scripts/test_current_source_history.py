"""Current audited source history must survive expansion without journal input."""
import copy
import datetime as dt
import unittest
from classification_exports import reconcile_writeoff_details
from classification_expansion import expand_payment
from test_writeoff_local_amounts import payment, row, DAY

class CurrentSourceHistory(unittest.TestCase):
    def build(self, missing_local=False):
        old=payment('AR_OLD',100,700)
        old['arrival_date']=dt.date(2026,8,1)
        now=payment('AR_NOW',100,800)
        now['arrival_date']=dt.date(2026,9,1)
        a=row('AR_OLD',1,None if missing_local else 700,None)
        a['date']=dt.date(2026,8,20)
        b=row('AR_NOW',2,800)
        raw=[a,b]
        before=copy.deepcopy(raw)
        reconcile_writeoff_details([now],{p['ar']:p for p in [old,now]},raw,DAY)
        self.assertEqual(raw,before)
        return now

    def test_source_history_survives_only_current_parent_expansion(self):
        p=self.build()
        history=p['_current_source_history_by_so']['SO_TEST']
        self.assertEqual(history['basis'],'audited_current_exports')
        self.assertEqual(history['as_of_date'],DAY.isoformat())
        self.assertEqual([(r['ar'],r['amount_local']) for r in history['events']],[('AR_OLD',700),('AR_NOW',800)])
        self.assertEqual(history['events'][0]['arrival_date'],'2026-08-01')
        self.assertEqual(history['events'][0]['posting_date'],'2026-08-20')
        rec=expand_payment(p,{})[0]
        self.assertEqual(rec['current_source_history'],history)
        rec['current_source_history']['events'][0]['amount_local']=999
        self.assertEqual(history['events'][0]['amount_local'],700)

    def test_unknown_local_amount_remains_unknown(self):
        p=self.build(True)
        history=p['_current_source_history_by_so']['SO_TEST']
        self.assertIsNone(history['events'][0]['amount_local'])
        self.assertIn('amount_local',history['events'][0]['missing_fields'])
        self.assertFalse(history['identity_fields_complete'])
        self.assertEqual(expand_payment(p,{})[0]['forced_code'],'E7')
        p['_fallback_allocation_state']={'parents':{'AR_RECORDED':{
            'hexiao_date':'2026-08-01','allocations':[{
                'so':'SO_TEST','allocated_orig':100,'allocated_local':700}]}}}
        self.assertEqual(expand_payment(p,{})[0]['forced_code'],'E7')

    def test_future_source_does_not_enter_current_snapshot(self):
        p=payment('AR_NOW',100,800);p['arrival_date']=DAY
        future=payment('AR_FUTURE',100,700);future['arrival_date']=DAY
        b=row('AR_FUTURE',3,700);b['date']=DAY+dt.timedelta(days=1)
        reconcile_writeoff_details([p],{'AR_NOW':p,'AR_FUTURE':future},[row('AR_NOW',1,800),b],DAY)
        self.assertEqual([e['ar'] for e in p['_current_source_history_by_so']['SO_TEST']['events']],['AR_NOW'])

    def test_repeated_physical_snapshots_are_not_extra_receipts(self):
        p=payment('AR_NOW',100,800);p['arrival_date']=DAY
        first=row('AR_NOW',1,800);duplicate=copy.deepcopy(first)
        duplicate['snapshot_date']=DAY+dt.timedelta(days=1)
        duplicate['_input_index']=2
        reconcile_writeoff_details([p],{'AR_NOW':p},[first,duplicate],DAY)
        history=p['_current_source_history_by_so']['SO_TEST']
        self.assertEqual(len(history['events']),1)
        self.assertFalse(history.get('complete_history',False))

    def test_unresolved_ancestor_is_not_silently_absent(self):
        from current_source_history import attach
        p=payment('AR_NOW',100,800)
        attach([p],{},[],{'SO_TEST':['AR_BAD']},DAY)
        history=p['_current_source_history_by_so']['SO_TEST']
        self.assertEqual(history['unresolved_parent_ars'],['AR_BAD'])
        self.assertFalse(history['identity_fields_complete'])

    def test_missing_identity_is_not_invented_from_target_date(self):
        from current_source_history import attach
        p=payment('AR_NOW',100,800)
        item=row('AR_NOW',1,800)
        item['date']=None
        item['_resolved_amount_local']=800
        attach([p],{'AR_NOW':p},[item],{},DAY)
        event=p['_current_source_history_by_so']['SO_TEST']['events'][0]
        self.assertIsNone(event['posting_date'])
        self.assertIsNone(event['arrival_date'])
        self.assertIn('posting_date',event['missing_fields'])
        self.assertIn('arrival_date',event['missing_fields'])

    def test_audited_event_without_physical_rowid_keeps_business_identity(self):
        from current_source_history import attach
        p=payment('AR_NOW',100,800);p['arrival_date']=DAY
        event=row('AR_NOW',1,800);event.update(rowid='',record_id='ORDER_AMOUNT|AR_NOW|SO_TEST',_resolved_amount_local=800)
        attach([p],{'AR_NOW':p},[event],{},DAY)
        history=p['_current_source_history_by_so']['SO_TEST']
        self.assertTrue(history['identity_fields_complete'])
        self.assertNotIn('rowid',history['events'][0]['missing_fields'])

    def test_itemized_cumulative_is_independent_of_old_allocation_journal(self):
        original=self.build()
        expected=expand_payment(copy.deepcopy(original),{})
        for amount in (1,999,10000):
            changed=copy.deepcopy(original)
            changed['_fallback_allocation_state']={'parents':{'AR_STALE':{
                'hexiao_date':'2026-08-01','allocations':[{
                    'so':'SO_TEST','allocated_orig':amount,'allocated_local':amount*7}]}}}
            with self.subTest(amount=amount):
                actual=expand_payment(changed,{})
                self.assertEqual(actual[0]['cumulative_received_local'],1500)
                self.assertEqual(actual,expected)

if __name__=='__main__':unittest.main()
