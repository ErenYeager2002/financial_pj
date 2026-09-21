from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, inspect, text

from app.infrastructure.database.migrate import DatabaseTarget, MigrationPreconditionError, migrate_database
from app.infrastructure.database.seed import seed_required_rows

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def target(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "database.db"))
    config = Config()
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    try:
        yield engine, config, ScriptDirectory.from_config(config).get_current_head()
    finally:
        engine.dispose()


def migrate(target, expected=None):
    engine, config, head = target
    return migrate_database(engine, config, expected_target=DatabaseTarget.from_engine(engine), expected_revision=expected, target_revision=head)


def test_fresh_migration_and_repeat_seed_are_idempotent(target):
    result = migrate(target)
    assert result.upgraded
    engine, config, head = target
    repeated = migrate(target, head)
    assert not repeated.upgraded
    assert "connection" not in config.attributes
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM scheduler_locks WHERE name='global'")) == 1
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == head


def test_wrong_target_rejected_before_opening_database(target):
    engine, config, head = target
    wrong = DatabaseTarget("sqlite", None, None, "/not-the-selected-database")
    with pytest.raises(MigrationPreconditionError, match="TARGET_MISMATCH"):
        migrate_database(engine, config, expected_target=wrong, expected_revision=None, target_revision=head)
    assert not Path(engine.url.database).exists()


def test_unversioned_legacy_table_is_not_stamped_or_modified(target):
    engine, config, head = target
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE files (id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO files VALUES ('synthetic-original')"))
    with pytest.raises(MigrationPreconditionError, match="LEGACY_IMPORT_REQUIRED"):
        migrate(target)
    with engine.connect() as connection:
        assert inspect(connection).get_table_names() == ["files"]
        assert connection.scalar(text("SELECT id FROM files")) == "synthetic-original"


def test_changed_revision_prevents_migration(target):
    migrate(target)
    with pytest.raises(MigrationPreconditionError, match="SOURCE_REVISION_CHANGED"):
        migrate(target)


def test_failure_clears_external_connection_binding_and_releases_lock(target, monkeypatch):
    from app.infrastructure.database import migrate as module
    def fail(*args):
        raise RuntimeError("synthetic migration failure")
    with monkeypatch.context() as patch:
        patch.setattr(module.command, "upgrade", fail)
        with pytest.raises(RuntimeError, match="synthetic migration failure"):
            migrate(target)
    assert "connection" not in target[1].attributes
    assert migrate(target).upgraded


def test_seed_does_not_commit_caller_transaction(target):
    migrate(target)
    engine, _, _ = target
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM scheduler_locks WHERE name='global'"))
    with engine.connect() as connection:
        transaction = connection.begin()
        seed_required_rows(connection)
        assert connection.get_transaction() is transaction
        transaction.rollback()
        assert connection.scalar(text("SELECT count(*) FROM scheduler_locks")) == 0
