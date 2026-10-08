"""Reported manual rows follow real insertions without rewriting approved plans."""
import json,shutil,unittest
import build_flow_plan,execution_flow_stage,verify_execution_write
from test_flow_source_receipts import SourceReceiptFlow

class ReportCoordinates(unittest.TestCase):
    setUp=SourceReceiptFlow.setUp
    tearDown=SourceReceiptFlow.tearDown
    entry=SourceReceiptFlow.entry
    row=SourceReceiptFlow.row
    read=SourceReceiptFlow.read
    modify=SourceReceiptFlow.modify

    def test_manual_rows_after_two_inserts_and_repeat(self):
        def initial(ws):
            ws.append(['2026-07-27','测试乙',9000,'汇款','WX',9000,None])
            ws.append(['2026-07-27','测试丙',9000,'汇款','WX SOOLD',None,None])
        self.modify(initial)
        rows=[self.row('SO1',1000,day='2026-08-01'),self.row('SO2',2000,day='2026-08-01'),
              self.row('SO3',3000,day='2026-08-01')]
        for i,(r,payer) in enumerate(zip(rows,['测试甲','测试乙','测试丙']),2):
            ar='AR'+str(i)
            r.update(ar=ar,flow_row_no=i,case_id=ar+'|'+r['so'])
            r['flow_identity']['payer']=payer
            r['flow_source_receipt']['ar']=ar
        baseline=self.root/'baseline'
        shutil.copytree(self.root/'02_我的表副本',baseline/'02_我的表副本')
        output=self.root/'04_产出';cp=output/'checked.json'
        cp.write_text(json.dumps({'hexiao_date':'2026-08-01','write':[],'skip':[],'conflict':[]}))
        def run():
            flow=build_flow_plan.build_plan({'hold':rows,'hexiao_date':'2026-08-01'})
            (output/'流转写入计划_校验后.json').write_text(json.dumps(flow))
            return execution_flow_stage.run(self.root,cp)
        first=run();self.assertTrue(first['flow_written'])
        self.assertEqual(first['manual_items'][0]['row_no'],4)
        self.assertIn('SOOLD',str(self.read('E4')))
        status=json.loads((output/'流转状态回填计划_20260801.json').read_text())
        self.assertEqual(status['manual_items'][0]['row_no'],4)
        self.assertEqual([x['appended_after_row'] for x in first['phases']['status']['changes']],[4,5])
        (output/'流转阶段执行结果.json').write_text(json.dumps(first))
        self.assertEqual(verify_execution_write.verify_flow(self.root,baseline,self.path,json.loads(cp.read_text()))['mode'],'approved_patch_all_parts')
        corrupt=json.loads(json.dumps(first));corrupt['manual_items'][0]['row_no']=6
        (output/'流转阶段执行结果.json').write_text(json.dumps(corrupt))
        with self.assertRaisesRegex(ValueError,'人工项目'):
            verify_execution_write.verify_flow(self.root,baseline,self.path,json.loads(cp.read_text()))
        for r,new_row in zip(rows,[2,3,4]):r['flow_row_no']=new_row
        again=run();self.assertTrue(again['flow_written'])
        self.assertEqual(again['manual_items'],first['manual_items'])
        self.assertEqual(again['phases']['status']['changed_count'],0)

    def test_reason_coordinates_shift_but_amounts_and_other_files_do_not(self):
        manual=[dict(ar='AR1',file='a.xlsx',sheet='明细',row_no=10,
            reason='流转行10,20,30已出现本次单号SO1；到账10.00元，差额20.00元')]
        changes=[{'文件':'a.xlsx','sheet':'明细','inserted_after_row':15},
                 {'文件':'other.xlsx','sheet':'明细','inserted_after_row':1},
                 {'文件':'a.xlsx','sheet':'其他','inserted_after_row':1}]
        result=execution_flow_stage.remap_manual_rows(manual,changes)
        self.assertEqual(result[0]['row_no'],10)
        self.assertEqual(result[0]['reason'],'流转行10,21,31已出现本次单号SO1；到账10.00元，差额20.00元')
        self.assertIn('10,20,30',manual[0]['reason'])
