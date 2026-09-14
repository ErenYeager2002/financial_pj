#!/usr/bin/env python3
"""Managed deployment entry point. Without --apply it only performs read-only checks."""
import argparse, fcntl, json, sys
import subprocess
from pathlib import Path
from maintenance_flow import PLANS, DeploymentFailure, deploy, recover, recover_frontend
from platform_adapter import PlatformAdapter

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',choices=['check','tool',*PLANS,'recover','recover-frontend'])
    parser.add_argument('--image',help='Already-built local image; never pulls or builds')
    parser.add_argument('--apply',action='store_true',help='Execute the selected fixed plan after guards pass')
    parser.add_argument('--skill-id',help='Target tool for the no-restart tool plan')
    parser.add_argument('--username',help='Platform administrator; password is read securely from the terminal')
    args=parser.parse_args()
    if args.plan=='tool':
        if not args.skill_id or args.image:
            parser.error('tool requires --skill-id and does not accept --image')
        command=[sys.executable,str(Path(__file__).resolve().parent/'deploy_tool.py'),args.skill_id]
        if args.apply: command.append('--apply')
        if args.username: command.extend(['--username',args.username])
        raise SystemExit(subprocess.run(command).returncode)
    if args.skill_id or args.username:
        parser.error('--skill-id and --username are only valid with the tool plan')
    if args.image and args.plan != 'recover-frontend' and (args.plan not in PLANS or not PLANS[args.plan].image_key):
        parser.error('This plan does not accept an image')
    if args.plan=='check' and args.apply:parser.error('check is always read-only')
    adapter=PlatformAdapter()
    if not args.apply:
        result={'mode':adapter.mode(),'task_counts':adapter.active_counts(),'read_only':True,'plan':args.plan}
        if args.plan in PLANS:
            result['services']=PLANS[args.plan].services
            adapter.preflight(PLANS[args.plan],args.image)
        print(json.dumps(result,ensure_ascii=False))
        return
    with (adapter.directory/'deployment.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise DeploymentFailure('Another managed deployment is active')
        if args.plan=='recover':recover(adapter)
        elif args.plan=='recover-frontend':recover_frontend(adapter,args.image)
        else:deploy(adapter,args.plan,args.image)

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:
        print('Deployment interrupted. Inspect maintenance state before continuing.',file=sys.stderr);sys.exit(130)
    except Exception as exc:
        print(str(exc) if isinstance(exc,DeploymentFailure) else 'Deployment failed; inspect service state and retained maintenance mode.',file=sys.stderr)
        sys.exit(1)
