from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import settings


class Base(DeclarativeBase):
    pass


is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

if is_sqlite:

    @event.listens_for(engine, "connect")
    def _configure_sqlite(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


SQLITE_RUNTIME_COLUMNS = {
    "runs": {
        "concurrency_limit": "INTEGER NOT NULL DEFAULT 1",
        "worker_id": "VARCHAR(128) NOT NULL DEFAULT ''",
        "attempt_count": "INTEGER NOT NULL DEFAULT 0",
        "heartbeat_at": "DATETIME",
        "lease_expires_at": "DATETIME",
    },
    "workflow_sessions": {
        "concurrency_limit": "INTEGER NOT NULL DEFAULT 1",
        "batch_id": "VARCHAR(36)",
        "batch_sequence": "INTEGER NOT NULL DEFAULT 0",
        "previous_workflow_id": "VARCHAR(36) NOT NULL DEFAULT ''",
    },
    "workflow_actions": {
        "worker_id": "VARCHAR(128) NOT NULL DEFAULT ''",
        "attempt_count": "INTEGER NOT NULL DEFAULT 0",
        "heartbeat_at": "DATETIME",
        "lease_expires_at": "DATETIME",
    },
}


def _upgrade_sqlite_runtime_schema() -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table, definitions in SQLITE_RUNTIME_COLUMNS.items():
            existing = {item["name"] for item in inspector.get_columns(table)}
            for column, definition in definitions.items():
                if column not in existing:
                    try:
                        connection.execute(
                            text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')
                        )
                    except OperationalError as exc:
                        if "duplicate column name" not in str(exc).lower():
                            raise


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    if is_sqlite:
        _upgrade_sqlite_runtime_schema()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scheduler_locks (name) VALUES ('global') ON CONFLICT(name) DO NOTHING"
            )
        )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
