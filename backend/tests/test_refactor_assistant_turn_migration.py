from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text

from app.models import AssistantTurn


@pytest.mark.parametrize("existing", [False, True])
def test_revision_creates_missing_table_or_preserves_valid_existing_rows(tmp_path, existing):
    engine = create_engine("sqlite:///" + str(tmp_path / "turns.db"))
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "backend/alembic"))
    try:
        with engine.connect() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "e0f1a2b3c4d5")
            if existing:
                AssistantTurn.__table__.create(connection)
                connection.execute(AssistantTurn.__table__.insert().values(owner_id="synthetic", department_id="synthetic", session_id="session", turn_id="turn", lease_expires_at=datetime.now(UTC)))
                connection.commit()
            command.upgrade(cfg, "f1a2b3c4d5e6")
            assert "assistant_turns" in inspect(connection).get_table_names()
            assert set(AssistantTurn.__table__.columns.keys()) == {c["name"] for c in inspect(connection).get_columns("assistant_turns")}
            assert connection.scalar(text("SELECT count(*) FROM assistant_turns")) == int(existing)
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "f1a2b3c4d5e6"
    finally:
        engine.dispose()


def test_existing_incompatible_table_is_not_silently_adopted(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "bad.db"))
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "backend/alembic"))
    try:
        with engine.connect() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "e0f1a2b3c4d5")
            connection.execute(text("CREATE TABLE assistant_turns (owner_id TEXT)"))
            connection.execute(text("INSERT INTO assistant_turns VALUES ('preserve')"))
            connection.commit()
            with pytest.raises(RuntimeError, match="INCOMPATIBLE"):
                command.upgrade(cfg, "f1a2b3c4d5e6")
            connection.rollback()
            assert connection.scalar(text("SELECT owner_id FROM assistant_turns")) == "preserve"
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "e0f1a2b3c4d5"
    finally:
        engine.dispose()
