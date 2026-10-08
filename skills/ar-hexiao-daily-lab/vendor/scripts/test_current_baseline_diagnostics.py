import unittest
import baseline_receipts as B
from test_current_workbook_receipts import fixture,ledger

class CurrentBaselineDiagnostics(unittest.TestCase):
    def test_multiple_receivable_rows_explain_current_difference_without_writes(self):
        records,rows=fixture();rec=records[0];rows={3:rows[3],4:rows[4]}
        rows[4]['yingshou']=40;rows[4]['huikuan']=40
        result=B.candidate(rec,{},ledger(rows))
        self.assertEqual(result['baseline_receipt_audit']['disposition'],'conflict')
        self.assertEqual(result['five_cols'],{})
        self.assertNotIn('row_operation',result)
        for token in ['SO_CURRENT','SOD_CURRENT','应收合计80.00元','交付额100.00元','差额20.00元','共有2行（3,4）','已收40.00元']:
            self.assertIn(token,result['reason'])

    def test_negative_cell_is_identified_and_remains_conflict(self):
        records,rows=fixture();rows={3:rows[3]};rows[3]['huikuan']=-1
        result=B.candidate(records[0],{},ledger(rows))
        self.assertEqual(result['baseline_receipt_audit']['disposition'],'conflict')
        self.assertIn('行3 回款明细=-1',result['reason'])
        self.assertEqual(result['five_cols'],{})

if __name__=='__main__':unittest.main()
