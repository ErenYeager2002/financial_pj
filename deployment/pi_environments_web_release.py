"""Publish shared financial write-status labels over the verified current Next source."""
from pathlib import Path
import sys,json,hashlib,subprocess,fcntl,re,shutil
ROOT=Path('/home/lee/financial-platform-isolated')
SOURCE=ROOT/'refactor-worktrees/full-platform-20260918'
sys.path.insert(0,str(ROOT/'releases/rebuild-e95b527/source/deployment'))
from platform_adapter import PlatformAdapter,PROJECT
from maintenance_flow import Plan
from ar_zero_sod_release import require_no_running
PLAN=Plan(('next',),'notice',False)
TAG='financial-platform-isolated-next:refactor-pr03-pi-environments-20260921'
EXPECTED='sha256:22184f555b75549842468c1b524d8d0820ba3cff087b4b89a59108e9dc4bfcf8'
EDITED={'web/src/config/platform-navigation.ts','web/src/app/dashboard/pi/page.tsx','web/src/app/dashboard/ai-chat/page.tsx','web/src/features/pi-runtime/pi-chat.tsx','web/src/features/pi-runtime/session-environments.tsx'}
def main():
 a=PlatformAdapter()
 with (a.directory/'deployment.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  a.preflight(PLAN,None);baseline=a.inspect();require_no_running(a)
  assert baseline['/'+PROJECT+'-next-1']['Image']==EXPECTED,'Frontend baseline changed'
  original=json.loads(a.command(['docker','exec',PROJECT+'-next-1','cat','/app/financial-build.json']))
  diff={n for n,h in original['source_hashes'].items() if hashlib.sha256((SOURCE/n).read_bytes()).hexdigest()!=h}
  assert diff==EDITED-{'web/src/features/pi-runtime/session-environments.tsx'},diff
  sys.path.insert(0,str(SOURCE/'scripts/refactor'))
  import build_pr03_web as builder
  paths=[SOURCE/n for n in builder.FILES]
  for name in builder.DIRECTORIES:paths.extend(p for p in sorted((SOURCE/name).rglob('*')) if not p.is_dir())
  hashes={p.relative_to(SOURCE).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
  assert set(hashes)-set(original['source_hashes'])=={'web/src/features/pi-runtime/session-environments.tsx'},'Unreviewed additional build input'
  compose=(ROOT/'compose.yaml').read_bytes();env=(ROOT/'.env').read_bytes()
  a.backup()
  report=SOURCE/'docs/refactor/reports/PR-03-web-image.json'
  if report.exists():shutil.copy2(report,a.release/'frontend-build.before.json')
  subprocess.run([sys.executable,str(SOURCE/'scripts/refactor/build_pr03_web.py'),'--builder',original['builder_image'],'--runtime',original['runtime_image'],'--tag',TAG],check=True)
  built=json.loads(report.read_text());assert built['source_hashes']==hashes,'Build source changed'
  image=built['image_id']
  assert json.loads(a.command(['docker','run','--rm','--read-only','--network','none','--entrypoint','cat',image,'/app/financial-build.json']))['source_hashes']==hashes
  current=a.inspect()
  assert all((current[n]['Id'],current[n]['Image'])==(c['Id'],c['Image']) for n,c in baseline.items()),'Runtime changed during build'
  assert all(hashlib.sha256((SOURCE/n).read_bytes()).hexdigest()==h for n,h in hashes.items()),'Source changed during build'
  assert (ROOT/'compose.yaml').read_bytes()==compose and (ROOT/'.env').read_bytes()==env,'Config changed'
  changed=False
  try:
   a.set_mode('notice');a.grace();require_no_running(a)
   text=compose.decode();m=re.search(r'(?ms)(^  next:\n.*?^    image: )([^\n]+)',text);assert m
   assert m.group(2).strip()==baseline['/'+PROJECT+'-next-1']['Config']['Image']
   text=text[:m.start(2)]+image+text[m.end(2):]
   changed=True;(ROOT/'compose.yaml').write_text(text)
   a.cutover(PLAN,None);a.wait_healthy(PLAN)
   assert a.inspect()['/'+PROJECT+'-next-1']['Image']==image
   assert json.loads(a.command(['docker','exec',PROJECT+'-next-1','cat','/app/financial-build.json']))['source_hashes']==hashes
   a.set_mode('normal');a.verify_mode('normal');a.record('succeeded','pi-environments-20260921')
   result={'status':'succeeded','image':image,'rollback':str(a.release),'edited_hashes':{n:hashes[n] for n in EDITED}}
   (a.release/'pi-environments-result.json').write_text(json.dumps(result));print(json.dumps(result),flush=True)
  except BaseException:
   if changed:
    shutil.copy2(a.release/'compose.yaml.before',ROOT/'compose.yaml');a.cutover(PLAN,None);a.wait_healthy(PLAN)
   a.set_mode('normal');a.verify_mode('normal');a.record('rolled_back','pi-environments-20260921');raise
if __name__=='__main__':main()
