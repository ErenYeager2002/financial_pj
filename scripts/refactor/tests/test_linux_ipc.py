"""Linux capability checks, not proof of application fencing or authorization."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux required for deployment IPC baseline')
class LinuxIPCTests(unittest.TestCase):
    def test_advisory_file_lock_excludes_other_process_and_releases(self):
        import fcntl
        with tempfile.TemporaryDirectory(prefix='financial-refactor-lock-') as temp:
            target = Path(temp)/'synthetic.lock'
            probe = "import fcntl,sys; f=open(sys.argv[1],'a'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)"
            with target.open('a') as held:
                fcntl.flock(held, fcntl.LOCK_EX|fcntl.LOCK_NB)
                denied = subprocess.run([sys.executable,'-B','-c',probe,str(target)],capture_output=True,text=True,timeout=5)
                self.assertNotEqual(denied.returncode,0)
                self.assertIn('BlockingIOError',denied.stderr)
            allowed = subprocess.run([sys.executable,'-B','-c',probe,str(target)],capture_output=True,text=True,timeout=5)
            self.assertEqual(allowed.returncode,0,allowed.stderr)

    def test_private_unix_socket_cross_process_request_response(self):
        with tempfile.TemporaryDirectory(prefix='financial-refactor-uds-') as temp:
            os.chmod(temp,0o700)
            target = str(Path(temp)/'test.sock')
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
                server.settimeout(5)
                server.bind(target)
                os.chmod(target,0o600)
                server.listen(1)
                child = subprocess.Popen([sys.executable,'-B','-c',"import socket,sys; s=socket.socket(socket.AF_UNIX); s.settimeout(5); s.connect(sys.argv[1]); s.sendall(b'synthetic-request'); assert s.recv(32)==b'synthetic-response'",target],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    connection,_ = server.accept()
                    with connection:
                        connection.settimeout(5)
                        self.assertEqual(connection.recv(32),b'synthetic-request')
                        connection.sendall(b'synthetic-response')
                    _,error=child.communicate(timeout=5)
                    self.assertEqual(child.returncode,0,error)
                    self.assertEqual(Path(target).stat().st_mode & 0o777,0o600)
                finally:
                    if child.poll() is None:
                        child.kill(); child.communicate()

if __name__=='__main__': unittest.main()
