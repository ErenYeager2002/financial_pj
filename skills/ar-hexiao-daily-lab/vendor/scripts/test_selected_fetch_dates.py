import io,json,unittest
from unittest.mock import patch
import fetch_secure,fetch_zhiyun

class SelectedDatesTest(unittest.TestCase):
    def invoke(self,**dates):
        payload=dict(account="fixture",password="fixture",workspace="/tmp/fixture",**dates)
        with patch("sys.stdin",io.StringIO(json.dumps(payload))), patch("sys.stderr",io.StringIO()), patch.object(fetch_zhiyun,"main",return_value=0) as fetch:
            result=fetch_secure.main()
        return result,[call.args[0][1] for call in fetch.call_args_list]

    def test_sparse_dates_only_fetch_selected_days(self):
        self.assertEqual(self.invoke(dates=["2026-09-17","2026-09-03","2026-09-04","2026-09-03"]),(0,["2026-09-03","2026-09-04","2026-09-17"]))

    def test_legacy_single_and_range_unchanged(self):
        self.assertEqual(self.invoke(reconciliation_date="2026-09-03"),(0,["2026-09-03"]))
        self.assertEqual(self.invoke(date_from="2026-09-03",date_to="2026-09-04"),(0,["2026-09-03","2026-09-04"]))

    def test_invalid_or_ambiguous_dates_do_not_fetch(self):
        for data in [dict(dates=[]),dict(dates="2026-09-03"),dict(dates=["invalid"]),dict(dates=["2026-09-03"],reconciliation_date="2026-09-04"),dict(dates=["2026-09-03"],date_from="2026-09-03",date_to="2026-09-04")]:
            with self.subTest(data=data):self.assertEqual(self.invoke(**data),(2,[]))

    def test_platform_payload_keeps_selected_dates(self):
        import ast
        from pathlib import Path
        source=Path('/app/backend/app/workflow_service.py')
        if not source.exists():self.skipTest('platform integration requires built image')
        tree=ast.parse(source.read_text())
        candidates=[n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test)=='len(batch_dates) > 1' and any(isinstance(x,ast.Call) and ast.unparse(x.func)=='fetch_payload.update' for x in ast.walk(n))]
        self.assertEqual(len(candidates),1)
        scope={'batch_dates':['2026-09-03','2026-09-04','2026-09-17'],'fetch_payload':{},'hexiao_date':'2026-09-03'}
        exec(compile(ast.Module(body=[candidates[0]],type_ignores=[]),str(source),'exec'),scope)
        self.assertEqual(self.invoke(**scope['fetch_payload']),(0,scope['batch_dates']))
