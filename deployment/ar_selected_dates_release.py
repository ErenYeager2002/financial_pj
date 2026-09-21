"""Targeted managed release; all artifacts here are persistent release/rollback files."""
import sys,os,json,hashlib,subprocess,shutil,fcntl,re
from pathlib import Path
ROOT=Path('/home/lee/financial-platform-isolated')
SOURCE=ROOT/'refactor-worktrees/full-platform-20260918'
sys.path.insert(0,str(ROOT/'releases/rebuild-e95b527/source/deployment'))
from platform_adapter import PlatformAdapter,PROJECT
from maintenance_flow import Plan,DeploymentFailure
from ar_zero_sod_release import active_snapshots,verify_snapshot_files,require_no_running
BUILD=ROOT/'releases/ar-selected-dates-20260921-build-v5'
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
        runtime=a.command(['docker','exec',PROJECT+'-api-1','cat','/app/backend/app/workflow_service.py'])
        old='fetch_payload.update({"date_from": batch_dates[0], "date_to": batch_dates[-1]})'
        new='fetch_payload.update({"dates": list(batch_dates)})'
        assert runtime.count(old)==1
        assert (SOURCE/'deployment/overlays/ar-selected-dates/workflow_service.py').read_text().strip()==runtime.replace(old,new).strip(), 'Backend runtime changed since narrow overlay preparation'
        require_no_running(a)
        for service in ('worker-standard','worker-task-discovery'):
            actual=a.command(['docker','exec',PROJECT+'-'+service+'-1','sha256sum','/app/backend/app/worker.py']).split()[0]
            assert actual=='80f925a23d7b5f6ca4bb79224613492dc5062fe49123da33211b0413257c50f3', 'Worker shutdown changed since review'
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
            paths=[]
            for name,version in [('ar-hexiao-daily','1.6.28-local.28'),('ar-hexiao-daily-lab','1.6.24-lab.6.local.28')]:
                p=SOURCE/'skills'/name/'tool.yaml';text=p.read_text()
                assert re.search(r'^version: (.+)$',text,re.M).group(1) in {version,version.rsplit('.',1)[0]+'.27'}
                p.write_text(re.sub(r'^version: .*$', 'version: '+version,text,count=1,flags=re.M))
                for rel in ['tool.yaml','SKILL.md','vendor/config/业务规则.md','vendor/scripts/fetch_secure.py','vendor/scripts/test_selected_fetch_dates.py','vendor/scripts/test_fetch_session_reuse.py']:
                    n=Path('skills')/name/rel;target=BUILD/n;target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(SOURCE/n,target);paths.append(n.as_posix())
            n='deployment/overlays/ar-selected-dates/workflow_service.py'
            target=BUILD/n;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(SOURCE/n,target);paths.append(n)
            hashes={n:hashlib.sha256((SOURCE/n).read_bytes()).hexdigest() for n in paths}
            (BUILD/'source-hashes.json').write_text(json.dumps(hashes))
            (BUILD/'baseline.json').write_text(json.dumps({k:{'id':v['Id'],'image':v['Image']} for k,v in baseline.items()}))
            compose_before=(ROOT/'compose.yaml').read_bytes();env_before=(ROOT/'.env').read_bytes()
            (BUILD/'compose.before').write_bytes(compose_before);os.chmod(BUILD/'compose.before',0o600)
        base_tag='financial-platform-isolated-backend:ar-selected-dates-base-20260921'
        a.command(['docker','tag',base,base_tag])
        assert a.command(['docker','image','inspect','--format','{{.Id}}',base_tag])==base
        (BUILD/'Dockerfile').write_text('FROM '+base_tag+'\nCOPY skills/ /app/skills/\nCOPY deployment/overlays/ar-selected-dates/ /app/backend/app/\n')
        (BUILD/'.dockerignore').write_text('*\n!Dockerfile\n!skills/\n!skills/**\n!deployment/\n!deployment/**\n')
        tag='financial-platform-isolated-backend:ar-selected-dates-20260921'
        result=subprocess.run(['docker','build','--network','none','-t',tag,str(BUILD)],capture_output=True,text=True)
        if result.returncode:raise DeploymentFailure('Build failed: '+result.stderr[-2000:])
        image=a.command(['docker','image','inspect','--format','{{.Id}}',tag])
        verify="import hashlib,json,sys;from pathlib import Path;h=json.loads(sys.argv[1]);assert all(hashlib.sha256((Path('/app')/p.replace('deployment/overlays/ar-selected-dates/','backend/app/')).read_bytes()).hexdigest()==v for p,v in h.items());print('source_hashes_verified')"
        a.command(['docker','run','--rm','--read-only','--network','none','--entrypoint','python',image,'-c',verify,json.dumps(hashes)])
        for name in ['ar-hexiao-daily','ar-hexiao-daily-lab']:
            test=['docker','run','--rm','--read-only','--network','none','--tmpfs','/tmp:rw,size=256m','-e','PYTHONDONTWRITEBYTECODE=1','-w','/app/skills/'+name+'/vendor/scripts','--entrypoint','python',image,'-m','unittest','test_selected_fetch_dates','test_fetch_session_reuse','-q']
            result=subprocess.run(test,capture_output=True,text=True)
            print(name+' selected-date regression:',result.returncode,result.stderr,flush=True)
            if result.returncode:raise DeploymentFailure('Selected-date regression failed')
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
            a.set_mode('normal');a.verify_mode('normal');a.record('succeeded','ar-selected-dates-20260921')
            result={'status':'succeeded','image':image,'rollback':str(a.release),'source_hashes':hashes}
            (BUILD/'deployment-result.json').write_text(json.dumps(result));print(json.dumps(result),flush=True)
        except BaseException:
            if changed:
                shutil.copy2(a.release/'compose.yaml.before',ROOT/'compose.yaml');a.cutover(PLAN,None);a.wait_healthy(PLAN)
            elif drained:a.command(['docker','start',PROJECT+'-worker-standard-1',PROJECT+'-worker-task-discovery-1'])
            a.set_mode('normal');a.verify_mode('normal');a.record('rolled_back','ar-selected-dates-20260921');raise

main()
