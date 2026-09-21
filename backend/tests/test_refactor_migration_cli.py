import json
import os
from pathlib import Path
import subprocess
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.infrastructure.database import cli
from app.infrastructure.database.migrate import DatabaseTarget, MigrationPreconditionError

ROOT = Path(__file__).resolve().parents[2]


def arguments(path, expected="none"):
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "backend/alembic"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    return ["--dialect", "sqlite", "--database", str(path), "--expected-revision", expected, "--target-revision", head], head


def test_command_subprocess_fresh_and_repeated_migration(tmp_path):
    path = tmp_path / "command.db"
    args, head = arguments(path)
    env = {**os.environ, "FINANCIAL_DATABASE_URL": "sqlite:///" + str(path)}
    for expected, changed in [("none", True), (head, False)]:
        args, _ = arguments(path, expected)
        result = subprocess.run([sys.executable, "-B", "-m", "app.infrastructure.database.cli", *args], env=env, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["revision"] == head and payload["upgraded"] is changed
    engine = create_engine(env["FINANCIAL_DATABASE_URL"])
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM scheduler_locks WHERE name='global'")) == 1
    finally:
        engine.dispose()


def test_target_mismatch_does_not_create_database(tmp_path, monkeypatch, capsys):
    actual = tmp_path / "actual.db"
    monkeypatch.setenv("FINANCIAL_DATABASE_URL", "sqlite:///" + str(actual))
    args, _ = arguments(tmp_path / "wrong.db")
    assert cli.main(args) == 1
    assert not actual.exists()
    assert json.loads(capsys.readouterr().err)["code"] == "MIGRATION_TARGET_MISMATCH"


def test_missing_url_fails_without_falling_back_to_application_settings(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("FINANCIAL_DATABASE_URL", raising=False)
    args, _ = arguments(tmp_path / "absent.db")
    assert cli.main(args) == 1
    assert json.loads(capsys.readouterr().err)["code"] == "MIGRATION_DATABASE_URL_REQUIRED"


def test_driver_failure_does_not_print_connection_secrets(tmp_path, monkeypatch, capsys):
    marker = "synthetic-secret-must-not-appear"
    path = tmp_path / "safe.db"
    monkeypatch.setenv("FINANCIAL_DATABASE_URL", "sqlite:///" + str(path))
    def fail(*args, **kwargs):
        raise RuntimeError("connection password=" + marker)
    monkeypatch.setattr(cli, "create_engine", fail)
    args, _ = arguments(path)
    assert cli.main(args) == 1
    output = capsys.readouterr()
    assert marker not in output.out + output.err
    assert json.loads(output.err)["code"] == "MIGRATION_FAILED"


@pytest.mark.parametrize("query", ["host=other", "service=other", "options=-csearch_path=other", "plugin=other", "hostaddr=127.0.0.2"])
def test_url_overrides_cannot_bypass_explicit_target(query):
    url = make_url("postgresql+psycopg://synthetic@selected:5432/synthetic?" + query)
    with pytest.raises(MigrationPreconditionError, match="OPTIONS_UNSUPPORTED"):
        DatabaseTarget.from_url(url)


def test_postgres_default_port_and_transport_options_are_normalized():
    target = DatabaseTarget.from_url(make_url("postgresql+psycopg://synthetic@selected/synthetic?sslmode=require"))
    assert target == DatabaseTarget("postgresql", "selected", 5432, "synthetic")


@pytest.mark.parametrize("variable", ["PGSERVICE", "PGSERVICEFILE", "PGOPTIONS", "PGHOSTADDR", "PGPORT"])
def test_libpq_environment_overrides_are_rejected_before_connect(variable, monkeypatch, capsys):
    monkeypatch.setenv("FINANCIAL_DATABASE_URL", "postgresql+psycopg://synthetic@selected/synthetic")
    monkeypatch.setenv(variable, "synthetic-override")
    monkeypatch.setattr(cli, "create_engine", lambda *args, **kwargs: pytest.fail("Ambiguous environment reached engine creation"))
    assert cli.main(["--dialect", "postgresql", "--host", "selected", "--database", "synthetic", "--expected-revision", "none", "--target-revision", "f1a2b3c4d5e6"]) == 1
    assert json.loads(capsys.readouterr().err)["code"] == "MIGRATION_CONNECTION_ENV_UNSUPPORTED"


def test_two_migration_command_processes_serialize_and_recheck_revision(tmp_path):
    import selectors
    from app.infrastructure.database.migration_lock import migration_lock

    path = tmp_path / "contended.db"
    args, head = arguments(path)
    env = {**os.environ, "FINANCIAL_DATABASE_URL": "sqlite:///" + str(path)}
    engine = create_engine(env["FINANCIAL_DATABASE_URL"])
    children = []
    # Ready is emitted after CLI import, before entering the real command.
    source = "from app.infrastructure.database.cli import main; print('READY', flush=True); raise SystemExit(main())"
    try:
        with engine.connect() as connection:
            with migration_lock(connection):
                for _ in range(2):
                    children.append(subprocess.Popen(
                        [sys.executable, "-B", "-c", source, *args], env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    ))
                with selectors.DefaultSelector() as selector:
                    for child in children:
                        selector.register(child.stdout, selectors.EVENT_READ)
                    while selector.get_map():
                        ready = selector.select(timeout=10)
                        assert ready, "Migration child did not reach the command entry"
                        for key, _ in ready:
                            assert key.fileobj.readline().strip() == "READY"
                            selector.unregister(key.fileobj)
                assert all(child.poll() is None for child in children)
            outputs = [child.communicate(timeout=20) for child in children]
        assert sorted(child.returncode for child in children) == [0, 1]
        for child, (stdout, stderr) in zip(children, outputs):
            if child.returncode == 0:
                assert json.loads(stdout)["revision"] == head
            else:
                assert json.loads(stderr)["code"] == "MIGRATION_SOURCE_REVISION_CHANGED"
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == head
            assert connection.scalar(text("SELECT count(*) FROM scheduler_locks WHERE name='global'")) == 1
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
        engine.dispose()
