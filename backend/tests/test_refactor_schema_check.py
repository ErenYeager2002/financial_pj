from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, event, inspect, text

from app.infrastructure.database.schema_check import (
    SchemaCompatibilityError,
    check_schema_compatible,
)


@contextmanager
def database(revisions=()):
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        if revisions:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
            for revision in revisions:
                connection.execute(text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": revision})
            connection.commit()
        try:
            yield connection
        finally:
            connection.close()
    engine.dispose()


def test_empty_database_rejected_without_creating_any_tables():
    with database() as connection:
        with pytest.raises(SchemaCompatibilityError, match="DATABASE_NOT_MIGRATED"):
            check_schema_compatible(connection, supported_revisions={"current"})
        assert inspect(connection).get_table_names() == []


@pytest.mark.parametrize("revision", ["supported-old", "supported-new"])
def test_explicit_expand_contract_versions_are_accepted_read_only(revision):
    with database([revision]) as connection:
        statements = []
        event.listen(connection, "before_cursor_execute", lambda conn, cursor, statement, params, context, many: statements.append(statement))
        transaction = connection.begin()
        status = check_schema_compatible(connection, supported_revisions={"supported-old", "supported-new"})
        assert status.revision == revision
        assert connection.get_transaction() is transaction
        assert not connection.closed
        assert statements and all(s.lstrip().upper().startswith(("SELECT", "PRAGMA")) for s in statements)
        transaction.rollback()


@pytest.mark.parametrize("revision", ["too-old", "too-new", "unknown-branch"])
def test_unsupported_versions_are_not_modified(revision):
    with database([revision]) as connection:
        with pytest.raises(SchemaCompatibilityError, match="DATABASE_REVISION_UNSUPPORTED"):
            check_schema_compatible(connection, supported_revisions={"supported"})
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision


def test_multiple_database_heads_rejected_even_when_each_is_supported():
    with database(["branch-a", "branch-b"]) as connection:
        with pytest.raises(SchemaCompatibilityError, match="DATABASE_MULTIPLE_REVISIONS"):
            check_schema_compatible(connection, supported_revisions={"branch-a", "branch-b"})


def test_required_table_check_detects_stamped_but_incomplete_schema():
    with database(["supported"]) as connection:
        with pytest.raises(SchemaCompatibilityError, match="DATABASE_REQUIRED_TABLES_MISSING"):
            check_schema_compatible(connection, supported_revisions={"supported"}, required_tables={"assistant_turns"})
        assert "assistant_turns" not in inspect(connection).get_table_names()


@pytest.mark.parametrize("policy", [set(), "supported", {None}])
def test_missing_or_malformed_policy_fails_closed(policy):
    with database(["supported"]) as connection:
        with pytest.raises(ValueError):
            check_schema_compatible(connection, supported_revisions=policy)
