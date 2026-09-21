"""Must run only through the disposable PostgreSQL refactor harness."""
import os
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.infrastructure.database.migration_lock import ADVISORY_KEY, MigrationLockError, migration_lock
from app.infrastructure.database.schema_check import check_schema_compatible


@pytest.fixture
def engine():
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/refactor"))
    from verify_isolation import verify
    url = os.environ["REFACTOR_POSTGRES_URL"]
    verify({**os.environ, "FINANCIAL_DATABASE_URL": url})
    assert url.startswith("postgresql+psycopg://")
    value = create_engine(url, pool_size=3)
    try:
        yield value
    finally:
        value.dispose()


def test_pg_lock_uses_same_session_across_commit_and_excludes_other_process(engine):
    child = """import os,sys
from sqlalchemy import create_engine
from app.infrastructure.database.migration_lock import migration_lock,MigrationLockError
engine=create_engine(os.environ['FINANCIAL_DATABASE_URL'])
try:
 with engine.connect() as connection:
  with migration_lock(connection,timeout=0.1):pass
except MigrationLockError as error:
 print(str(error));sys.exit(7)
finally:engine.dispose()
"""
    with engine.connect() as connection:
        with migration_lock(connection, timeout=0):
            pid = connection.scalar(text("SELECT pg_backend_pid()"))
            connection.commit()
            assert connection.scalar(text("SELECT pg_backend_pid()")) == pid
            connection.commit()
            result = subprocess.run([sys.executable, "-B", "-c", child], capture_output=True, text=True, timeout=10, env={**os.environ, "FINANCIAL_DATABASE_URL": str(engine.url.render_as_string(hide_password=False))})
            assert result.returncode == 7 and "MIGRATION_LOCK_TIMEOUT" in result.stdout
        result = subprocess.run([sys.executable, "-B", "-c", child], capture_output=True, text=True, timeout=10, env={**os.environ, "FINANCIAL_DATABASE_URL": str(engine.url.render_as_string(hide_password=False))})
        assert result.returncode == 0, "Competing process could not acquire released lock"


def test_pg_failure_releases_lock_and_lost_lock_invalidates_connection(engine):
    with engine.connect() as connection:
        with pytest.raises(RuntimeError, match="synthetic failure"):
            with migration_lock(connection):
                raise RuntimeError("synthetic failure")
        with engine.connect() as other:
            with migration_lock(other, timeout=0):
                pass
        with pytest.raises(MigrationLockError, match="MIGRATION_LOCK_LOST"):
            with migration_lock(connection):
                assert connection.scalar(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_KEY})
                connection.commit()
        assert connection.invalidated


def test_pg_schema_check_works_for_role_without_ddl_privilege(engine):
    # Unique disposable schema/role; no public schema permissions are altered.
    name = "refactor_" + uuid4().hex[:12]
    with engine.connect() as connection:
        connection.execute(text(f'CREATE ROLE "{name}" NOLOGIN'))
        connection.execute(text(f'CREATE SCHEMA "{name}"'))
        connection.execute(text(f'CREATE TABLE "{name}".alembic_version (version_num VARCHAR(32) PRIMARY KEY)'))
        connection.execute(text(f"INSERT INTO \"{name}\".alembic_version VALUES ('supported')"))
        connection.execute(text(f'GRANT USAGE ON SCHEMA "{name}" TO "{name}"'))
        connection.execute(text(f'GRANT SELECT ON "{name}".alembic_version TO "{name}"'))
        connection.commit()
        try:
            connection.execute(text(f'SET ROLE "{name}"'))
            connection.execute(text(f'SET search_path TO "{name}"'))
            connection.commit()
            assert check_schema_compatible(connection, supported_revisions={"supported"}).revision == "supported"
            connection.commit()
            with pytest.raises(DBAPIError):
                connection.execute(text('CREATE TABLE forbidden (id INTEGER)'))
            connection.rollback()
        finally:
            connection.execute(text('RESET ROLE'))
            connection.execute(text('RESET search_path'))
            connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
            connection.execute(text(f'DROP ROLE "{name}"'))
            connection.commit()


