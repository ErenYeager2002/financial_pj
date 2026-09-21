"""Strict structural verification for explicitly selected, unversioned SQLite baselines."""
import json

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection


def sqlite_schema_signature(connection: Connection) -> str:
    inspector = inspect(connection)
    tables = {}
    for name in sorted(set(inspector.get_table_names()) - {"alembic_version"}):
        columns = []
        for column in inspector.get_columns(name):
            columns.append({
                "name": column["name"], "type": str(column["type"]),
                "nullable": column["nullable"], "default": column.get("default"),
                "computed": column.get("computed"),
            })
        tables[name] = {
            "columns": sorted(columns, key=lambda item: item["name"]),
            "primary_key": inspector.get_pk_constraint(name),
            "foreign_keys": sorted(inspector.get_foreign_keys(name), key=lambda item: json.dumps(item, sort_keys=True, default=str)),
            "unique_constraints": sorted(inspector.get_unique_constraints(name), key=lambda item: json.dumps(item, sort_keys=True, default=str)),
            "checks": sorted(inspector.get_check_constraints(name), key=lambda item: json.dumps(item, sort_keys=True, default=str)),
            "indices": sorted(inspector.get_indexes(name), key=lambda item: item["name"]),
        }
    # Trigger/view behaviour and special table options must not be silently adopted.
    objects = connection.execute(text(
        "SELECT type, name, sql FROM sqlite_master WHERE type IN ('trigger','view') ORDER BY type,name"
    )).all()
    table_options = connection.execute(text(
        "SELECT name, wr, strict FROM pragma_table_list WHERE schema='main' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' ORDER BY name"
    )).all()
    return json.dumps({"tables": tables, "objects": [list(row) for row in objects], "table_options": [list(row) for row in table_options]}, sort_keys=True, default=str)


def baseline_signature(config: Config, revision: str) -> str:
    """Build only the declared historic baseline in an ephemeral in-memory database."""
    reference = create_engine("sqlite://")
    try:
        isolated = Config()
        isolated.set_main_option("script_location", config.get_main_option("script_location"))
        with reference.connect() as connection:
            isolated.attributes["connection"] = connection
            command.upgrade(isolated, revision)
            return sqlite_schema_signature(connection)
    finally:
        reference.dispose()
