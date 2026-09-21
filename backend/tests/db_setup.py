"""Explicit schema preparation for synthetic test databases, never service startup."""
from pathlib import Path
import tempfile

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.database import engine, _alembic_config
from app.infrastructure.database.migrate import DatabaseTarget, migrate_database
from app.settings import settings


def migrate_test_database():
    import os
    if settings.environment != "test":
        raise RuntimeError("TEST_MIGRATION_REQUIRES_TEST_ENVIRONMENT")
    target = DatabaseTarget.from_engine(engine)
    if engine.dialect.name == "postgresql":
        if os.environ.get("REFACTOR_HTTP_POSTGRES") != "1":
            raise RuntimeError("TEST_MIGRATION_REQUIRES_EXPLICIT_POSTGRES")
        from verify_isolation import verify
        verify(os.environ)
        if str(engine.url.render_as_string(hide_password=False)) != os.environ["FINANCIAL_DATABASE_URL"]:
            raise RuntimeError("TEST_MIGRATION_TARGET_MISMATCH")
    elif engine.dialect.name == "sqlite":
        path = Path(target.database).resolve()
        data = settings.data_dir.resolve()
        temporary = Path(tempfile.gettempdir()).resolve()
        if not path.is_relative_to(data) or not data.is_relative_to(temporary):
            raise RuntimeError("TEST_MIGRATION_REQUIRES_TEMPORARY_DATABASE")
    else:
        raise RuntimeError("TEST_MIGRATION_REQUIRES_SYNTHETIC_DATABASE")
    cfg = _alembic_config()
    with engine.connect() as connection:
        heads = MigrationContext.configure(connection).get_current_heads()
    if len(heads) > 1:
        raise RuntimeError("TEST_DATABASE_HAS_MULTIPLE_REVISIONS")
    return migrate_database(
        engine, cfg, expected_target=target,
        expected_revision=heads[0] if heads else None,
        target_revision=ScriptDirectory.from_config(cfg).get_current_head(),
    )
