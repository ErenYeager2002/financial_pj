"""Migration-only locks; callers must use a dedicated connection with no transaction."""
from contextlib import contextmanager
import fcntl
import math
import os
from pathlib import Path
import stat
import time

from sqlalchemy import text
from sqlalchemy.engine import Connection

# A stable signed bigint scoped by PostgreSQL to the current database.
ADVISORY_KEY = 0x46494E4D494752


class MigrationLockError(RuntimeError):
    pass


def _wait(deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise MigrationLockError("MIGRATION_LOCK_TIMEOUT")
    time.sleep(min(0.05, remaining))


@contextmanager
def migration_lock(connection: Connection, *, timeout: float = 30):
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("Lock timeout must be finite and non-negative")
    if connection.in_transaction():
        raise MigrationLockError("MIGRATION_REQUIRES_DEDICATED_CONNECTION")
    deadline = time.monotonic() + timeout
    dialect = connection.dialect.name
    if dialect == "postgresql":
        acquired = False
        try:
            while True:
                acquired = bool(connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": ADVISORY_KEY}))
                connection.commit()  # Session lock survives transaction boundaries.
                if acquired:
                    break
                _wait(deadline)
            yield connection
        finally:
            # Never return a pooled connection while it may own a session lock.
            try:
                if connection.in_transaction():
                    connection.rollback()
                if acquired:
                    released = connection.scalar(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_KEY})
                    connection.commit()
                    if not released:
                        raise MigrationLockError("MIGRATION_LOCK_LOST")
            except BaseException:
                connection.invalidate()
                raise
        return
    if dialect != "sqlite":
        raise MigrationLockError("MIGRATION_DATABASE_UNSUPPORTED")
    database = connection.engine.url.database
    if not database or database == ":memory:" or connection.engine.url.query:
        raise MigrationLockError("MIGRATION_REQUIRES_FILE_SQLITE")
    source = Path(database).absolute()
    for component in (source, *source.parents):
        if component.is_symlink():
            raise MigrationLockError("MIGRATION_SQLITE_SYMLINK_REJECTED")
    lock_path = source.with_name(source.name + ".migration.lock")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    acquired = False
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise MigrationLockError("MIGRATION_LOCK_FILE_UNSAFE")
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                _wait(deadline)
        if os.stat(lock_path, follow_symlinks=False).st_ino != info.st_ino:
            raise MigrationLockError("MIGRATION_LOCK_FILE_REPLACED")
        yield connection
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        # Keep the inode: unlinking allows simultaneous owners of different files.
