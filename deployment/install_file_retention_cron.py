#!/usr/bin/env python3
"""Install only this platform's file-retention cron entry, preserving other jobs."""
from pathlib import Path
import os
import subprocess
ROOT=Path('/home/lee/financial-platform-isolated')
MARKER='# financial-platform-file-retention-v1'
JOB='* * * * * /usr/bin/python3 /home/lee/financial-platform-isolated/deployment/retain_files.py --apply 2>&1 | /usr/bin/logger -t financial-platform-file-retention'

def main():
    if os.getuid()!=1000 or (ROOT/'DEPLOYMENT_ID').read_text().strip()!='financial-platform-isolated-20260907-01a0799a':
        raise RuntimeError('Unexpected deployment user or root')
    result=subprocess.run(['crontab','-l'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if result.returncode not in (0,1):raise RuntimeError('Cannot read existing crontab')
    previous=result.stdout.decode()
    if MARKER in previous:
        if MARKER+'\n'+JOB in previous:return
        raise RuntimeError('Existing retention entry differs; review before changing')
    backup=ROOT/'releases/file-retention-20260910/crontab.before'
    fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as out:out.write(previous)
    updated=previous.rstrip('\n')+'\n'+MARKER+'\n'+JOB+'\n'
    subprocess.run(['crontab','-'],input=updated.encode(),check=True)
    actual=subprocess.check_output(['crontab','-l']).decode()
    if actual!=updated:raise RuntimeError('Crontab readback mismatch')
    print('Retention cron installed; existing jobs preserved')

if __name__=='__main__':main()
