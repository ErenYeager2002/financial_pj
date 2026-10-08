import unittest
from test_flow_monthly import MonthlySafetyTest
import build_flow_plan,flow_order_prefill

class SalesInitialsTest(unittest.TestCase):
    setUp=MonthlySafetyTest.setUp
    tearDown=MonthlySafetyTest.tearDown
    entry=MonthlySafetyTest.entry
    plans=MonthlySafetyTest.plans
    run_items=MonthlySafetyTest.run_items
    read=MonthlySafetyTest.read
    modify=MonthlySafetyTest.modify
    def named(self,so='SO1',amount=1000,name='王志'):
        row=self.entry(so,amount);row['sales_name']=name;return row
    def blank(self):self.modify(lambda ws:setattr(ws['E2'],'value',None))
    def test_same_month_fills_sales_and_preserves_balance(self):
        self.blank();changes,errors=self.run_items('2026-07-28',[self.named()])
        self.assertEqual(errors,[]);self.assertTrue(changes)
        self.assertEqual(str(self.read('E2')).splitlines()[0],'WZ')
        self.assertEqual(self.read('F2'),'9000-1000=8000')
        before=self.path.read_bytes();self.assertEqual(self.run_items('2026-07-28',[self.named()]),([],[]));self.assertEqual(before,self.path.read_bytes())
    def test_existing_sales_preserved(self):
        self.assertEqual(self.run_items('2026-07-28',[self.named()])[1],[])
        self.assertTrue(str(self.read('E2')).startswith('WX'));self.assertNotIn('WZ',str(self.read('E2')))
    def test_cross_month_carries_sales(self):
        self.blank();self.assertEqual(self.run_items('2026-07-28',[self.named()])[1],[])
        self.assertEqual(self.run_items('2026-08-01',[self.named('SO2',3000)])[1],[])
        self.assertTrue(str(self.read('E3')).startswith('WZ'));self.assertEqual(self.read('F3'),'8000-3000=5000')
    def test_first_posting_cross_month_fills_sales(self):
        self.blank();self.assertEqual(self.run_items('2026-08-01',[self.named()])[1],[])
        self.assertTrue(str(self.read('E3')).startswith('WZ'));self.assertEqual(self.read('F3'),'9000-1000=8000')
    def test_classification_preserves_parent_sales_name(self):
        from classification_decision import classify_one
        result = classify_one(
            {"ar": "AR1", "so": "SO1", "sales_name": "张健", "status": "已作废"},
            None, {}, 0.01, 2026,
        )
        self.assertEqual(result["sales_name"], "张健")

    def test_missing_sales_does_not_block(self):
        self.blank();self.assertEqual(self.run_items('2026-07-28',[self.named(name='')])[1],[])
        self.assertTrue(str(self.read('E2')).startswith('SO1'))
    def test_multiple_sales_are_not_guessed(self):
        p=build_flow_plan.build_plan({'auto':[self.named(),self.named('SO2',2000,'李明')],'hexiao_date':'2026-07-28'})
        self.assertFalse(p['items'][0].get('sales_initials'));self.assertIn('多个',p['items'][0].get('sales_initials_note',''))
    def test_existing_so_is_not_mistaken_for_sales(self):
        row=self.named();row['flow_order_existing']='SO1  1,000.00'
        p=build_flow_plan.build_plan({'auto':[row],'hexiao_date':'2026-07-28'})
        self.assertTrue(p['items'][0]['order_suggest'].startswith('WZ\n'))
    def test_prefill_and_completion_keep_sales(self):
        import apply_flow
        self.blank();row=self.named();row.update(bucket='hold',code='E2')
        row['split_payment_source']['so_delivery_local']=1000
        plan=build_flow_plan.build_plan({'hold':[row],'hexiao_date':'2026-07-28'})
        self.assertEqual(apply_flow.write_flow_items(self.root,plan['items'],in_place=True,phase='prefill')[1],[])
        self.assertTrue(str(self.read('E2')).startswith('WZ'));self.assertEqual(self.read('F2'),9000)
        row.update(bucket='auto',code='')
        self.assertEqual(self.run_items('2026-07-28',[row])[1],[])
        self.assertEqual(str(self.read('E2')).count('WZ'),1);self.assertEqual(self.read('F2'),'9000-1000=8000')
    def test_rich_text_color_preserved(self):
        import flow_sales_initials,xlsx_patch
        value=xlsx_patch.RichTextValue((xlsx_patch.RichTextRun('SO1  1000','FFFF0000'),))
        result=flow_sales_initials.rich(value,{'sales_initials':'WZ'})
        self.assertEqual(result.runs[-1].color,'FFFF0000');self.assertTrue(''.join(r.text for r in result.runs).startswith('WZ'))
    def test_chinese_initials_and_invalid_name(self):
        import flow_sales_initials as f
        for name,wanted in [('王志','WZ'),('李小明','LXM'),('曾明','ZM'),('单明','SM')]:
            self.assertEqual(f.from_records([{'sales_name':name}])['sales_initials'],wanted)
        self.assertFalse(f.from_records([{'sales_name':'未知/王志'}])['sales_initials'])

    def test_fixed_sales_alias_mapping(self):
        import flow_sales_initials as f
        expected = [
            ('\u5434\u6d2a\u4f1f', 'WH'), ('\u90d1\u745e', 'ZR'), ('\u9648\u971e', 'CX'),
            ('\u8d75\u8d3a\u658c', 'HB'), ('\u5b59\u82d7\u7ea2', 'SM'), ('\u5f20\u4e3d\u4e3d', 'ZL'),
            ('\u5f20\u5065', 'JZ'), ('\u77f3\u8096\u749e', 'SX'), ('\u4e8e\u5360\u56fd', 'ZG'),
            ('\u9a86\u5229\u98de', 'LL'), ('\u738b\u96c4', 'WX'), ('\u80e1\u4f1f\u660e', 'HW'),
            ('\u6768\u5229\u5b8f', 'YL'), ('\u59dc\u5f81', 'OJ'), ('\u9ec4\u6021\u73ae', 'HY'),
            ('\u674e\u521a', 'LG'), ('\u6881\u73b2\u73b2', 'IL'), ('\u9ad8\u6d0b', 'GY'),
            ('\u725b\u5f3a', 'NQ'), ('\u738b\u8273\u73b2', 'AA'),
        ]
        for name, wanted in expected:
            self.assertEqual(f.from_records([{'sales_name': name}])['sales_initials'], wanted)
        self.assertEqual(f.ensure('SO26090001  1000', {'sales_initials': 'YB'}).splitlines()[0], 'YB')

    def test_embedded_existing_sales_preserved(self):
        import flow_sales_initials as f
        self.assertEqual(f.ensure('WXSO26090001  1000',{'sales_initials':'WZ'}),'WXSO26090001  1000')
