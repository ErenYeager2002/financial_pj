from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]


class MigrationComposeTests(unittest.TestCase):
    def configurations(self):
        for environment in ("production", "development"):
            yield environment, yaml.safe_load((ROOT / "deploy" / environment / "compose.yaml").read_text())["services"]

    def test_migration_is_an_explicit_one_shot_with_only_database_dependency(self):
        for environment, services in self.configurations():
            with self.subTest(environment=environment):
                migrate = services["migrate"]
                self.assertEqual(migrate["restart"], "no")
                self.assertNotIn("profiles", migrate)
                self.assertEqual(migrate["depends_on"], {"postgres": {"condition": "service_healthy"}})
                command = migrate["command"]
                self.assertEqual(command[:3], ["python", "-m", "app.infrastructure.database.cli"])
                for option, variable in (("--expected-revision", "FINANCIAL_MIGRATION_EXPECTED_REVISION"), ("--target-revision", "FINANCIAL_MIGRATION_TARGET_REVISION")):
                    self.assertIn(variable + ":?", command[command.index(option) + 1])
                self.assertNotIn("migrate_sqlite_to_postgres", " ".join(command))

    def test_api_and_database_workers_require_successful_migration(self):
        for environment, services in self.configurations():
            for name, service in services.items():
                if name == "api" or name.startswith("worker-") and name != "worker-agent":
                    with self.subTest(environment=environment, service=name):
                        self.assertEqual(service["depends_on"]["migrate"]["condition"], "service_completed_successfully")

    def test_full_dependency_graph_is_acyclic(self):
        for environment, services in self.configurations():
            done = set()
            def visit(name, path):
                self.assertNotIn(name, path, f"Dependency cycle in {environment}: {path}")
                self.assertIn(name, services)
                if name in done:
                    return
                for dependency in services[name].get("depends_on", {}):
                    visit(dependency, (*path, name))
                done.add(name)
            for name in services:
                visit(name, ())

    def test_data_import_is_separate_opt_in_and_never_a_runtime_dependency(self):
        services = dict(self.configurations())["production"]
        service = services["import-sqlite"]
        self.assertEqual(service["profiles"], ["data-import"])
        self.assertIn("/app/scripts/migrate_sqlite_to_postgres.py", service["command"])
        self.assertNotIn("app.infrastructure.database.cli", service["command"])
        for other in services.values():
            self.assertNotIn("import-sqlite", other.get("depends_on", {}))
