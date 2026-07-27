from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="financial-skill-tests-")).resolve()
PROJECT_ROOT = Path(__file__).resolve().parents[2]

os.environ["FINANCIAL_ENV"] = "test"
os.environ["FINANCIAL_DATA_DIR"] = str(TEST_DATA_DIR)
os.environ["FINANCIAL_DATABASE_URL"] = (
    f"sqlite:///{(TEST_DATA_DIR / 'financial-tests.db').as_posix()}"
)
os.environ["FINANCIAL_SKILL_DIR"] = str(PROJECT_ROOT / "skills")


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_data():
    yield
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
