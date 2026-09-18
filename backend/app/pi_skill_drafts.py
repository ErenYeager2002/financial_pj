"""Immutable candidate snapshots; publication requires web-authenticated admin approval."""
import base64,difflib,hashlib,io,json,os,shutil,zipfile
from datetime import datetime,timezone
from uuid import uuid4,UUID
from fastapi import HTTPException
from .settings import settings
from .pi_runtime_service import owner_scope
from .pi_model_access import atomic_json
from . import native_skill_service as native
from .skill_install_service import _package_files
from .native_skill_policy import require_native_skill
from .audit_service import record_audit

def root(user):return settings.data_dir/'pi-skill-proposals'/owner_scope(user)
def locate(user,identity):
    try:identity=str(UUID(identity))
    except ValueError:raise HTTPException(404,'发布草稿不存在。') from None
    own=root(user)/identity
    if (own/'proposal.json').is_file():return own
    if user.is_admin:
        for p in (settings.data_dir/'pi-skill-proposals').glob('*/'+identity+'/proposal.json'):
            value=json.loads(p.read_text())
            if value.get('department_id')==user.department_id:return p.parent
    raise HTTPException(404,'发布草稿不存在。')
def get(user,identity):return json.loads((locate(user,identity)/'proposal.json').read_text())
def visible(user):
    paths=(settings.data_dir/'pi-skill-proposals').glob('*/*/proposal.json') if user.is_admin else root(user).glob('*/proposal.json')
    values=[json.loads(p.read_text()) for p in paths]
    return [{k:v for k,v in item.items() if k not in {'owner','department_id'}} for item in values if item.get('owner')==owner_scope(user) or (user.is_admin and item.get('department_id')==user.department_id)]

def propose(db,user,session_id,skill_id,base_commit,archive):
    require_native_skill(db,user,skill_id)
    current=native.installed_skill(skill_id)
    if current.commit!=base_commit:raise HTTPException(409,'Skill 已更新，请以当前版本重新准备草稿。')
    try:
        raw=base64.b64decode(archive,validate=True)
        if len(raw)>6*1024*1024:raise ValueError('发布压缩包超过 6 MiB')
        files=_package_files(raw)
        title,description,_=native.parse_instructions(files.get('SKILL.md',b''),skill_id)
        for name,content in files.items():
            if name.endswith('.py'):compile(content,name,'exec')
    except Exception as exc:raise HTTPException(422,'草稿结构或 Python 语法检查失败：'+str(exc)[:160]) from None
    baseline=native.native_root()/'packages'/skill_id/current.commit
    with zipfile.ZipFile(io.BytesIO(raw)) as zipped:
        executable={i.filename for i in zipped.infolist() if (i.external_attr>>16)&0o111}
    changes=[]
    for name in sorted(set(files)|{p.relative_to(baseline).as_posix() for p in baseline.rglob('*') if p.is_file()}):
        old=(baseline/name).read_bytes() if (baseline/name).is_file() else None;new=files.get(name)
        old_exec=bool((baseline/name).stat().st_mode&0o111) if old is not None else False
        new_exec=name in executable
        if old==new and old_exec==new_exec:continue
        try:diff=''.join(difflib.unified_diff((old or b'').decode().splitlines(True),(new or b'').decode().splitlines(True),fromfile='before/'+name,tofile='after/'+name))
        except UnicodeError:diff='二进制文件变更'
        if old_exec!=new_exec:diff=f'Executable permission: {old_exec} -> {new_exec}\n'+diff
        changes.append({'path':name,'change':'added' if old is None else 'deleted' if new is None else 'modified','diff':diff[:20000],'truncated':len(diff)>20000})
    if not changes:raise HTTPException(409,'草稿与当前版本一致。')
    digest=hashlib.sha256(raw).hexdigest();identity=str(uuid4());directory=root(user)/identity;directory.mkdir(parents=True,mode=0o700)
    (directory/'package.zip').write_bytes(raw)
    value={'id':identity,'owner':owner_scope(user),'department_id':user.department_id,'skill_id':skill_id,'session_id':session_id,'base_commit':base_commit,'sha256':digest,'state':'pending','created_at':datetime.now(timezone.utc).isoformat(),'changes':changes,'validation':'SKILL.md 结构和 Python 语法已检查；业务结果未自动验收'}
    atomic_json(directory/'proposal.json',value)
    record_audit(db,actor=user,action='pi.skill.propose',resource_type='native_skill',resource_id=skill_id,details={'candidate':identity,'sha256':digest});db.commit()
    return {'candidate_id':identity,'state':'pending','message':'已生成不可变发布草稿，请用户在会话的发布确认面板审核并确认。'}

def publish(db,user,identity,expected):
    from .auth import require_admin
    require_admin(user)
    with native.source._source_guard():
        value=get(user,identity)
        if value['sha256']!=expected:raise HTTPException(409,'待确认版本不匹配。')
        if value['state']=='published':return value
        require_native_skill(db,user,value['skill_id'])
        current=native.installed_skill(value['skill_id'])
        directory=locate(user,identity)
        raw=(directory/'package.zip').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:raise HTTPException(409,'发布草稿完整性检查失败。')
        files=_package_files(raw);title,description,_=native.parse_instructions(files['SKILL.md'],value['skill_id'])
        # Content revision, not a claimed Git commit. Existing native snapshots use a 40-hex key.
        revision=hashlib.sha256(b'pi-draft-v1\0'+raw).hexdigest()[:40]
        if current.commit not in {value['base_commit'],revision}:raise HTTPException(409,'线上 Skill 已更新，请重新准备草稿。')
        package=native.native_root()/'packages'/value['skill_id']/revision
        if not package.exists():
            stage=package.parent/('.draft-'+uuid4().hex);stage.mkdir(parents=True)
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:executable={i.filename for i in archive.infolist() if (i.external_attr>>16)&0o111}
                for name,content in files.items():
                    p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content);p.chmod(0o755 if name in executable else 0o644)
                os.replace(stage,package)
            finally:
                if stage.exists():shutil.rmtree(stage)
        updated=current.model_copy(update={'commit':revision,'name':title,'description':description,'source_path':'pi-draft/'+identity,'installed_at':datetime.now(timezone.utc).isoformat()})
        atomic_json(native.native_root()/'installed'/(current.id+'.json'),updated.model_dump())
        value.update(state='published',revision=revision);atomic_json(directory/'proposal.json',value)
        record_audit(db,actor=user,action='pi.skill.publish',resource_type='native_skill',resource_id=current.id,details={'candidate':identity,'revision':revision,'sha256':expected});db.commit();return value
