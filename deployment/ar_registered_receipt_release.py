"""Publish a verified AR lab correction through an immutable image cutover."""
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

from pathlib import Path

ROOT = Path('/home/lee/financial-platform-isolated')
SOURCE = ROOT / 'refactor-worktrees/full-platform-20260918'
sys.path.insert(0, str(SOURCE / 'deployment'))
from deploy_tool import ToolDeployment, HASH, atomic_write, command, tree
from maintenance_flow import DeploymentFailure, Plan
from platform_adapter import PlatformAdapter, PROJECT

class Adapter(PlatformAdapter):
    def healthy_sample(self):
        name = '/' + PROJECT + '-worker-agent-1'
        current = self.inspect()[name]
        expected = self.protected[name]
        if current['Id'] != expected[0]:
            raise DeploymentFailure('Agent container was replaced outside the release')
        # The unchanged Agent container may restart when the API reconnects.
        self.protected[name] = (current['Id'], current['State']['StartedAt'])
        return super().healthy_sample()


SKILL = 'ar-hexiao-daily-lab'
IMAGE_TAG = 'financial-platform-isolated-backend:ar-lab-crossdate-status-20260923'
PLAN = Plan(('api', 'worker-standard', 'worker-task-discovery'), 'normal', True)


def reconnect(tool):
    if tool.control:
        try:
            tool.control.stdin.close()
            tool.control.wait(timeout=5)
        except Exception:
            tool.control.kill()
            tool.control.wait()
    current = tool.inspect()
    tool.identities = dict(zip(tool.containers, [item['Id'] for item in current]))
    tool.baseline = [(item['Id'], item['State']['StartedAt']) for item in current]
    addresses = [value['IPAddress'] for key, value in current[0]['NetworkSettings']['Networks'].items()
                 if key == 'financial-platform-isolated_edge' and value.get('IPAddress')]
    if len(addresses) != 1:
        raise DeploymentFailure('Replacement API network address unavailable')
    tool.base_url = 'http://' + addresses[0] + ':8000'
    tool.guarded = False
    tool.start_control()


