import copy
import datetime as dt
import unittest
from current_parent_receipt_group import prove

class ParentReceiptGroupTest(unittest.TestCase):
    def fixture(self):
        parents=[]
        for ar in ('AR_A','AR_B'):
            parents.append(dict(ar=ar,status='手动核销',hexiao_date='2026-08-25',arrival_date='2026-08-12',
                currency='人民币CNY',amount_orig=450,amount_local=450,total_amount_orig=450,total_amount_local=450,
                orders=[dict(so='SO_A',deliver=900,deliver_local=900)],
                duplicate_writeoff_audit={'status':'parent_fallback'},_source_meta={'raw_writeoff_rows':0}))
        rows={5:dict(SO='SO_A',SOD='SOD_A',应收金额=900,回款明细=900,计提=900,
                     是否结账='是',收款时间=dt.date(2026,8,12),收款方式='汇',差异=None)}
        return parents,rows

    def test_group_proves_amounts_without_splitting_settled_row(self):
        parents,rows=self.fixture();before=copy.deepcopy((parents,rows))
        proof=prove(parents,rows,'2026-08-25')
        self.assertEqual(proof['amounts_by_ar'],{'AR_A':450,'AR_B':450})
        self.assertEqual(proof['ledger_total'],900)
        self.assertEqual(proof,prove(list(reversed(parents)),rows,'2026-08-25'))
        self.assertEqual(before,(parents,rows))

    def test_incomplete_or_non_equivalent_group_is_rejected(self):
        for mode in ('one','duplicate_ar','extra_order','future','currency','fee','history','short','extra_row','date','way','difference','unsettled'):
            with self.subTest(mode=mode):
                parents,rows=self.fixture()
                if mode=='one':parents.pop()
                if mode=='duplicate_ar':parents[1]['ar']=parents[0]['ar']
                if mode=='extra_order':parents[0]['orders'].append(dict(so='SO_B',deliver=1,deliver_local=1))
                if mode=='future':parents[0]['hexiao_date']='2026-08-26'
                if mode=='currency':parents[0]['currency']='USD'
                if mode=='fee':parents[0]['fee']=1
                if mode=='history':parents[0]['_current_source_history_by_so']={'SO_A':{'events':[{'amount':1}]}}
                if mode=='short':rows[5]['回款明细']=899
                if mode=='extra_row':rows[6]=copy.deepcopy(rows[5])
                if mode=='date':rows[5]['收款时间']=dt.date(2026,7,12)
                if mode=='way':rows[5]['收款方式']='未知'
                if mode=='difference':rows[5]['差异']=1
                if mode=='unsettled':rows[5]['是否结账']='否'
                self.assertIsNone(prove(parents,rows,'2026-08-25'))

    def test_recheck_rejects_changed_workbook_source_and_proof(self):
        from current_parent_receipt_group import check
        parents,rows=self.fixture();proof=prove(parents,rows,'2026-08-25')
        item=dict(ar='AR_A',so='SO_A',code='OK_SO_ALREADY_SETTLED',_check={'verdict':'skip'},
            source_lineage={'source':dict(ar='AR_A',so='SO_A',currency='CNY',reconciliation_date='2026-08-25',parent_amount_local=450,parent_amount_orig=450)})
        self.assertEqual(check(proof,rows,item,'2026-08-25')['amount'],450)
        for mode in ('row','accrual','proof_amount','parent_amount','source_amount','source_currency','date','write'):
            with self.subTest(mode=mode):
                p,r,i=copy.deepcopy((proof,rows,item))
                if mode=='row':r[5]['回款明细']=899
                if mode=='accrual':r[5]['计提']=899
                if mode=='proof_amount':p['amounts_by_ar']['AR_A']=900
                if mode=='parent_amount':p['source_payments'][0]['amount_local']=900
                if mode=='source_amount':i['source_lineage']['source']['parent_amount_local']=900
                if mode=='source_currency':i['source_lineage']['source']['currency']='USD'
                if mode=='date':i['source_lineage']['source']['reconciliation_date']='2026-08-26'
                if mode=='write':i['_check']['verdict']='write'
                self.assertIsNone(check(p,r,i,'2026-08-25'))
