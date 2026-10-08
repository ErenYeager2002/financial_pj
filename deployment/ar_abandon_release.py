"""Publish the bounded unpublished-result disposition UI and API with rollback."""
from pathlib import Path
import fcntl, hashlib, json, os, re, shutil, subprocess, time, uuid
from platform_adapter import PlatformAdapter, PROJECT, ROOT
from maintenance_flow import Plan, DeploymentFailure
from deploy_tool import ToolDeployment
from ar_current_balance_readonly_release import Adapter, reconnect, atomic_text

SOURCE=Path(__file__).resolve().parents[1]
SERVICES=('api','worker-standard','worker-task-discovery','next')
PLAN=Plan(SERVICES,'normal',True)
BACKEND=['backend/app/'+name+'.py' for name in ('ar_abandon','main','ar_execution_safety','ar_execution_recovery','ar_business_investigation','ar_execution_runner','ar_material_lifecycle')]
BACKEND+=['backend/tests/test_ar_abandon.py']
WEB={'web/src/features/workflow-agent/components/workflow-execution-results.tsx','web/src/app/api/platform/workflows/[workflowId]/execution/abandon/route.ts'}

def run(args, timeout=600):
 p=subprocess.run(args,text=True,capture_output=True,timeout=timeout,env={**os.environ,'DOCKER_BUILDKIT':'0'})
 if p.returncode:raise DeploymentFailure('Release command failed: '+Path(args[0]).name+' '+p.stderr[-1500:])
 return p.stdout.strip()