def main():
    adapter = Adapter()
    tool = ToolDeployment(SKILL, '302789')
    compose_before = None
    stopped = False
    changed = False
    with (ROOT / 'maintenance/deployment.lock').open('a') as deployment_lock:
        fcntl.flock(deployment_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        api = PROJECT + '-api-1'
        command(['docker', 'exec', api, 'python', '-c',
                 'from app.skill_release_service import _publish_lock_path;_publish_lock_path().touch(exist_ok=True)'])
        lock_name = command(['docker', 'exec', api, 'python', '-c',
                             'from app.skill_release_service import _publish_lock_path;print(_publish_lock_path().name)']).decode().strip()
        if not re.fullmatch(r'\.skill-release\.publish(?:\.\d+)?\.lock', lock_name):
            raise DeploymentFailure('Unexpected tool publication lock')
        with (ROOT / 'data' / lock_name).open('rb') as publish_lock:
            fcntl.flock(publish_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            adapter.preflight(PLAN, None)
            baseline = adapter.inspect()
            compose_before = (ROOT / 'compose.yaml').read_bytes()
            print(json.dumps(tool.preflight(), ensure_ascii=False), flush=True)
            image = adapter.command(['docker', 'image', 'inspect', '--format', '{{.Id}}', IMAGE_TAG])
            base = baseline['/' + api]['Image']
            base_layers = json.loads(adapter.command(['docker', 'image', 'inspect', base]))[0]['RootFS']['Layers']
            candidate_layers = json.loads(adapter.command(['docker', 'image', 'inspect', image]))[0]['RootFS']['Layers']
            if not base_layers or candidate_layers[:len(base_layers)] != base_layers:
                raise DeploymentFailure('Candidate image base differs from running services')
            actual_tree = json.loads(command(['docker', 'run', '--rm', '--pull', 'never', '--network', 'none',
                                              '--read-only', '--tmpfs', '/tmp:rw,exec,nosuid,size=256m',
                                              '--entrypoint', 'python', image, '-c', HASH,
                                              '/app/skills/' + SKILL]))
            if actual_tree != tool.new_tree:
                raise DeploymentFailure('Candidate tool tree differs from current persistent source')
            tests = subprocess.run(['docker', 'run', '--rm', '--pull', 'never', '--network', 'none',
                                    '--read-only', '--tmpfs', '/tmp:rw,exec,nosuid,size=256m',
                                    '-e', 'PYTHONDONTWRITEBYTECODE=1',
                                    '-w', '/app/skills/' + SKILL + '/vendor/scripts',
                                    '--entrypoint', 'python', image, '-m', 'unittest', '-q',
                                    'test_flow_carry_legacy', 'test_flow_completion', 'test_flow_current_balance', 'test_flow_current_parent_proof', 'test_flow_monthly', 'test_flow_name_map', 'test_flow_order_prefill', 'test_flow_report_reasons', 'test_flow_sales_initials', 'test_flow_source_receipts', 'test_flow_unique_weak', 'test_receipt_ownership'], capture_output=True, text=True, timeout=180)
            if tests.returncode:
                raise DeploymentFailure('Candidate receipt ownership tests failed')
            print('Candidate AR flow and receipt tests: 461 passed', flush=True)
            if (ROOT / 'compose.yaml').read_bytes() != compose_before:
                raise DeploymentFailure('Compose changed during preparation')
            current = adapter.inspect()
            if any(current[name]['Id'] != item['Id'] for name, item in baseline.items()):
                raise DeploymentFailure('Service changed during preparation')
            adapter.backup()
            tool.record_dir = adapter.release / (adapter.release.name + '-tool-' + SKILL)
            tool.record_dir.mkdir(mode=0o700)
            tool.new_image = image
            try:
                tool.login()
                if tool.operation('status')['state'] != 'enabled':
                    raise DeploymentFailure('Tool already paused by another operation')
                tool.pause()
                tool.wait_idle()
                adapter.wait_idle()
                if tree(tool.content) != tool.new_tree:
                    raise DeploymentFailure('Source changed after candidate build')
                if (ROOT / 'compose.yaml').read_bytes() != compose_before:
                    raise DeploymentFailure('Compose changed before cutover')
                # The workers finish active work before stopping; no task is cancelled.
                adapter.command(['docker', 'stop', '--timeout', '-1',
                                 PROJECT + '-worker-standard-1', PROJECT + '-worker-task-discovery-1'],
                                timeout=7200)
                stopped = True
                if any(adapter.active_counts().values()):
                    raise DeploymentFailure('New task appeared during worker drain')
                config = compose_before.decode()
                for service in PLAN.services:
                    pattern = r'(?ms)(^  ' + re.escape(service) + r':\n.*?^    image: )[^\n]+'
                    config, count = re.subn(pattern, lambda match: match.group(1) + image,
                                            config, count=1)
                    if count != 1:
                        raise DeploymentFailure('Selected service image declaration missing')
                atomic_write(ROOT / 'compose.yaml', config.encode(), mode=0o600)
                changed = True
                adapter.cutover(PLAN, None)
                adapter.wait_healthy(PLAN)
                running = adapter.inspect()
                for service in PLAN.services:
                    name = '/' + PROJECT + '-' + service + '-1'
                    if running[name]['Image'] != image:
                        raise DeploymentFailure('Selected service did not start on candidate image')
                    observed = json.loads(command(['docker', 'exec', running[name]['Id'], 'python',
                                                   '-c', HASH, '/app/skills/' + SKILL]))
                    if observed != tool.new_tree:
                        raise DeploymentFailure('Runtime tool hash differs from source')
                reconnect(tool)
                tool.reload()
                availability = tool.api('/api/admin/skills/' + SKILL + '/availability')
                if availability.get('current_version') != tool.version or availability.get('state') != 'disabled':
                    raise DeploymentFailure('Registry version or tool pause state is incorrect')
                adapter.verify_mode('normal')
                tool.resume()
                tool.record('succeeded')
                adapter.record('succeeded', 'ar-lab-crossdate-status-targeted-cutover')
                print(json.dumps({'status': 'succeeded', 'version': tool.version, 'image': image,
                                  'rollback': str(adapter.release), 'global_maintenance': False}), flush=True)
            except BaseException:
                if tool.pause_owned:
                    if changed:
                        if (ROOT / 'compose.yaml').read_bytes() != config.encode():
                            raise DeploymentFailure('Compose changed after cutover; manual recovery required')
                        adapter.rollback_runtime(PLAN)
                        adapter.wait_healthy(PLAN)
                    elif stopped:
                        adapter.command(['docker', 'start', PROJECT + '-worker-standard-1',
                                         PROJECT + '-worker-task-discovery-1'], timeout=180)
                        adapter.wait_healthy(PLAN)
                    reconnect(tool)
                    tool.resume()
                    tool.record('restored')
                raise
            finally:
                tool.close()


if __name__ == '__main__':
    main()
