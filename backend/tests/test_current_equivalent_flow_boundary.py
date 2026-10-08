"""Writer boundary for independently proven equal receipts, not a matching proof.

These synthetic inputs explicitly supply distinct rows and checked amounts.
Passing this test does not authorize assigning ambiguous real receipts to rows.
"""
import unittest
from test_flow_monthly import MonthlySafetyTest

class EquivalentFlowWriterBoundary(unittest.TestCase):
    def test_two_proven_receipts_keep_independent_balances_and_repeat(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                fixture=MonthlySafetyTest();fixture.setUp()
                try:
                    def rows(ws):
                        ws['C2']=450;ws['F2']=450
                        ws.append([cell.value for cell in ws[2]])
                    fixture.modify(rows)
                    entries=[fixture.entry(so='SO1',amount=450,ar=ar,row=row)
                             for ar,row in [('AR_A',2),('AR_B',3)]]
                    for entry in entries:
                        entry['flow_identity']['amount']=450
                        entry['split_payment_source']['so_delivery_local']=900
                    if reverse:entries.reverse()
                    changed,errors=fixture.run_items('2026-07-28',entries)
                    self.assertFalse(errors);self.assertEqual(len(changed),2)
                    self.assertEqual(fixture.read('F2'),'450-450=0')
                    self.assertEqual(fixture.read('F3'),'450-450=0')
                    self.assertEqual(fixture.read('C2'),450);self.assertEqual(fixture.read('C3'),450)
                    self.assertNotIn('900',str(fixture.read('E2')))
                    self.assertNotIn('900',str(fixture.read('E3')))
                    before=fixture.path.read_bytes()
                    self.assertEqual(fixture.run_items('2026-07-28',list(reversed(entries))),([],[]))
                    self.assertEqual(fixture.path.read_bytes(),before)
                finally:fixture.tearDown()

    def test_two_receipts_cannot_both_claim_one_row(self):
        fixture=MonthlySafetyTest();fixture.setUp()
        try:
            entries=[fixture.entry(so='SO1',amount=450,ar=ar,row=2) for ar in ('AR_A','AR_B')]
            before=fixture.path.read_bytes()
            changes,errors=fixture.run_items('2026-07-28',entries)
            self.assertFalse(changes);self.assertTrue(errors)
            self.assertEqual(fixture.path.read_bytes(),before)
        finally:fixture.tearDown()
