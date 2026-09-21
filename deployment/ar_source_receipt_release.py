"""Source receipt tool release on read-only containers; no global maintenance."""
import sys,json,subprocess,hashlib,fcntl,re,shutil,os
from pathlib import Path
ROOT=Path('/home/lee/financial-platform-isolated')
SOURCE=ROOT/'refactor-worktrees/full-platform-20260918'
CANDIDATE=ROOT/'releases/ar-source-receipt-20260921/source'
sys.path.insert(0,str(CANDIDATE/'deployment'))
from deploy_tool import ToolDeployment,tree,command
sys.path.insert(0,str(ROOT/'releases/rebuild-e95b527/source/deployment'))
from platform_adapter import PlatformAdapter,PROJECT
from maintenance_flow import Plan,DeploymentFailure
from ar_zero_sod_release import active_snapshots,verify_snapshot_files,require_no_running
BUILD=ROOT/'releases/ar-source-receipt-20260921/readonly-release'
PLAN=Plan(('api','worker-standard','worker-task-discovery'),'normal',True)
class Adapter(PlatformAdapter):
 def healthy_sample(self):
  name='/'+PROJECT+'-worker-agent-1';current=self.inspect()[name];expected=self.protected[name]
  if current['Id']!=expected[0]:raise DeploymentFailure('Agent container replaced')
  self.protected[name]=(current['Id'],current['State']['StartedAt'])
  return super().healthy_sample()
def reconnect(tool):
 if tool.control:
  try:tool.control.stdin.close();tool.control.wait(timeout=5)
  except Exception:tool.control.kill();tool.control.wait()
 current=tool.inspect();tool.identities=dict(zip(tool.containers,[x['Id'] for x in current]))
 tool.baseline=[(x['Id'],x['State']['StartedAt']) for x in current]
 addresses=[v['IPAddress'] for k,v in current[0]['NetworkSettings']['Networks'].items() if k=='financial-platform-isolated_edge']
 tool.base_url='http://'+addresses[0]+':8000';tool.start_control()
def main():
 a=Adapter();paused=[];changed=False;drained=False
 with (ROOT/'maintenance/deployment.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  a.preflight(PLAN,None);baseline=a.inspect();compose=(ROOT/'compose.yaml').read_bytes()
  base=baseline['/'+PROJECT+'-api-1']['Image']
  tools=[ToolDeployment(name,'302789') for name in ('ar-hexiao-daily','ar-hexiao-daily-lab')]
  for tool in tools:print(tool.preflight(),flush=True)
  BUILD.mkdir(exist_ok=True)
  for tool in tools:
   dst=BUILD/'skills'/tool.skill_id
   if dst.exists():assert tree(dst)==tool.new_tree,'Candidate changed'
   else:shutil.copytree(tool.content,dst,ignore=shutil.ignore_patterns('__pycache__','.pytest_cache','.ruff_cache'))
  (BUILD/'Dockerfile').write_text('FROM '+base+'\nCOPY --chown=10001:10001 skills/ /app/skills/\n')
  (BUILD/'.dockerignore').write_text('*\n!Dockerfile\n!skills/\n!skills/**\n')
  r=subprocess.run(['docker','build','--network','none','-t','financial-platform-isolated-backend:source-receipt-20260921',str(BUILD)],capture_output=True,text=True,env={**os.environ,'DOCKER_BUILDKIT':'0'})
  if r.returncode:raise DeploymentFailure('Candidate build failed: '+r.stderr[-1000:])
  image=a.command(['docker','image','inspect','--format','{{.Id}}','financial-platform-isolated-backend:source-receipt-20260921'])
  hashes={str(p.relative_to(BUILD)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (BUILD/'skills').rglob('*') if p.is_file()}
  verify="import sys,json,hashlib;from pathlib import Path;h=json.loads(sys.argv[1]);assert all(hashlib.sha256((Path('/app')/p).read_bytes()).hexdigest()==v for p,v in h.items());print('verified')"
  for tool in tools:
   cmd=['docker','run','--rm','--network','none','--read-only','--tmpfs','/tmp','-e','PYTHONDONTWRITEBYTECODE=1','-w','/app/skills/'+tool.skill_id+'/vendor/scripts','--entrypoint','python',image,'-m','unittest','test_flow_source_receipts','test_flow_monthly','test_flow_order_prefill','test_flow_completion','test_flow_unique_weak','test_order_duplicate_gate','test_missing_order_priority','-q']
   result=subprocess.run(cmd,capture_output=True,text=True);print(tool.skill_id,result.returncode,result.stderr[-500:],flush=True)
   if result.returncode:raise DeploymentFailure('Candidate tests failed')
  assert (ROOT/'compose.yaml').read_bytes()==compose,'Concurrent configuration change'
  current=a.inspect();assert all(current[n]['Id']==v['Id'] for n,v in baseline.items()),'Concurrent service update'
  a.backup();snapshots=active_snapshots(a)
  try:
   for tool in tools:
    tool.record_dir=a.release/('tool-'+tool.skill_id);tool.record_dir.mkdir();tool.new_image=image
    tool.login();tool.pause();paused.append(tool);tool.wait_idle()
   # SIGTERM drain waits for running Python work; it does not cancel or retry it.
   a.command(['docker','stop','--timeout','-1',PROJECT+'-worker-standard-1',PROJECT+'-worker-task-discovery-1'],timeout=7200);drained=True
   require_no_running(a)
   assert (ROOT/'compose.yaml').read_bytes()==compose,'Concurrent configuration change'
   text=compose.decode()
   for service in PLAN.services:
    pattern=r'(?ms)(^  '+re.escape(service)+r':\n.*?^    image: )[^\n]+'
    text,n=re.subn(pattern,lambda m:m.group(1)+image,text,count=1);assert n==1
   changed=True;(ROOT/'compose.yaml').write_text(text)
   a.cutover(PLAN,None);a.wait_healthy(PLAN)
   for service in PLAN.services:a.command(['docker','exec',PROJECT+'-'+service+'-1','python','-c',verify,json.dumps(hashes)],timeout=60)
   assert verify_snapshot_files(a,snapshots)==snapshots,'Pinned task snapshot changed'
   for tool in paused:
    reconnect(tool);tool.reload()
    status=tool.api('/api/admin/skills/'+tool.skill_id+'/availability')
    assert status['current_version']==tool.version and status['state']=='disabled'
    tool.resume();tool.record('succeeded')
   a.verify_mode('normal');a.record('succeeded','ar-source-receipt-no-global-maintenance')
   result={'status':'succeeded','image':image,'rollback':str(a.release),'versions':{t.skill_id:t.version for t in tools},'global_maintenance':False,'hashes':hashes}
   (BUILD/'result.json').write_text(json.dumps(result));print(json.dumps({k:v for k,v in result.items() if k!='hashes'}),flush=True)
  except BaseException:
   if changed:
    shutil.copy2(a.release/'compose.yaml.before',ROOT/'compose.yaml');a.cutover(PLAN,None);a.wait_healthy(PLAN)
   elif drained:a.command(['docker','start',PROJECT+'-worker-standard-1',PROJECT+'-worker-task-discovery-1'])
   for tool in paused:
    reconnect(tool);tool.resume();tool.record('restored')
   a.verify_mode('normal');raise
  finally:
   for tool in tools:tool.close()
if __name__=='__main__':main()
