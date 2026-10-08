"""Publish both AR tool packages on read-only containers without global maintenance."""
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from deploy_tool import ToolDeployment, digest, tree, HASH
from maintenance_flow import DeploymentFailure, Plan
from platform_adapter import PlatformAdapter, PROJECT, ROOT

PLAN = Plan(('api', 'worker-standard', 'worker-task-discovery'), 'normal', True)
SOURCE = Path(__file__).resolve().parents[1]
TOOLS = ('ar-hexiao-daily', 'ar-hexiao-daily-lab')


class Adapter(PlatformAdapter):
    def healthy_sample(self):
        # The agent container is outside this release and must keep its identity.
        return super().healthy_sample()


def reconnect(tool):
    if tool.control:
        try:
            tool.control.stdin.close()
            tool.control.wait(timeout=5)
        except Exception:
            tool.control.kill()
            tool.control.wait()
    current = tool.inspect()
    tool.identities = dict(zip(tool.containers, [value['Id'] for value in current]))
    tool.baseline = [(value['Id'], value['State']['StartedAt']) for value in current]
    addresses = [value['IPAddress'] for name, value in current[0]['NetworkSettings']['Networks'].items()
                 if name == 'financial-platform-isolated_edge' and value.get('IPAddress')]
    if len(addresses) != 1:
        raise DeploymentFailure('API network address changed unexpectedly')
    tool.base_url = 'http://' + addresses[0] + ':8000'
    tool.start_control()


