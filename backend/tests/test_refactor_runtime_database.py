from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, event, inspect, text

from app.infrastructure.database.migrate import DatabaseTarget, migrate_database
from app.infrastructure.database.runtime_check import check_runtime_database
from app.infrastructure.database.schema_check import SchemaCompatibilityError


@pytest.fixture
def database(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "runtime.db"))
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "backend/alembic"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    migrate_database(engine, cfg, expected_target=DatabaseTarget.from_engine(engine), expected_revision=None, target_revision=head)
    try:
        yield engine, head
    finally:
        engine.dispose()


def test_parallel_runtime_checks_do_not_issue_ddl_or_dml(database):
    engine, head = database
    statements = []
    event.listen(engine, "before_cursor_execute", lambda c, cur, sql, p, ctx, many: statements.append(sql))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: check_runtime_database(engine).revision, range(20)))
    assert results == [head] * 20
    assert statements and all(sql.lstrip().upper().startswith(("SELECT", "PRAGMA")) for sql in statements)


def test_missing_seed_is_not_repaired_by_runtime(database):
    engine, _ = database
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM scheduler_locks WHERE name='global'"))
    with pytest.raises(SchemaCompatibilityError, match="DATABASE_REQUIRED_SEED_MISSING"):
        check_runtime_database(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM scheduler_locks")) == 0


def test_empty_database_is_not_migrated_by_runtime(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "empty.db"))
    try:
        with pytest.raises(SchemaCompatibilityError, match="DATABASE_NOT_MIGRATED"):
            check_runtime_database(engine)
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


def test_unknown_revision_is_not_stamped_or_upgraded(database):
    engine, _ = database
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='unknown'"))
    with pytest.raises(SchemaCompatibilityError, match="DATABASE_REVISION_UNSUPPORTED"):
        check_runtime_database(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "unknown"


def test_worker_refuses_to_poll_when_database_is_not_ready(tmp_path, monkeypatch):
    from app import database as module, worker
    engine = create_engine("sqlite:///" + str(tmp_path / "worker-empty.db"))
    monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(worker, "run_once", lambda *args: pytest.fail("Worker polled an unready database"))
    try:
        with pytest.raises(SchemaCompatibilityError, match="DATABASE_NOT_MIGRATED"):
            worker.run_loop(("standard",), "synthetic")
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


def test_discovery_worker_refuses_to_poll_when_database_is_not_ready(tmp_path, monkeypatch):
    from app import database as module, task_discovery_worker as worker
    engine = create_engine("sqlite:///" + str(tmp_path / "discovery-empty.db"))
    monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(worker.signal, "signal", lambda *args: None)
    monkeypatch.setattr(worker, "run_discovery_tick", lambda *args: pytest.fail("Discovery polled an unready database"))
    try:
        with pytest.raises(SchemaCompatibilityError, match="DATABASE_NOT_MIGRATED"):
            worker.main()
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


def test_api_lifespan_refuses_to_serve_when_database_is_not_ready(tmp_path, monkeypatch):
    import asyncio
    from app import database as module, main
    engine = create_engine("sqlite:///" + str(tmp_path / "api-empty.db"))
    monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(main.registry, "refresh", lambda: pytest.fail("API initialized services before database readiness"))

    async def start():
        async with main.lifespan(main.app):
            pytest.fail("API served an unready database")

    try:
        with pytest.raises(SchemaCompatibilityError, match="DATABASE_NOT_MIGRATED"):
            asyncio.run(start())
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("revision", ["f1a2b3c4d5e6", "f2a3b4c5d6e7"])
def test_pre_submission_revisions_are_rejected_without_changes(database, revision):
    engine, _ = database
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num=:revision"), {"revision": revision})
    with pytest.raises(SchemaCompatibilityError, match="DATABASE_REVISION_UNSUPPORTED"):
        check_runtime_database(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision


@pytest.mark.parametrize("table,column", [
    ("runs", "heartbeat_at"),
    ("runs", "source_command_id"),
    ("idempotency_requests", "reservation_token"),
    ("idempotency_requests", "prepared_payload_json"),
])
def test_current_revision_with_missing_runtime_column_is_not_ready(database, table, column):
    engine, revision = database
    with engine.begin() as connection:
        connection.execute(text(f'ALTER TABLE "{table}" DROP COLUMN "{column}"'))
    with pytest.raises(SchemaCompatibilityError, match="DATABASE_REQUIRED_COLUMNS_MISSING"):
        check_runtime_database(engine)
    with engine.connect() as connection:
        assert column not in {item["name"] for item in inspect(connection).get_columns(table)}
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision



def test_worker_processes_start_concurrently_without_schema_writes(database, tmp_path):
    import json
    import os
    import subprocess
    import sys

    engine, _ = database
    environment = {
        **os.environ,
        "FINANCIAL_DATABASE_URL": str(engine.url),
        "FINANCIAL_DATA_DIR": str(tmp_path / "worker-data"),
        "FINANCIAL_ENV": "test",
        "FINANCIAL_TASK_DISCOVERY_ENABLED": "false",
        "FINANCIAL_AR_HEXIAO_EXECUTION_ENABLED": "false",
    }
    source = """import json,sqlite3
from sqlalchemy import event
from app.database import engine
from app.worker import main
observed={'connections':0,'ddl_attempts':0}
blocked={getattr(sqlite3,name) for name in dir(sqlite3) if name.startswith(('SQLITE_CREATE_','SQLITE_DROP_'))}|{sqlite3.SQLITE_ALTER_TABLE,sqlite3.SQLITE_ATTACH}
@event.listens_for(engine,'connect')
def guard(connection,record):
 observed['connections']+=1
 def authorize(action,arg1,arg2,database,source):
  if action in blocked:
   observed['ddl_attempts']+=1
   return sqlite3.SQLITE_DENY
  return sqlite3.SQLITE_OK
 connection.set_authorizer(authorize)
main()
print('WORKER_RESULT:'+json.dumps(observed),flush=True)
"""
    children = []
    try:
        for number in range(3):
            children.append(subprocess.Popen(
                [sys.executable, "-B", "-c", source, "--once", "--pools", "python", "--worker-id", f"synthetic-worker-{number}"],
                env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ))
        for child in children:
            stdout, stderr = child.communicate(timeout=25)
            assert child.returncode == 0, stderr
            line = next(line for line in stdout.splitlines() if line.startswith("WORKER_RESULT:"))
            observed = json.loads(line.split(":", 1)[1])
            assert observed["connections"] >= 1 and observed["ddl_attempts"] == 0
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM runs")) == 0
            assert connection.scalar(text("SELECT count(*) FROM workflow_actions")) == 0
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
