from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

from app import auth_service
from app.auth_models import User


@pytest.fixture
def bootstrap_database(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "bootstrap.db"), connect_args={"timeout": 20})
    User.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    configuration = SimpleNamespace(bootstrap_admin_username="synthetic-admin", bootstrap_admin_password="", data_dir=tmp_path)
    monkeypatch.setattr(auth_service, "settings", configuration)
    try:
        yield engine, factory, configuration
    finally:
        engine.dispose()


def test_concurrent_bootstrap_creates_one_account_and_matching_private_password(bootstrap_database):
    engine, factory, configuration = bootstrap_database
    def initialize(_):
        with factory() as db:
            return auth_service.bootstrap_admin(db)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(initialize, range(16))) == ["synthetic-admin"] * 16
    token = configuration.data_dir / "initial_admin_password.txt"
    password = token.read_text().rstrip().split("：", 1)[1]
    assert token.stat().st_mode & 0o777 == 0o600
    with factory() as db:
        users = db.scalars(select(User)).all()
        assert len(users) == 1 and users[0].must_change_password
        assert auth_service.verify_password(users[0].password_hash, password)
    assert not list(configuration.data_dir.glob(".bootstrap-*"))


def test_configured_password_is_idempotent_and_not_published(bootstrap_database):
    _, factory, configuration = bootstrap_database
    configuration.bootstrap_admin_password = "synthetic-first-password"
    with factory() as db:
        auth_service.bootstrap_admin(db)
    configuration.bootstrap_admin_password = "synthetic-second-password"
    with factory() as db:
        auth_service.bootstrap_admin(db)
    with factory() as db:
        user = db.scalar(select(User))
        assert auth_service.verify_password(user.password_hash, "synthetic-first-password")
        assert not user.must_change_password
    assert not (configuration.data_dir / "initial_admin_password.txt").exists()


def test_password_file_failure_rolls_back_account(bootstrap_database, monkeypatch):
    _, factory, _ = bootstrap_database
    def fail(*args):
        raise OSError("synthetic publication failure")
    monkeypatch.setattr(auth_service, "_write_bootstrap_password", fail)
    with factory() as db:
        with pytest.raises(OSError, match="synthetic publication failure"):
            auth_service.bootstrap_admin(db)
    with factory() as db:
        assert db.scalar(select(User)) is None


def test_bootstrap_never_commits_an_existing_caller_transaction(bootstrap_database):
    _, factory, _ = bootstrap_database
    with factory() as db:
        db.execute(text("SELECT 1"))
        transaction = db.get_transaction()
        with pytest.raises(RuntimeError, match="REQUIRES_FRESH_SESSION"):
            auth_service.bootstrap_admin(db)
        assert db.get_transaction() is transaction
        db.rollback()


def test_commit_failure_preserves_private_recoverable_password_file(bootstrap_database):
    _, factory, configuration = bootstrap_database
    token = configuration.data_dir / "initial_admin_password.txt"

    def reject_commit(session):
        assert token.exists()
        raise RuntimeError("synthetic commit failure")

    with factory() as db:
        event.listen(db, "before_commit", reject_commit)
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            auth_service.bootstrap_admin(db)
    first_password = token.read_text().rstrip().split("：", 1)[1]
    assert token.stat().st_mode & 0o777 == 0o600
    with factory() as db:
        assert db.scalar(select(User)) is None

    # Keep the restricted file on an ambiguous commit outcome; deleting it could
    # discard the only password for an account whose commit actually succeeded.
    # A fresh retry consults the database under the bootstrap lock first.
    with factory() as db:
        auth_service.bootstrap_admin(db)
    recovered_password = token.read_text().rstrip().split("：", 1)[1]
    assert recovered_password != first_password
    assert token.stat().st_mode & 0o777 == 0o600
    with factory() as db:
        users = db.scalars(select(User)).all()
        assert len(users) == 1
        assert auth_service.verify_password(users[0].password_hash, recovered_password)
        assert not auth_service.verify_password(users[0].password_hash, first_password)
    with factory() as db:
        auth_service.bootstrap_admin(db)
    assert token.read_text().rstrip().split("：", 1)[1] == recovered_password
    assert not list(configuration.data_dir.glob(".bootstrap-*"))


def test_error_after_committed_bootstrap_retains_matching_password(bootstrap_database):
    _, factory, configuration = bootstrap_database
    token = configuration.data_dir / "initial_admin_password.txt"

    def fail_after_commit(session):
        raise RuntimeError("synthetic post-commit failure")

    with factory() as db:
        event.listen(db, "after_commit", fail_after_commit)
        with pytest.raises(RuntimeError, match="synthetic post-commit failure"):
            auth_service.bootstrap_admin(db)
    published = token.read_text()
    password = published.rstrip().split("：", 1)[1]
    with factory() as db:
        users = db.scalars(select(User)).all()
        assert len(users) == 1
        assert auth_service.verify_password(users[0].password_hash, password)
    with factory() as db:
        auth_service.bootstrap_admin(db)
    assert token.read_text() == published
    assert token.stat().st_mode & 0o777 == 0o600
