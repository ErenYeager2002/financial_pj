"""Publish the two AR tools on read-only platform containers without global maintenance."""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid
from deploy_tool import ToolDeployment, HASH, tree
from maintenance_flow import DeploymentFailure, Plan
from platform_adapter import PlatformAdapter, PROJECT

ROOT = Path('/home/lee/financial-platform-isolated')
SOURCE = Path(__file__).resolve().parents[1]
SKILLS = ('ar-hexiao-daily-lab', 'ar-hexiao-daily')
PLAN = Plan(('api', 'worker-standard', 'worker-task-discovery'), 'normal', True)


class Adapter(PlatformAdapter):
    def healthy_sample(self):
        # The unchanged Agent may reconnect when the API is recreated.
        name = '/' + PROJECT + '-worker-agent-1'
        current = self.inspect()[name]
        previous = self.protected[name]
        if current['Id'] != previous[0] or current['Image'] != self.original_agent_image:
            raise DeploymentFailure('Agent identity changed during AR tool release')
        self.protected[name] = (current['Id'], current['State']['StartedAt'])
        return super().healthy_sample()


def reconnect(tool):
    if tool.control:
        tool.control.stdin.close()
        try:
            tool.control.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tool.control.kill()
            tool.control.wait()
    current = tool.inspect()
    tool.identities = dict(zip(tool.containers, [value['Id'] for value in current]))
    tool.baseline = [(value['Id'], value['State']['StartedAt']) for value in current]
    network = current[0]['NetworkSettings']['Networks'].get('financial-platform-isolated_edge') or {}
    if not network.get('IPAddress'):
        raise DeploymentFailure('Replacement API address unavailable')
    tool.base_url = 'http://' + network['IPAddress'] + ':8000'
    tool.start_control()


def run(args, *, timeout=600):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                            env={**os.environ, 'DOCKER_BUILDKIT': '0'})
    if result.returncode:
        raise DeploymentFailure('AR release command failed: ' + Path(args[0]).name)
    return result.stdout.strip()


