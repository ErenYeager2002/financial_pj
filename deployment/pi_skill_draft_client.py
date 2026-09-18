import base64,fcntl,io,json,os,re,shutil,sys,zipfile
from uuid import uuid4
from pathlib import Path
from pi_business_client import query

def run(body):
    name=body.get('skill_id','')
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,71}',name):raise ValueError('Invalid Skill name')
    revisions=json.loads(os.environ.get('PI_SKILL_REVISIONS','{}'))
    if name not in revisions:raise ValueError('Skill is not mounted in this session')
    root=Path('/context/skill-drafts');root.mkdir(parents=True,exist_ok=True);target=root/name/revisions[name]
    if root.resolve()!=root or target.is_symlink():raise ValueError('Unsafe draft path')
    if body.get('action')=='prepare':
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.parent.resolve()!=target.parent:raise ValueError('Unsafe draft parent')
        with (target.parent/'.prepare.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if not target.exists():
                temporary=target.parent/('.prepare-'+uuid4().hex)
                try:
                    shutil.copytree(Path('/skills')/name,temporary,symlinks=False)
                    (temporary/'.pi-base.json').write_text(json.dumps({'base_commit':revisions[name]}))
                    os.replace(temporary,target)
                finally:
                    if temporary.exists():shutil.rmtree(temporary)
        return {'draft':str(target),'message':'可使用 read/edit/write/bash 修改和验证此草稿。完成后调用 propose，发布仍需用户确认。'}
    if body.get('action')!='propose':raise ValueError('Invalid action')
    base=json.loads((target/'.pi-base.json').read_text())['base_commit'];buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        count=0;total=0
        for p in sorted(target.rglob('*')):
            if p.is_symlink():raise ValueError('Draft must not contain symlinks')
            if not p.is_file() or p.name=='.pi-base.json' or '__pycache__' in p.parts or '.git' in p.parts:continue
            count+=1;total+=p.stat().st_size
            if count>2000 or total>200*1024*1024:raise ValueError('Draft too large')
            archive.write(p,p.relative_to(target).as_posix())
    raw=buffer.getvalue()
    if len(raw)>6*1024*1024:raise ValueError('Compressed draft exceeds 6 MiB')
    return query({'skill_id':name,'base_commit':base,'archive':base64.b64encode(raw).decode()},path='/platform/skill-proposal')

if __name__=='__main__':
    try:print(json.dumps(run(json.loads(sys.argv[1])),ensure_ascii=False))
    except Exception as exc:print(json.dumps({'error':str(exc)[:200]},ensure_ascii=False));sys.exit(1)
