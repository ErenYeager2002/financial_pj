import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from process_control import run_group

@unittest.skipUnless(sys.platform.startswith('linux'),'Linux process groups')
class ProcessControlTests(unittest.TestCase):
    def test_timeout_kills_term_ignoring_descendant(self):
        with tempfile.TemporaryDirectory(prefix='financial-refactor-process-') as temp:
            pidfile=Path(temp)/'pid'
            child="import os,signal,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path(os.environ['PIDFILE']).write_text(str(os.getpid())); time.sleep(60)"
            parent="import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); time.sleep(60)"
            with self.assertRaises(subprocess.TimeoutExpired):
                run_group([sys.executable,'-c',parent,child],env={**os.environ,'PIDFILE':str(pidfile)},timeout=1)
            pid=int(pidfile.read_text())
            for _ in range(30):
                stat=Path(f'/proc/{pid}/stat')
                if not stat.exists() or stat.read_text().split()[2]=='Z': break
                time.sleep(.01)
            else: self.fail('Descendant still running after timeout')
    def test_success_output_and_exit_preserved(self):
        result=run_group([sys.executable,'-c',"print('synthetic')"],timeout=2)
        self.assertEqual(result.returncode,0);self.assertEqual(result.stdout.strip(),'synthetic')
