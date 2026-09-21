"""Exercise the built PR-01 image against a disposable, network-isolated PostgreSQL."""
import argparse
import json
import re
import time
import uuid
from postgres_baseline import LABEL, command, cleanup

PROBE = r"""
import json, os, subprocess, sys
from sqlalchemy import create_engine, text
from alembic import command
from app.database import _alembic_config
from app.infrastructure.database.runtime_check import check_runtime_database
url = os.environ['FINANCIAL_DATABASE_URL']
engine = create_engine(url)
with engine.begin() as connection:
    config = _alembic_config()
    config.attributes['connection'] = connection
    command.upgrade(config, 'f1a2b3c4d5e6')
for expected in ['f1a2b3c4d5e6', 'f2a3b4c5d6e7']:
    args = [sys.executable, '-B', '-m', 'app.infrastructure.database.cli', '--dialect', 'postgresql',
        '--host', '127.0.0.1', '--port', '5432', '--database', 'financial_refactor_image',
        '--expected-revision', expected, '--target-revision', 'f2a3b4c5d6e7']
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('IMAGE_MIGRATION_FAILED: ' + result.stdout)
check_runtime_database(engine)
with engine.begin() as connection:
    assert connection.scalar(text("SELECT count(*) FROM scheduler_locks WHERE name='global'")) == 1
    connection.execute(text("CREATE ROLE synthetic_readonly LOGIN PASSWORD 'synthetic-readonly'"))
    connection.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
    connection.execute(text("GRANT USAGE ON SCHEMA public TO synthetic_readonly"))
    connection.execute(text("GRANT SELECT ON ALL TABLES IN SCHEMA public TO synthetic_readonly"))
readonly = create_engine('postgresql+psycopg://synthetic_readonly:synthetic-readonly@127.0.0.1:5432/financial_refactor_image')
with readonly.connect() as connection:
    assert not connection.scalar(text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')"))
check_runtime_database(readonly)
readonly.dispose()
engine.dispose()
print(json.dumps({'previous_revision': 'f1a2b3c4d5e6', 'target_revision': 'f2a3b4c5d6e7',
    'upgrade': 'passed', 'repeat_migration': 'passed', 'single_seed': 'passed', 'no_ddl_role_runtime_check': 'passed'}))
"""


TRANSACTION_PROBE = r"""
from datetime import UTC, datetime
from types import SimpleNamespace
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.auth_models import User, UserSkillPermission
from app.models import RunRecord, RunEvent, StepRun
from app.run_service import PreparedRun, persist_run
from app import worker

manifest = {
 'schema_version':1,'id':'synthetic','name':'Synthetic','version':'1.0.0',
 'status':'published','description':'Synthetic image transaction probe',
 'input_schema':{'type':'object'},'output_schema':{'type':'object'},
 'handler':{'adapter':'python','entrypoint':'synthetic.py','worker_pool':'python'},
 'runtime':{'timeout_seconds':30,'memory_mb':128,'concurrency_limit':1},
 'risk':{'level':'read_only','requires_confirmation':False},
}
with Session(engine) as db:
 db.add(User(id='image-synthetic-owner',username='image-synthetic-owner',password_hash='unusable-synthetic'))
 db.flush()
 db.add(UserSkillPermission(id='image-synthetic-grant',user_id='image-synthetic-owner',skill_id='synthetic',can_run=True))
 db.commit()
def prepare():
 return PreparedRun(RunRecord(id='image-synthetic-run',owner_id='image-synthetic-owner',department_id='finance',
  skill_id='synthetic',skill_name='Synthetic',skill_version='1.0.0',skill_hash='a'*64,
  manifest_path='/tmp/synthetic/tool.yaml',manifest_snapshot=json.dumps(manifest),
  adapter='python',worker_pool='python',state='queued',progress=0,
  parameters_json='{}',files_json='{}',queued_at=datetime.now(UTC)),None,{})
with Session(engine) as db:
 persist_run(db,prepare())
 db.flush()
 db.rollback()
with Session(engine) as db:
 assert db.scalar(select(func.count()).select_from(RunRecord)) == 0
 assert db.scalar(select(func.count()).select_from(StepRun)) == 0
 assert db.scalar(select(func.count()).select_from(RunEvent)) == 0
 persist_run(db,prepare())
 db.commit()
def fail_after_progress(ctx):
 ctx.emit('synthetic progress',progress=37)
 ctx.run.result_json='{"unpublished":true}'
 ctx.db.flush()
 raise RuntimeError('synthetic candidate failure')
worker.get_adapter=lambda name:SimpleNamespace(execute=fail_after_progress)
worker.run_root=lambda *args:__import__('pathlib').Path('/tmp/image-synthetic-work')
with Session(engine) as db:
 run=worker.claim_next_run(db,('python',),'image-synthetic-worker')
 assert run is not None and run.attempt_count==1
 worker.execute_run(db,run)
with Session(engine) as db:
 run=db.get(RunRecord,'image-synthetic-run')
 assert run.state=='failed' and run.result_json=='{}' and run.progress==37
 assert db.scalar(select(func.count()).select_from(RunEvent))==4
engine.dispose()
print(json.dumps({'candidate_transaction_rollback':'passed','candidate_claim':'passed',
 'candidate_independent_progress':'passed','candidate_failure_discards_unpublished_result':'passed'}))
"""


