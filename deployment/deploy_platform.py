#!/usr/bin/env python3
"""Managed deployment entry point. Without --apply it only performs read-only checks."""
import argparse, fcntl, json, sys
import subprocess
from pathlib import Path
from maintenance_flow import PLANS, DeploymentFailure, deploy, recover, recover_frontend, recover_schema
from platform_adapter import PlatformAdapter

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',choices=['schema-status','check','tool',*PLANS,'recover','recover-frontend','recover-schema'])
    parser.add_argument('--image',help='Already-built local image; never pulls or builds')
    parser.add_argument('--rollback-image', help='Exact verified local compatible rollback image; backend-schema only')
    parser.add_argument('--schema-expected-revision', help='Reviewed database revision; only for backend-schema')
    parser.add_argument('--schema-target-revision', help='Exact reviewed target; only for backend-schema')
    parser.add_argument('--agent-image', help='Exact local Agent digest for paired backend-schema release')
    parser.add_argument('--rollback-agent-image', help='Verified Agent digest compatible with rollback backend')
    parser.add_argument('--apply',action='store_true',help='Execute the selected fixed plan after guards pass')
    parser.add_argument('--skill-id',help='Target tool for the no-restart tool plan')
    parser.add_argument('--username',help='Platform administrator; password is read securely from the terminal')
    args=parser.parse_args()
    if args.plan in {'backend-schema', 'recover-schema'}:
        if not args.image or not args.schema_expected_revision or not args.schema_target_revision:
            parser.error('backend-schema requires image and both reviewed schema revisions')
    elif args.schema_expected_revision or args.schema_target_revision:
        parser.error('Schema revision arguments are only valid for backend-schema')
    if args.plan == 'backend-schema' and not args.rollback_image:
        parser.error('backend-schema requires --rollback-image')
    if args.rollback_image and args.plan not in {'backend-schema', 'recover-schema'}:
        parser.error('--rollback-image is only valid with schema release or recovery')
    if args.agent_image or args.rollback_agent_image:
        if args.plan not in {'backend-schema', 'recover-schema'}:
            parser.error('Agent image arguments require backend-schema or recover-schema')
        if not args.agent_image or not args.rollback_agent_image:
            parser.error('Supply both --agent-image and --rollback-agent-image')
    if args.plan=='tool':
        if not args.skill_id or args.image:
            parser.error('tool requires --skill-id and does not accept --image')
        command=[sys.executable,str(Path(__file__).resolve().parent/'deploy_tool.py'),args.skill_id]
        if args.apply: command.append('--apply')
        if args.username: command.extend(['--username',args.username])
        raise SystemExit(subprocess.run(command).returncode)
    if args.skill_id or args.username:
        parser.error('--skill-id and --username are only valid with the tool plan')
    if args.image and args.plan not in {'recover-frontend', 'recover-schema'} and (args.plan not in PLANS or not PLANS[args.plan].image_key):
        parser.error('This plan does not accept an image')
    if args.plan in {'check', 'schema-status'} and args.apply:parser.error('check is always read-only')
    adapter=PlatformAdapter()
    adapter.schema_rollback_image = args.rollback_image
    adapter.schema_agent_image = args.agent_image
    adapter.schema_rollback_agent_image = args.rollback_agent_image
    if args.plan in {'backend-schema', 'recover-schema'}:
        adapter.schema_revisions = (args.schema_expected_revision, args.schema_target_revision)
    if args.plan == 'schema-status':
        print(json.dumps(adapter.schema_status(), ensure_ascii=False))
        return
    if not args.apply:
        result={'mode':adapter.mode(),'task_counts':adapter.active_counts(),'read_only':True,'plan':args.plan}
        if args.plan == 'recover-schema':
            adapter.preflight_schema_recovery(args.image)
        if args.plan in PLANS:
            result['services']=PLANS[args.plan].services
            if adapter.schema_agent_image is not None:
                result['services'] = (*result['services'], 'worker-agent')
            adapter.preflight(PLANS[args.plan],args.image)
        print(json.dumps(result,ensure_ascii=False))
        return
    with (adapter.directory/'deployment.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise DeploymentFailure('Another managed deployment is active')
        if args.plan=='recover':recover(adapter)
        elif args.plan=='recover-schema':recover_schema(adapter,args.image)
        elif args.plan=='recover-frontend':recover_frontend(adapter,args.image)
        else:deploy(adapter,args.plan,args.image)

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:
        print('Deployment interrupted. Inspect maintenance state before continuing.',file=sys.stderr);sys.exit(130)
    except Exception as exc:
        print(str(exc) if isinstance(exc,DeploymentFailure) else 'Deployment failed; inspect service state and retained maintenance mode.',file=sys.stderr)
        sys.exit(1)
