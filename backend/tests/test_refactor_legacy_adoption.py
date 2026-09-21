from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, inspect, text

from app.infrastructure.database.migrate import DatabaseTarget, MigrationPreconditionError, migrate_database
from app.infrastructure.database.legacy_schema import sqlite_schema_signature


@pytest.fixture
def legacy(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "legacy.db"))
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "backend/alembic"))
    script = ScriptDirectory.from_config(cfg)
    baseline, head = script.get_base(), script.get_current_head()
    with engine.connect() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, baseline)
        connection.execute(text("DROP TABLE alembic_version"))
        connection.execute(text("INSERT INTO files (id, owner_id, department_id, kind, original_name, stored_path, content_type, size_bytes, sha256, created_at) VALUES ('preserved', 'synthetic', 'finance', 'input', 'synthetic.xlsx', 'synthetic', 'application/octet-stream', 1, 'synthetic', CURRENT_TIMESTAMP)"))
        connection.commit()
        cfg.attributes.pop("connection")
    try:
        yield engine, cfg, baseline, head
    finally:
        engine.dispose()


def adopt(legacy):
    engine, cfg, baseline, head = legacy
    return migrate_database(engine, cfg, expected_target=DatabaseTarget.from_engine(engine), expected_revision=None, target_revision=head, legacy_baseline=baseline)


def test_matching_unversioned_baseline_upgrades_preserving_history(legacy):
    result = adopt(legacy)
    assert result.adopted_legacy and result.upgraded and result.previous_revision is None
    engine, _, _, head = legacy
    with engine.connect() as connection:
        assert {"users", "assistant_turns"}.issubset(inspect(connection).get_table_names())
        assert connection.scalar(text("SELECT original_name FROM files WHERE id='preserved'")) == "synthetic.xlsx"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == head
        assert connection.scalar(text("SELECT count(*) FROM scheduler_locks WHERE name='global'")) == 1


@pytest.mark.parametrize("change", [
    "ALTER TABLE files ADD COLUMN unexpected TEXT",
    "DROP INDEX ix_files_owner_id",
    "CREATE TABLE unexpected (id INTEGER)",
    "CREATE TRIGGER unexpected AFTER INSERT ON files BEGIN SELECT 1; END",
])
def test_structure_mismatch_refuses_stamp_and_preserves_original(legacy, change):
    engine, _, _, _ = legacy
    with engine.begin() as connection:
        connection.execute(text(change))
    with engine.connect() as connection:
        before = sqlite_schema_signature(connection)
    with pytest.raises(MigrationPreconditionError, match="LEGACY_SCHEMA_MISMATCH"):
        adopt(legacy)
    with engine.connect() as connection:
        assert sqlite_schema_signature(connection) == before
        assert "alembic_version" not in inspect(connection).get_table_names()
        assert connection.scalar(text("SELECT original_name FROM files WHERE id='preserved'")) == "synthetic.xlsx"


def test_failed_legacy_upgrade_rolls_back_stamp_and_keeps_original_schema(legacy, monkeypatch):
    from app.infrastructure.database import migrate as module
    real_upgrade = module.command.upgrade
    def fail_upgrade(cfg, revision):
        if revision == legacy[3]:
            cfg.attributes["connection"].execute(text("CREATE TABLE partially_created (id INTEGER)"))
            raise RuntimeError("synthetic upgrade failure")
        return real_upgrade(cfg, revision)
    with legacy[0].connect() as connection:
        before = sqlite_schema_signature(connection)
    monkeypatch.setattr(module.command, "upgrade", fail_upgrade)
    with pytest.raises(RuntimeError, match="synthetic upgrade failure"):
        adopt(legacy)
    with legacy[0].connect() as connection:
        assert sqlite_schema_signature(connection) == before
        assert "alembic_version" not in inspect(connection).get_table_names()
    assert "connection" not in legacy[1].attributes


def test_explicit_legacy_command_reports_adoption(legacy, monkeypatch, capsys):
    import json
    from app.infrastructure.database.cli import main
    engine, _, baseline, head = legacy
    monkeypatch.setenv("FINANCIAL_DATABASE_URL", str(engine.url))
    assert main(["--dialect", "sqlite", "--database", engine.url.database,
                 "--expected-revision", "none", "--target-revision", head,
                 "--legacy-baseline", baseline]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["adopted_legacy"] and result["revision"] == head


def test_legacy_baseline_must_be_exact_root_revision(legacy):
    engine, cfg, _, head = legacy
    with pytest.raises(MigrationPreconditionError, match="LEGACY_BASELINE_INVALID"):
        migrate_database(engine, cfg, expected_target=DatabaseTarget.from_engine(engine), expected_revision=None, target_revision=head, legacy_baseline=head)
    with engine.connect() as connection:
        assert "alembic_version" not in inspect(connection).get_table_names()