def run():
    adapter = Adapter()
    tools = [ToolDeployment(name, '302789') for name in TOOLS]
    paused = []
    switched = False
    stopped = False
    with (ROOT / 'maintenance/deployment.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        adapter.preflight(PLAN, None)
        baseline = adapter.inspect()
        compose_before = (ROOT / 'compose.yaml').read_bytes()
        for tool in tools:
            print(tool.preflight(), flush=True)
        if any(adapter.active_counts().values()):
            raise DeploymentFailure('Active work exists; defer tool cutover')
        adapter.backup()
        release = adapter.release
        content = release / 'tool-content'
        content.mkdir()
        for tool in tools:
            shutil.copytree(tool.content, content / tool.skill_id,
                            ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache', '.ruff_cache'))
            if tree(content / tool.skill_id) != tool.new_tree:
                raise DeploymentFailure('Source changed during release preparation')
        dockerfile = 'FROM ' + baseline['/' + PROJECT + '-api-1']['Image'] + '\n'
        dockerfile += 'USER 0:0\nRUN rm -rf ' + ' '.join('/app/skills/' + name for name in TOOLS) + '\n'
        dockerfile += 'COPY --chown=10001:10001 tool-content/ /app/skills/\nUSER 10001:10001\n'
        (release / 'Dockerfile').write_text(dockerfile)
        (release / '.dockerignore').write_text('*\n!Dockerfile\n!tool-content/\n!tool-content/**\n')
        image_tag = 'financial-platform-isolated-backend:ar-confirmed-flow-20260924'
        build = subprocess.run(['docker', 'build', '--network=none', '--pull=false', '-t', image_tag, str(release)],
                               capture_output=True, text=True, timeout=600,
                               env={**os.environ, 'DOCKER_BUILDKIT': '0'})
        if build.returncode:
            raise DeploymentFailure('Candidate image build failed: ' + build.stderr[-1000:])
        image = adapter.command(['docker', 'image', 'inspect', '--format', '{{.Id}}', image_tag])
        for tool in tools:
            actual = json.loads(adapter.command(['docker', 'run', '--rm', '--network=none', '--read-only',
                                                 '--tmpfs', '/tmp', '--entrypoint', 'python', image,
                                                 '-c', HASH, '/app/skills/' + tool.skill_id], timeout=90))
            if digest(actual) != digest(tool.new_tree) or actual != tool.new_tree:
                raise DeploymentFailure('Candidate package hash mismatch: ' + tool.skill_id)
            tested = subprocess.run(['docker', 'run', '--rm', '--network=none', '--read-only', '--tmpfs', '/tmp',
                                     '-e', 'PYTHONDONTWRITEBYTECODE=1', '-w', '/app/skills/' + tool.skill_id + '/vendor/scripts',
                                     '--entrypoint', 'python', image, '-m', 'unittest',
                                     'test_flow_confirmed_cases', 'test_flow_monthly', 'test_flow_source_receipts',
                                     'test_flow_name_map', '-q'], capture_output=True, text=True, timeout=120)
            print(json.dumps({'tool': tool.skill_id, 'candidate_tests_ok': tested.returncode == 0}), flush=True)
            if tested.returncode:
                raise DeploymentFailure('Candidate tests failed: ' + tool.skill_id + ' ' + tested.stderr[-500:])
        if (ROOT / 'compose.yaml').read_bytes() != compose_before:
            raise DeploymentFailure('Compose configuration changed concurrently')
        current = adapter.inspect()
        if any(current[name]['Id'] != value['Id'] for name, value in baseline.items()):
            raise DeploymentFailure('Container changed concurrently')
        try:
            for tool in tools:
                tool.record_dir = release / (release.name + '-tool-' + tool.skill_id)
                tool.record_dir.mkdir()
                tool.new_image = image
                tool.login()
                if tool.operation('status')['state'] != 'enabled':
                    raise DeploymentFailure('Tool is already paused: ' + tool.skill_id)
                tool.pause()
                paused.append(tool)
                tool.wait_idle()
            adapter.command(['docker', 'stop', '--timeout', '-1',
                             PROJECT + '-worker-standard-1', PROJECT + '-worker-task-discovery-1'], timeout=7200)
            stopped = True
            if any(adapter.active_counts().values()):
                raise DeploymentFailure('Active work appeared during drain')
            compose = compose_before.decode()
            for service in PLAN.services:
                pattern = r'(?ms)(^  ' + re.escape(service) + r':\n.*?^    image: )[^\n]+'
                compose, count = re.subn(pattern, lambda match: match.group(1) + image, compose, count=1)
                if count != 1:
                    raise DeploymentFailure('Image declaration missing: ' + service)
            (ROOT / 'compose.yaml').write_text(compose)
            switched = True
            adapter.cutover(PLAN, None)
            adapter.wait_healthy(PLAN)
            for tool in tools:
                for container in tool.containers:
                    actual = json.loads(adapter.command(['docker', 'exec', container, 'python', '-c',
                                                         HASH, '/app/skills/' + tool.skill_id], timeout=90))
                    if actual != tool.new_tree:
                        raise DeploymentFailure('Runtime package hash mismatch: ' + container + '/' + tool.skill_id)
            for tool in paused:
                reconnect(tool)
                tool.reload()
                availability = tool.api('/api/admin/skills/' + tool.skill_id + '/availability')
                if availability.get('current_version') != tool.version or availability.get('state') != 'disabled':
                    raise DeploymentFailure('Published version unavailable: ' + tool.skill_id)
                tool.resume()
                tool.record('succeeded')
            adapter.verify_mode('normal')
            adapter.record('succeeded', 'ar-confirmed-flow-no-global-maintenance')
            print(json.dumps({'status': 'succeeded', 'image': image, 'rollback': str(release),
                              'versions': {tool.skill_id: tool.version for tool in tools},
                              'global_maintenance': False}), flush=True)
        except BaseException:
            if switched:
                shutil.copy2(release / 'compose.yaml.before', ROOT / 'compose.yaml')
                adapter.cutover(PLAN, None)
                adapter.wait_healthy(PLAN)
            elif stopped:
                adapter.command(['docker', 'start', PROJECT + '-worker-standard-1',
                                 PROJECT + '-worker-task-discovery-1'], timeout=120)
            for tool in paused:
                reconnect(tool)
                if tool.operation('status')['state'] != 'enabled':
                    tool.resume()
                tool.record('restored')
            adapter.verify_mode('normal')
            raise
        finally:
            for tool in tools:
                tool.close()


if __name__ == '__main__':
    run()
