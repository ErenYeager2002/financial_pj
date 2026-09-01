from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"


def _run_python(source: str, *, db_url: str, data_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["FINANCIAL_DATABASE_URL"] = db_url
    env["FINANCIAL_DATA_DIR"] = str(data_dir)
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _alembic(db_url: str, data_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["FINANCIAL_DATABASE_URL"] = db_url
    env["FINANCIAL_DATA_DIR"] = str(data_dir)
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_fresh_database_upgrades_to_head(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    data_dir = tmp_path / "data"
    db_url = f"sqlite:///{db_path.as_posix()}"

    result = _alembic(db_url, data_dir, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    assert db_path.is_file()

    code = (
        "from app.database import SessionLocal, engine\n"
        "from sqlalchemy import inspect, text\n"
        "with engine.connect() as c:\n"
        "    tables = set(inspect(c).get_table_names())\n"
        "    version = c.scalar(text('select version_num from alembic_version'))\n"
        "    columns = {item['name'] for item in inspect(c).get_columns('users')}\n"
        "print('tables:', len(tables), 'version:', version)\n"
        "assert 'runs' in tables and 'files' in tables and 'workflow_sessions' in tables\n"
        "assert {'clerk_user_id', 'clerk_organization_id'} <= columns\n"
        "assert version is not None and version != ''\n"
        "assert len(tables) >= 10\n"
    )
    verify = _run_python(code, db_url=db_url, data_dir=data_dir)
    assert verify.returncode == 0, verify.stderr
    assert "version:" in verify.stdout


def test_legacy_database_without_auth_tables_is_upgraded(tmp_path: Path) -> None:
    """复现真实旧库：只有基线迁移前的表，没有认证表。

    过去用最新 ORM create_all 构造“旧库”，实际上已包含认证表，掩盖了
    “stamp head 却不执行迁移”的缺陷。本测试用基线迁移精确构造旧库结构。
    """
    db_path = tmp_path / "legacy.db"
    data_dir = tmp_path / "data"
    db_url = f"sqlite:///{db_path.as_posix()}"

    baseline = _run_python(
        "from app.database import _baseline_revision\nprint(_baseline_revision())",
        db_url=db_url,
        data_dir=data_dir,
    )
    assert baseline.returncode == 0, baseline.stderr
    baseline_rev = baseline.stdout.strip()

    # 1) 只升级到基线迁移 → 得到历史结构，且不存在认证表。
    upgraded = _alembic(db_url, data_dir, "upgrade", baseline_rev)
    assert upgraded.returncode == 0, upgraded.stderr

    # 2) 在旧库写入一条历史文件记录。
    seed = (
        "from app.database import engine\n"
        "from sqlalchemy import inspect, text\n"
        "with engine.connect() as c:\n"
        "    tables = set(inspect(c).get_table_names())\n"
        "    assert 'users' not in tables and 'user_sessions' not in tables\n"
        "with engine.begin() as c:\n"
        "    c.execute(text(\n"
        "        \"INSERT INTO files (id, owner_id, department_id, kind, original_name, \"\n"
        "        \"stored_path, content_type, size_bytes, sha256, created_at) \"\n"
        "        \"VALUES (:id, :owner_id, :department_id, :kind, :original_name, \"\n"
        "        \":stored_path, :content_type, :size_bytes, :sha256, CURRENT_TIMESTAMP)\"), {\n"
        "        'id': 'legacy-file-0001', 'owner_id': 'demo-user', 'department_id': 'finance',\n"
        "        'kind': 'input', 'original_name': 'legacy.xlsx',\n"
        "        'stored_path': 'C:/legacy.xlsx',\n"
        "        'content_type': 'application/octet-stream', 'size_bytes': 42, 'sha256': '0'*64,\n"
        "    })\n"
    )
    seeded = _run_python(seed, db_url=db_url, data_dir=data_dir)
    assert seeded.returncode == 0, seeded.stderr

    # Alembic 建基线时会留下版本表；真实历史库没有该表，必须删除后再验证
    # init_db 的“有业务表、无 alembic_version”接管分支。
    remove_version = _run_python(
        "from sqlalchemy import text\n"
        "from app.database import engine\n"
        "with engine.begin() as c:\n"
        "    c.execute(text('DROP TABLE alembic_version'))\n",
        db_url=db_url,
        data_dir=data_dir,
    )
    assert remove_version.returncode == 0, remove_version.stderr

    # 3) 运行 init_db：旧库应先 stamp 基线，再 upgrade head，
    #    真正创建认证表，并保留历史数据。
    run_init = (
        "from app.database import init_db, SessionLocal\n"
        "from app.models import FileRecord\n"
        "init_db()\n"
        "with SessionLocal() as db:\n"
        "    row = db.get(FileRecord, 'legacy-file-0001')\n"
        "    assert row is not None and row.original_name == 'legacy.xlsx'\n"
        "print('upgraded')\n"
    )
    migrated = _run_python(run_init, db_url=db_url, data_dir=data_dir)
    assert migrated.returncode == 0, migrated.stderr
    assert "upgraded" in migrated.stdout

    # 4) 校验认证表已真实创建，alembic_version 位于 head。
    check = (
        "from alembic.script import ScriptDirectory\n"
        "from sqlalchemy import inspect, text\n"
        "from app.database import _alembic_config, engine\n"
        "with engine.connect() as c:\n"
        "    tables = set(inspect(c).get_table_names())\n"
        "    version = c.scalar(text('select version_num from alembic_version'))\n"
        "    assert {'users', 'user_sessions', 'user_skill_permissions'} <= tables\n"
        "    columns = {item['name'] for item in inspect(c).get_columns('users')}\n"
        "    assert {'clerk_user_id', 'clerk_organization_id'} <= columns\n"
        "    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()\n"
        "    assert version == head\n"
        "print('head:', version)\n"
    )
    verified = _run_python(check, db_url=db_url, data_dir=data_dir)
    assert verified.returncode == 0, verified.stderr
    assert "head:" in verified.stdout

    # 5) 管理员初始化必须可用（不再出现 no such table: users）。
    bootstrap = (
        "from app.database import SessionLocal, init_db\n"
        "from app.auth_service import bootstrap_admin, get_user_by_username\n"
        "init_db()\n"
        "with SessionLocal() as db:\n"
        "    username = bootstrap_admin(db)\n"
        "    assert get_user_by_username(db, username) is not None\n"
        "print('bootstrap-ok')\n"
    )
    bootstrapped = _run_python(bootstrap, db_url=db_url, data_dir=data_dir)
    assert bootstrapped.returncode == 0, bootstrapped.stderr
    assert "bootstrap-ok" in bootstrapped.stdout


def test_upgrade_downgrade_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "roundtrip.db"
    data_dir = tmp_path / "data"
    db_url = f"sqlite:///{db_path.as_posix()}"

    up = _alembic(db_url, data_dir, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    down = _alembic(db_url, data_dir, "downgrade", "base")
    assert down.returncode == 0, down.stderr
    up_again = _alembic(db_url, data_dir, "upgrade", "head")
    assert up_again.returncode == 0, up_again.stderr


def test_model_trace_downgrade_removes_pre_draft_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "model-trace-downgrade.db"
    data_dir = tmp_path / "data"
    db_url = f"sqlite:///{db_path.as_posix()}"

    upgraded = _alembic(db_url, data_dir, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    seeded = _run_python(
        "from sqlalchemy import text\n"
        "from app.database import engine\n"
        "with engine.begin() as connection:\n"
        "    connection.execute(text(\"\"\"\n"
        "        INSERT INTO model_trace_records (\n"
        "            id, owner_id, department_id, run_id, task_draft_id,\n"
        "            connection_id, purpose, provider, model, status,\n"
        "            duration_ms, input_tokens, output_tokens, failure_code, created_at\n"
        "        ) VALUES (\n"
        "            'pre-draft-trace', 'owner', 'finance', NULL, NULL,\n"
        "            'connection', 'assistant_recommendation', 'synthetic',\n"
        "            'synthetic', 'failed', 1, 2, 3, 'ValueError', CURRENT_TIMESTAMP\n"
        "        )\n"
        "    \"\"\"))\n",
        db_url=db_url,
        data_dir=data_dir,
    )
    assert seeded.returncode == 0, seeded.stderr

    downgraded = _alembic(db_url, data_dir, "downgrade", "b4c8e2f7190a")
    assert downgraded.returncode == 0, downgraded.stderr
    verified = _run_python(
        "from sqlalchemy import text\n"
        "from app.database import engine\n"
        "with engine.connect() as connection:\n"
        "    assert connection.scalar(text(\"select count(*) from "
        "model_trace_records where run_id is null and task_draft_id is null\")) == 0\n",
        db_url=db_url,
        data_dir=data_dir,
    )
    assert verified.returncode == 0, verified.stderr


def test_workflow_step_migration_preserves_existing_task_records(tmp_path: Path) -> None:
    db_path = tmp_path / "workflow-steps.db"
    data_dir = tmp_path / "data"
    db_url = f"sqlite:///{db_path.as_posix()}"
    previous_head = "a8b6d1c904fe"

    old_schema = _alembic(db_url, data_dir, "upgrade", previous_head)
    assert old_schema.returncode == 0, old_schema.stderr

    seed = _run_python(
        "from datetime import UTC, datetime\n"
        "from sqlalchemy import MetaData, Table\n"
        "from app.database import SessionLocal, engine\n"
        "from app.models import RunRecord\n"
        "with SessionLocal() as db:\n"
        "    db.add(RunRecord(\n"
        "        id='legacy-run', owner_id='user-1', department_id='finance',\n"
        "        skill_id='reconcile-bank', skill_name='reconcile-bank',\n"
        "        skill_version='1.0.0', skill_hash='a'*64,\n"
        "        manifest_path='tool.yaml', manifest_snapshot='{}',\n"
        "        adapter='python', worker_pool='python',\n"
        "    ))\n"
        "    workflows = Table('workflow_sessions', MetaData(), autoload_with=engine)\n"
        "    db.execute(workflows.insert().values(\n"
        "        id='legacy-workflow', owner_id='user-1', owner_name='',\n"
        "        department_id='finance', skill_id='ar-hexiao-daily',\n"
        "        skill_name='ar-hexiao-daily', skill_version='1.5.1',\n"
        "        skill_hash='b'*64, skill_commit='', concurrency_limit=1,\n"
        "        model_connection_id='model-1', model_provider='qwen',\n"
        "        model_name='qwen-plus', state='active', stage='awaiting_date',\n"
        "        reconciliation_date='', batch_sequence=0, previous_workflow_id='',\n"
        "        context_json='{}', files_json='{}', artifacts_json='[]',\n"
        "        progress=0, progress_message='', error_message='',\n"
        "        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),\n"
        "    ))\n"
        "    db.commit()\n",
        db_url=db_url,
        data_dir=data_dir,
    )
    assert seed.returncode == 0, seed.stderr

    upgraded = _alembic(db_url, data_dir, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    verify = _run_python(
        "from sqlalchemy import inspect, text\n"
        "from app.database import engine\n"
        "expected = {\n"
        "    'workflow_definitions', 'step_definitions', 'step_runs',\n"
        "    'artifact_bindings', 'approval_bindings',\n"
        "}\n"
        "with engine.connect() as connection:\n"
        "    inspector = inspect(connection)\n"
        "    tables = set(inspector.get_table_names())\n"
        "    assert expected <= tables\n"
        "    legacy_runs = connection.scalar(text(\"select count(*) from runs "
        "where id='legacy-run'\"))\n"
        "    assert legacy_runs == 1\n"
        "    assert connection.scalar(text(\"select count(*) from workflow_sessions "
        "where id='legacy-workflow'\")) == 1\n"
        "    step_run_columns = {column['name'] for column in inspector.get_columns('step_runs')}\n"
        "    assert {'run_id', 'workflow_session_id', 'owner_id', 'department_id'} <= "
        "step_run_columns\n"
        "    step_definition_columns = {column['name'] for column in "
        "inspector.get_columns('step_definitions')}\n"
        "    assert {'department_id', 'retryable'} <= step_definition_columns\n"
        "    workflow_checks = {item['name'] for item in "
        "inspector.get_check_constraints('workflow_definitions')}\n"
        "    assert 'ck_workflow_definitions_status' in workflow_checks\n"
        "    definition_checks = {item['name'] for item in "
        "inspector.get_check_constraints('step_definitions')}\n"
        "    assert {'ck_step_definitions_non_idempotent_no_retry', "
        "'ck_step_definitions_risk_level', 'ck_step_definitions_worker_pool'} "
        "<= definition_checks\n"
        "    run_checks = {item['name'] for item in "
        "inspector.get_check_constraints('step_runs')}\n"
        "    assert 'ck_step_runs_state' in run_checks\n"
        "    step_run_fks = {item['name'] for item in "
        "inspector.get_foreign_keys('step_runs')}\n"
        "    assert {'fk_step_runs_run_scope', 'fk_step_runs_step_department', "
        "'fk_step_runs_workflow_scope'} <= step_run_fks\n"
        "    artifact_fks = {item['name'] for item in "
        "inspector.get_foreign_keys('artifact_bindings')}\n"
        "    assert {'fk_artifact_bindings_step_scope', "
        "'fk_artifact_bindings_file_scope'} <= artifact_fks\n"
        "    approval_fks = {item['name'] for item in "
        "inspector.get_foreign_keys('approval_bindings')}\n"
        "    assert {'fk_approval_bindings_step_scope', "
        "'fk_approval_bindings_approval_scope'} <= approval_fks\n"
        "    workflow_uniques = {item['name'] for item in "
        "inspector.get_unique_constraints('workflow_definitions')}\n"
        "    assert 'uq_workflow_definitions_department_key_version' in workflow_uniques\n"
        "    step_indexes = {item['name'] for item in inspector.get_indexes('step_runs')}\n"
        "    expected_indexes = {'ix_step_runs_owner_state', "
        "'ix_step_runs_department_state'}\n"
        "    assert expected_indexes <= step_indexes\n"
        "    assert 'ux_runs_id_owner_department' in "
        "{item['name'] for item in inspector.get_indexes('runs')}\n"
        "    assert 'ux_workflow_sessions_id_owner_department' in "
        "{item['name'] for item in inspector.get_indexes('workflow_sessions')}\n"
        "    assert 'ux_files_id_owner_department' in "
        "{item['name'] for item in inspector.get_indexes('files')}\n"
        "    assert 'ux_approval_records_id_requester_department' in "
        "{item['name'] for item in inspector.get_indexes('approval_records')}\n",
        db_url=db_url,
        data_dir=data_dir,
    )
    assert verify.returncode == 0, verify.stderr

    downgraded = _alembic(db_url, data_dir, "downgrade", previous_head)
    assert downgraded.returncode == 0, downgraded.stderr

    verify_down = _run_python(
        "from sqlalchemy import inspect, text\n"
        "from app.database import engine\n"
        "removed = {\n"
        "    'workflow_definitions', 'step_definitions', 'step_runs',\n"
        "    'artifact_bindings', 'approval_bindings',\n"
        "}\n"
        "with engine.connect() as connection:\n"
        "    assert not (removed & set(inspect(connection).get_table_names()))\n"
        "    legacy_runs = connection.scalar(text(\"select count(*) from runs "
        "where id='legacy-run'\"))\n"
        "    assert legacy_runs == 1\n"
        "    assert connection.scalar(text(\"select count(*) from workflow_sessions "
        "where id='legacy-workflow'\")) == 1\n",
        db_url=db_url,
        data_dir=data_dir,
    )
    assert verify_down.returncode == 0, verify_down.stderr


def test_workflow_binding_migration_blocks_raw_mutations(tmp_path: Path) -> None:
    db_path = tmp_path / "immutable-bindings.db"
    data_dir = tmp_path / "data"
    db_url = f"sqlite:///{db_path.as_posix()}"

    upgraded = _alembic(db_url, data_dir, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    verify = _run_python(
        "from datetime import UTC, datetime, timedelta\n"
        "from sqlalchemy import text\n"
        "from sqlalchemy.exc import DBAPIError\n"
        "from app.auth_models import User\n"
        "from app.database import SessionLocal, engine\n"
        "from app.models import (ApprovalBinding, ApprovalRecord, ArtifactBinding, "
        "FileRecord, RunRecord, StepDefinition, StepRun, WorkflowDefinition)\n"
        "with SessionLocal() as db:\n"
        "    db.add(User(id='immutable-owner', username='immutable-owner', "
        "password_hash='unused', role='skill_admin', department_id='finance'))\n"
        "    db.add(RunRecord(id='immutable-run', owner_id='immutable-owner', "
        "department_id='finance', skill_id='reconcile-bank', skill_name='reconcile-bank', "
        "skill_version='1.0.0', skill_hash='a'*64, manifest_path='tool.yaml', "
        "manifest_snapshot='{}', adapter='python', worker_pool='python'))\n"
        "    db.add(FileRecord(id='immutable-file', owner_id='immutable-owner', "
        "department_id='finance', kind='input', original_name='source.xlsx', "
        "stored_path='source.xlsx', size_bytes=1, sha256='b'*64))\n"
        "    db.flush()\n"
        "    db.add(ApprovalRecord(id='immutable-approval', resource_type='run', "
        "resource_id='immutable-run', run_id='immutable-run', department_id='finance', "
        "skill_id='reconcile-bank', snapshot_sha256='c'*64, preview_sha256='d'*64, "
        "snapshot_json='{}', preview_json='{}', requested_by='immutable-owner', "
        "expires_at=datetime.now(UTC)+timedelta(hours=1)))\n"
        "    db.add(WorkflowDefinition(id='immutable-definition', department_id='finance', "
        "workflow_key='immutable-flow', name='immutable-flow', version='1', "
        "status='published', skill_id='reconcile-bank', skill_version='1.0.0', "
        "skill_hash='a'*64, created_by='immutable-owner'))\n"
        "    db.flush()\n"
        "    db.add(StepDefinition(id='immutable-step', "
        "workflow_definition_id='immutable-definition', department_id='finance', "
        "step_key='validate', name='validate', step_type='file_validation', position=0, "
        "timeout_seconds=30, max_attempts=1, risk_level='read_only', "
        "worker_pool='python'))\n"
        "    db.flush()\n"
        "    db.add(StepRun(id='immutable-step-run', step_definition_id='immutable-step', "
        "run_id='immutable-run', owner_id='immutable-owner', department_id='finance'))\n"
        "    db.flush()\n"
        "    db.add(ArtifactBinding(id='immutable-artifact-binding', "
        "step_run_id='immutable-step-run', file_id='immutable-file', "
        "owner_id='immutable-owner', department_id='finance', direction='input', "
        "role='source', sha256='b'*64))\n"
        "    db.add(ApprovalBinding(id='immutable-approval-binding', "
        "step_run_id='immutable-step-run', approval_record_id='immutable-approval', "
        "owner_id='immutable-owner', department_id='finance', snapshot_sha256='c'*64))\n"
        "    db.commit()\n"
        "for table_name, column_name in ((\"artifact_bindings\", \"metadata_json\"), "
        "(\"approval_bindings\", \"snapshot_sha256\")):\n"
        "    try:\n"
        "        with engine.begin() as connection:\n"
        "            statement = f\"UPDATE {table_name} SET {column_name}='changed'\"\n"
        "            connection.execute(text(statement))\n"
        "    except DBAPIError:\n"
        "        continue\n"
        "    raise AssertionError(f'{table_name} accepted a raw UPDATE')\n"
        "for table_name in ('artifact_bindings', 'approval_bindings'):\n"
        "    try:\n"
        "        with engine.begin() as connection:\n"
        "            connection.execute(text(f'DELETE FROM {table_name}'))\n"
        "    except DBAPIError:\n"
        "        continue\n"
        "    raise AssertionError(f'{table_name} accepted a raw DELETE')\n"
        "try:\n"
        "    with engine.begin() as connection:\n"
        "        connection.execute(text(\"UPDATE step_runs SET can_retry=1 "
        "WHERE id='immutable-step-run'\"))\n"
        "except DBAPIError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('non-idempotent step run accepted can_retry')\n",
        db_url=db_url,
        data_dir=data_dir,
    )
    assert verify.returncode == 0, verify.stderr


def test_fetched_bundle_migration_backfills_historical_previews_and_roundtrips(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "fetched-bundles.db"
    data_dir = tmp_path / "data"
    db_url = f"sqlite:///{db_path.as_posix()}"
    previous_head = "a6b7c8d9e0f1"

    old_schema = _alembic(db_url, data_dir, "upgrade", previous_head)
    assert old_schema.returncode == 0, old_schema.stderr

    seed = _run_python(
        "from datetime import UTC, datetime\n"
        "from sqlalchemy import MetaData, Table\n"
        "from app.database import engine\n"
        "metadata = MetaData()\n"
        "workflows = Table('workflow_sessions', metadata, autoload_with=engine)\n"
        "previews = Table('workflow_fetched_data_previews', metadata, autoload_with=engine)\n"
        "now = datetime.now(UTC)\n"
        "with engine.begin() as connection:\n"
        "    connection.execute(workflows.insert().values(\n"
        "        id='historical-workflow', owner_id='owner-1', owner_name='owner',\n"
        "        department_id='finance', skill_id='ar-hexiao-daily',\n"
        "        skill_name='应收核销日清', skill_version='1.6.12', skill_hash='a'*64,\n"
        "        skill_commit='', concurrency_limit=1, model_connection_id='model-1',\n"
        "        model_provider='platform', model_name='deterministic', state='succeeded',\n"
        "        stage='completed', reconciliation_date='2026-08-20', batch_id=None,\n"
        "        batch_sequence=0, previous_workflow_id='', material_set_id=None,\n"
        "        context_json='{}', files_json='{}', artifacts_json='[]', progress=100,\n"
        "        progress_message='completed', error_message='', created_at=now, updated_at=now,\n"
        "    ))\n"
        "    connection.execute(previews.insert().values(\n"
        "        id='historical-preview', workflow_id='historical-workflow',\n"
        "        reconciliation_date='2026-08-20', revision='b'*64, summary_json='{}',\n"
        "        created_at=now,\n"
        "    ))\n",
        db_url=db_url,
        data_dir=data_dir,
    )
    assert seed.returncode == 0, seed.stderr

    upgraded = _alembic(db_url, data_dir, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    verify = _run_python(
        "import json\n"
        "from sqlalchemy import inspect, text\n"
        "from app.database import engine\n"
        "with engine.connect() as connection:\n"
        "    inspector = inspect(connection)\n"
        "    tables = set(inspector.get_table_names())\n"
        "    assert {'fetched_bundles', 'fetched_bundle_files'} <= tables\n"
        "    bundle_columns = {item['name'] for item in "
        "inspector.get_columns('fetched_bundles')}\n"
        "    assert {'purge_attempts', 'purge_retry_at'} <= bundle_columns\n"
        "    workflow_columns = {item['name'] for item in "
        "inspector.get_columns('workflow_sessions')}\n"
        "    preview_columns = {item['name'] for item in "
        "inspector.get_columns('workflow_fetched_data_previews')}\n"
        "    assert 'fetched_bundle_id' in workflow_columns\n"
        "    assert 'bundle_id' in preview_columns\n"
        "    row = connection.execute(text(\"\"\"\n"
        "        SELECT id, state, source_type, dates_json, raw_available,\n"
        "               preview_available, replayable\n"
        "        FROM fetched_bundles WHERE source_workflow_id='historical-workflow'\n"
        "    \"\"\")).mappings().one()\n"
        "    assert row['state'] == 'raw_purged' and row['source_type'] == 'live'\n"
        "    assert json.loads(row['dates_json']) == ['2026-08-20']\n"
        "    assert not row['raw_available'] and row['preview_available'] "
        "and not row['replayable']\n"
        "    assert connection.scalar(text(\"select fetched_bundle_id from workflow_sessions "
        "where id='historical-workflow'\")) == row['id']\n"
        "    assert connection.scalar(text(\"select bundle_id from "
        "workflow_fetched_data_previews where id='historical-preview'\")) == row['id']\n"
        "    checks = {item['name'] for item in "
        "inspector.get_check_constraints('fetched_bundles')}\n"
        "    assert {'ck_fetched_bundles_state', 'ck_fetched_bundles_raw_replayable', "
        "'ck_fetched_bundles_purged_flags', 'ck_fetched_bundles_purge_attempts'} <= checks\n",
        db_url=db_url,
        data_dir=data_dir,
    )
    assert verify.returncode == 0, verify.stderr

    downgraded = _alembic(db_url, data_dir, "downgrade", previous_head)
    assert downgraded.returncode == 0, downgraded.stderr
    verify_down = _run_python(
        "from sqlalchemy import inspect, text\n"
        "from app.database import engine\n"
        "with engine.connect() as connection:\n"
        "    inspector = inspect(connection)\n"
        "    tables = set(inspector.get_table_names())\n"
        "    assert 'fetched_bundles' not in tables and 'fetched_bundle_files' not in tables\n"
        "    assert 'fetched_bundle_id' not in {item['name'] for item in "
        "inspector.get_columns('workflow_sessions')}\n"
        "    assert 'bundle_id' not in {item['name'] for item in "
        "inspector.get_columns('workflow_fetched_data_previews')}\n"
        "    assert connection.scalar(text(\"select count(*) from "
        "workflow_fetched_data_previews where id='historical-preview'\")) == 1\n",
        db_url=db_url,
        data_dir=data_dir,
    )
    assert verify_down.returncode == 0, verify_down.stderr
