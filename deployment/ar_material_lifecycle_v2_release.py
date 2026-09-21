"""Targeted managed release; all artifacts here are persistent release/rollback files."""
import sys,os,json,hashlib,subprocess,shutil,fcntl,re
from pathlib import Path
ROOT=Path('/home/lee/financial-platform-isolated')
SOURCE=ROOT/'refactor-worktrees/full-platform-20260918'
sys.path.insert(0,str(ROOT/'releases/rebuild-e95b527/source/deployment'))
from platform_adapter import PlatformAdapter,PROJECT
from maintenance_flow import Plan,DeploymentFailure
from ar_zero_sod_release import active_snapshots,verify_snapshot_files,require_no_running
BUILD=ROOT/'releases/ar-material-lifecycle-v2-20260921-build'
PLAN=Plan(('api','worker-standard','worker-task-discovery'),'full',True)

class AllocationReleaseAdapter(PlatformAdapter):
    def healthy_sample(self):
        # The existing Node Agent exits when API polling fails during cutover.
        # Accept only its automatic restart, never a replaced container/image.
        name='/'+PROJECT+'-worker-agent-1'
        current=self.inspect()[name]
        expected=self.protected[name]
        if current['Id']!=expected[0]:
            raise DeploymentFailure('Agent container was replaced during deployment')
        self.protected[name]=(current['Id'],current['State']['StartedAt'])
        # Parent still checks health, all other protected services, and returns
        # restart counters; wait_healthy requires repeated stable samples.
        return super().healthy_sample()

