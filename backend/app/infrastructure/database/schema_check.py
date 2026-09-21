"""Read-only startup checks. This module never migrates, stamps, or seeds."""
from collections.abc import Collection
from dataclasses import dataclass

from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import Connection


class SchemaCompatibilityError(RuntimeError):
    """A database is not compatible with this application's declared policy."""

    def __init__(self, code: str) -> None:
        self.code = code
        # Do not include connection URLs, credentials, or arbitrary DB values.
        super().__init__(code)


@dataclass(frozen=True)
class SchemaCompatibility:
    revision: str


def check_schema_compatible(
    connection: Connection,
    *,
    supported_revisions: Collection[str],
    required_tables: Collection[str] = (),
) -> SchemaCompatibility:
    """Accept explicit expand/contract revisions; never equate compatibility to head.

    Connection/transaction ownership remains with the caller. Required tables are
    an optional minimum application contract, not a substitute for migrations.
    """
    if isinstance(supported_revisions, str) or not supported_revisions:
        raise ValueError("An explicit non-empty supported revision collection is required")
    if any(not isinstance(item, str) or not item for item in supported_revisions):
        raise ValueError("Supported revisions must be non-empty strings")
    heads = MigrationContext.configure(connection).get_current_heads()
    if not heads:
        raise SchemaCompatibilityError("DATABASE_NOT_MIGRATED")
    if len(heads) != 1:
        raise SchemaCompatibilityError("DATABASE_MULTIPLE_REVISIONS")
    if heads[0] not in supported_revisions:
        raise SchemaCompatibilityError("DATABASE_REVISION_UNSUPPORTED")
    if required_tables:
        tables = set(inspect(connection).get_table_names())
        if not set(required_tables).issubset(tables):
            raise SchemaCompatibilityError("DATABASE_REQUIRED_TABLES_MISSING")
    return SchemaCompatibility(revision=heads[0])
