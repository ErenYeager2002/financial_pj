"""Explicit migration use case. Runtime readiness must not call this module."""
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Engine, URL

from .migration_lock import migration_lock
from .schema_check import check_schema_compatible
from .seed import seed_required_rows


class MigrationPreconditionError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabaseTarget:
    dialect: str
    host: str | None
    port: int | None
    database: str

    @classmethod
    def from_url(cls, url: URL) -> "DatabaseTarget":
        dialect = url.get_backend_name()
        name = url.database or ""
        if dialect == "sqlite":
            if not name or name == ":memory:" or url.query or url.host or url.username:
                raise MigrationPreconditionError("MIGRATION_REQUIRES_FILE_SQLITE")
            return cls(dialect, None, None, str(Path(name).absolute()))
        if dialect != "postgresql":
            raise MigrationPreconditionError("MIGRATION_UNSUPPORTED_DIALECT")
        # libpq host/service/options query parameters can redirect the connection
        # or change the schema while the visible URL target remains unchanged.
        permitted = {"sslmode", "sslrootcert", "sslcert", "sslkey", "connect_timeout", "application_name"}
        if set(url.query) - permitted or any(not isinstance(value, str) for value in url.query.values()):
            raise MigrationPreconditionError("MIGRATION_CONNECTION_OPTIONS_UNSUPPORTED")
        if not name or not url.host or "," in url.host:
            raise MigrationPreconditionError("MIGRATION_REQUIRES_EXPLICIT_TARGET")
        return cls(dialect, url.host, url.port or 5432, name)

    @classmethod
    def from_engine(cls, engine: Engine) -> "DatabaseTarget":
        return cls.from_url(engine.url)



@dataclass(frozen=True)
class MigrationResult:
    previous_revision: str | None
    revision: str
    upgraded: bool
    adopted_legacy: bool = False


def migrate_database(
    engine: Engine,
    config: Config,
    *,
    expected_target: DatabaseTarget,
    expected_revision: str | None,
    target_revision: str,
    lock_timeout: float = 30,
    legacy_baseline: str | None = None,
) -> MigrationResult:
    if DatabaseTarget.from_engine(engine) != expected_target:
        raise MigrationPreconditionError("MIGRATION_TARGET_MISMATCH")
    if "connection" in config.attributes:
        raise MigrationPreconditionError("MIGRATION_CONFIG_ALREADY_HAS_CONNECTION")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1:
        raise MigrationPreconditionError("MIGRATION_REQUIRES_SINGLE_HEAD")
    if target_revision != heads[0]:
        raise MigrationPreconditionError("MIGRATION_TARGET_REVISION_MISMATCH")
    known_revisions = {item.revision for item in script.walk_revisions()}
    if expected_revision is not None and expected_revision not in known_revisions:
        raise MigrationPreconditionError("MIGRATION_EXPECTED_REVISION_UNKNOWN")
    reference_signature = None
    if legacy_baseline is not None:
        if engine.dialect.name != "sqlite" or expected_revision is not None or legacy_baseline != script.get_base():
            raise MigrationPreconditionError("MIGRATION_LEGACY_BASELINE_INVALID")
        from .legacy_schema import baseline_signature
        reference_signature = baseline_signature(config, legacy_baseline)
    with engine.connect() as connection:
        with migration_lock(connection, timeout=lock_timeout):
            if legacy_baseline is not None:
                # Prevent schema/data changes between verification and stamp/upgrade.
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            current_heads = MigrationContext.configure(connection).get_current_heads()
            if len(current_heads) > 1:
                raise MigrationPreconditionError("MIGRATION_DATABASE_HAS_MULTIPLE_HEADS")
            current = current_heads[0] if current_heads else None
            if current != expected_revision:
                raise MigrationPreconditionError("MIGRATION_SOURCE_REVISION_CHANGED")
            if current is None:
                tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
                if legacy_baseline is not None:
                    from .legacy_schema import sqlite_schema_signature
                    if not tables or sqlite_schema_signature(connection) != reference_signature:
                        raise MigrationPreconditionError("MIGRATION_LEGACY_SCHEMA_MISMATCH")
                elif tables:
                    raise MigrationPreconditionError("MIGRATION_LEGACY_IMPORT_REQUIRED")
            if legacy_baseline is None:
                connection.commit()  # End ordinary metadata inspection before Alembic begins.
            config.attributes["connection"] = connection
            try:
                if legacy_baseline is not None:
                    command.stamp(config, legacy_baseline)
                command.upgrade(config, target_revision)
                connection.commit()
                check_schema_compatible(connection, supported_revisions={target_revision}, required_tables={"scheduler_locks"})
                seed_required_rows(connection)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                config.attributes.pop("connection", None)
            return MigrationResult(current, target_revision, current != target_revision, legacy_baseline is not None)
