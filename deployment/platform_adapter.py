"""Fixed-host adapter for the financial platform deployment flow."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, re, shutil, subprocess, time, urllib.request, urllib.error, uuid
from maintenance_flow import DeploymentFailure
from schema_release import SCHEMA_SERVICES, SchemaRelease
from frontend_release import FrontendRelease

ROOT = Path('/home/lee/financial-platform-isolated')
PROJECT = 'financial-platform-isolated'
SERVICES = ('api', 'next', 'worker-standard', 'worker-task-discovery', 'worker-agent', 'egress-proxy', 'postgres', 'gateway')

class PlatformAdapter:
    def __init__(self):
        if (ROOT/'DEPLOYMENT_ID').read_text().strip() != 'financial-platform-isolated-20260907-01a0799a':
            raise DeploymentFailure('Deployment identity mismatch')
        self.directory = ROOT/'maintenance'
        self.frontend_rollback_plan = None
        self.frontend_observation_required = False
        self.frontend_release = None
        self.expected_frontend_image = None
        self.release = None
        self.image_id = None
        self.protected = {}
        self.schema_revisions = None
        self.schema_release = None
        self.schema_overlay = None
        self.schema_migration_attempted = False
        self.schema_container_ids = {}
        self.schema_stop_requested = set()
        self.schema_rollback_image = None
        self.schema_rollback_plan = None
        self.schema_rollback_overlay = None
        self.expected_schema_image = None
        self.schema_recovery = False
        self.schema_agent_identity = None
        self.schema_agent_image = None
        self.schema_rollback_agent_image = None
        self.expected_agent_image = None
        self.agent_switch_observation_required = False

    def command(self, args, timeout=30):
        completed = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
        if completed.returncode:
            raise DeploymentFailure('A deployment check/command failed; inspect service state before recovery')
        return completed.stdout.strip()

    def compose(self):
        return ['docker', 'compose', '--project-name', PROJECT, '--env-file', str(ROOT/'.env'), '-f', str(ROOT/'compose.yaml')]

    def mode(self):
        return json.loads((self.directory/'current/status.json').read_text())['mode']

    def set_mode(self, mode):
        if mode not in ('normal', 'notice', 'worker', 'full'):
            raise DeploymentFailure('Unsupported maintenance mode')
        target = self.directory/'states'/mode
        if not (target/'status.json').is_file():
            raise DeploymentFailure('Maintenance assets missing')
        temporary = self.directory/('switch-'+uuid.uuid4().hex)
        temporary.symlink_to('states/'+mode, target_is_directory=True)
        os.replace(temporary, self.directory/'current')
        print('Maintenance mode:', mode, flush=True)

    def public_status(self):
        request = urllib.request.Request('http://127.0.0.1:8443/maintenance/status', headers={'Host': 'localhost'})
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status != 200:raise DeploymentFailure('Gateway status check failed')
            return json.load(response)['mode']

    def verify_mode(self, expected):
        if self.public_status() != expected:
            raise DeploymentFailure('Gateway did not confirm maintenance state')

    def inspect(self):
        values = json.loads(self.command(['docker', 'inspect', *[PROJECT+'-'+s+'-1' for s in SERVICES]]))
        return {c['Name']: c for c in values}

    def active_counts(self):
        sql = "SELECT json_build_object('runs',(SELECT count(*) FROM runs WHERE state NOT IN ('succeeded','failed','cancelled')),'batches',(SELECT count(*) FROM workflow_batches WHERE state NOT IN ('succeeded','failed','cancelled')),'actions',(SELECT count(*) FROM workflow_actions WHERE state !~ '(^|:)(succeeded|failed|cancelled)$'),'discovery',(SELECT count(*) FROM task_discovery_checks WHERE state IN ('queued','running')),'assistant',(SELECT count(*) FROM assistant_turns WHERE state='running'))"
        result = self.command(['docker','exec','-e','PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=5000',PROJECT+'-postgres-1','psql','-X','-qAt','-U','financial','-d','financial','-c',sql])
        value = json.loads(result)
        if set(value) != {'runs','batches','actions','discovery','assistant'} or not all(isinstance(n,int) and n>=0 for n in value.values()):
            raise DeploymentFailure('Invalid read-only task status')
        return value

    def preflight(self, plan, image):
        self.assert_no_unresolved_schema_migration()
        self.verify_mode('normal')
        containers = self.inspect()
        if not all(c['State']['Running'] for c in containers.values()):
            raise DeploymentFailure('A platform service is already stopped; inspect before deployment')
        self.protected = {name: (c['Id'], c['State']['StartedAt']) for name,c in containers.items() if name not in {'/'+PROJECT+'-'+service+'-1' for service in plan.services}}
        if image:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}', image):raise DeploymentFailure('Invalid image reference')
            self.image_id = self.command(['docker','image','inspect','--format','{{.Id}}',image])
            if not re.fullmatch(r'sha256:[0-9a-f]{64}',self.image_id):raise DeploymentFailure('Image must already exist locally')
        if tuple(plan.services) == ("next",) and self.image_id:
            self.frontend_release = FrontendRelease.prepare((ROOT/"compose.yaml").read_text(), self.image_id)
            old_image = containers['/'+PROJECT+'-next-1']['Image']
            if self.command(['docker','image','inspect','--format','{{.Id}}',old_image]) != old_image:
                raise DeploymentFailure('Original frontend image is unavailable for recovery')
            self.frontend_rollback_plan = FrontendRelease.prepare((ROOT/"compose.yaml").read_text(), old_image)
        if self.schema_revisions is not None:
            if tuple(plan.services) != SCHEMA_SERVICES or not image or not self.image_id:
                raise DeploymentFailure('Schema migration requires the backend-schema plan and an existing image')
            self.schema_container_ids = {service: containers['/'+PROJECT+'-'+service+'-1']['Id'] for service in SCHEMA_SERVICES}
            self.capture_schema_agent(containers)
            self.validate_agent_images()
            self.schema_release = SchemaRelease.prepare(
                (ROOT/'compose.yaml').read_text(), self.image_id, *self.schema_revisions,
                agent_image_id=getattr(self, 'schema_agent_image', None),
            )
        if self.schema_release is not None:
            if not self.schema_rollback_image or not re.fullmatch(r'sha256:[0-9a-f]{64}', self.schema_rollback_image):
                raise DeploymentFailure('Schema release requires an exact verified rollback image')
            resolved = self.command(['docker', 'image', 'inspect', '--format', '{{.Id}}', self.schema_rollback_image])
            if resolved != self.schema_rollback_image:
                raise DeploymentFailure('Rollback image is unavailable locally')
            self.schema_rollback_plan = SchemaRelease.prepare((ROOT/'compose.yaml').read_text(), resolved, *self.schema_revisions, agent_image_id=getattr(self, 'schema_rollback_agent_image', None))
        self.command(self.compose()+['config','--quiet'])
        if plan.requires_idle:self.active_counts()

    def validate_agent_images(self):
        candidate = getattr(self, 'schema_agent_image', None)
        rollback = getattr(self, 'schema_rollback_agent_image', None)
        if (candidate is None) != (rollback is None):
            raise DeploymentFailure('Paired release requires both candidate and rollback Agent images')
        for image in (candidate, rollback):
            if image is not None:
                if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
                    raise DeploymentFailure('Agent image must be an exact local digest')
                if self.command(['docker', 'image', 'inspect', '--format', '{{.Id}}', image]) != image:
                    raise DeploymentFailure('Verified Agent image is unavailable locally')

    def backup(self):
        stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
        self.release=ROOT/'releases'/('managed-'+stamp)
        self.release.mkdir(mode=0o700)
        for name in ('.env','compose.yaml','Caddyfile'):
            shutil.copy2(ROOT/name,self.release/(name+'.before'))
            os.chmod(self.release/(name+'.before'),0o600)

        if self.schema_release is not None:
            self.schema_overlay = self.release/'schema-image.override.json'
            with open(self.schema_overlay, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
                stream.write(self.schema_release.overlay_text())
            self.command(self.compose()+['-f', str(self.schema_overlay), 'config', '--quiet'])
            if self.schema_rollback_plan is not None:
                self.schema_rollback_overlay = self.release/'schema-rollback.override.json'
                with open(self.schema_rollback_overlay, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
                    stream.write(self.schema_rollback_plan.overlay_text())


    def preflight_schema_recovery(self, image):
        if self.mode() != 'full':
            raise DeploymentFailure('Schema recovery requires retained full maintenance')
        self.verify_mode('full')
        self.assert_no_unresolved_schema_migration()
        path = self.directory/'schema-migration.json'
        if not path.exists():
            raise DeploymentFailure('No retained schema migration to recover')
        record = json.loads(path.read_text())
        if not image or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}', image):
            raise DeploymentFailure('Invalid recovery image')
        self.image_id = self.command(['docker', 'image', 'inspect', '--format', '{{.Id}}', image])
        expected, target = self.schema_revisions
        if (self.image_id, expected, target) != (record.get('image_id'), record.get('expected_revision'), record.get('target_revision')):
            raise DeploymentFailure('Recovery must match the retained schema release')
        original = (ROOT/'compose.yaml').read_text()
        if hashlib.sha256(original.encode()).hexdigest() not in {record.get('original_sha256'), record.get('target_sha256'), record.get('rollback_sha256')}:
            raise DeploymentFailure('Deployment configuration changed since retained migration')
        for attribute, key in (('schema_agent_image', 'agent_image_id'), ('schema_rollback_agent_image', 'rollback_agent_image_id')):
            retained = record.get(key)
            supplied = getattr(self, attribute, None)
            if supplied is not None and supplied != retained:
                raise DeploymentFailure('Agent recovery image differs from retained release')
            setattr(self, attribute, retained)
        self.validate_agent_images()
        self.schema_release = SchemaRelease.prepare(original, self.image_id, expected, target, agent_image_id=self.schema_agent_image)
        rollback = record.get('rollback_image')
        if not isinstance(rollback, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', rollback):
            raise DeploymentFailure('Retained release is missing verified rollback identity')
        if self.schema_rollback_image is not None and self.schema_rollback_image != rollback:
            raise DeploymentFailure('Recovery rollback image differs from retained release')
        resolved = self.command(['docker', 'image', 'inspect', '--format', '{{.Id}}', rollback])
        if resolved != rollback:
            raise DeploymentFailure('Retained rollback image is unavailable')
        self.schema_rollback_image = rollback
        self.schema_rollback_plan = SchemaRelease.prepare(original, rollback, expected, target, agent_image_id=self.schema_rollback_agent_image)
        self.schema_recovery = True

        # Confirm the database still has the successful execution's target; a
        # historical container exit alone cannot prove current schema state.
        revision = self.command(['docker', 'exec', '-e', 'PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=5000', PROJECT+'-postgres-1',
            'psql', '-X', '-qAt', '-U', 'financial', '-d', 'financial', '-c', 'SELECT version_num FROM alembic_version ORDER BY version_num'])
        if revision != target:
            raise DeploymentFailure('Current database revision differs from recovery target')
        containers = self.inspect()
        self.protected = {name: (c['Id'], c['State']['StartedAt']) for name, c in containers.items()
            if name not in {'/'+PROJECT+'-'+service+'-1' for service in SCHEMA_SERVICES}}
        self.capture_schema_agent(containers)
        self.command(self.compose()+['config', '--quiet'])

    def record_schema_migration(self, record):
        name = record.get('container_name', '')
        if not re.fullmatch(PROJECT+r'-schema-[0-9a-f]{12}', name):
            raise DeploymentFailure('Invalid retained migration identity')
        history = self.directory/'schema-history'
        history.mkdir(mode=0o700, exist_ok=True)
        # Preserve each execution before advancing the latest pointer. These are
        # bounded release audit records, not migration stdout or credentials.
        for destination in (history/(name+'.json'), self.directory/'schema-migration.json'):
            temporary = destination.parent/('schema-state-'+uuid.uuid4().hex)
            try:
                with open(temporary, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
                    json.dump(record, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)

    def schema_status(self):
        path = self.directory/'schema-migration.json'
        if not path.exists():
            return {'state': 'none'}
        record = json.loads(path.read_text())
        name = record.get('container_name', '')
        if not re.fullmatch(PROJECT+r'-schema-[0-9a-f]{12}', name):
            raise DeploymentFailure('Invalid retained migration identity')
        try:
            info = json.loads(self.command(['docker', 'inspect', '--format', '{"state":{{json .State}},"image":{{json .Image}},"labels":{{json .Config.Labels}}}', name]))
        except (DeploymentFailure, subprocess.TimeoutExpired, json.JSONDecodeError):
            return {'state': 'unknown', 'container_name': name, 'recorded_phase': record.get('phase')}
        labels = info.get('labels') or {}
        if info.get('image') != record.get('image_id') or labels.get('com.docker.compose.project') != PROJECT or labels.get('com.docker.compose.service') != 'api':
            raise DeploymentFailure('Retained migration container identity mismatch')
        state = info['state']
        return {'state': state.get('Status', 'unknown'), 'running': bool(state.get('Running')),
                'exit_code': state.get('ExitCode'), 'container_name': name, 'recorded_phase': record.get('phase')}

    def assert_no_unresolved_schema_migration(self):
        status = self.schema_status()
        if status['state'] == 'none':
            return
        if status['state'] != 'exited' or status.get('running') or status.get('exit_code') != 0:
            raise DeploymentFailure('Schema migration is running, failed or unverified; inspect schema-status before recovery')

    def verify_schema_target(self, plan=None, overlay=None):
        plan = plan or self.schema_release
        overlay = overlay or self.schema_overlay
        if plan is None or overlay is None:
            raise DeploymentFailure('Schema readback requires the reviewed image overlay')
        # Use the candidate's exact readiness contract, including required columns
        # and seed. This process has read-only PostgreSQL transactions and cannot
        # migrate or repair anything, including when reusing a historical result.
        code = (
            "import json; from app.database import check_runtime_database; "
            "status=check_runtime_database(); print(json.dumps({'revision':status.revision}))"
        )
        output = self.command(self.compose()+['-f', str(overlay), 'run', '--rm',
            '--name', PROJECT+'-schema-check-'+uuid.uuid4().hex[:12], '--no-deps', '--pull', 'never', '-T',
            '-e', 'PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=10000',
            '--entrypoint', 'python', 'api', '-B', '-c', code], timeout=60)
        try:
            result = json.loads(output)
        except json.JSONDecodeError as error:
            raise DeploymentFailure('Schema readback returned invalid evidence') from error
        if result != {'revision': plan.target_revision}:
            raise DeploymentFailure('Current database differs from the reviewed schema target')

    def migrate_before_cutover(self):
        if self.schema_release is None or self.schema_overlay is None:
            raise DeploymentFailure('Reviewed schema release was not prepared')
        original = (ROOT/'compose.yaml').read_text()
        if hashlib.sha256(original.encode()).hexdigest() != self.schema_release.original_sha256:
            raise DeploymentFailure('Deployment configuration changed after preflight')
        identity = {
            'image_id': self.schema_release.image_id,
            'expected_revision': self.schema_release.expected_revision,
            'target_revision': self.schema_release.target_revision,
            'original_sha256': self.schema_release.original_sha256,
        }
        if self.schema_release.agent_image_id is not None:
            identity['agent_image_id'] = self.schema_release.agent_image_id
            identity['rollback_agent_image_id'] = self.schema_rollback_plan.agent_image_id
        record_path = self.directory/'schema-migration.json'
        previous = json.loads(record_path.read_text()) if record_path.exists() else None
        # A timed-out observer must inspect the original execution, never start
        # another migration merely because the compose client stopped waiting.
        if previous is not None:
            self.assert_no_unresolved_schema_migration()
        reuse = previous is not None and all(previous.get(key) == value for key, value in identity.items() if key != 'original_sha256') and all(previous.get(key) == identity.get(key) for key in ('agent_image_id', 'rollback_agent_image_id')) and identity['original_sha256'] in {previous.get('original_sha256'), previous.get('target_sha256'), previous.get('rollback_sha256')}
        if reuse:
            self.schema_migration_attempted = True
            record = previous
        else:
            record = dict(identity, target_sha256=hashlib.sha256(self.schema_release.compose_text.encode()).hexdigest(), container_name=PROJECT+'-schema-'+uuid.uuid4().hex[:12], phase='starting')
            if self.schema_rollback_plan is not None:
                record['rollback_image'] = self.schema_rollback_plan.image_id
                record['rollback_sha256'] = hashlib.sha256(self.schema_rollback_plan.compose_text.encode()).hexdigest()
            self.record_schema_migration(record)
            try:
                self.schema_migration_attempted = True
                self.command(self.compose()+['-f', str(self.schema_overlay), 'run', '--name', record['container_name'], '--no-deps', '--pull', 'never', '-T', '--entrypoint', 'python', 'api', *self.schema_release.migration_arguments()], timeout=300)
            except BaseException:
                record['phase'] = 'observation_required'
                self.record_schema_migration(record)
                raise
        record['phase'] = 'completed'
        self.record_schema_migration(record)
        self.verify_schema_target()
        # Recheck after the migration; publish image pins only after success.
        if hashlib.sha256((ROOT/'compose.yaml').read_text().encode()).hexdigest() != self.schema_release.original_sha256:
            raise DeploymentFailure('Deployment configuration changed during migration')
        temporary = ROOT/('compose.schema-'+uuid.uuid4().hex)
        try:
            with open(temporary, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
                stream.write(self.schema_release.compose_text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, ROOT/'compose.yaml')
        finally:
            temporary.unlink(missing_ok=True)

    def grace(self):
        # Let the banner arrive and previously accepted short requests complete.
        time.sleep(10)

    def wait_idle(self):
        deadline=time.monotonic()+1800
        consecutive=0
        while time.monotonic()<deadline:
            counts=self.active_counts()
            consecutive=consecutive+1 if not any(counts.values()) else 0
            print('Unfinished task counts:',json.dumps(counts),flush=True)
            if consecutive>=3:return
            time.sleep(5)
        raise DeploymentFailure('Tasks did not finish within 30 minutes; no services were restarted')

    def observe_schema_agent_switch(self, containers, record):
        """Read back the replacement after a prior observer exited; never start it."""
        name = '/'+PROJECT+'-worker-agent-1'
        candidate = containers[name]
        pairs = ((self.schema_release.image_id, self.schema_release.agent_image_id),
                 (self.schema_rollback_plan.image_id, self.schema_rollback_plan.agent_image_id))
        target = record.get('target_image')
        expected_backend = next((backend for backend, agent in pairs if agent == target), None)
        labels = candidate.get('Config', {}).get('Labels') or {}
        api = containers['/'+PROJECT+'-api-1']
        if (expected_backend is None or candidate['Id'] == record.get('id')
                or candidate['Image'] != target or not candidate['State'].get('Running')
                or candidate['State'].get('Health', {}).get('Status', 'healthy') != 'healthy'
                or labels.get('com.docker.compose.project') != PROJECT
                or labels.get('com.docker.compose.service') != 'worker-agent'
                or api['Image'] != expected_backend or not api['State'].get('Running')
                or api['State'].get('Health', {}).get('Status') != 'healthy'):
            raise DeploymentFailure('Agent replacement outcome is not confirmed; retain maintenance')
        # Observe one concrete container identity twice. A running replacement,
        # not a stale status file or an elapsed timeout, supplies the evidence.
        identity = (candidate['Id'], candidate['Image'], candidate['State']['StartedAt'], candidate['RestartCount'])
        time.sleep(1)
        second = self.inspect()
        observed = second[name]
        observed_api = second['/'+PROJECT+'-api-1']
        if ((observed['Id'], observed['Image'], observed['State']['StartedAt'], observed['RestartCount']) != identity
                or not observed['State'].get('Running')
                or observed['State'].get('Health', {}).get('Status', 'healthy') != 'healthy'
                or observed_api['Image'] != expected_backend or not observed_api['State'].get('Running')
                or observed_api['State'].get('Health', {}).get('Status') != 'healthy'):
            raise DeploymentFailure('Agent replacement did not remain stable during observation')

    def capture_schema_agent(self, containers):
        name = '/'+PROJECT+'-worker-agent-1'
        container = containers[name]
        state_path = self.directory/'schema-agent-stop.json'
        record = json.loads(state_path.read_text()) if state_path.exists() else {}
        if record.get('phase') == 'switch-requested':
            if not self.schema_recovery:
                raise DeploymentFailure('Agent switch requires explicit observed schema recovery')
            self.observe_schema_agent_switch(containers, record)
        self.schema_agent_identity = {
            'id': container['Id'], 'image': container['Image'],
            'started_at': container['State']['StartedAt'], 'restarts': container['RestartCount'],
        }
        self.schema_container_ids['worker-agent'] = container['Id']
        # Its image/config remain protected; only this explicitly coordinated
        # dependency stop/start may change its process start time.
        self.protected.pop(name, None)
        if not container['State'].get('Running'):
            owned = (record.get('id'), record.get('image')) == (container['Id'], container['Image'])
            paired_images = {plan.agent_image_id for plan in
                (getattr(self, 'schema_release', None), getattr(self, 'schema_rollback_plan', None)) if plan is not None}
            failed_replacement = (getattr(self, 'schema_recovery', False) and owned and record.get('phase') in {'resumed', 'stopped'}
                and container['Image'] in paired_images and container['State'].get('Status') == 'exited'
                and container['State'].get('ExitCode') != 0)
            if not owned or (record.get('phase') not in {'stop-requested', 'stopped'} and not failed_replacement):
                raise DeploymentFailure('Stopped Agent is not owned by the retained maintenance attempt')
            if container['State'].get('Status') != 'exited' or (container['State'].get('ExitCode') != 0 and not failed_replacement):
                raise DeploymentFailure('Retained Agent has not exited cleanly')
            self.schema_agent_failed_stopped = failed_replacement
            self.schema_stop_requested.add('worker-agent')

    def record_schema_agent_state(self, phase):
        record = dict(self.schema_agent_identity, phase=phase)
        if getattr(self, 'expected_agent_image', None) is not None:
            record['target_image'] = self.expected_agent_image
        temporary = self.directory/('agent-state-'+uuid.uuid4().hex)
        try:
            with open(temporary, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
                json.dump(record, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory/'schema-agent-stop.json')
        finally:
            temporary.unlink(missing_ok=True)


    def resume_schema_agent(self):
        if getattr(self, 'agent_switch_observation_required', False):
            raise DeploymentFailure('Agent switch outcome requires observation before recovery')
        if self.schema_agent_identity is None:
            return
        containers = self.inspect()
        api = containers['/'+PROJECT+'-api-1']
        if not api['State'].get('Running') or api['State'].get('Health', {}).get('Status') != 'healthy':
            raise DeploymentFailure('API must be healthy before Agent resumes')
        expected_api = getattr(self, 'expected_schema_image', None)
        if expected_api is not None and api['Image'] != expected_api:
            raise DeploymentFailure('API image differs from the paired release')
        name = '/'+PROJECT+'-worker-agent-1'
        agent = containers[name]
        if (agent['Id'], agent['Image']) != (self.schema_agent_identity['id'], self.schema_agent_identity['image']):
            raise DeploymentFailure('Agent identity changed outside coordinated maintenance')
        if 'worker-agent' in self.schema_stop_requested:
            replacing_failed = (getattr(self, 'schema_agent_failed_stopped', False)
                and getattr(self, 'expected_agent_image', None) not in (None, agent['Image']))
            if agent['State'].get('Running') or agent['State'].get('Status') != 'exited' or (agent['State'].get('ExitCode') != 0 and not replacing_failed):
                raise DeploymentFailure('Agent has not completed its graceful stop')
            target = getattr(self, 'expected_agent_image', None)
            if target is not None and target != agent['Image']:
                self.replace_schema_agent(target)
                return
            self.command(['docker', 'start', agent['Id']], timeout=60)
            agent = self.inspect()[name]
            if (agent['Id'], agent['Image']) != (self.schema_agent_identity['id'], self.schema_agent_identity['image']) or not agent['State'].get('Running'):
                raise DeploymentFailure('Original Agent did not resume')
            self.schema_agent_identity.update(started_at=agent['State']['StartedAt'], restarts=agent['RestartCount'])
            self.record_schema_agent_state('resumed')
            self.schema_stop_requested.remove('worker-agent')
        elif (agent['State']['StartedAt'], agent['RestartCount']) != (self.schema_agent_identity['started_at'], self.schema_agent_identity['restarts']):
            raise DeploymentFailure('Agent restarted outside coordinated maintenance')

    def replace_schema_agent(self, target):
        """Replace only an already-drained Agent, after API health is confirmed."""
        if self.mode() != 'full':
            raise DeploymentFailure('Paired Agent switch requires full maintenance')
        self.verify_mode('full')
        allowed = [self.schema_release]
        rollback = getattr(self, 'schema_rollback_plan', None)
        if rollback is not None:
            allowed.append(rollback)
        current = (ROOT/'compose.yaml').read_text()
        if not any(plan.agent_image_id == target and plan.compose_text == current for plan in allowed):
            raise DeploymentFailure('Paired Agent configuration changed after verification')
        self.record_schema_agent_state('switch-requested')
        try:
            self.command(self.compose()+['up', '-d', '--no-deps', '--no-build', '--pull', 'never',
                '--force-recreate', '--timeout', '120', 'worker-agent'], timeout=180)
            agent = self.inspect()['/'+PROJECT+'-worker-agent-1']
            labels = agent.get('Config', {}).get('Labels') or {}
            if (agent['Image'] != target or not agent['State'].get('Running')
                    or labels.get('com.docker.compose.project') != PROJECT
                    or labels.get('com.docker.compose.service') != 'worker-agent'):
                raise DeploymentFailure('Replacement Agent identity was not verified')
        except BaseException:
            self.agent_switch_observation_required = True
            raise
        self.schema_agent_identity = {
            'id': agent['Id'], 'image': agent['Image'],
            'started_at': agent['State']['StartedAt'], 'restarts': agent['RestartCount'],
        }
        self.record_schema_agent_state('resumed')
        self.schema_stop_requested.remove('worker-agent')

    def stop_schema_service_gracefully(self, service, *, allow_failed_stopped=False):
        if service not in SCHEMA_SERVICES and not (service == 'worker-agent' and self.schema_agent_identity is not None):
            raise DeploymentFailure('Service is outside the schema release scope')
        name = PROJECT+'-'+service+'-1'
        def state():
            value = json.loads(self.command(['docker', 'inspect', '--format',
                '{"id":{{json .Id}},"state":{{json .State}},"labels":{{json .Config.Labels}}}', name]))
            labels = value.get('labels') or {}
            if labels.get('com.docker.compose.project') != PROJECT or labels.get('com.docker.compose.service') != service:
                raise DeploymentFailure('Schema service identity mismatch')
            return value
        before = state()
        if service == 'worker-agent' and before['id'] != self.schema_agent_identity['id']:
            raise DeploymentFailure('Agent identity changed before coordinated stop')
        if before['state'].get('Running'):
            # Infinite daemon grace: never escalate a financial task to SIGKILL.
            # A client observation timeout leaves maintenance closed; it is not
            # evidence of process exit and cannot authorize migration/cutover.
            self.schema_stop_requested.add(service)
            if service == 'worker-agent':
                self.record_schema_agent_state('stop-requested')
            self.command(['docker', 'stop', '--timeout', '-1', name], timeout=300)
        after = state()
        if after['id'] != before['id'] or after['state'].get('Status') != 'exited' or after['state'].get('Running') or (after['state'].get('ExitCode') != 0 and not (allow_failed_stopped and not before['state'].get('Running'))):
            raise DeploymentFailure('Schema service has not exited cleanly; retain maintenance')
        if service == 'worker-agent':
            self.schema_agent_failed_stopped = bool(allow_failed_stopped and not before['state'].get('Running') and after['state'].get('ExitCode') != 0)
            self.schema_stop_requested.add('worker-agent')
            self.record_schema_agent_state('stopped')

    def quiesce_schema_services(self, *, allow_failed_stopped=False):
        if getattr(self, 'agent_switch_observation_required', False):
            raise DeploymentFailure('Agent switch outcome requires observation before another cutover')
        if self.mode() != 'full':
            raise DeploymentFailure('Schema cutover requires full maintenance')
        self.verify_mode('full')
        # Confirm the actual application path is closed, not just the banner.
        try:
            with urllib.request.urlopen('http://127.0.0.1:8443/api/health', timeout=5) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
        if status != 503:
            raise DeploymentFailure('Public application ingress is not closed')
        self.wait_idle()
        self.stop_schema_service_gracefully('worker-task-discovery', allow_failed_stopped=allow_failed_stopped)
        # Drain anything accepted before ingress closed or started by the final
        # discovery tick. Standard Worker and API stay available for completion.
        self.wait_idle()
        self.stop_schema_service_gracefully('worker-standard', allow_failed_stopped=allow_failed_stopped)
        self.stop_schema_service_gracefully('worker-agent', allow_failed_stopped=allow_failed_stopped)
        self.stop_schema_service_gracefully('api', allow_failed_stopped=allow_failed_stopped)
        if any(self.active_counts().values()):
            raise DeploymentFailure('Unfinished tasks remain after graceful drain; migration refused')

    def cutover(self, plan, image):
        if self.schema_revisions is not None:
            self.quiesce_schema_services(allow_failed_stopped=self.schema_recovery)
            self.migrate_before_cutover()
            self.expected_schema_image = self.schema_release.image_id
            self.expected_agent_image = self.schema_release.agent_image_id
        elif image and tuple(plan.services) == ("next",):
            release = self.frontend_release
            if release is None or hashlib.sha256((ROOT/'compose.yaml').read_bytes()).hexdigest() != release.original_sha256:
                raise DeploymentFailure('Frontend configuration changed since preflight')
            temporary = ROOT/('compose.frontend-'+uuid.uuid4().hex)
            try:
                with open(temporary,'x',opener=lambda path,flags:os.open(path,flags,0o600)) as stream:
                    stream.write(release.compose_text)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary,ROOT/'compose.yaml')
            finally:
                temporary.unlink(missing_ok=True)
            self.expected_frontend_image = release.image_id
        elif image:
            p=ROOT/'.env'
            lines=p.read_text().splitlines()
            if sum(line.startswith(plan.image_key+'=') for line in lines)!=1:
                raise DeploymentFailure('Image setting missing or duplicated')
            content='\n'.join(plan.image_key+'='+self.image_id if line.startswith(plan.image_key+'=') else line for line in lines)+'\n'
            temp=ROOT/('.env.deploy-'+uuid.uuid4().hex)
            with open(temp,'x',opener=lambda path,flags:os.open(path,flags,0o600)) as f:f.write(content)
            os.replace(temp,p)
        try:
            self.start_selected_services(plan)
        except subprocess.TimeoutExpired:
            if tuple(plan.services) == ("next",):
                self.frontend_observation_required = True
            raise

    def rollback_frontend(self):
        """Restore only the pinned prior Next image after a confirmed failed cutover."""
        rollback = self.frontend_rollback_plan
        release = self.frontend_release
        if self.mode() != 'full' or rollback is None or release is None:
            raise DeploymentFailure('No prepared frontend recovery under full maintenance')
        if self.frontend_observation_required:
            raise DeploymentFailure('Frontend operation outcome requires observation before recovery')
        current = (ROOT/'compose.yaml').read_text()
        if hashlib.sha256(current.encode()).hexdigest() not in {
            release.original_sha256, hashlib.sha256(release.compose_text.encode()).hexdigest()
        }:
            raise DeploymentFailure('Frontend configuration changed outside this release')
        # The failed replacement may have removed Next entirely. Inspect only
        # protected services so a missing target cannot prevent its recovery.
        containers = {value['Name']:value for value in json.loads(self.command(
            ['docker','inspect',*self.protected.keys()]))}
        for name, expected in self.protected.items():
            value = containers.get(name)
            if value is None or (value['Id'],value['State']['StartedAt']) != expected or not value['State']['Running']:
                raise DeploymentFailure('Protected service changed; frontend recovery refused')
        if self.command(['docker','image','inspect','--format','{{.Id}}',rollback.image_id]) != rollback.image_id:
            raise DeploymentFailure('Original frontend image is unavailable')
        # Reuse the same drift guard and atomic Compose replacement as cutover.
        self.frontend_release = FrontendRelease.prepare(current,rollback.image_id)
        from maintenance_flow import PLANS
        self.cutover(PLANS['frontend'],rollback.image_id)
        return True

    def start_selected_services(self, plan):
        up=self.compose()+['up','-d','--no-deps','--no-build','--pull','never','--force-recreate','--timeout','120']
        if 'api' in plan.services:
            self.command(up+['--wait','--wait-timeout','120','api'],timeout=180)
        remaining=[service for service in plan.services if service!='api']
        if remaining:self.command(up+remaining,timeout=300)
        if self.schema_revisions is not None:
            self.resume_schema_agent()

    def rollback_after_schema_migration(self):
        if self.schema_rollback_plan is None or self.schema_rollback_overlay is None:
            raise DeploymentFailure('No prepared compatible rollback image')
        status = self.schema_status()
        if status.get('state') != 'exited' or status.get('running') or status.get('exit_code') != 0:
            raise DeploymentFailure('Migration is not confirmed successful; rollback refused')
        current = (ROOT/'compose.yaml').read_text()
        allowed = {self.schema_release.original_sha256, hashlib.sha256(self.schema_release.compose_text.encode()).hexdigest()}
        if hashlib.sha256(current.encode()).hexdigest() not in allowed:
            raise DeploymentFailure('Configuration changed outside this schema release')
        self.quiesce_schema_services(allow_failed_stopped=True)
        self.verify_schema_target(self.schema_rollback_plan, self.schema_rollback_overlay)
        if (ROOT/'compose.yaml').read_text() != current:
            raise DeploymentFailure('Configuration changed during rollback checks')
        temporary = ROOT/('compose.rollback-'+uuid.uuid4().hex)
        try:
            with open(temporary, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
                stream.write(self.schema_rollback_plan.compose_text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, ROOT/'compose.yaml')
        finally:
            temporary.unlink(missing_ok=True)
        # Application-only rollback: no migration command and no DB downgrade.
        from maintenance_flow import PLANS
        self.expected_schema_image = self.schema_rollback_plan.image_id
        self.expected_agent_image = self.schema_rollback_plan.agent_image_id
        self.start_selected_services(PLANS['backend-schema'])
        return True

    def restore_before_schema_migration(self):
        """Restart original containers only when this attempt never began DDL."""
        if self.schema_release is None or self.schema_migration_attempted:
            return False
        if self.mode() != 'full' or not self.schema_container_ids:
            return False
        if hashlib.sha256((ROOT/'compose.yaml').read_bytes()).hexdigest() != self.schema_release.original_sha256:
            raise DeploymentFailure('Cannot restore original services after configuration drift')
        revision = self.command(['docker', 'exec', '-e', 'PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=5000',
            PROJECT+'-postgres-1', 'psql', '-X', '-qAt', '-U', 'financial', '-d', 'financial', '-c',
            'SELECT version_num FROM alembic_version ORDER BY version_num'])
        if revision != self.schema_release.expected_revision:
            raise DeploymentFailure('Original application cannot be restored against a changed database')
        containers = self.inspect()
        stopped = []
        for service in self.schema_container_ids:
            container = containers['/'+PROJECT+'-'+service+'-1']
            if container['Id'] != self.schema_container_ids[service]:
                raise DeploymentFailure('Original service container was replaced; restoration refused')
            state = container['State']
            if state.get('Running'):
                if service in self.schema_stop_requested:
                    # A timed-out stop is still potentially in progress. It must
                    # not be treated as an untouched running service.
                    raise DeploymentFailure('Original service has not finished stopping; inspect before recovery')
                continue
            if service not in self.schema_stop_requested:
                raise DeploymentFailure('A service stopped outside this deployment; restoration refused')
            if state.get('Status') != 'exited' or state.get('ExitCode') != 0:
                raise DeploymentFailure('Original service did not exit cleanly')
            if service != 'worker-agent':
                stopped.append(container['Id'])
        if stopped:
            self.command(['docker', 'start', *stopped], timeout=60)
        if self.schema_agent_identity is not None:
            deadline = time.monotonic()+120
            while time.monotonic() < deadline:
                api = self.inspect()['/'+PROJECT+'-api-1']
                if api['State'].get('Running') and api['State'].get('Health', {}).get('Status') == 'healthy':
                    break
                time.sleep(2)
            else:
                raise DeploymentFailure('Original API did not become healthy before Agent recovery')
            self.resume_schema_agent()
        return True

    def verify_recorded_image_pair(self):
        path = self.directory/'schema-migration.json'
        if not path.exists():
            return
        record = json.loads(path.read_text())
        candidate_agent = record.get('agent_image_id')
        if candidate_agent is None:
            return
        containers = self.inspect()
        actual = tuple(containers['/'+PROJECT+'-'+service+'-1']['Image'] for service in SCHEMA_SERVICES)
        agent = containers['/'+PROJECT+'-worker-agent-1']['Image']
        pairs = ((record.get('image_id'), candidate_agent),
                 (record.get('rollback_image'), record.get('rollback_agent_image_id')))
        if not any(actual == (backend,) * len(SCHEMA_SERVICES) and agent == paired_agent
                   for backend, paired_agent in pairs if backend and paired_agent):
            raise DeploymentFailure('API/Agent images do not match a recorded candidate or rollback pair')
        state_path = self.directory/'schema-agent-stop.json'
        if state_path.exists() and json.loads(state_path.read_text()).get('phase') == 'switch-requested':
            raise DeploymentFailure('Agent switch needs explicit schema recovery and verification')

    def healthy_sample(self):
        self.assert_no_unresolved_schema_migration()
        self.verify_recorded_image_pair()
        containers=self.inspect()
        if self.schema_agent_identity is not None:
            agent = containers['/'+PROJECT+'-worker-agent-1']
            expected = self.schema_agent_identity
            if (agent['Id'], agent['Image'], agent['State']['StartedAt'], agent['RestartCount']) != (expected['id'], expected['image'], expected['started_at'], expected['restarts']):
                raise DeploymentFailure('Agent changed after coordinated resume')
        if getattr(self, 'expected_frontend_image', None) is not None:
            if containers['/'+PROJECT+'-next-1']['Image'] != self.expected_frontend_image:
                raise DeploymentFailure('Frontend is not running the verified image')
        if self.expected_schema_image is not None:
            for service in SCHEMA_SERVICES:
                if containers['/'+PROJECT+'-'+service+'-1']['Image'] != self.expected_schema_image:
                    raise DeploymentFailure('Schema service is not running the verified image')

        if not all(c['State']['Running'] and c['State'].get('Health',{}).get('Status','healthy')=='healthy' for c in containers.values()):
            raise DeploymentFailure('Services are not ready')
        if any((containers[name]['Id'],containers[name]['State']['StartedAt']) != expected for name,expected in self.protected.items()):
            raise DeploymentFailure('A service outside the selected plan changed; inspect before reopening')
        self.active_counts()  # read-only DB connectivity, does not require business tasks to be idle
        code="import urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=5)); assert d['status']=='ok' and not d['registry_errors']"
        self.command(['docker','exec',PROJECT+'-api-1','python','-c',code])
        # The rebuilt gateway intentionally returns 503 for every application
        # path during full maintenance. Verify gateway mode, then probe the
        # actual Next-to-API session path inside the application network.
        self.verify_mode(self.mode())
        code = (
            "import urllib.request,urllib.error\n"
            "try:r=urllib.request.urlopen('http://next:3000/api/auth/session',timeout=5)\n"
            "except urllib.error.HTTPError as e:r=e\n"
            "assert r.status in (200,401), 'Frontend/API session service is not ready'\n"
            "r.close()"
        )
        self.command(['docker','exec',PROJECT+'-api-1','python','-c',code])
        return {name:(c['Id'],c['RestartCount']) for name,c in containers.items()}

    def wait_healthy(self, plan):
        deadline=time.monotonic()+180
        previous=None
        stable=0
        while time.monotonic()<deadline:
            try:
                sample=self.healthy_sample()
                stable=stable+1 if sample==previous else 0
                previous=sample
                if stable>=2:return
            except (DeploymentFailure, urllib.error.URLError, TimeoutError, subprocess.TimeoutExpired):
                previous=None;stable=0
            time.sleep(5)
        raise DeploymentFailure('Readiness did not stabilize; maintenance remains active')

    def record(self, outcome, plan):
        value={'at':datetime.now(timezone.utc).isoformat(),'outcome':outcome,'plan':plan,'mode':self.mode()}
        with (self.directory/'deployment-events.jsonl').open('a') as f:f.write(json.dumps(value)+'\n')
        print(json.dumps(value),flush=True)

    def preflight_frontend_recovery(self, image):
        self.verify_mode('full')
        containers = self.inspect()
        next_name = '/'+PROJECT+'-next-1'
        others = {name:c for name,c in containers.items() if name != next_name}
        if not all(c['State']['Running'] and c['State'].get('Health',{}).get('Status','healthy')=='healthy' for c in others.values()):
            raise DeploymentFailure('A non-frontend service is unhealthy; recovery refused')
        self.protected = {name:(c['Id'],c['State']['StartedAt']) for name,c in others.items()}
        if not image or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}',image):
            raise DeploymentFailure('A valid existing frontend image is required')
        self.image_id = self.command(['docker','image','inspect','--format','{{.Id}}',image])
        if not re.fullmatch(r'sha256:[0-9a-f]{64}',self.image_id):
            raise DeploymentFailure('Image must already exist locally')
        self.frontend_release = FrontendRelease.prepare((ROOT/"compose.yaml").read_text(), self.image_id)
        self.command(self.compose()+['config','--quiet'])
        self.active_counts()
