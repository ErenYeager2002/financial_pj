import copy,datetime,unittest
from classification_exports import reconcile_writeoff_details
from classification_expansion import expand_payment
from writeoff_local_amounts import detail_local,add_complete

DAY=datetime.date(2026,9,20)

def payment(ar,amount=200,local=1438.38):
    return {'ar':ar,'currency':'USD','amount_orig':amount,'amount_local':local,
        'total_amount_orig':amount,'total_amount_local':local,'shoukuan_date':DAY.isoformat(),
        'hexiao_date':DAY,'status':'已核销','_source_meta':{'historical_detail_rows':0},
        'orders':[{'so':'SO_TEST','deliver':400,'deliver_local':3000,'currency':'USD','rate':7.5}],
        'sod_lines':{'SO_TEST':[{'sod':'SOD_TEST','deliver':400,'currency':'USD'}]}}

def row(ar,num,local,rate=7.1919):
    return {'record_id':str(num),'rowid':str(num),'ar':ar,'so':'SO_TEST','date':DAY,
        'snapshot_date':DAY,'amount':100,'amount_local':local,'currency':'USD','rate':rate,
        'revoked':'','source':'synthetic','_input_index':num}

class SourceLocalAmounts(unittest.TestCase):
    def reconcile(self,parents,rows):
        result=reconcile_writeoff_details(parents,{p['ar']:p for p in parents},rows,DAY)
        self.assertTrue(all(a['status']=='normal' for a in result[1].values()))
        return result
    def test_explicit_precedes_rate_and_zero_is_present(self):
        self.assertEqual(detail_local({'amount':100,'amount_local':0,'currency':'USD','rate':7}),0)
        self.assertEqual(detail_local({'amount':100,'amount_local':719.19,'currency':'USD','rate':9}),719.19)
    def test_only_own_conversion_evidence(self):
        for currency,rate,expected in [('CNY',None,100),('人民币',9,100),('USD',7.1919,719.19),('USD',None,None),('USD',0,None),('USD',-1,None),('',7,None)]:
            with self.subTest(currency=currency,rate=rate):
                self.assertEqual(detail_local({'amount':100,'currency':currency,'rate':rate}),expected)
    def test_missing_is_absorbing_not_zero(self):
        amounts={};add_complete(amounts,'SO',719.19);add_complete(amounts,'SO',None);add_complete(amounts,'SO',700)
        self.assertIsNone(amounts['SO'])
    def test_mixed_explicit_and_own_rate_is_complete(self):
        p=payment('AR_A');raw=[row('AR_A',1,719.19),row('AR_A',2,None)];before=copy.deepcopy(raw)
        self.reconcile([p],raw)
        self.assertEqual(raw,before)
        self.assertEqual(p['writeoffs_local']['SO_TEST'],1438.38)
        actual=expand_payment(p,{})[0]
        self.assertEqual(actual['amount_local'],1438.38)
        self.assertEqual(actual['cumulative_received_local'],1438.38)
        self.assertEqual(actual['deliver_local'],3000) # delivery never uses receipt FX
        self.assertFalse(actual.get('forced_code'))
    def test_distinct_detail_rates_not_parent_ratio(self):
        p=payment('AR_A',local=1500)
        self.reconcile([p],[row('AR_A',1,None,7),row('AR_A',2,None,8)])
        self.assertEqual(p['writeoffs_local']['SO_TEST'],1500)
    def test_unresolved_current_amount_holds(self):
        p=payment('AR_A');self.reconcile([p],[row('AR_A',1,719.19),row('AR_A',2,None,None)])
        self.assertIsNone(p['writeoffs_local']['SO_TEST'])
        self.assertIsNone(p['cumulative_writeoffs_local']['SO_TEST'])
        self.assertEqual(expand_payment(p,{})[0]['forced_code'],'E7')
    def test_historical_gap_propagates_to_later_parent_only(self):
        parents=[payment('AR_A',100,719.19),payment('AR_B',100,719.19),payment('AR_C',100,719.19)]
        self.reconcile(parents,[row('AR_A',1,719.19),row('AR_B',2,None,None),row('AR_C',3,719.19)])
        self.assertEqual(parents[0]['cumulative_writeoffs_local']['SO_TEST'],719.19)
        self.assertIsNone(parents[1]['cumulative_writeoffs_local']['SO_TEST'])
        self.assertIsNone(parents[2]['cumulative_writeoffs_local']['SO_TEST'])
        self.assertFalse(expand_payment(parents[0],{})[0].get('forced_code'))
        self.assertEqual(expand_payment(parents[2],{})[0]['forced_code'],'E7')
    def test_cross_parent_own_rates_sum(self):
        parents=[payment('AR_A',100,700),payment('AR_B',100,800)]
        self.reconcile(parents,[row('AR_A',1,None,7),row('AR_B',2,None,8)])
        self.assertEqual(parents[0]['cumulative_writeoffs_local']['SO_TEST'],700)
        self.assertEqual(parents[1]['cumulative_writeoffs_local']['SO_TEST'],1500)
    def test_no_detail_parent_cannot_allocate_against_incomplete_history(self):
        parents=[payment('AR_A',100,719.19),payment('AR_B',100,719.19)]
        self.reconcile(parents[:1],[row('AR_A',1,None,None)])
        parents[1]['cumulative_writeoffs_local']=dict(parents[0]['cumulative_writeoffs_local'])
        parents[1]['cumulative_writeoffs']=dict(parents[0]['cumulative_writeoffs'])
        self.assertEqual(expand_payment(parents[1],{})[0]['forced_code'],'E7')
    def test_foreign_without_source_local_never_becomes_raw_local(self):
        p=payment('AR_A',100,719.19)
        p.update(writeoffs={'SO_TEST':100},cumulative_writeoffs={'SO_TEST':100},duplicate_writeoff_audit={'comparison_basis':'detail_original'})
        self.assertEqual(expand_payment(p,{})[0]['forced_code'],'E7')

    def test_converted_receipts_write_readback_and_repeat_consistently(self):
        import tempfile,openpyxl
        from pathlib import Path
        import test_delivery_above_receivable as T
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'initial.xlsx'
            b=openpyxl.Workbook();w=b.active;w.title='明细'
            w.append(['新智云单号','实收金额','应收金额','计提','回款明细','是否结账','收款时间','收款方式(支/汇/现)','差异'])
            w.append(['SO_TEST','SOD_TEST',1000,None,None,'否',None,None,None]);b.save(path);b.close()
            helper=T.DeliveryAboveReceivable()
            parents=[payment('AR_A'),payment('AR_B',200,1561.62)]
            rows=[row('AR_A',1,719.19),row('AR_A',2,None),row('AR_B',3,None,7.8081),row('AR_B',4,None,7.8081)]
            self.reconcile(parents,rows)
            journal={}
            for index,parent in enumerate(parents):
                rec=expand_payment(parent,{})[0]
                path,journal,actual=helper.step(path,rec,journal)
                self.assertEqual([r['应收金额'] for r in actual.values()],[1000]+[None]*(index+1))
                self.assertEqual(round(sum(r['回款明细'] or 0 for r in actual.values()),2),1438.38 if index==0 else 3000)
                self.assertEqual(sum(r['计提'] or 0 for r in actual.values()),0 if index==0 else 3000)

if __name__=='__main__':unittest.main()
