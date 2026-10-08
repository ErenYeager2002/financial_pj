import copy
import unittest
import flow_current_deductions as D
import flow_parent_net as N
import flow_source_receipts as S
import common

class VisibleDeductions(unittest.TestCase):
    def fixture(self):
        source=[dict(key='source|'+str(i),case_id='AR|SO'+str(i),so='SO'+str(i),date=day,amount=amount)
                for i,day,amount in [(1,'2026-08-01','70'),(2,'2026-09-02','20')]]
        entries=[copy.deepcopy(source[0]),dict(key='legacy:2:1',so='',amount='20'),dict(key='legacy:2:2',so='',amount='5')]
        chain=dict(months=[dict(start='100',remaining='5',entries=entries,signature=['2026-08-01','customer','100','汇款','WX SO1 SO2 20 SO3'],legacy_sos=['SO2','SO3'])])
        item=dict(monthly_entries=[source[1]],monthly_receipt_history=dict(basis='current_source_reconcile',fetched_history=True,
            date='2026-09-02',opening='100',entries=source))
        return chain,item
    def test_proved_prefix_keeps_later_deduction_and_money(self):
        chain,item=self.fixture();before=copy.deepcopy(chain);result=D.bind(chain,item)
        self.assertEqual(chain,before)
        self.assertEqual(result['months'][0]['entries'][:2],item['monthly_receipt_history']['entries'])
        self.assertEqual(result['months'][0]['entries'][2],chain['months'][0]['entries'][2])
        self.assertEqual(result['months'][0]['remaining'],'5')
        self.assertEqual(result['months'][0]['legacy_sos'],['SO3'])
        self.assertEqual(D.bind(result,item),result)
    def test_incomplete_or_changed_evidence_does_not_bind(self):
        for mode in ('money','unknown','identity','future','balance','double_so','no_explicit_amount'):
            chain,item=self.fixture()
            if mode=='money':item['monthly_receipt_history']['entries'][0]['amount']='69'
            if mode=='unknown':chain['months'][0]['signature'][4]='SO1 SO4 SO3'
            if mode=='identity':chain['months'][0]['entries'][0]['case_id']='OTHER'
            if mode=='future':item['monthly_receipt_history']['entries'][0]['date']='2026-10-01'
            if mode=='balance':chain['months'][0]['remaining']='4'
            if mode=='no_explicit_amount':chain['months'][0]['signature'][4]='SO1 SO2 SO3'
            if mode=='double_so':chain['months'][0]['signature'][4]='SO1 SO2 SO3 SO2'
            self.assertEqual(D.bind(chain,item),chain,mode)
    def test_exact_closed_prefix(self):
        chain,item=self.fixture();m=chain['months'][0];m.update(start='90',remaining='0');m['entries'].pop();m['signature'][4]='SO1 SO2';item['monthly_receipt_history']['opening']='90'
        self.assertEqual(D.bind(chain,item)['months'][0]['entries'],item['monthly_receipt_history']['entries'])

class EquivalentParentEntries(unittest.TestCase):
    def fixture(self):
        day='2026-09-02';sources=[dict(ar='AR1',so=so,date=day,amount=str(amount),amount_orig=str(amount),currency='CNY',basis='current_source_so_receipt',event=[day,'HX'+so,'ROW'+so]) for so,amount in [('SO1',60),('SO2',40)]]
        item=dict(ar='AR1',source_receipts=sources,monthly_entries=[dict(key='parent-net|AR1',amount='100',date=day)])
        entries=S.allocations(item,common.norm_date(day))
        return dict(months=[dict(entries=entries,remaining='0')]),item
    def test_existing_same_events_preserved_not_recharged(self):
        chain,item=self.fixture();N.validate_existing(chain,item)
        self.assertEqual(item['monthly_entries'],chain['months'][0]['entries'])
    def test_equal_total_wrong_identity_still_rejected(self):
        for mode in ('identity','amount','remaining'):
            chain,item=self.fixture()
            if mode=='identity':chain['months'][0]['entries'][0]['key']+='OTHER'
            if mode=='amount':chain['months'][0]['entries'][0]['amount']='59'
            if mode=='remaining':chain['months'][0]['remaining']='1'
            with self.assertRaises(ValueError):N.validate_existing(chain,item)

if __name__=='__main__':unittest.main()
