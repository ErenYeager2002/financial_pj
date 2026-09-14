"""Classification gates exercised in an isolated real Chromium page."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"skills/consolidated-statements/scripts"))
from collector import set_classification, query_classified_balance
from engine import SourceError
from playwright.sync_api import sync_playwright

class ClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=sync_playwright().start()
        cls.browser=cls.p.chromium.launch(headless=True)
    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.p.stop()
    def setUp(self):
        self.page=self.browser.new_page()
        self.page.set_content("""
<div onclick="document.querySelector('#reclass').checked=!document.querySelector('#reclass').checked">
<input id="reclass" type="checkbox" style="pointer-events:none"><span>重分类</span></div>
<div onclick="document.querySelector('#tax').checked=!document.querySelector('#tax').checked">
<input id="tax" type="checkbox" checked style="pointer-events:none"><span>应交税费重分类</span></div>
<button id="query">查询</button><script>window.count=0;</script>
""")
    def tearDown(self):self.page.close()
    def query(self):self.page.locator("#query").click()
    def setup_query(self,condition):
        self.page.evaluate("""condition => document.querySelector('#query').onclick=()=>{
window.count++;
if(eval(condition)){document.querySelector('#reclass').checked=false;document.querySelector('#tax').checked=true;}
}""",condition)
    def test_month_change_is_corrected_before_query(self):
        self.setup_query("false")
        query_classified_balance(self.page,self.query)
        set_classification(self.page,verify_only=True)
        self.assertEqual(self.page.evaluate("window.count"),1)
    def test_query_reset_requires_second_query(self):
        self.setup_query("window.count===1")
        query_classified_balance(self.page,self.query)
        self.assertEqual(self.page.evaluate("window.count"),2)
        set_classification(self.page,verify_only=True)
    def test_repeated_resets_stop_export(self):
        self.setup_query("true")
        with self.assertRaisesRegex(SourceError,"停止导出"):
            query_classified_balance(self.page,self.query)
        self.assertEqual(self.page.evaluate("window.count"),2)
    def test_export_gate_does_not_silently_fix_stale_results(self):
        set_classification(self.page)
        self.page.locator("#tax").evaluate("(el)=>el.checked=true")
        with self.assertRaises(SourceError):set_classification(self.page,verify_only=True)
        self.assertTrue(self.page.locator("#tax").is_checked())
    def test_ambiguous_controls_are_rejected(self):
        self.page.locator("#reclass").evaluate("(el)=>el.parentElement.appendChild(document.createElement('input')).type='checkbox'")
        with self.assertRaisesRegex(SourceError,"唯一识别"):set_classification(self.page)

if __name__=="__main__":unittest.main()
