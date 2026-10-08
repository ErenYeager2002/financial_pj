"""A same-batch closure must not invent a new source during post-write review."""
import copy
import unittest
import classify_hexiao as C
import current_parent_allocation as P
from execution_lineage import indexed_decisions, match_final_records
from test_current_parent_rows_allocation import CurrentRows

class ZeroAllocationLineage(unittest.TestCase):
    def test_same_batch_closure_preserves_sources(self):
        fixture=CurrentRows()
        p,after=fixture.fixture()
        first=copy.deepcopy(p)
        first.update(ar='AR_FIRST',arrival_date='2026-08-01',amount_orig=50.,amount_local=50.,total_amount_orig=50.,total_amount_local=50.)
        before=C.LedgerIndex(synthetic={'so':{'SO_A':[2],'SO_B':[3]},'sod':{'SOD_A':[2],'SOD_B':[3]},'rows':{
            2:dict(so='SO_A',sod='SOD_A',yingshou=40,huikuan=None,jiezhang='否'),
            3:dict(so='SO_B',sod='SOD_B',yingshou=60,huikuan=None,jiezhang='否')}})
        after.row_snapshot[3]['shoukuan_time']='2026-08-01'
        def classify(ledger):
            payments=copy.deepcopy([first,p])
            for item in payments:
                P.attach(item,{2026:ledger},payments=payments)
                item['_ledger_received_local_by_so']={so:ledger.so_totals(so)[1] for so in ledger.so_index}
                item['_ledger_settled_sos']=[so for so in ledger.so_index if ledger.so_settlement(so)['all_settled']]
            return C.classify_records(C.expand_payments(payments,{}),ledger,{})
        initial=classify(before);final=classify(after)
        self.assertFalse(initial['hold']);self.assertFalse(initial['exception'])
        self.assertFalse(final['hold']);self.assertFalse(final['exception'])
        links=match_final_records(indexed_decisions(initial),indexed_decisions(final))
        self.assertEqual(len(links),4)
        zero=next(r for r in initial['auto'] if r['ar']==p['ar'] and r['so']=='SO_A')
        self.assertEqual(zero['code'],'OK_FALLBACK_ZERO_ALLOCATION')
        self.assertEqual(zero['parent_allocation_audit']['allocated_local'],0)
        damaged=copy.deepcopy(final)
        damaged['auto']=[r for r in damaged['auto'] if r['ar']!='AR_FIRST']
        with self.assertRaises(ValueError):match_final_records(indexed_decisions(initial),indexed_decisions(damaged))

if __name__=='__main__':unittest.main()