def test_pg_full_migration_uses_lock_connection_and_seeds_once(engine):
    from pathlib import Path
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from app.infrastructure.database.migrate import DatabaseTarget, migrate_database
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "backend/alembic"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    target = DatabaseTarget.from_engine(engine)
    first = migrate_database(engine, cfg, expected_target=target, expected_revision=None, target_revision=head)
    assert first.upgraded
    repeated = migrate_database(engine, cfg, expected_target=target, expected_revision=head, target_revision=head)
    assert not repeated.upgraded
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM scheduler_locks WHERE name='global'")) == 1
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == head

@pytest.mark.parametrize("wrong_timezone", [False, True])
def test_pg_existing_assistant_turns_preserves_rows_and_rejects_timezone_drift(engine, wrong_timezone):
    from datetime import UTC, datetime
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from app.models import AssistantTurn

    name = "refactor_turns_" + uuid4().hex[:12]
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "backend/alembic"))
    with engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{name}"'))
        connection.execute(text(f'SET search_path TO "{name}"'))
        connection.commit()
        try:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "e0f1a2b3c4d5")
            AssistantTurn.__table__.create(connection)
            connection.execute(AssistantTurn.__table__.insert().values(
                owner_id="synthetic", department_id="synthetic", session_id="session",
                turn_id="preserved", lease_expires_at=datetime.now(UTC),
            ))
            if wrong_timezone:
                connection.execute(text("ALTER TABLE assistant_turns ALTER COLUMN lease_expires_at TYPE TIMESTAMP WITHOUT TIME ZONE"))
            connection.commit()
            if wrong_timezone:
                with pytest.raises(RuntimeError, match="TIMEZONE_INCOMPATIBLE"):
                    command.upgrade(cfg, "f1a2b3c4d5e6")
                connection.rollback()
            else:
                command.upgrade(cfg, "f1a2b3c4d5e6")
                connection.commit()
            assert connection.scalar(text("SELECT turn_id FROM assistant_turns")) == "preserved"
            expected = "e0f1a2b3c4d5" if wrong_timezone else "f1a2b3c4d5e6"
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == expected
        finally:
            connection.rollback()
            cfg.attributes.pop("connection", None)
            connection.execute(text("RESET search_path"))
            connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
            connection.commit()


def test_pg_concurrent_bootstrap_has_one_account_and_matching_generated_password(engine, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker
    from app import auth_service
    from app.auth_models import User

    name = "refactor_bootstrap_" + uuid4().hex[:12]
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{name}"'))
    scoped = engine.execution_options(schema_translate_map={None: name})
    factory = sessionmaker(scoped)
    monkeypatch.setattr(auth_service, "settings", SimpleNamespace(
        bootstrap_admin_username="synthetic-pg-admin", bootstrap_admin_password="", data_dir=tmp_path,
    ))
    try:
        User.__table__.create(scoped)
        def initialize(_):
            with factory() as db:
                return auth_service.bootstrap_admin(db)
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert list(pool.map(initialize, range(16))) == ["synthetic-pg-admin"] * 16
        token = tmp_path / "initial_admin_password.txt"
        password = token.read_text().rstrip().split("：", 1)[1]
        assert token.stat().st_mode & 0o777 == 0o600
        with factory() as db:
            users = db.scalars(select(User)).all()
            assert len(users) == 1 and users[0].must_change_password
            verified = auth_service.verify_password(users[0].password_hash, password)
            assert verified
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))


def test_pg_offline_release_sql_executes_to_the_declared_revision(engine, monkeypatch):
    from io import StringIO
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    import sqlalchemy
    from sqlalchemy import inspect

    name = "refactor_offline_" + uuid4().hex[:12]
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "backend/alembic"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{name}"'))
        connection.execute(text(f'SET search_path TO "{name}"'))
        connection.commit()
        try:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "e0f1a2b3c4d5")
            connection.commit()
            cfg.attributes.pop("connection")
            cfg.attributes["database_url"] = "postgresql://offline.invalid/unused"
            cfg.output_buffer = StringIO()
            with monkeypatch.context() as patch:
                patch.setattr(sqlalchemy, "create_engine", lambda *a, **k: pytest.fail("Offline SQL requested a connection"))
                command.upgrade(cfg, "e0f1a2b3c4d5:" + head, sql=True)
            connection.exec_driver_sql(cfg.output_buffer.getvalue())
            connection.commit()
            assert "assistant_turns" in inspect(connection).get_table_names()
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == head
        finally:
            connection.rollback()
            connection.execute(text("RESET search_path"))
            connection.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
            connection.commit()
