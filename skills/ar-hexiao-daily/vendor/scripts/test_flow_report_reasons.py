import tempfile
import unittest
from pathlib import Path
import openpyxl
from build_execution_report import flow_explanation, write_report

class FlowReportReasonsTest(unittest.TestCase):
    def test_skipped_explains_each_order(self):
        flow={'flow_written':True,'report_items':[{'ar':'AR1','verdict':'skip','reason':'没有经验证的本次核销金额可登记'}]}
        records=[{'ar':'AR1','so':'SO1','final_reason':'当前材料缺少完整回款记录'},{'ar':'AR2','so':'OTHER','final_reason':'私有原因'}]
        label,reason=flow_explanation('AR1',flow,records)
        self.assertEqual(label,'暂未登记');self.assertIn('SO1：当前材料缺少完整回款记录',reason);self.assertNotIn('OTHER',reason)
    def test_prefill_is_not_reported_as_no_write(self):
        flow={'flow_written':True,'phases':{'prefill':{'changes':[{'AR':'AR1'}]}}}
        label,reason=flow_explanation('AR1',flow,[{'ar':'AR1','so':'SO1','final_reason':'缺少2024年盈亏材料'}])
        self.assertEqual(label,'已预填，待核销');self.assertIn('未据此扣减预收',reason);self.assertIn('2024',reason)
    def test_manual_reason_is_preserved(self):
        label,reason=flow_explanation('AR1',{'flow_written':True,'manual_items':[{'ar':'AR1','reason':'日期金额多命中2行'}]},[])
        self.assertEqual(label,'手填');self.assertIn('多命中2行',reason)
    def test_missing_evidence_does_not_claim_already_registered(self):
        label,reason=flow_explanation('AR1',{'flow_written':True},[])
        self.assertEqual(label,'未新增登记');self.assertIn('未保存逐笔原因',reason)
    def test_incomplete_phase_does_not_claim_prefill_success(self):
        label,reason=flow_explanation('AR1',{'flow_written':False,'reason':'写后回读不一致','phases':{'prefill':{'changes':[{'AR':'AR1'}]}}},[])
        self.assertEqual(label,'流转未完成');self.assertIn('写后回读不一致',reason)
    def test_workbook_explanation_and_order_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'核销日清_20260920.xlsx'
            w=openpyxl.Workbook();s=w.active;s.title='流转表怎么填';s.append(['列'+str(i) for i in range(12)]);s.append(['AR1','待处理','','','待写后确认','SO1 100','','','','','','']);w.save(target);w.close()
            payload={'reconciliation_date':'2026-09-20','counts':{},'write_count':0,'records':[], 'flow':{'flow_written':True,'report_items':[{'ar':'AR1','order_only':True,'reason':'订单缺少对应年度材料'}],'phases':{'prefill':{'changes':[{'AR':'AR1'}]}}}}
            write_report(payload,target,{'auto':[],'hold':[],'exception':[]},{'write':[],'skip':[],'conflict':[]})
            w=openpyxl.load_workbook(target);s=w['流转表怎么填'];self.assertEqual(s['B2'].value,'已预填，待核销');self.assertIn('缺少对应年度材料',s['L2'].value);self.assertEqual(s['F2'].value,'SO1 100');w.close()

    def test_real_phase_failure_shape_has_specific_reason(self):
        for phase in ({'state':'failed','reason':'流转计划无效'}, {'state':'failed','problems':['目标行身份变化']}):
            label,reason=flow_explanation('AR1',{'flow_written':False,'phases':{'status':phase}},[])
            self.assertEqual(label,'流转未完成')
            self.assertIn(phase.get('reason') or phase['problems'][0],reason)
    def test_status_order_only_change_is_not_settlement(self):
        label,reason=flow_explanation('AR1',{'flow_written':True,'phases':{'status':{'changes':[{'AR':'AR1','操作':'仅预填订单信息'}]}}},[])
        self.assertEqual(label,'已预填，待核销');self.assertIn('未据此扣减预收',reason)
