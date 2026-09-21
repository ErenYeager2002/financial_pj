from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection

from alembic import context

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 导入模型元数据，保证 autogenerate 能识别全部表。
from app import models as _models  # noqa: E402,F401
from app.database import Base  # noqa: E402
from app.settings import settings  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return config.attributes.get("database_url", settings.database_url)


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_with_connection(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if "connection" in config.attributes:
        connection = config.attributes["connection"]
        if not isinstance(connection, Connection):
            raise TypeError("Migration requires a SQLAlchemy Connection")
        # The caller owns its transaction, advisory lock, and connection lifetime.
        _run_with_connection(connection)
        return
    database_url = _database_url()
    connectable = create_engine(
        database_url,
        poolclass=pool.NullPool,
        connect_args={"check_same_thread": False, "timeout": 30}
        if database_url.startswith("sqlite")
        else {},
    )
    try:
        with connectable.connect() as connection:
            _run_with_connection(connection)
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
