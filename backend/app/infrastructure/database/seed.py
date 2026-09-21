"""Required platform rows, with transaction ownership retained by the caller."""
from sqlalchemy import text
from sqlalchemy.engine import Connection


def seed_required_rows(connection: Connection) -> None:
    connection.execute(text(
        "INSERT INTO scheduler_locks (name) VALUES ('global') "
        "ON CONFLICT(name) DO NOTHING"
    ))
