from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="financial-skill-tests-")).resolve()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_SKILL_DIR = TEST_DATA_DIR / "skills"
shutil.copytree(
    PROJECT_ROOT / "skills",
    TEST_SKILL_DIR,
    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache"),
)
workflow_manifest = TEST_SKILL_DIR / "ar-hexiao-daily" / "tool.yaml"
workflow_payload = yaml.safe_load(workflow_manifest.read_text(encoding="utf-8"))
workflow_runtime = workflow_payload.setdefault("runtime", {})
workflow_runtime.pop("network_allowlist", None)
workflow_runtime["network_targets"] = ["https://zhiyun.synthetic.example:443"]
workflow_manifest.write_text(
    yaml.safe_dump(workflow_payload, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
)

os.environ["FINANCIAL_ENV"] = "test"
os.environ["FINANCIAL_DATA_DIR"] = str(TEST_DATA_DIR)
os.environ["FINANCIAL_DATABASE_URL"] = (
    f"sqlite:///{(TEST_DATA_DIR / 'financial-tests.db').as_posix()}"
)
os.environ["FINANCIAL_SKILL_DIR"] = str(TEST_SKILL_DIR)
# 测试使用固定管理员口令，避免 bootstrap 随机口令阻塞自动化登录。
os.environ["FINANCIAL_BOOTSTRAP_ADMIN_PASSWORD"] = "test-admin-password"


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_data():
    yield
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
