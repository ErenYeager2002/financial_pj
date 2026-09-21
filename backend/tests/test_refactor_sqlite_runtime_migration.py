from pathlib import Path
import importlib.util
import re

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect, text

from app.models import RunRecord

ROOT = Path(__file__).resolve().parents[2]


def repair_definitions():
    path = ROOT / "backend/alembic/versions/20260918_f2a3b4c5d6e7_sqlite_runtime_columns.py"
    spec = importlib.util.spec_from_file_location("runtime_revision", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.definitions()


@pytest.mark.parametrize("old_missing_columns", [False, True])
def test_formal_sqlite_upgrade_retains_data_and_repairs_all_historical_columns(tmp_path, old_missing_columns):
    engine = create_engine("sqlite:///" + str(tmp_path / "old.db"))
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "backend/alembic"))
    try:
        with engine.connect() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "f1a2b3c4d5e6")
            connection.execute(RunRecord.__table__.insert().values(
                id="synthetic-preserved", owner_id="synthetic", skill_id="synthetic",
                skill_name="Synthetic", skill_version="1", skill_hash="synthetic",
                manifest_path="synthetic", manifest_snapshot="{}", adapter="python",
                worker_pool="standard", message="preserve this business text",
            ))
            connection.commit()
            if old_missing_columns:
                # Fixture reconstruction temporarily removes and restores triggers;
                # the migration under test itself must retain them unchanged.
                triggers = connection.execute(text("SELECT name, sql FROM sqlite_master WHERE type='trigger' ORDER BY name")).all()
                for name, _ in triggers:
                    connection.exec_driver_sql('DROP TRIGGER "' + name.replace('"', '""') + '"')
                operations = Operations(MigrationContext.configure(connection))
                for table, columns in repair_definitions().items():
                    names = {column.name for column in columns}
                    indices = inspect(connection).get_indexes(table)
                    checks = inspect(connection).get_check_constraints(table)
                    with operations.batch_alter_table(table, recreate="always") as batch:
                        for check in checks:
                            if any(re.search(r"\b" + re.escape(name) + r"\b", check["sqltext"]) for name in names):
                                batch.drop_constraint(check["name"], type_="check")
                        for index in indices:
                            if names.intersection(index["column_names"]):
                                batch.drop_index(index["name"])
                        for column in columns:
                            batch.drop_column(column.name)
                for _, sql in triggers:
                    connection.exec_driver_sql(sql)
                connection.commit()
            trigger_before = connection.execute(text("SELECT name, sql FROM sqlite_master WHERE type='trigger' ORDER BY name")).all()
            command.upgrade(cfg, "f2a3b4c5d6e7")
            connection.commit()
            command.upgrade(cfg, "f2a3b4c5d6e7")
            for table, columns in repair_definitions().items():
                actual = {column["name"] for column in inspect(connection).get_columns(table)}
                assert {column.name for column in columns}.issubset(actual)
            row = connection.execute(text("SELECT message, concurrency_limit, worker_id, attempt_count, heartbeat_at, lease_expires_at FROM runs WHERE id='synthetic-preserved'")).one()
            assert tuple(row) == ("preserve this business text", 1, "", 0, None, None)
            assert connection.execute(text("SELECT name, sql FROM sqlite_master WHERE type='trigger' ORDER BY name")).all() == trigger_before
            assert connection.scalar(text("SELECT count(*) FROM runs")) == 1
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "f2a3b4c5d6e7"
    finally:
        engine.dispose()
