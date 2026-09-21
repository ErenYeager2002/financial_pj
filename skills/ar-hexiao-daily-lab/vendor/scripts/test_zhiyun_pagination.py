import unittest
from unittest.mock import patch
import fetch_zhiyun as F
from zhiyun_pagination import PageAccumulator

class PaginationTests(unittest.TestCase):
    def client(self):
        c=F.ZhiyunClient('http://example.invalid','synthetic');self.addCleanup(c.session.close);return c
    def test_server_short_pages_continue_until_declared_total(self):
        c=self.client();seen=[]
        def post(path,body,timeout=90):
            page=body['pageIndex'];seen.append(page)
            return {'data':[{'rowid':str(page)}],'count':5}
        with patch.object(c,'post',side_effect=post):rows,total=c.filter_rows_by_date('ws','date','2026-09-20',page_size=2)
        self.assertEqual(len(rows),5);self.assertEqual(total,5);self.assertEqual(seen,[1,2,3,4,5])
    def test_premature_empty_page_is_not_success(self):
        c=self.client()
        with patch.object(c,'post',side_effect=[{'data':[{'rowid':'1'}],'count':5},{'data':[],'count':5}]):
            with self.assertRaises(F.FetchError):c.filter_rows_by_date('ws','date','2026-09-20',page_size=2)
    def test_malformed_pages_are_not_empty(self):
        for response in [None,{}, {'data':{}},{'data':[1]}]:
            with self.subTest(response=response):
                collector=PageAccumulator(2,F.FetchError)
                with self.assertRaises(F.FetchError):collector.accept(response)
    def test_search_past_old_twenty_page_limit(self):
        c=self.client()
        def post(path,body,timeout=90):
            page=body['pageIndex'];return {'data':[{'rowid':str(page)}] if page<=21 else []}
        with patch.object(c,'post',side_effect=post):rows=c.search_rows('ws','SO_TEST',page_size=1)
        self.assertEqual(len(rows),21)
    def test_relation_past_old_fifty_page_limit_and_keeps_controls(self):
        c=self.client()
        def post(path,body,timeout=90):
            page=body['pageIndex'];return {'data':{'data':[{'rowid':str(page)}] if page<=51 else []},'worksheet':{'controls':[{'controlId':'SO'}]}}
        with patch.object(c,'post',side_effect=post):rows,controls=c.relation_rows('ws','row','control',page_size=1)
        self.assertEqual(len(rows),51);self.assertEqual(controls,[{'controlId':'SO'}])
    def test_duplicate_page_rejected(self):
        c=self.client()
        with patch.object(c,'post',return_value={'data':[{'rowid':'same'}]}):
            with self.assertRaises(F.FetchError):c.search_rows('ws','SO_TEST',page_size=1)
    def test_changed_total_rejected(self):
        p=PageAccumulator(1,F.FetchError);self.assertFalse(p.accept({'data':[{'rowid':'1'}],'count':2}))
        with self.assertRaises(F.FetchError):p.accept({'data':[{'rowid':'2'}],'count':3})
    def test_exact_total_avoids_extra_request(self):
        p=PageAccumulator(2,F.FetchError);self.assertTrue(p.accept({'data':[{},{}],'count':2}))
    def test_unknown_total_short_page_is_valid(self):
        p=PageAccumulator(2,F.FetchError);self.assertTrue(p.accept([{}]))
    def test_limit_cannot_return_truncated_rows(self):
        p=PageAccumulator(1,F.FetchError,max_pages=2);self.assertFalse(p.accept([{'rowid':'1'}]))
        with self.assertRaises(F.FetchError):p.accept([{'rowid':'2'}])
    def test_explicit_empty_result_is_valid(self):
        p=PageAccumulator(2,F.FetchError);self.assertTrue(p.accept({'data':[],'count':0}))
    def test_bad_count_rejected(self):
        for count in [-1,'x',1.5,0]:
            with self.subTest(count=count),self.assertRaises(F.FetchError):PageAccumulator(1,F.FetchError).accept({'data':[{}],'count':count})
    def test_later_request_failure_propagates(self):
        c=self.client()
        with patch.object(c,'post',side_effect=[{'data':[{'rowid':'1'}]},F.FetchError('synthetic request failure')]):
            with self.assertRaisesRegex(F.FetchError,'synthetic request failure'):c.search_rows('ws','SO_TEST',page_size=1)

    def test_sod_search_error_cannot_publish_day_exports(self):
        import tempfile
        from pathlib import Path
        def controls(names):return [{'controlId':n,'controlName':n,'dataSource':n} for n in names]
        tables={F.WS_HUIKUAN:controls([F.REL_XIADAN,F.REL_JIESUAN,F.REL_HEXIAO_MINGXI,F.REL_SODLINE]),F.REL_XIADAN:controls(F.XIADAN_COLS),F.REL_HEXIAO_MINGXI:controls(F.MINGXI_COLS),F.REL_SODLINE:controls(F.SODLINE_COLS)}
        def post(client,path,b,timeout=90):
            ws=b['worksheetId']
            if path=='worksheet/getWorksheetInfo':return {'controls':tables[ws]}
            if path=='worksheet/getRowRelationRows':
                name=b['controlId'];rows=[{'SO':'SO26000001','交付额/本币':'10'}] if name==F.REL_XIADAN else []
                return {'data':rows,'worksheet':{'controls':tables[name]}}
            if ws==F.WS_HUIKUAN:return {'data':[{'rowid':'ar',F.F_HK['ar']:'AR_TEST',F.F_HK['hexiao_date']:'2026-09-03'}],'count':1}
            if ws==F.REL_XIADAN:return {'data':[{'SO':b['keyWords'],'项目交付日期':'2026-09-01'}]}
            if ws==F.REL_SODLINE:raise F.FetchError('synthetic SOD page failure')
            return {'data':[]}
        with tempfile.TemporaryDirectory() as temp,patch.object(F.ZhiyunClient,'post',post),patch.object(F,'publish_day_exports') as publish:
            with self.assertRaises(F.FetchError):F.fetch_day(self.client(),'2026-09-03',Path(temp))
            publish.assert_not_called()

if __name__=='__main__':unittest.main()
