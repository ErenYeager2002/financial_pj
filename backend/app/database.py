from __future__ import annotations

from collections.abc import Generator

from alembic.config import Config
from sqlalchemy import create_engine, event
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


def _alembic_config() -> Config:
    """返回指向仓库 alembic.ini 的配置，脚本路径固定为绝对路径。"""
    project_root = settings.project_root
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "backend" / "alembic"))
    config.set_main_option("prepend_sys_path", str(project_root / "backend"))
    return config


def check_runtime_database():
    """Runtime entry: read-only readiness, with no automatic schema repair."""
    from .infrastructure.database.runtime_check import check_runtime_database as check

    return check(engine)


def init_db() -> None:
    """Compatibility wrapper: readiness only; migrate explicitly before startup."""
    check_runtime_database()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
