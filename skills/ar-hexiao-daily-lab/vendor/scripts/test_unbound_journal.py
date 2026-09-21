import copy,json,runpy,unittest
import baseline_receipts as B

class UnboundJournalTest(unittest.TestCase):
    def fixture(self):
        key=B.group_key('SO_TEST','SOD_TEST')
        event=json.dumps(['AR_TEST','SO_TEST','SOD_TEST','HX_TEST'])
        group={'baseline_receivable':1000,'scope_only':True,'events':{},'ordinary_events':{event:{'signature':[400,'2026-09-03','汇']}}}
        return key,event,group

    def test_actual_rebinding_output_is_valid_journal(self):
        functions=runpy.run_path('/app/backend/app/ar_material_rebinding.py')
        key,event,group=self.fixture()
        ledger={'baseline_receipts':{key:group}}
        rows=[{'so':'SO_TEST','sod':'SOD_TEST','amount':0,'date':'','method':''}]
        updated,audit=functions['rebind_missing_baseline_events'](ledger,functions['differences_from_current_rows'](ledger,rows))
        self.assertTrue(audit)
        self.assertEqual(updated['baseline_receipts'][key]['ordinary_events'],{})
        self.assertIn(event,updated['baseline_receipts'][key]['unbound_ordinary_events'])
        B.validate_journal(updated['baseline_receipts'])
        self.assertIn(event,ledger['baseline_receipts'][key]['ordinary_events'])

    def test_unverified_empty_group_still_rejected(self):
        key,event,group=self.fixture();group['ordinary_events']={}
        with self.assertRaises(ValueError):B.validate_journal({key:group})

    def test_malformed_archive_still_rejected(self):
        key,event,group=self.fixture();group['unbound_ordinary_events']=group.pop('ordinary_events');group['ordinary_events']={}
        group['unbound_ordinary_events'][event]['signature']=[-1,'2026-09-03','汇']
        with self.assertRaises(ValueError):B.validate_journal({key:group})