def atomic_text(path, content):
    temporary = path.with_name(path.name + '.balance-' + uuid.uuid4().hex)
    with open(temporary, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def release():
    adapter = Adapter()
    with (ROOT / 'maintenance/deployment.lock').open('a') as deployment_lock:
        fcntl.flock(deployment_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_name = run(['docker', 'exec', PROJECT + '-api-1', 'python', '-c',
                         'from app.skill_release_service import _publish_lock_path; p=_publish_lock_path(); p.touch(exist_ok=True); print(p.name)'])
        if not re.fullmatch(r'\.skill-release\.publish(?:\.\d+)?\.lock', lock_name):
            raise DeploymentFailure('Skill release lock name invalid')
        with (ROOT / 'data' / lock_name).open('rb') as skill_lock:
            fcntl.flock(skill_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _release_locked(adapter)


def _release_locked(adapter):
    adapter.preflight(PLAN, None)
    baseline = adapter.inspect()
    adapter.original_agent_image = baseline['/' + PROJECT + '-worker-agent-1']['Image']
    old_image = baseline['/' + PROJECT + '-api-1']['Image']
    original_compose = (ROOT / 'compose.yaml').read_bytes()
    tools = [ToolDeployment(skill, '302789') for skill in SKILLS]
    for tool in tools:
        tool.preflight()
        print(json.dumps({'skill': tool.skill_id, 'version': tool.version,
                          'changed_files': len(tool.changed)}, ensure_ascii=False), flush=True)
    build = ROOT / 'releases' / ('ar-current-balance-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    build.mkdir(mode=0o700)
    try:
        for tool in tools:
            if tree(tool.content) != tool.new_tree:
                raise DeploymentFailure('AR source changed during preparation')
            shutil.copytree(tool.content, build / 'skills' / tool.skill_id,
                            ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache', '.ruff_cache'))
        atomic_text(build / 'Dockerfile', 'FROM ' + old_image + '\nCOPY --chown=10001:10001 skills/ /app/skills/\n')
        atomic_text(build / '.dockerignore', '*\n!Dockerfile\n!skills/\n!skills/**\n')
        image_tag = 'financial-platform-isolated-backend:ar-current-balance-' + uuid.uuid4().hex[:12]
        run(['docker', 'build', '--network', 'none', '--pull=false', '-t', image_tag, str(build)])
        image = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image_tag])
        for tool in tools:
            result = json.loads(run(['docker', 'run', '--rm', '--network', 'none', '--read-only',
                                     '--tmpfs', '/tmp', '--entrypoint', 'python', image,
                                     '-c', HASH, '/app/skills/' + tool.skill_id]))
            if result != tool.new_tree:
                raise DeploymentFailure('Built skill tree differs from reviewed source')
            tests = run(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--tmpfs', '/tmp',
                         '--entrypoint', 'python', '-e', 'PYTHONDONTWRITEBYTECODE=1',
                         '-w', '/app/skills/' + tool.skill_id + '/vendor/scripts', image,
                         '-m', 'unittest', 'test_flow_monthly', 'test_flow_source_receipts',
                         'test_flow_current_balance', 'test_flow_carry_legacy',
                         'test_flow_completion', 'test_flow_unique_weak', '-q'])
            print(json.dumps({'skill': tool.skill_id, 'image_tests': 'passed'}, ensure_ascii=False), flush=True)
        if (ROOT / 'compose.yaml').read_bytes() != original_compose:
            raise DeploymentFailure('Compose changed during image preparation')
        if any(adapter.inspect()[name]['Id'] != old['Id'] for name, old in baseline.items()):
            raise DeploymentFailure('Container changed during image preparation')
        adapter.backup()
        paused = []
        changed = False
        drained = False
        try:
            for tool in tools:
                tool.record_dir = adapter.release / (adapter.release.name + '-tool-' + tool.skill_id)
                tool.record_dir.mkdir(mode=0o700)
                tool.new_image = image
                tool.login()
                if tool.operation('status')['state'] != 'enabled':
                    raise DeploymentFailure('AR tool is already paused')
                tool.pause()
                paused.append(tool)
                tool.wait_idle()
            adapter.wait_idle()
            adapter.command(['docker', 'stop', '--timeout', '-1',
                             PROJECT + '-worker-standard-1', PROJECT + '-worker-task-discovery-1'], timeout=7200)
            drained = True
            if any(adapter.active_counts().values()):
                raise DeploymentFailure('A task appeared during AR release drain')
            if (ROOT / 'compose.yaml').read_bytes() != original_compose:
                raise DeploymentFailure('Compose changed during AR release drain')
            compose_text = original_compose.decode()
            for service in PLAN.services:
                pattern = r'(?ms)(^  ' + re.escape(service) + r':\n.*?^    image: )[^\n]+'
                compose_text, count = re.subn(pattern, lambda match: match.group(1) + image,
                                               compose_text, count=1)
                if count != 1:
                    raise DeploymentFailure('Target service image declaration missing')
            atomic_text(ROOT / 'compose.yaml', compose_text)
            changed = True
            adapter.cutover(PLAN, None)
            adapter.wait_healthy(PLAN)
            for service in PLAN.services:
                actual = adapter.command(['docker', 'inspect', '--format', '{{.Image}}',
                                          PROJECT + '-' + service + '-1'])
                if actual != image:
                    raise DeploymentFailure('Target service image mismatch')
            for tool in paused:
                reconnect(tool)
                if any(tool.runtime_hash(container) != tool.new_tree for container in tool.containers):
                    raise DeploymentFailure('Live skill files differ from published source')
                tool.reload()
                state = tool.api('/api/admin/skills/' + tool.skill_id + '/availability')
                if state.get('current_version') != tool.version or state.get('state') != 'disabled':
                    raise DeploymentFailure('Live skill version or paused state mismatch')
                tool.resume()
                tool.record('succeeded')
            adapter.verify_mode('normal')
            adapter.record('succeeded', 'ar-current-balance-scoped')
            (build / 'result.json').write_text(json.dumps({'status': 'succeeded', 'image': image,
                'rollback': str(adapter.release), 'versions': {tool.skill_id: tool.version for tool in tools}},
                ensure_ascii=False, indent=2))
            print(json.dumps({'status': 'succeeded', 'image': image,
                              'versions': {tool.skill_id: tool.version for tool in tools},
                              'global_maintenance': False}, ensure_ascii=False), flush=True)
        except BaseException:
            if changed:
                shutil.copy2(adapter.release / 'compose.yaml.before', ROOT / 'compose.yaml')
                adapter.cutover(PLAN, None)
                adapter.wait_healthy(PLAN)
            elif drained:
                adapter.command(['docker', 'start', PROJECT + '-worker-standard-1',
                                 PROJECT + '-worker-task-discovery-1'])
            for tool in paused:
                reconnect(tool)
                tool.resume()
                tool.record('restored')
            adapter.verify_mode('normal')
            raise
        finally:
            for tool in tools:
                tool.close()
    except BaseException:
        print('AR release did not complete; inspect retained release record and live services.', flush=True)
        raise


if __name__ == '__main__':
    release()
