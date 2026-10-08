import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import apply_all
import batch_ledger
import current_execution_registration as R
import fallback_allocation_ledger as F

class Registration(unittest.TestCase):
    def test_real_completion_ignores_corrupt_old_audits_and_preserves_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws=Path(tmp);folder=ws/'03_台账';folder.mkdir()
            originals={F.LEDGER_NAME:b'broken allocation',batch_ledger.LEDGER_NAME:b'broken batch'}
            for name,raw in originals.items():(folder/name).write_bytes(raw)
            plan={'hexiao_date':'2026-08-20','write':[],'skip':[],
                  'business_rules':{'reconciliation_policy':'current-workbook-v1'}}
            checked=ws/'checked.json';checked.write_text(json.dumps(plan))
            for attempt in range(2):
                before={name:(folder/name).read_bytes() for name in originals}
                stdout=io.StringIO();stderr=io.StringIO()
                with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
                    apply_all._record_done(SimpleNamespace(workspace=str(ws),checked=str(checked)),ledger_written=False,flow_written=True)
                self.assertEqual(stderr.getvalue(),'')
                self.assertIn('AR_WRITE_RESULT',stdout.getvalue())
                paths=list((ws/'04_产出').glob('*.json'));self.assertEqual(len(paths),1)
                receipt=json.loads(paths[0].read_text())
                self.assertEqual(receipt['json_ledgers'][F.LEDGER_NAME]['parents'],{})
                self.assertEqual(set(receipt['json_ledgers'][batch_ledger.LEDGER_NAME]['runs']),{'2026-08-20'})
                self.assertEqual(receipt['written'],{'盈亏':False,'流转':True})
                for name,raw in originals.items():
                    if name == F.LEDGER_NAME:self.assertEqual((folder/name).read_bytes(),raw)
                    self.assertEqual(base64.b64decode(receipt['historical_audit_files'][name]['base64']),raw)
                self.assertEqual(batch_ledger.load(ws)['runs']['2026-08-20']['stage'],'applied')
            self.assertFalse(list((ws/'04_产出').glob('.current-registration-*')))

    def test_legacy_registration_keeps_existing_entry_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'checked.json';p.write_text(json.dumps({'hexiao_date':'2026-08-20'}))
            with patch.object(F,'commit',return_value=(Path('audit.json'),0)) as commit,patch.object(batch_ledger,'record'),contextlib.redirect_stdout(io.StringIO()):
                apply_all._record_done(SimpleNamespace(workspace=tmp,checked=str(p)),ledger_written=False,flow_written=False)
            commit.assert_called_once()

    def test_wrong_policy_is_rejected_without_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):R.record(tmp,{'hexiao_date':'2026-08-20'}, {})
            self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_parent_repeat_ignores_only_registration_clock_and_rejects_changed_amount(self):
        from test_allocation_contract import audit, plan
        import datetime as dt
        class Clock(dt.datetime):
            stamp=1
            @classmethod
            def now(cls):return cls(2026,9,29,10,0,cls.stamp)
        checked=plan(audit());checked['business_rules']={'reconciliation_policy':'current-workbook-v1'}
        with tempfile.TemporaryDirectory() as tmp,patch.object(F.dt,'datetime',Clock):
            path,_=R.record(tmp,checked,{'盈亏':True,'流转':True});before=path.read_bytes()
            self.assertIn('AR_TEST',json.loads(before)['json_ledgers'][F.LEDGER_NAME]['parents'])
            Clock.stamp=30
            same,_=R.record(tmp,checked,{'盈亏':True,'流转':True})
            self.assertEqual(path,same);self.assertEqual(path.read_bytes(),before)
            corrupt=json.loads(before);corrupt['json_ledgers'][F.LEDGER_NAME]['parents']['AR_TEST']['parent_amount']=31
            path.write_text(json.dumps(corrupt))
            with self.assertRaises(ValueError):R.record(tmp,checked,{'盈亏':True,'流转':True})
