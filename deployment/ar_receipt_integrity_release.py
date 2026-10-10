"""Scoped lab receipt-integrity release, preserving the current backend image."""
import json
import os
import subprocess
import ar_current_balance_readonly_release as base
from ar_current_workbook_lab_release import ToolDeployment
from maintenance_flow import DeploymentFailure

TESTS = (
    'test_multi_sod_settlement_tail', 'test_inferred_source_conflict', 'test_merged_arrival',
    'test_flow_append_bottom.AppendBottom', 'test_flow_monthly', 'test_flow_completion',
    'test_flow_parent_net', 'test_flow_source_receipts', 'test_flow_current_balance',
    'test_flow_current_coverage', 'test_flow_carry_legacy', 'test_flow_blank_rebuild.BlankRebuild',
    'test_flow_name_map', 'test_flow_unique_weak', 'test_flow_order_prefill',
    'test_current_source_history', 'test_current_source_matching', 'test_writeoff_local_amounts',
    'test_settlement_boundary', 'test_split_baseline_preservation', 'test_source_history_gap',
    'test_current_preflight.CurrentPreflight', 'test_current_cli_inputs', 'test_allocation_contract',
)
_original_run = base.run
# Docker initializes these entries on every container creation. Compare their
# content, type, permissions and owner, but not the container creation timestamp.
DOCKER_CREATED_MTIME = frozenset({
    '.dockerenv', 'dev', 'dev/console', 'etc', 'etc/hostname', 'etc/hosts',
    'etc/mtab', 'etc/resolv.conf',
})



def filesystem_manifest(container):
    import hashlib
    import tarfile
    proc=subprocess.Popen(['docker','export',container],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    files={}
    with tarfile.open(fileobj=proc.stdout,mode='r|') as archive:
        for member in archive:
            digest=None
            if member.isfile():
                digest=hashlib.file_digest(archive.extractfile(member),'sha256').hexdigest()
            files[member.name]=(member.type.decode(),member.mode,member.uid,member.gid,
                                member.size,member.linkname,
                                None if member.name in DOCKER_CREATED_MTIME else float(member.mtime),
                                digest,member.pax_headers)
    if proc.wait(timeout=120):
        raise DeploymentFailure('Base filesystem verification failed')
    return files


def flatten_base(dockerfile):
    from pathlib import Path
    import uuid
    text=dockerfile.read_text()
    image=text.splitlines()[0].removeprefix('FROM ')
    info=json.loads(_original_run(['docker','image','inspect',image]))[0]
    if len(info['RootFS']['Layers'])<400:return
    config=info['Config']
    supported={'User','ExposedPorts','Env','Cmd','WorkingDir','ArgsEscaped'}
    if set(config)-supported or info['Os']!='linux':
        raise DeploymentFailure('Flattening requires explicit review of image configuration')
    changes=[]
    for key in ('User','WorkingDir'):
        if config.get(key):changes+=['--change',{'User':'USER','WorkingDir':'WORKDIR'}[key]+' '+config[key]]
    for value in config.get('Env') or []:
        name,setting=value.split('=',1)
        if not name.replace('_','').isalnum() or any(c in setting for c in '\r\n'):
            raise DeploymentFailure('Unsupported base environment value')
        changes+=['--change','ENV '+name+'='+json.dumps(setting)]
    if config.get('Cmd'):changes+=['--change','CMD '+json.dumps(config['Cmd'])]
    for port in config.get('ExposedPorts') or {}:changes+=['--change','EXPOSE '+port]
    cached=os.environ.get('AR_RELEASE_FLATTENED_BASE')
    tag=cached or 'financial-platform-isolated-backend:flattened-'+uuid.uuid4().hex[:12]
    original=_original_run(['docker','create',image]);imported=None
    try:
        expected=filesystem_manifest(original)
        # Reusing a candidate still requires the full config and filesystem
        # comparison below; a cached tag is never treated as proof by itself.
        if not cached:
            export=subprocess.Popen(['docker','export',original],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            result=subprocess.run(['docker','import',*changes,'-',tag],stdin=export.stdout,
                                  capture_output=True,text=True,timeout=180)
            export.stdout.close()
            if result.returncode or export.wait(timeout=120):
                raise DeploymentFailure('Flattened image creation failed')
        new=json.loads(_original_run(['docker','image','inspect',tag]))[0]
        # ArgsEscaped affects legacy Windows shell-form commands only. The Linux
        # command array and all actual execution settings must be identical.
        if ({k:v for k,v in new['Config'].items() if k!='ArgsEscaped'}
                !={k:v for k,v in config.items() if k!='ArgsEscaped'}):
            raise DeploymentFailure('Flattened image execution settings differ')
        imported=_original_run(['docker','create',tag])
        if filesystem_manifest(imported)!=expected:
            raise DeploymentFailure('Flattened image filesystem differs')
        dockerfile.write_text(text.replace('FROM '+image+'\n','FROM '+new['Id']+'\n',1))
        print(json.dumps({'base_flattened':True,'verified_files':len(expected),
                          'previous_layers':len(info['RootFS']['Layers']),
                          'new_layers':len(new['RootFS']['Layers'])}),flush=True)
    finally:
        for container in (original,imported):
            if container:_original_run(['docker','rm',container])


def run(args, *, timeout=600):
    if args[:2]==['docker','build']:
        from pathlib import Path
        flatten_base(Path(args[-1])/'Dockerfile')
    if '-m' in args and 'unittest' in args:
        index=args.index('unittest')
        args=args[:index+1]+list(TESTS)+['-q']
        result=subprocess.run(args,capture_output=True,text=True,timeout=timeout,
                              env={**os.environ,'DOCKER_BUILDKIT':'0'})
        if result.returncode:
            print(result.stderr[-8000:],flush=True)
            raise DeploymentFailure('Receipt-integrity image regression failed')
        print(json.dumps({'image_tests':'passed','summary':result.stderr.strip().splitlines()[-3:]},
                         ensure_ascii=False),flush=True)
        return result.stdout.strip()
    return _original_run(args,timeout=timeout)


if __name__=='__main__':
    base.SKILLS=('ar-hexiao-daily-lab',)
    base.ToolDeployment=ToolDeployment
    base.run=run
    base.release()
