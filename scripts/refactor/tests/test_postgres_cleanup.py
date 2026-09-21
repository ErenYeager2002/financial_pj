import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import postgres_baseline as pg

class PostgresCleanupTests(unittest.TestCase):
    def test_cleanup_requires_matching_identity(self):
        result=subprocess.CompletedProcess([],0,json.dumps({pg.LABEL:'someone-else'}),'')
        with patch.object(pg,'command',return_value=result) as call:
            with self.assertRaisesRegex(RuntimeError,'OWNERSHIP'): pg.cleanup('synthetic','ours')
            self.assertEqual(call.call_count,1)
    def test_start_timeout_still_checks_both_container_names(self):
        missing=subprocess.CompletedProcess([],1,'','Error: No such object')
        with patch.object(pg,'command',side_effect=[subprocess.TimeoutExpired('docker',60),missing,missing]) as call:
            with self.assertRaises(subprocess.TimeoutExpired):pg.main()
            inspections=[x.args[0] for x in call.call_args_list if x.args[0][1]=='inspect']
            self.assertEqual(len(inspections),2)
            self.assertTrue(inspections[0][2].startswith('financial-refactor-client-'))
            self.assertTrue(inspections[1][2].startswith('financial-refactor-pg-'))

    def test_missing_container_accepts_docker_message_case_variants(self):
        for message in ['Error: No such object: synthetic', 'error: no such object: synthetic', 'Error response from daemon: No such container: synthetic']:
            with self.subTest(message=message):
                result=subprocess.CompletedProcess([],1,'',message)
                with patch.object(pg,'command',return_value=result) as call:
                    pg.cleanup('synthetic','ours')
                    self.assertEqual(call.call_count,1)

    def test_daemon_failure_is_not_treated_as_absent_container(self):
        result=subprocess.CompletedProcess([],1,'','Cannot connect to the Docker daemon')
        with patch.object(pg,'command',return_value=result) as call:
            with self.assertRaisesRegex(RuntimeError,'INSPECTION_FAILED'):
                pg.cleanup('synthetic','ours')
            self.assertEqual(call.call_count,1)
