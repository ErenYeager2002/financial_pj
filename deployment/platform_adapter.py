"""Fixed-host adapter for the financial platform deployment flow."""
from pathlib import Path
from datetime import datetime, timezone
import json, os, re, shutil, subprocess, time, urllib.request, urllib.error, uuid
from maintenance_flow import DeploymentFailure

ROOT = Path('/home/lee/financial-platform-isolated')
PROJECT = 'financial-platform-isolated'
SERVICES = ('api', 'next', 'worker-standard', 'worker-task-discovery', 'worker-agent', 'egress-proxy', 'postgres', 'gateway')

class PlatformAdapter:
    def __init__(self):
        if (ROOT/'DEPLOYMENT_ID').read_text().strip() != 'financial-platform-isolated-20260907-01a0799a':
            raise DeploymentFailure('Deployment identity mismatch')
        self.directory = ROOT/'maintenance'
        self.release = None
        self.image_id = None
        self.protected = {}

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
        sql = "SELECT json_build_object('runs',(SELECT count(*) FROM runs WHERE state NOT IN ('succeeded','failed','cancelled')),'batches',(SELECT count(*) FROM workflow_batches WHERE state NOT IN ('succeeded','failed','cancelled')),'actions',(SELECT count(*) FROM workflow_actions WHERE state !~ '(^|:)(succeeded|failed|cancelled)$'),'discovery',(SELECT count(*) FROM task_discovery_checks WHERE state IN ('queued','running')))"
        result = self.command(['docker','exec','-e','PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=5000',PROJECT+'-postgres-1','psql','-X','-qAt','-U','financial','-d','financial','-c',sql])
        value = json.loads(result)
        if set(value) != {'runs','batches','actions','discovery'} or not all(isinstance(n,int) and n>=0 for n in value.values()):
            raise DeploymentFailure('Invalid read-only task status')
        return value

    def preflight(self, plan, image):
        self.verify_mode('normal')
        containers = self.inspect()
        if not all(c['State']['Running'] for c in containers.values()):
            raise DeploymentFailure('A platform service is already stopped; inspect before deployment')
        self.protected = {name: (c['Id'], c['State']['StartedAt']) for name,c in containers.items() if name not in {'/'+PROJECT+'-'+service+'-1' for service in plan.services}}
        if image:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}', image):raise DeploymentFailure('Invalid image reference')
            self.image_id = self.command(['docker','image','inspect','--format','{{.Id}}',image])
            if not re.fullmatch(r'sha256:[0-9a-f]{64}',self.image_id):raise DeploymentFailure('Image must already exist locally')
        self.command(self.compose()+['config','--quiet'])
        if plan.requires_idle:self.active_counts()

    def backup(self):
        stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
        self.release=ROOT/'releases'/('managed-'+stamp)
        self.release.mkdir(mode=0o700)
        for name in ('.env','compose.yaml','Caddyfile'):
            shutil.copy2(ROOT/name,self.release/(name+'.before'))
            os.chmod(self.release/(name+'.before'),0o600)

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

    def cutover(self, plan, image):
        if image:
            p=ROOT/'.env'
            lines=p.read_text().splitlines()
            if sum(line.startswith(plan.image_key+'=') for line in lines)!=1:
                raise DeploymentFailure('Image setting missing or duplicated')
            content='\n'.join(plan.image_key+'='+self.image_id if line.startswith(plan.image_key+'=') else line for line in lines)+'\n'
            temp=ROOT/('.env.deploy-'+uuid.uuid4().hex)
            with open(temp,'x',opener=lambda path,flags:os.open(path,flags,0o600)) as f:f.write(content)
            os.replace(temp,p)
        up=self.compose()+['up','-d','--no-deps','--no-build','--pull','never','--force-recreate','--timeout','120']
        if 'api' in plan.services:
            self.command(up+['--wait','--wait-timeout','120','api'],timeout=180)
        remaining=[service for service in plan.services if service!='api']
        if remaining:self.command(up+remaining,timeout=300)

    def healthy_sample(self):
        containers=self.inspect()
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
        self.command(self.compose()+['config','--quiet'])
        self.active_counts()