def main():
 a=Adapter()
 with (ROOT/'maintenance/deployment.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  lock_name=run(['docker','exec',PROJECT+'-api-1','python','-c','from app.skill_release_service import _publish_lock_path; p=_publish_lock_path(); p.touch(exist_ok=True); print(p.name)'])
  if not re.fullmatch(r'\.skill-release\.publish(?:\.\d+)?\.lock',lock_name):raise DeploymentFailure('Invalid skill publish lock')
  skill_lock=(ROOT/'data'/lock_name).open('rb')
  fcntl.flock(skill_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  a.preflight(PLAN,None);baseline=a.inspect()
  a.original_agent_image=baseline['/'+PROJECT+'-worker-agent-1']['Image']
  if any(a.active_counts().values()):raise DeploymentFailure('Active work exists; wait before release')
  current_web=json.loads(run(['docker','exec',PROJECT+'-next-1','cat','/app/financial-build.json']))
  built_web=json.loads((SOURCE/'docs/refactor/reports/PR-03-web-image.json').read_text())
  changed={n for n in set(current_web['source_hashes'])|set(built_web['source_hashes']) if current_web['source_hashes'].get(n)!=built_web['source_hashes'].get(n)}
  if changed!=WEB:raise DeploymentFailure('Unexpected frontend build inputs: '+str(changed))
  if any(not (SOURCE/n).is_file() or hashlib.sha256((SOURCE/n).read_bytes()).hexdigest()!=h for n,h in built_web['source_hashes'].items()):raise DeploymentFailure('Frontend source changed after build')
  web_image=built_web['image_id']
  if json.loads(run(['docker','run','--rm','--read-only','--network','none','--entrypoint','cat',web_image,'/app/financial-build.json']))['source_hashes']!=built_web['source_hashes']:raise DeploymentFailure('Frontend image mismatch')
  images={baseline['/'+PROJECT+'-'+name+'-1']['Image'] for name in SERVICES if name!='next'}
  if len(images)!=1:raise DeploymentFailure('Backend runtime differs')
  build=ROOT/'releases'/('ar-abandon-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);build.mkdir(mode=0o700)
  old=ROOT/'releases/ar-abandon-20260924-source-before'
  for n in BACKEND:
   if (old/n).is_file():
    live=run(['docker','exec',PROJECT+'-api-1','sha256sum','/app/'+n]).split()[0]
    if live!=hashlib.sha256((old/n).read_bytes()).hexdigest():raise DeploymentFailure('Backend baseline changed: '+n)
   dest=build/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(SOURCE/n,dest)
  hashes={n:hashlib.sha256((build/n).read_bytes()).hexdigest() for n in BACKEND}
  (build/'source-hashes.json').write_text(json.dumps(hashes))
  (build/'Dockerfile').write_text('FROM '+images.pop()+'\nCOPY --chown=10001:10001 backend/ /app/backend/\n')
  (build/'.dockerignore').write_text('*\n!Dockerfile\n!backend/\n!backend/**\n')
  tag='financial-platform-isolated-backend:ar-abandon-'+uuid.uuid4().hex[:10]
  run(['docker','build','--network','none','--pull=false','-t',tag,str(build)])
  image=run(['docker','image','inspect','--format','{{.Id}}',tag])
  print(run(['docker','run','--rm','--read-only','--network','none','--tmpfs','/tmp:rw,size=768m','-e','PYTHONDONTWRITEBYTECODE=1','-e','FINANCIAL_ENV=test','-e','FINANCIAL_DATA_DIR=/tmp/ar-abandon-tests','-e','FINANCIAL_DATABASE_URL=sqlite:////tmp/ar-abandon-tests.db','-e','PYTHONPATH=/app/backend','--entrypoint','python',image,'/app/backend/tests/test_ar_abandon.py','-q']),flush=True)
  verify="import hashlib,json,sys;from pathlib import Path;h=json.loads(sys.argv[1]);assert all(hashlib.sha256((Path('/app')/n).read_bytes()).hexdigest()==v for n,v in h.items());print('source_hashes_verified')"
  run(['docker','run','--rm','--read-only','--network','none','--entrypoint','python',image,'-c',verify,json.dumps(hashes)])
  if any(hashlib.sha256((SOURCE/n).read_bytes()).hexdigest()!=h for n,h in hashes.items()):raise DeploymentFailure('Backend source changed during build')
  tools=[ToolDeployment(skill,'302789') for skill in ('ar-hexiao-daily-lab','ar-hexiao-daily')]
  for tool in tools:tool.preflight()
  if any(a.inspect()[name]['Id']!=value['Id'] for name,value in baseline.items()):raise DeploymentFailure('Concurrent release')
  original=(ROOT/'compose.yaml').read_bytes();a.backup();paused=[];changed=False;drained=False
  try:
   for tool in tools:
    tool.record_dir=a.release/('abandon-tool-'+tool.skill_id);tool.record_dir.mkdir(mode=0o700);tool.new_image=image
    tool.login()
    if tool.operation('status')['state']!='enabled':raise DeploymentFailure('Tool already paused')
    tool.pause();paused.append(tool);tool.wait_idle()
   a.wait_idle()
   a.command(['docker','stop','--timeout','-1',PROJECT+'-worker-standard-1',PROJECT+'-worker-task-discovery-1'],timeout=7200);drained=True
   if any(a.active_counts().values()):raise DeploymentFailure('New task started')
   if (ROOT/'compose.yaml').read_bytes()!=original:raise DeploymentFailure('Compose changed')
   content=original.decode()
   for service in SERVICES:
    content,count=re.subn(r'(?ms)(^  '+re.escape(service)+r':\n.*?^    image: )[^\n]+',lambda m:m.group(1)+(web_image if service=='next' else image),content,count=1)
    if count!=1:raise DeploymentFailure('Missing image declaration')
   atomic_text(ROOT/'compose.yaml',content);changed=True
   a.cutover(PLAN,None);a.wait_healthy(PLAN)
   for service in SERVICES:
    if a.inspect()['/'+PROJECT+'-'+service+'-1']['Image']!=(web_image if service=='next' else image):raise DeploymentFailure('Wrong runtime image')
    if service!='next':run(['docker','exec',PROJECT+'-'+service+'-1','python','-c',verify,json.dumps(hashes)])
   if json.loads(run(['docker','exec',PROJECT+'-next-1','cat','/app/financial-build.json']))['source_hashes']!=built_web['source_hashes']:raise DeploymentFailure('Wrong web runtime')
   for tool in paused:
    reconnect(tool)
    if any(tool.runtime_hash(c)!=tool.new_tree for c in tool.containers):raise DeploymentFailure('Tool package changed')
    tool.resume();tool.record('succeeded')
   a.verify_mode('normal');a.record('succeeded','ar-abandonment')
   result={'status':'succeeded','backend':image,'frontend':web_image,'rollback':str(a.release),'source_hashes':hashes}
   (build/'result.json').write_text(json.dumps(result));print(json.dumps(result),flush=True)
  except BaseException:
   if changed:
    shutil.copy2(a.release/'compose.yaml.before',ROOT/'compose.yaml');a.cutover(PLAN,None);a.wait_healthy(PLAN)
   elif drained:a.command(['docker','start',PROJECT+'-worker-standard-1',PROJECT+'-worker-task-discovery-1'])
   for tool in paused:reconnect(tool);tool.resume();tool.record('restored')
   a.verify_mode('normal');raise
  finally:
   for tool in tools:tool.close()

if __name__=='__main__':main()
