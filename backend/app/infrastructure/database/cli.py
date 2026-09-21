"""Explicit schema migration command; credentials are accepted only via environment."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import sys

from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from .migrate import DatabaseTarget, MigrationPreconditionError, migrate_database


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Migrate an explicitly selected financial database")
    parser.add_argument("--dialect", required=True, choices=("sqlite", "postgresql"))
    parser.add_argument("--database", required=True)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--expected-revision", required=True, help="Exact existing revision, or none for a new empty database")
    parser.add_argument("--target-revision", required=True, help="Exact reviewed target revision; head is not accepted")
    parser.add_argument("--legacy-baseline", help="Explicitly adopt an unversioned SQLite only if its complete schema matches this baseline")
    parser.add_argument("--lock-timeout", type=float, default=30)
    args = parser.parse_args(argv)
    engine = None
    try:
        raw_url = os.environ.get("FINANCIAL_DATABASE_URL")
        if not raw_url:
            raise MigrationPreconditionError("MIGRATION_DATABASE_URL_REQUIRED")
        url = make_url(raw_url)
        if url.drivername not in {"sqlite", "postgresql+psycopg"}:
            raise MigrationPreconditionError("MIGRATION_UNSUPPORTED_DRIVER")
        selected = DatabaseTarget.from_url(url)
        if selected.dialect == "postgresql" and any(os.environ.get(key) for key in ("PGSERVICE", "PGSERVICEFILE", "PGOPTIONS", "PGHOSTADDR", "PGPORT")):
            raise MigrationPreconditionError("MIGRATION_CONNECTION_ENV_UNSUPPORTED")
        if args.dialect == "sqlite":
            if args.host is not None or args.port is not None:
                raise MigrationPreconditionError("MIGRATION_SQLITE_HOST_NOT_ALLOWED")
            expected = DatabaseTarget("sqlite", None, None, str(Path(args.database).absolute()))
        else:
            if not args.host:
                raise MigrationPreconditionError("MIGRATION_REQUIRES_EXPLICIT_TARGET")
            expected = DatabaseTarget("postgresql", args.host, args.port or 5432, args.database)
        if selected != expected:
            raise MigrationPreconditionError("MIGRATION_TARGET_MISMATCH")
        engine = create_engine(url, poolclass=NullPool, hide_parameters=True)
        cfg = Config()
        cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[3] / "alembic"))
        result = migrate_database(
            engine, cfg, expected_target=expected,
            expected_revision=None if args.expected_revision == "none" else args.expected_revision,
            target_revision=args.target_revision, lock_timeout=args.lock_timeout,
            legacy_baseline=args.legacy_baseline,
        )
        print(json.dumps({"status": "migrated", **asdict(result)}))
        return 0
    except Exception as error:
        # DBAPI messages may contain URLs, SQL values, or authentication details.
        candidate = str(error) if isinstance(error, MigrationPreconditionError) else getattr(error, "code", "")
        code = candidate if isinstance(candidate, str) and re.fullmatch(r"(?:MIGRATION|DATABASE)_[A-Z_]+", candidate) else "MIGRATION_FAILED"
        print(json.dumps({"status": "failed", "code": code}), file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