RECOVERY_PROBE = r"""
from app.settings import settings
from app.modules.execution.idempotency import Scope, Operation, reserve, mark_prepared, bind
from app.modules.execution.idempotency_models import IdempotencyRequest
from app.modules.execution.canonical import request_fingerprint
from app.modules.execution.submission import prepare_submission, persist_submission, SubmissionRecoveryOnly
assert settings.submission_replay_only is True
scope=Scope('image-synthetic-owner','finance',Operation.RUN_CREATE)
submitted={'synthetic':'recovery'}
pin={'revision':'image-test'}
fingerprint=request_fingerprint(operation=scope.operation.value,owner_id=scope.owner_id,department_id=scope.department_id,submitted=submitted,pinned_revision=pin)
def no_work(*args): raise AssertionError('Recovery attempted new work')
options=dict(scope=scope,key='bound',submitted=submitted,authorize=lambda db:None,select_pin=no_work,prepare=no_work,replay_only=settings.submission_replay_only)
try:
 prepare_submission(engine,**options)
except SubmissionRecoveryOnly: pass
else: raise AssertionError('New submission accepted')
with Session(engine) as db:
 assert db.scalar(select(func.count()).select_from(IdempotencyRequest))==0
 row,_=reserve(db,scope,'bound',fingerprint=fingerprint,pinned_revision=pin)
 token=row.reservation_token
 mark_prepared(db,scope,'bound',token,{'synthetic':'frozen'})
 bind(db,scope,'bound',token,execution_kind='run',execution_id='image-synthetic-run')
 db.commit()
ticket=prepare_submission(engine,**options)
with Session(engine) as db:
 run=persist_submission(db,ticket,authorize=lambda db:None,validate_prepared=no_work,load_bound=lambda db,kind,rid:db.get(RunRecord,rid),replay_only=settings.submission_replay_only)
 assert run.id=='image-synthetic-run'
 db.commit()
 assert db.scalar(select(func.count()).select_from(RunRecord))==1
print(json.dumps({'recovery_image_default':'replay-only','new_submission':'blocked_without_receipt','bound_replay':'passed','new_run_created':False}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--transactions', action='store_true')
    parser.add_argument('--recovery-mode', action='store_true', help='Verify degraded image policy with synthetic bound receipt')
    parser.add_argument('--previous-revision', choices=['f1a2b3c4d5e6','f2a3b4c5d6e7','f3a4b5c6d7e8'], default='f1a2b3c4d5e6')
    parser.add_argument('--target-revision', choices=['f2a3b4c5d6e7','f3a4b5c6d7e8','f4b5c6d7e8f9'], default='f2a3b4c5d6e7')
    args = parser.parse_args()
    if args.recovery_mode and not args.transactions:
        parser.error("recovery-mode requires transactions probe fixture")
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', args.image):
        parser.error('requires exact already-built image ID')
    probe = PROBE.replace('f1a2b3c4d5e6', '__SOURCE_REVISION__').replace('f2a3b4c5d6e7', args.target_revision).replace('__SOURCE_REVISION__', args.previous_revision)
    identity = uuid.uuid4().hex
    database = 'financial-refactor-image-pg-' + identity[:12]
    client = 'financial-refactor-image-client-' + identity[:12]
    try:
        result = command(['docker', 'run', '-d', '--name', database, '--label', LABEL+'='+identity,
            '--network', 'none', '--tmpfs', '/var/lib/postgresql/data:rw,size=512m', '--tmpfs', '/var/run/postgresql',
            '-e', 'POSTGRES_DB=financial_refactor_image', '-e', 'POSTGRES_USER=synthetic', '-e', 'POSTGRES_PASSWORD=synthetic-only',
            'docker.m.daocloud.io/library/postgres:16-alpine'], timeout=60)
        if result.returncode:
            raise RuntimeError('IMAGE_TEST_DATABASE_START_FAILED')
        for _ in range(30):
            ready = command(['docker', 'exec', database, 'pg_isready', '-U', 'synthetic', '-d', 'financial_refactor_image'], timeout=5)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('IMAGE_TEST_DATABASE_NOT_READY')
        result = command(['docker', 'run', '--rm', '--name', client, '--label', LABEL+'='+identity,
            '--read-only', '--network', 'container:'+database, '--tmpfs', '/tmp:rw,size=128m',
            '-e', 'FINANCIAL_DATABASE_URL=postgresql+psycopg://synthetic:synthetic-only@127.0.0.1:5432/financial_refactor_image',
            '--entrypoint', 'python', args.image, '-B', '-c', probe + (TRANSACTION_PROBE if args.transactions else '') + (RECOVERY_PROBE if args.recovery_mode else '')], timeout=90)
        if result.returncode:
            raise RuntimeError('IMAGE_POSTGRES_CHECK_FAILED: '+result.stderr[-3000:])
        print(result.stdout.strip())
    finally:
        errors = []
        for target in [client, database]:
            try:
                cleanup(target, identity)
            except Exception as error:
                errors.append(error)
        if errors:
            raise RuntimeError('IMAGE_TEST_CLEANUP_INCOMPLETE') from errors[0]


if __name__ == '__main__':
    main()
