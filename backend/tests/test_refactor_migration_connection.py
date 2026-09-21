"""Alembic must use the connection holding the migration lock."""
from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy
from sqlalchemy import create_engine, inspect, text

from app import models  # noqa: F401 - Load metadata before forbidding engines.

ROOT = Path(__file__).resolve().parents[2]


def config():
    value = Config()
    value.set_main_option("script_location", str(ROOT / "backend/alembic"))
    return value


def test_upgrade_uses_supplied_connection_without_opening_another_engine(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "migration.db"))
    def unexpected(*args, **kwargs):
        pytest.fail("Alembic opened an engine instead of using the lock-owning connection")
    try:
        with engine.connect() as connection:
            cfg = config()
            cfg.attributes["connection"] = connection
            monkeypatch.setattr(sqlalchemy, "create_engine", unexpected)
            command.upgrade(cfg, "head")
            assert not connection.closed
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == ScriptDirectory.from_config(cfg).get_current_head()
            assert "runs" in inspect(connection).get_table_names()
            connection.commit()
            command.upgrade(cfg, "head")
            assert not connection.closed
    finally:
        engine.dispose()


def test_invalid_supplied_connection_is_rejected_without_fallback(monkeypatch):
    cfg = config()
    cfg.attributes["connection"] = object()
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **k: pytest.fail("Unsafe fallback"))
    with pytest.raises(TypeError, match="SQLAlchemy Connection"):
        command.upgrade(cfg, "head")


def test_offline_baseline_emits_sql_without_connecting(monkeypatch):
    cfg = config()
    cfg.attributes["database_url"] = "postgresql://synthetic:unused@invalid/financial_refactor_test_offline"
    cfg.output_buffer = StringIO()
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **k: pytest.fail("Offline mode opened an engine"))
    baseline = ScriptDirectory.from_config(cfg).get_bases()[0]
    command.upgrade(cfg, baseline, sql=True)
    assert "CREATE TABLE" in cfg.output_buffer.getvalue()
    assert "alembic_version" in cfg.output_buffer.getvalue()


def test_offline_current_release_upgrade_emits_complete_sql_without_connection(monkeypatch):
    cfg = config()
    cfg.attributes["database_url"] = "postgresql://synthetic:unused@invalid/financial_refactor_test_offline"
    cfg.output_buffer = StringIO()
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *a, **k: pytest.fail("Offline mode opened an engine"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    command.upgrade(cfg, "e0f1a2b3c4d5:" + head, sql=True)
    output = cfg.output_buffer.getvalue()
    assert "CREATE TABLE assistant_turns" in output
    assert head in output and "COMMIT;" in output
    assert "unused" not in output and "invalid" not in output
