import copy
import unittest
from unittest.mock import patch
import classify_hexiao as C


def fixture():
    amounts={'SOD_A':100.,'SOD_B':80.,'SOD_C':60.,'SOD_D':60.}
    rows={i:{'so':'SO_TEST','sod':sod,'yingshou':value,'huikuan':None,'jiti':None,'jiezhang':'否'} for i,(sod,value) in enumerate(amounts.items(),2)}
    ledger=C.LedgerIndex(synthetic={'so':{'SO_TEST':list(rows)},'sod':{r['sod']:[i] for i,r in rows.items()},'rows':rows})
    records=[]
    for index,value in enumerate([20.,280.]):
        records.append({'ar':'AR_'+str(index),'so':'SO_TEST','sod':'','default_first_sod':True,
          'default_amount_local':value,'default_amount_orig':value,'default_cumulative_received_local':20. if index==0 else 300.,
          'default_sod_lines':[{'sod':k,'deliver_local':v,'currency':'人民币CNY'} for k,v in amounts.items()],
          'sod_delivery_local':amounts,'all_sods':list(amounts),'so_delivery_local':300.,
          'currency':'人民币CNY','hexiao_date':'2026-09-03','shoukuan_date':'2026-06-01',
          'delivery_date':'2026-01-01','target_ledger_year':2026,
          'writeoff_sequence_key':['2026-09-03','HX_'+str(index),'detail_'+str(index)]})
    return records,ledger

class ItemizedSequenceTest(unittest.TestCase):
    def test_two_itemized_receipts_share_capacity(self):
        records,ledger=fixture();result=C.classify_records(records,ledger)
        self.assertEqual(result['hold'],[])
        self.assertEqual(result['exception'],[])
        slices={(r['ar'],r['sod']):r['split_payment_source']['amount_local'] for r in result['auto']}
        self.assertEqual(slices,{('AR_0','SOD_A'):20.,('AR_1','SOD_A'):80.,('AR_1','SOD_B'):80.,('AR_1','SOD_C'):60.,('AR_1','SOD_D'):60.})
        self.assertTrue(all(r.get('split_chain_group_id') for r in result['auto'] if r['sod']=='SOD_A'))

    def test_already_written_first_receipt_is_not_reserved_twice(self):
        records,ledger=fixture()
        ledger.row_snapshot[2].update(yingshou=20.,huikuan=20.,jiezhang='是',shoukuan_time='2026-09-03',shoukuan_way='冲预收')
        ledger.row_snapshot[6]={'so':'SO_TEST','sod':'SOD_A','yingshou':80.,'huikuan':None,'jiezhang':'否'}
        ledger.so_index['SO_TEST'].append(6);ledger.sod_index['SOD_A'].append(6)
        result=C.classify_records(records,ledger)
        self.assertEqual(result['exception'],[])
        self.assertEqual(result['hold'],[])
        total=sum(r['split_payment_source']['amount_local'] for r in result['auto'] if r['ar']=='AR_1')
        self.assertEqual(total,280.)

    def test_rejected_chain_blocks_other_slices(self):
        records,ledger=fixture()
        import classification_runner as runner
        with patch.object(runner,'_make_split_payment_chain',return_value=(None,'synthetic chain failure')):
            result=C.classify_records(records,ledger)
        self.assertEqual(result['auto'],[])
        self.assertEqual(len(result['hold']),5)


class SequenceGuardTest(unittest.TestCase):
    def test_validation_failure_blocks_peers_but_not_other_so(self):
        import receipt_sequence as R
        members=['a','b']
        items=[{'case_id':'a','receipt_sequence_cases':members,'_check':{'verdict':'conflict'}},
               {'case_id':'b','receipt_sequence_cases':members,'_check':{'verdict':'write'}},
               {'case_id':'other','_check':{'verdict':'write'}}]
        R.guard(items,checked=True)
        self.assertEqual([i['_check']['verdict'] for i in items],['conflict','conflict','write'])

    def test_missing_member_rejected_on_prewrite_recheck(self):
        import receipt_sequence as R
        items=[{'case_id':'a','receipt_sequence_cases':['a','b'],'_check':{'verdict':'write'}}]
        R.guard(items,checked=True)
        self.assertEqual(items[0]['_check']['verdict'],'conflict')

if __name__=='__main__':unittest.main()
