#!/usr/bin/env python3
"""Publish one tool without restarting services or entering global maintenance."""
from __future__ import annotations
import argparse
import ast
import fcntl
import getpass
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from scoped_tool_flow import ScopeError, publish

ROOT = Path('/home/lee/financial-platform-isolated')
SOURCE = Path(__file__).resolve().parents[1]
SERVICES = ('api', 'worker-standard', 'worker-task-discovery')
SAFE_ID = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}\Z')
IGNORE = {'__pycache__', '.pytest_cache', '.ruff_cache', '.git'}
DEPENDENCIES = {'requirements.txt', 'pyproject.toml', 'poetry.lock', 'uv.lock', 'package.json', 'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock'}


def command(args, *, data=None, timeout=60):
    environment={**os.environ,'DOCKER_BUILDKIT':'0'} if args[:2]==['docker','build'] else None
    result = subprocess.run(args, input=data, capture_output=True, timeout=timeout, env=environment)
    if result.returncode:
        # Tool output can contain business data or credentials; never echo it.
        raise ScopeError('部署子命令失败：' + Path(args[0]).name)
    return result.stdout


def tree(root):
    result = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if any(part in IGNORE for part in relative.parts):
            continue
        if path.is_symlink():
            raise ScopeError('工具包不允许符号链接')
        if path.is_file():
            result[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif not path.is_dir():
            raise ScopeError('工具包包含非普通文件')
    return result


def digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def atomic_write(path, content, mode=0o600):
    temporary = path.with_name(path.name + '.scoped-' + uuid.uuid4().hex)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


# Runs with no database access. The affected tool is disabled and the scheduler
# row is locked while all three containers receive the same tree. Unchanged
# probe dependencies are never replaced; existing reminder probes keep running.
SYNC = r'''
import hashlib,json,os,shutil,sys
from pathlib import Path
source,target=map(Path,sys.argv[1:])
assert source.is_dir() and target.is_dir() and not target.is_symlink()
assert target.parent==Path('/app/skills')
assert source.parent==Path('/app/skills') and source.name.startswith('.scoped-')
for path in source.rglob('*'):
    assert not path.is_symlink()
for path in target.rglob('*'):
    assert not path.is_symlink()
wanted={p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}
for path in list(target.rglob('*')):
    if path.is_file() and path.relative_to(target).as_posix() not in wanted:
        path.unlink()
for path in sorted(source.rglob('*')):
    if path.is_file():
        dest=target/path.relative_to(source)
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.is_file() and hashlib.sha256(dest.read_bytes()).digest()==hashlib.sha256(path.read_bytes()).digest():
            continue
        temporary=dest.with_name('.scoped-write-'+dest.name)
        shutil.copy2(path,temporary); os.replace(temporary,dest)
for path in sorted(target.rglob('*'),key=lambda p:len(p.parts),reverse=True):
    if path.is_dir() and not any(path.iterdir()): path.rmdir()
'''

HASH = r'''
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]); result={}
for p in sorted(root.rglob('*')):
    r=p.relative_to(root)
    if any(x in {'__pycache__','.pytest_cache','.ruff_cache','.git'} for x in r.parts): continue
    assert not p.is_symlink()
    if p.is_file(): result[r.as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
print(json.dumps(result,sort_keys=True))
'''

MANIFEST = r'''
import json,sys,yaml
from app.registry import SkillManifest,validate_declared_operational_profile
p=yaml.safe_load(sys.stdin.read());validate_declared_operational_profile(p)
m=SkillManifest.model_validate(p)
print(json.dumps(m.model_dump(mode='json'),sort_keys=True))
'''


class ToolDeployment:
    def __init__(self, skill_id, username=None, wait_seconds=1800):
        if not SAFE_ID.fullmatch(skill_id):
            raise ScopeError('无效工具编号')
        self.skill_id = skill_id
        self.username = username
        self.wait_seconds = wait_seconds
        self.content = SOURCE / 'skills' / skill_id
        if not self.content.is_dir() or self.content.is_symlink():
            raise ScopeError('持久化源码中没有该工具')
        self.containers = ['financial-platform-isolated-' + name + '-1' for name in SERVICES]
        self.record_dir = None
        self.control = None
        self.guarded = False
        self.switched = []
        self.persisted = False
        self.pause_owned = False
        self.stages = []
        self.generation = None
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def inspect(self):
        return json.loads(command(['docker', 'inspect', *self.containers]))

    def normal(self):
        if (ROOT / 'maintenance/current').resolve().name != 'normal':
            raise ScopeError('全站当前不在正常状态；单工具发布不会修改全站维护状态')

    def stable(self):
        self.normal()
        now = self.inspect()
        if [(x['Id'],x['State']['StartedAt']) for x in now] != self.baseline:
            raise ScopeError('服务已被其他发布替换，停止单工具发布')
        if not all(x['State']['Running'] for x in now):
            raise ScopeError('相关服务不健康')

    def api(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base_url + path, data=data, headers={'Content-Type':'application/json'})
        try:
            with self.http.open(request, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise ScopeError('平台接口拒绝操作，HTTP ' + str(exc.code)) from None

    def runtime_hash(self, container):
        return json.loads(command(['docker','exec',self.identities[container],'python','-c',HASH,'/app/skills/'+self.skill_id]))

    def manifest(self, data):
        return json.loads(command(['docker','exec','-i',self.identities[self.containers[0]],'python','-c',MANIFEST],data=data))

    def preflight(self):
        self.normal()
        if not SOURCE.is_relative_to(ROOT/'releases'):
            raise ScopeError('发布脚本不在持久化源码目录内')
        if (ROOT / 'DEPLOYMENT_ID').read_text().strip() != 'financial-platform-isolated-20260907-01a0799a':
            raise ScopeError('部署目录身份不匹配')
        current = self.inspect()
        self.baseline = [(x['Id'],x['State']['StartedAt']) for x in current]
        self.identities=dict(zip(self.containers,[x['Id'] for x in current]))
        images = {x['Image'] for x in current}
        if len(images) != 1 or not all(x['State']['Running'] for x in current):
            raise ScopeError('相关服务镜像不一致或未运行，需要先核实全局部署')
        self.old_image = images.pop()
        networks = current[0]['NetworkSettings']['Networks']
        addresses = [v['IPAddress'] for k,v in networks.items() if k == 'financial-platform-isolated_edge' and v.get('IPAddress')]
        if len(addresses) != 1:
            raise ScopeError('API 网络配置不符合当前部署入口')
        self.base_url = 'http://' + addresses[0] + ':8000'
        health = self.api('/api/health')
        if health.get('status') != 'ok' or health.get('registry_errors'):
            raise ScopeError('API 或工具注册表不健康')
        self.old_trees = {n:self.runtime_hash(n) for n in self.containers}
        if len({digest(x) for x in self.old_trees.values()}) != 1:
            raise ScopeError('工具运行副本不一致，拒绝覆盖已有差异')
        self.new_tree = tree(self.content)
        self.old_tree = self.old_trees[self.containers[0]]
        old_data = command(['docker','exec',self.identities[self.containers[0]],'cat','/app/skills/'+self.skill_id+'/tool.yaml'])
        old_manifest = self.manifest(old_data)
        new_manifest = self.manifest((self.content/'tool.yaml').read_bytes())
        if new_manifest['id'] != self.skill_id:
            raise ScopeError('工具编号与 manifest 不一致')
        self.version = new_manifest['version']
        old_version = old_manifest.pop('version'); new_manifest.pop('version')
        if old_manifest != new_manifest:
            raise ScopeError('工具执行契约发生变化，需单独评估公共服务更新，不适用本入口')
        changed = {p for p in self.old_tree.keys() | self.new_tree.keys() if self.old_tree.get(p)!=self.new_tree.get(p)}
        if any(Path(p).name in DEPENDENCIES or Path(p).name.startswith('requirements') and Path(p).suffix=='.txt' for p in changed):
            raise ScopeError('依赖发生变化，不能按脚本更新发布')
        if changed and self.version == old_version:
            raise ScopeError('工具内容已变化，请先在持久化源码中更新工具版本号')
        for file in self.content.rglob('*.py'):
            if not any(x in IGNORE for x in file.relative_to(self.content).parts):
                compile(file.read_bytes(),str(file),'exec')
        self.env_before = (ROOT/'.env').read_bytes()
        matches = re.findall(rb'^BACKEND_IMAGE=(.+)$',self.env_before,re.M)
        if len(matches)!=1:
            raise ScopeError('BACKEND_IMAGE 配置不唯一')
        configured = json.loads(command(['docker','image','inspect',matches[0].decode().strip()]))[0]['Id']
        # A previous no-restart release deliberately leaves Container.Image at
        # its original base. The persisted image is the base for the next layer.
        self.build_base = configured
        image_info=json.loads(command(['docker','image','inspect',configured]))[0]
        if image_info['Config']['User']!='10001:10001':
            raise ScopeError('镜像执行用户与当前部署规范不一致')
        persisted_tree=json.loads(command(['docker','run','--rm','--network','none','--entrypoint','python',configured,'-c',HASH,'/app/skills']))
        for container in self.containers:
            runtime_tree=json.loads(command(['docker','exec',self.identities[container],'python','-c',HASH,'/app/skills']))
            if runtime_tree != persisted_tree:
                raise ScopeError('运行工具与持久镜像不一致，先核实已有发布差异')
        if configured != self.old_image:
            records = sorted((ROOT/'releases').glob('tool-*/status.json'),key=lambda p:p.stat().st_mtime,reverse=True)
            matched = False
            for record in records:
                info=json.loads(record.read_text())
                if info.get('status')=='succeeded' and info.get('new_image')==configured and info.get('containers')==[list(x) for x in self.baseline]:
                    matched=True; break
            if not matched:
                raise ScopeError('启动镜像与运行镜像差异没有成功的单工具发布记录')
        self.validate_discovery_dependencies(changed)
        self.changed = sorted(changed)
        return {'scope':'tool','skill_id':self.skill_id,'version':self.version,'changed_files':len(changed),'global_maintenance':False,'restart_services':[],'read_only':True}

    def validate_discovery_dependencies(self, changed):
        # The current discovery worker only probes this built-in tool and does
        # not observe availability. Its code cannot be updated without a new
        # worker protocol. Keep its import closure unchanged in this entry point.
        if self.skill_id != 'ar-hexiao-daily':
            return
        scripts=self.content/'vendor/scripts'
        pending=[scripts/'fetch_zhiyun.py']
        protected=set()
        seen=set()
        while pending:
            path=pending.pop()
            if path in seen or not path.is_file(): continue
            seen.add(path)
            protected.add(path.relative_to(self.content).as_posix())
            syntax=ast.parse(path.read_bytes())
            for node in ast.walk(syntax):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in {'__import__','eval','exec'}:
                    raise ScopeError('任务检查依赖包含动态导入，需单独评估发布方式')
                names=[]
                if isinstance(node,ast.Import): names=[x.name for x in node.names]
                elif isinstance(node,ast.ImportFrom) and node.module: names=[node.module]
                for name in names:
                    if name.split('.')[0]=='importlib':
                        raise ScopeError('任务检查依赖使用动态导入，需单独评估发布方式')
                    parts=name.split('.')
                    for count in range(1,len(parts)+1):
                        relative=Path(*parts[:count])
                        for candidate in (scripts/relative.with_suffix('.py'),scripts/relative/'__init__.py'):
                            if candidate.is_file(): pending.append(candidate)
        protected.update(p for p in self.old_tree.keys() | self.new_tree.keys() if p.startswith('vendor/scripts/') and not p.endswith('.py'))
        if protected.intersection(changed):
            raise ScopeError('改动涉及共享任务检查 Worker 的依赖，当前无重启入口不发布这部分')

    def login(self):
        if not self.username:
            raise ScopeError('--apply 需要 --username，密码通过终端安全输入')
        password = getpass.getpass('平台管理员密码: ')
        user = self.api('/api/auth/login',{'username':self.username,'password':password})
        del password
        if user.get('role')!='skill_admin' or user.get('must_change_password'):
            raise ScopeError('需要已完成初始密码修改的管理员账号')
        # Obtain the cookie value from the local CookieJar without logging it.
        jars = [h.cookiejar for h in self.http.handlers if isinstance(h,urllib.request.HTTPCookieProcessor)]
        cookies = list(jars[0])
        if len(cookies)!=1:
            raise ScopeError('登录会话 cookie 不符合预期')
        self.token = cookies[0].value
        self.start_control()

    def start_control(self):
        script = (Path(__file__).parent/'tool_runtime_control.py').read_text()
        self.control = subprocess.Popen(['docker','exec','-i',self.identities[self.containers[0]],'python','-u','-c',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)

    def operation(self, operation):
        request={'token':self.token,'skill_id':self.skill_id,'operation':operation,'generation':self.generation,
                 'deployment_id':self.record_dir.name if self.record_dir else ''}
        for attempt in range(2):
            try:
                self.control.stdin.write(json.dumps(request)+'\n'); self.control.stdin.flush()
                with selectors.DefaultSelector() as ready:
                    ready.register(self.control.stdout,selectors.EVENT_READ)
                    if not ready.select(20): raise TimeoutError()
                line=self.control.stdout.readline()
                if not line: raise BrokenPipeError()
                response=json.loads(line)
                self.guarded=bool(response.get('guarded',False))
                if not response['ok']: raise ScopeError(response['error'])
                result=response['result']
                if 'generation' in result: self.generation=result['generation']
                return result
            except (BrokenPipeError,TimeoutError):
                lost_guard=self.guarded
                self.control.kill(); self.control.wait()
                self.guarded=False
                self.start_control()
                if attempt or lost_guard:
                    raise ScopeError('发布控制连接中断；请核对发布记录与工具状态') from None
        raise ScopeError('发布控制未返回结果')

    def prepare(self):
        if not self.changed:
            raise ScopeError('工具内容没有变化，不需要发布')
        self.login()
        initial=self.operation('status')
        if initial['state']!='enabled':
            raise ScopeError('工具已被其他操作暂停，请先处理原暂停原因')
        self.record_dir = ROOT/'releases'/('tool-'+self.skill_id+'-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
        self.record_dir.mkdir(mode=0o700)
        shutil.copytree(self.content,self.record_dir/'content',symlinks=True,ignore=shutil.ignore_patterns(*IGNORE))
        if tree(self.record_dir/'content')!=self.new_tree:
            raise ScopeError('准备期间工具源码发生变化')
        for index,container in enumerate(self.containers):
            command(['docker','cp',self.identities[container]+':/app/skills/'+self.skill_id,str(self.record_dir/('before-'+str(index)))])
            if tree(self.record_dir/('before-'+str(index)))!=self.old_tree:
                raise ScopeError('准备期间运行工具发生变化')
        atomic_write(self.record_dir/'env.before',self.env_before)
        self.new_image='financial-platform-isolated-backend:tool-'+uuid.uuid4().hex[:16]
        dockerfile=('FROM '+self.build_base+'\nUSER 0:0\nRUN rm -rf /app/skills/'+self.skill_id+'\nCOPY --chown=10001:10001 content/ /app/skills/'+self.skill_id+'/\nUSER 10001:10001\n')
        atomic_write(self.record_dir/'Dockerfile',dockerfile.encode())
        atomic_write(self.record_dir/'.dockerignore',b'*\n!Dockerfile\n!content/\n!content/**\n')
        command(['docker','build','--network=none','--pull=false','-t',self.new_image,str(self.record_dir)],timeout=600)
        self.new_image=json.loads(command(['docker','image','inspect',self.new_image]))[0]['Id']
        self.stage_name='.scoped-'+uuid.uuid4().hex
        for container in self.containers:
            self.stages.append((container,self.stage_name))
            command(['docker','cp',str(self.record_dir/'content'),self.identities[container]+':/app/skills/'+self.stage_name])
        self.stable()
        self.record('prepared')

    def pause(self):
        self.stable(); self.record('pause_requested'); self.pause_requested=True
        self.operation('pause'); self.pause_owned=True
        self.record('draining')

    def wait_idle(self):
        deadline=time.monotonic()+self.wait_seconds
        while time.monotonic()<deadline:
            self.stable()
            state=self.operation('status')
            if state['active_work_count']==0:
                self.operation('disable'); self.record('disabled'); return
            print(json.dumps({'skill_id':self.skill_id,'active_work_count':state['active_work_count'],'state':'draining'}),flush=True)
            time.sleep(5)
        raise ScopeError('等待工具任务完成超时；没有中断或重跑任务')

    def guard(self):
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            try:
                self.operation('guard'); self.guarded=True; return
            except ScopeError as exc:
                if '仍有任务' not in str(exc): raise
                time.sleep(2)
        raise ScopeError('目标工具仍有任务检查，暂不切换')

    def release_guard(self):
        if self.guarded:
            self.operation('release_guard'); self.guarded=False

    def synchronize(self, container, stage):
        command(['docker','exec','--user','0:0',self.identities[container],'python','-c',SYNC,'/app/skills/'+stage,'/app/skills/'+self.skill_id],timeout=30)

    def cutover(self):
        self.stable()
        if tree(self.content)!=self.new_tree:
            raise ScopeError('工具源码在构建后发生变化，停止切换')
        if any(self.runtime_hash(n)!=self.old_tree for n in self.containers):
            raise ScopeError('工具运行文件在构建后发生变化，停止切换')
        self.guard(); self.record('switching')
        for container in self.containers:
            self.switched.append(container)
            self.synchronize(container,self.stage_name)

    def reload(self):
        result=self.api('/api/admin/registry/reload',{})
        if result.get('errors'):
            raise ScopeError('刷新后工具注册表有错误')

    def verify(self):
        self.stable()
        if any(self.runtime_hash(n)!=self.new_tree for n in self.containers):
            raise ScopeError('运行文件哈希与发布内容不一致')
        self.reload()
        result=self.api('/api/admin/skills/'+self.skill_id+'/availability')
        if result.get('current_version')!=self.version or result.get('state')!='disabled':
            raise ScopeError('API 版本或暂停状态核验失败')
        self.record('verified')

    def persist(self):
        if (ROOT/'.env').read_bytes()!=self.env_before:
            raise ScopeError('启动配置已被其他操作修改')
        self.env_after=re.sub(rb'^BACKEND_IMAGE=.+$',b'BACKEND_IMAGE='+self.new_image.encode(),self.env_before,flags=re.M)
        self.persisted=True
        atomic_write(ROOT/'.env',self.env_after)
        self.record('persisted')

    def restore(self):
        self.stable()
        if self.switched:
            if not self.guarded: self.guard()
            for container in self.switched:
                index=self.containers.index(container)
                stage='.scoped-restore-'+uuid.uuid4().hex
                self.stages.append((container,stage))
                command(['docker','cp',str(self.record_dir/('before-'+str(index))),self.identities[container]+':/app/skills/'+stage])
                self.synchronize(container,stage)
                if self.runtime_hash(container)!=self.old_tree:
                    raise ScopeError('旧工具恢复哈希不匹配')
            self.reload()
        if self.persisted:
            current_env=(ROOT/'.env').read_bytes()
            if current_env==self.env_after:
                atomic_write(ROOT/'.env',self.env_before)
            elif current_env!=self.env_before:
                raise ScopeError('恢复时启动配置已被其他操作修改')
        self.release_guard()
        self.stable()

    def resume(self):
        self.release_guard(); self.operation('resume'); self.pause_owned=False

    def record(self,status):
        if self.record_dir:
            atomic_write(self.record_dir/'status.json',json.dumps({'scope':'tool','skill_id':self.skill_id,'status':status,'generation':self.generation,'old_image':self.old_image,'new_image':getattr(self,'new_image',None),'old_hash':digest(self.old_tree),'new_hash':digest(self.new_tree),'containers':self.baseline,'updated_at':time.time()},ensure_ascii=False,indent=2).encode())
        print(json.dumps({'scope':'tool','skill_id':self.skill_id,'status':status},ensure_ascii=False),flush=True)

    def close(self):
        for container,stage in self.stages:
            try:
                cleanup="import shutil,sys;from pathlib import Path;p=Path(sys.argv[1]);assert p.parent==Path('/app/skills') and p.name.startswith('.scoped-') and not p.is_symlink();shutil.rmtree(p)"
                command(['docker','exec','--user','0:0',self.identities[container],'python','-c',cleanup,'/app/skills/'+stage])
            except Exception:
                print('发布暂存目录清理未完成：'+self.identities[container]+':/app/skills/'+stage,file=sys.stderr)
        if self.control:
            self.control.stdin.close()
            try: self.control.wait(timeout=5)
            except subprocess.TimeoutExpired: self.control.kill(); self.control.wait()
        if hasattr(self,'token'):
            try: self.api('/api/auth/logout',{})
            except Exception: pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('skill_id')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--username')
    args=parser.parse_args()
    adapter=ToolDeployment(args.skill_id,args.username)
    if not args.apply:
        print(json.dumps(adapter.preflight(),ensure_ascii=False)); return
    with (ROOT/'maintenance/deployment.lock').open('a') as deployment_lock:
        try: fcntl.flock(deployment_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise ScopeError('已有平台或工具发布进行中')
        # Same lock used by existing API releases, opened by its owning API user.
        command(['docker','exec',adapter.containers[0],'python','-c','from app.skill_release_service import _publish_lock_path; p=_publish_lock_path();p.touch(exist_ok=True)'])
        lock_name=command(['docker','exec',adapter.containers[0],'python','-c','from app.skill_release_service import _publish_lock_path;print(_publish_lock_path().name)']).decode().strip()
        if not re.fullmatch(r'\.skill-release\.publish(?:\.\d+)?\.lock',lock_name): raise ScopeError('发布锁路径无效')
        with (ROOT/'data'/lock_name).open('rb') as publish_lock:
            try: fcntl.flock(publish_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise ScopeError('已有工具发布进行中')
            try: publish(adapter)
            finally: adapter.close()

if __name__=='__main__':
    try: main()
    except (ScopeError,KeyboardInterrupt) as exc:
        print(str(exc) or '发布已中断，请核对该工具的发布记录。',file=sys.stderr);sys.exit(1)
    except Exception:
        print('发布未完成，请核对单工具发布记录；没有主动切换全站维护状态。',file=sys.stderr);sys.exit(1)
