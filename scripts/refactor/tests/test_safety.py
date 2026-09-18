import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("isolation", ROOT / "scripts/refactor/verify_isolation.py")
isolation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(isolation)

class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="financial-refactor-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / ".refactor-isolated").write_text("synthetic-only-v1")
        self.env = {
            "REFACTOR_TEST_ROOT": str(self.root),
            "FINANCIAL_ENV": "test",
            "FINANCIAL_DATA_DIR": str(self.root / "data"),
            "FINANCIAL_DATABASE_URL": "sqlite:///" + str(self.root / "test.db"),
            "FINANCIAL_AR_HEXIAO_EXECUTION_ENABLED": "false",
            "FINANCIAL_TASK_DISCOVERY_ENABLED": "false",
            "REFACTOR_REAL_CONNECTORS": "disabled",
        }
    def test_valid_synthetic_environment(self):
        isolation.verify(self.env)
    def test_missing_marker_rejected(self):
        (self.root / ".refactor-isolated").unlink()
        with self.assertRaises(ValueError): isolation.verify(self.env)
    def test_production_database_rejected(self):
        self.env["FINANCIAL_DATABASE_URL"] = "postgresql://test:test@postgres/financial"
        with self.assertRaises(ValueError): isolation.verify(self.env)
    def test_outside_data_rejected(self):
        self.env["FINANCIAL_DATA_DIR"] = "/var/lib/financial-platform"
        with self.assertRaises(ValueError): isolation.verify(self.env)
    def test_symlink_rejected(self):
        (self.root / "escape").symlink_to("/tmp", target_is_directory=True)
        self.env["FINANCIAL_DATA_DIR"] = str(self.root / "escape/data")
        with self.assertRaises(ValueError): isolation.verify(self.env)
    def test_real_connector_rejected(self):
        self.env["FINANCIAL_ZHIYUN_BASE_URL"] = "https://company.example"
        with self.assertRaises(ValueError): isolation.verify(self.env)
    def test_write_gate_rejected(self):
        self.env["FINANCIAL_AR_HEXIAO_EXECUTION_ENABLED"] = "true"
        with self.assertRaises(ValueError): isolation.verify(self.env)
    def test_pg_requires_explicit_test_name_and_host(self):
        self.env["FINANCIAL_DATABASE_URL"] = "postgresql://test:test@127.0.0.1/financial_refactor_test_001"
        isolation.verify(self.env)
        self.env["FINANCIAL_DATABASE_URL"] = "postgresql://test:test@192.168.30.46/financial_refactor_test_001"
        with self.assertRaises(ValueError): isolation.verify(self.env)

if __name__ == "__main__": unittest.main()