def main():
    a=AllocationReleaseAdapter()
    with (a.directory/'deployment.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        a.preflight(PLAN,None)
        baseline=a.inspect()
        services=['api','worker-standard','worker-task-discovery']
        bases={baseline['/'+PROJECT+'-'+s+'-1']['Image'] for s in services}
        assert len(bases)==1, 'Runtime bases differ; prepare separate overlays'
        base=next(iter(bases))
        require_no_running(a)
        for service in ('worker-standard','worker-task-discovery'):
            actual=a.command(['docker','exec',PROJECT+'-'+service+'-1','sha256sum','/app/backend/app/worker.py']).split()[0]
            assert actual=='40c0e420bd382561544f0bf4a18227025daefc4bfec69c3c901f5d61b0fc9d52', 'Worker shutdown changed since review'
        if BUILD.exists():
            saved=json.loads((BUILD/'baseline.json').read_text())
            assert all(baseline[n]['Id']==v['id'] and baseline[n]['Image']==v['image'] for n,v in saved.items()), 'Runtime changed since interrupted build'
            hashes=json.loads((BUILD/'source-hashes.json').read_text())
            assert all(hashlib.sha256((SOURCE/n).read_bytes()).hexdigest()==h and hashlib.sha256((BUILD/n).read_bytes()).hexdigest()==h for n,h in hashes.items()), 'Prepared sources changed'
            compose_before=(BUILD/'compose.before').read_bytes()
            assert (ROOT/'compose.yaml').read_bytes()==compose_before, 'Configuration changed since build'
            env_before=(ROOT/'.env').read_bytes()
        else:
            BUILD.mkdir(mode=0o700)
            paths=['backend/app/ar_material_lifecycle.py', 'backend/app/ar_material_copies.py', 'backend/app/ar_publication.py', 'backend/app/ar_formal_ledger_service.py', 'backend/app/ar_material_history.py', 'backend/app/workflow_service.py', 'backend/app/workflow_material_service.py', 'backend/app/file_service.py', 'backend/app/main.py', 'backend/app/ar_material_candidates.py', 'backend/app/worker.py', 'backend/app/ar_staging_retention.py', 'backend/tests/test_ar_material_lifecycle.py', 'backend/tests/test_ar_material_candidates.py', 'backend/tests/test_workflow_material_sets.py']
            for n in paths:
                target=BUILD/n;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(SOURCE/n,target)
            hashes={n:hashlib.sha256((SOURCE/n).read_bytes()).hexdigest() for n in paths}
            (BUILD/'source-hashes.json').write_text(json.dumps(hashes))
            (BUILD/'baseline.json').write_text(json.dumps({k:{'id':v['Id'],'image':v['Image']} for k,v in baseline.items()}))
            compose_before=(ROOT/'compose.yaml').read_bytes();env_before=(ROOT/'.env').read_bytes()
            (BUILD/'compose.before').write_bytes(compose_before);os.chmod(BUILD/'compose.before',0o600)
        base_tag='financial-platform-isolated-backend:ar-material-lifecycle-base-20260921'
        a.command(['docker','tag',base,base_tag])
        assert a.command(['docker','image','inspect','--format','{{.Id}}',base_tag])==base
        (BUILD/'Dockerfile').write_text('FROM '+base_tag+'\nCOPY backend/ /app/backend/\n')
        (BUILD/'.dockerignore').write_text('*\n!Dockerfile\n!backend/\n!backend/**\n')
        tag='financial-platform-isolated-backend:ar-material-lifecycle-v2-20260921'
        result=subprocess.run(['docker','build','--network','none','-t',tag,str(BUILD)],capture_output=True,text=True)
        if result.returncode:raise DeploymentFailure('Build failed: '+result.stderr[-2000:])
        image=a.command(['docker','image','inspect','--format','{{.Id}}',tag])
        verify="import hashlib,json,sys;from pathlib import Path;h=json.loads(sys.argv[1]);assert all(hashlib.sha256((Path('/app')/p).read_bytes()).hexdigest()==v for p,v in h.items());print('source_hashes_verified')"
        a.command(['docker','run','--rm','--read-only','--network','none','--entrypoint','python',image,'-c',verify,json.dumps(hashes)])
        test=['docker','run','--rm','--read-only','--network','bridge','--tmpfs','/tmp:rw,size=768m','-e','PYTHONDONTWRITEBYTECODE=1','-e','PYTHONPATH=/app/backend','-v',str(SOURCE/'backend/tests')+':/app/backend/tests:ro','-w','/app/backend','--entrypoint','python',image,'-c',"import subprocess,sys;subprocess.run([sys.executable,'-m','pip','install','--disable-pip-version-check','--no-cache-dir','--target','/tmp/testdeps','pytest==8.3.5'],check=True,stdout=subprocess.DEVNULL);sys.path.insert(0,'/tmp/testdeps');import pytest;raise SystemExit(pytest.main(['tests/test_ar_material_lifecycle.py', 'tests/test_publication_current_evidence.py', 'tests/test_ar_material_candidates.py', 'tests/test_ar_material_rebinding.py', 'tests/test_workflow_material_sets.py', '-q', '-p', 'no:cacheprovider']))"]
        result=subprocess.run(test,capture_output=True,text=True,timeout=180)
        print('Built image tests:',result.returncode,result.stdout[-2000:],result.stderr[-600:],flush=True)
        if result.returncode:raise DeploymentFailure('Built image regression failed')
        current=a.inspect()
        assert all((current[n]['Id'],current[n]['Image'])==(v['Id'],v['Image']) for n,v in baseline.items()),'Concurrent runtime change'
        assert all(hashlib.sha256((SOURCE/n).read_bytes()).hexdigest()==h for n,h in hashes.items()),'Concurrent source change'
        assert (ROOT/'compose.yaml').read_bytes()==compose_before and (ROOT/'.env').read_bytes()==env_before,'Concurrent configuration change'
        snapshots=active_snapshots(a)
        a.backup();changed=False;drained=False
        try:
            a.set_mode('notice');a.grace();drained=True
            a.command(['docker','stop','--timeout','-1',PROJECT+'-worker-standard-1',PROJECT+'-worker-task-discovery-1'],timeout=7200)
            require_no_running(a);a.set_mode('full');a.verify_mode('full');require_no_running(a)
            assert (ROOT/'compose.yaml').read_bytes()==compose_before and (ROOT/'.env').read_bytes()==env_before,'Config changed before cutover'
            text=compose_before.decode()
            for service in services:
                pattern=r'(?ms)(^  '+re.escape(service)+r':\n.*?^    image: )([^\n]+)'
                match=re.search(pattern,text);assert match, 'Missing service image'
                assert match.group(2).strip()==baseline['/'+PROJECT+'-'+service+'-1']['Config']['Image'],'Service image changed'
                text=text[:match.start(2)]+image+text[match.end(2):]
            changed=True
            (ROOT/'compose.yaml').write_text(text)
            a.cutover(PLAN,None);a.wait_healthy(PLAN)
            for service in services:a.command(['docker','exec',PROJECT+'-'+service+'-1','python','-c',verify,json.dumps(hashes)])
            assert verify_snapshot_files(a,snapshots)==snapshots,'Pinned snapshots changed'
            a.set_mode('normal');a.verify_mode('normal');a.record('succeeded','ar-material-lifecycle-v2-20260921')
            result={'status':'succeeded','image':image,'rollback':str(a.release),'source_hashes':hashes}
            (BUILD/'deployment-result.json').write_text(json.dumps(result));print(json.dumps(result),flush=True)
        except BaseException:
            if changed:
                shutil.copy2(a.release/'compose.yaml.before',ROOT/'compose.yaml');a.cutover(PLAN,None);a.wait_healthy(PLAN)
            elif drained:a.command(['docker','start',PROJECT+'-worker-standard-1',PROJECT+'-worker-task-discovery-1'])
            a.set_mode('normal');a.verify_mode('normal');a.record('rolled_back','ar-material-lifecycle-v2-20260921');raise

main()
