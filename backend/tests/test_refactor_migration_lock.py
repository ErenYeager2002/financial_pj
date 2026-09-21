from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text

from app.infrastructure.database.migration_lock import MigrationLockError, migration_lock


def test_sqlite_lock_excludes_other_process_and_survives_transaction(tmp_path):
    database = tmp_path / "lock.db"
    engine = create_engine("sqlite:///" + str(database))
    child = """import sys
from sqlalchemy import create_engine
from app.infrastructure.database.migration_lock import migration_lock, MigrationLockError
engine=create_engine('sqlite:///'+sys.argv[1])
try:
 with engine.connect() as connection:
  with migration_lock(connection,timeout=0.1): pass
except MigrationLockError as error:
 print(str(error));sys.exit(7)
finally: engine.dispose()
"""
    try:
        with engine.connect() as connection:
            with migration_lock(connection, timeout=0):
                connection.execute(text("CREATE TABLE synthetic (id INTEGER)"))
                connection.commit()
                result = subprocess.run([sys.executable, "-B", "-c", child, str(database)], capture_output=True, text=True, timeout=10)
                assert result.returncode == 7 and "MIGRATION_LOCK_TIMEOUT" in result.stdout
            result = subprocess.run([sys.executable, "-B", "-c", child, str(database)], capture_output=True, text=True, timeout=10)
            assert result.returncode == 0, result.stderr
    finally:
        engine.dispose()


def test_sqlite_lock_is_released_after_failure_and_inode_is_preserved(tmp_path):
    database = tmp_path / "failure.db"
    engine = create_engine("sqlite:///" + str(database))
    try:
        with engine.connect() as connection:
            with pytest.raises(RuntimeError, match="synthetic failure"):
                with migration_lock(connection):
                    raise RuntimeError("synthetic failure")
            lock = database.with_name(database.name + ".migration.lock")
            inode = lock.stat().st_ino
            with migration_lock(connection, timeout=0):
                assert lock.stat().st_ino == inode
    finally:
        engine.dispose()


def test_active_caller_transaction_is_not_committed_or_rolled_back(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "transaction.db"))
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            with pytest.raises(MigrationLockError, match="DEDICATED_CONNECTION"):
                with migration_lock(connection):
                    pytest.fail("Entered migration")
            assert connection.get_transaction() is transaction
            transaction.rollback()
    finally:
        engine.dispose()


def test_lock_symlink_is_rejected(tmp_path):
    database = tmp_path / "link.db"
    target = tmp_path / "protected"
    target.write_text("synthetic-original")
    database.with_name(database.name + ".migration.lock").symlink_to(target)
    engine = create_engine("sqlite:///" + str(database))
    try:
        with engine.connect() as connection:
            with pytest.raises(OSError):
                with migration_lock(connection):
                    pytest.fail("Followed symlink")
        assert target.read_text() == "synthetic-original"
    finally:
        engine.dispose()
