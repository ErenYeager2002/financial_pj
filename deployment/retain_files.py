#!/usr/bin/env python3
"""Online file-center retention. Default is a read-only plan, --apply retires files."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path('/home/lee/financial-platform-isolated')
SOURCE = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--install-guard', action='store_true', help='Install the online PostgreSQL reference guard')
    parser.add_argument('--details', action='store_true', help='Include file identities for a private review record')
    args = parser.parse_args()
    if not SOURCE.is_relative_to(ROOT / 'releases'):
        raise RuntimeError('Unexpected persistent source location')
    if (ROOT / 'DEPLOYMENT_ID').read_text().strip() != 'financial-platform-isolated-20260907-01a0799a':
        raise RuntimeError('Unexpected deployment identity')
    if (ROOT / 'maintenance/current').resolve().name != 'normal':
        print(json.dumps({'postponed': 'platform_deployment'})); return
    with (ROOT / 'maintenance/deployment.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'postponed': 'platform_deployment'})); return
        if (ROOT / 'maintenance/current').resolve().name != 'normal':
            print(json.dumps({'postponed': 'platform_deployment'})); return
        info = json.loads(subprocess.check_output(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'inspect', 'financial-platform-isolated-api-1'], stderr=subprocess.DEVNULL))[0]
        if not info['State']['Running'] or info['State'].get('Health', {}).get('Status') != 'healthy':
            print(json.dumps({'postponed': 'api_unhealthy'})); return
        bootstrap = """import hashlib,json,os,sys,types
os.nice(10)
module=types.ModuleType('app.file_retention')
module.__package__='app'
sys.modules[module.__name__]=module
source=sys.stdin.read()
exec(compile(source,'file_retention.py','exec'),module.__dict__)
result=module.cleanup(dry_run=DRY_RUN)
output=result if DETAILS else module.summary(result)
output['policy_sha256']=hashlib.sha256(source.encode()).hexdigest()
print(json.dumps(output,ensure_ascii=False))
""".replace('DRY_RUN', repr(not args.apply)).replace('DETAILS', repr(args.details))
        payload = (SOURCE / 'backend/app/file_retention.py').read_bytes()
        if args.install_guard:
            payload = (SOURCE / 'deployment/file_retention_guard.sql').read_bytes()
            bootstrap = "import sys,json; from app.database import engine; sql=sys.stdin.read(); conn=engine.connect(); tx=conn.begin(); conn.exec_driver_sql(sql); tx.commit(); conn.close(); print(json.dumps({'guard_installed':True}))"
        result = subprocess.run(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', 'exec', '-i', '-e', 'PYTHONDONTWRITEBYTECODE=1', info['Id'], 'python', '-c', bootstrap],
                                input=payload,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        if result.returncode:
            raise RuntimeError('File retention failed; originals are protected by transaction checks and deletion journal')
        print(result.stdout.decode().strip())

if __name__ == '__main__':
    try: main()
    except Exception:
        print('File retention did not finish; inspect retained records before retrying.', file=sys.stderr)
        sys.exit(1)
