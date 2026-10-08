import copy
import unittest
import baseline_receipts as BR
import classify_hexiao as C
import validate_plan as V
import settlement_status as S
from test_current_workbook_receipts import fixture,ledger

class CurrentSettledBoundary(unittest.TestCase):
    def example(self):
        records,rows=fixture();rec=records[0]
        rec.update(amount_orig=100.3,amount_local=100.3,cumulative_received_local=100.3,
                   current_source_history={'basis':'audited_current_exports','events':[],
                                           'identity_fields_complete':True,'unresolved_parent_ars':[]})
        row=rows[4];row.update(yingshou=100,huikuan=100,jiti=100)
        return rec,{4:row}

    def classify(self,rec,rows):
        book=ledger(rows);plan=C.classify_records([copy.deepcopy(rec)],book,{})
        before={int(k):v for k,v in BR.ledger_rows(book,rec['so'],rec['sod']).items()}
        return plan,V.validate(plan,before),before

    def test_whole_settled_source_difference_preserves_existing_values(self):
        rec,rows=self.example();original=copy.deepcopy(rows)
        plan,checked,_=self.classify(rec,rows)
        self.assertEqual(checked['counts'],{'write':0,'skip':1,'conflict':0},plan)
        item=checked['skip'][0]
        self.assertEqual(item['code'],S.SO_ALREADY_SETTLED)
        self.assertFalse(item.get('current_workbook_receipts'))
        self.assertFalse(item.get('five_cols'))
        self.assertIn('current_workbook_conflict',item)
        self.assertEqual(rows,original)

    def test_unfinished_order_still_requires_current_source_binding(self):
        rec,rows=self.example();rows[4].update(yingshou=90,huikuan=90,jiti=None)
        rows[5]=dict(rows[4],yingshou=10,huikuan=None,jiti=None,jiezhang='否',shoukuan_time=None,shoukuan_way=None)
        plan,checked,_=self.classify(rec,rows)
        self.assertEqual(checked['counts']['write'],0)
        self.assertEqual(plan['hold'][0]['code'],'E_CURRENT_SOURCE_ROW_BINDING')

    def test_revoked_and_parent_amount_failure_stay_blocked(self):
        for field,value in [('status','已作废'),('forced_code','E_PARENT_WRITEOFF_MISMATCH')]:
            rec,rows=self.example();rec[field]=value
            plan,checked,_=self.classify(rec,rows)
            self.assertEqual(checked['counts']['skip'],0,plan)
            self.assertEqual(checked['counts']['write'],0,plan)

    def test_reopen_row_after_plan_rejects_settled_skip(self):
        rec,rows=self.example();plan,checked,before=self.classify(rec,rows)
        self.assertEqual(checked['counts']['skip'],1,plan)
        before[4]['是否结账']='否'
        self.assertEqual(V.validate(plan,before)['counts']['conflict'],1)

if __name__=='__main__':unittest.main()
