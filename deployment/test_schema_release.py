import tempfile
import hashlib
import json
import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

import yaml

import platform_adapter
from platform_adapter import PlatformAdapter
from maintenance_flow import PLANS, DeploymentFailure, deploy
from schema_release import SchemaRelease, SCHEMA_SERVICES

IMAGE = "sha256:" + "a" * 64
ORIGINAL = """name: financial-platform-isolated
services:
  api:
    image: sha256:old-api
    environment:
      FINANCIAL_DATABASE_URL: synthetic-only
  worker-standard:
    image: ${BACKEND_IMAGE}
  worker-task-discovery:
    image: ${BACKEND_IMAGE}
  next:
    image: unchanged-next
  postgres:
    image: unchanged-postgres
networks:
  data:
    internal: true
"""


class SchemaReleaseTests(unittest.TestCase):
    def test_only_three_finance_images_change(self):
        plan = SchemaRelease.prepare(ORIGINAL, IMAGE, "e0f1a2b3c4d5", "f2a3b4c5d6e7")
        old, new = yaml.safe_load(ORIGINAL), yaml.safe_load(plan.compose_text)
        for name in SCHEMA_SERVICES:
            old["services"][name]["image"] = IMAGE
        self.assertEqual(old, new)
        self.assertEqual(yaml.safe_load(plan.overlay_text()), {"services": {"api": {"image": IMAGE}}})

    def test_other_project_and_ambiguous_image_configuration_rejected(self):
        for source in (ORIGINAL.replace("name: financial-platform-isolated", "name: dashboard"), ORIGINAL.replace("    image: sha256:old-api", "    image: one\n    image: two")):
            with self.assertRaises(DeploymentFailure):
                SchemaRelease.prepare(source, IMAGE, "e0f1a2b3c4d5", "f2a3b4c5d6e7")

    def adapter(self, root):
        (root / "compose.yaml").write_text(ORIGINAL)
        adapter = PlatformAdapter.__new__(PlatformAdapter)
        adapter.directory = root / "maintenance"
        adapter.directory.mkdir()
        adapter.schema_migration_attempted = False
        adapter.schema_container_ids = {}
        adapter.schema_stop_requested = set()
        adapter.schema_rollback_plan = None
        adapter.schema_rollback_overlay = None
        adapter.expected_schema_image = None
        adapter.schema_recovery = False
        adapter.schema_agent_identity = None
        adapter.schema_rollback_image = None
        adapter.resume_schema_agent = Mock()
        adapter.quiesce_schema_services = Mock()
        adapter.verify_schema_target = Mock()
        adapter.schema_revisions = ("e0f1a2b3c4d5", "f2a3b4c5d6e7")
        adapter.schema_release = SchemaRelease.prepare(ORIGINAL, IMAGE, *adapter.schema_revisions)
        adapter.schema_overlay = root / "override.json"
        adapter.schema_overlay.write_text(adapter.schema_release.overlay_text())
        return adapter

    def test_migration_succeeds_before_pins_and_service_switch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                calls = []
                def command(args, timeout=30):
                    calls.append(args)
                    if "run" in args:
                        self.assertEqual((root / "compose.yaml").read_text(), ORIGINAL)
                    return ""
                adapter.command = command
                adapter.cutover(PLANS["backend-schema"], IMAGE)
                self.assertIn("run", calls[0])
                self.assertIn("app.infrastructure.database.cli", calls[0])
                self.assertTrue(all("up" in call for call in calls[1:]))
                self.assertEqual((root / "compose.yaml").read_text(), adapter.schema_release.compose_text)
                self.assertFalse((root / ".env").exists())

    def test_migration_failure_never_publishes_config_or_starts_services(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                calls = []
                def command(args, timeout=30):
                    calls.append(args)
                    raise DeploymentFailure("synthetic migration failure")
                adapter.command = command
                with self.assertRaisesRegex(DeploymentFailure, "synthetic migration failure"):
                    adapter.cutover(PLANS["backend-schema"], IMAGE)
                self.assertEqual(len(calls), 1)
                self.assertNotIn("up", calls[0])
                self.assertEqual((root / "compose.yaml").read_text(), ORIGINAL)

    def test_configuration_drift_blocks_migration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                (root / "compose.yaml").write_text(ORIGINAL + "# independent change\n")
                adapter.command = lambda *args, **kwargs: self.fail("Drifted deployment executed a command")
                with self.assertRaisesRegex(DeploymentFailure, "changed after preflight"):
                    adapter.cutover(PLANS["backend-schema"], IMAGE)

    def test_configuration_drift_during_migration_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                def command(args, timeout=30):
                    self.assertIn("run", args)
                    (root / "compose.yaml").write_text(ORIGINAL + "# independent change\n")
                    return ""
                adapter.command = command
                with self.assertRaisesRegex(DeploymentFailure, "changed during migration"):
                    adapter.cutover(PLANS["backend-schema"], IMAGE)
                self.assertTrue((root / "compose.yaml").read_text().endswith("# independent change\n"))


    def test_timeout_keeps_named_container_record_and_does_not_switch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                calls = []
                def command(args, timeout=30):
                    calls.append(args)
                    raise subprocess.TimeoutExpired(args, timeout)
                adapter.command = command
                with self.assertRaises(subprocess.TimeoutExpired):
                    adapter.cutover(PLANS["backend-schema"], IMAGE)
                record_path = adapter.directory / "schema-migration.json"
                record = json.loads(record_path.read_text())
                self.assertEqual(record["phase"], "observation_required")
                self.assertIn(record["container_name"], calls[0])
                self.assertNotIn("--rm", calls[0])
                self.assertEqual(record_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual((root / "compose.yaml").read_text(), ORIGINAL)
                self.assertEqual(len(calls), 1)

    def test_recovery_guard_uses_actual_container_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = self.adapter(root)
            adapter.record_schema_migration({"container_name": "financial-platform-isolated-schema-123456abcdef", "image_id": IMAGE, "phase": "observation_required"})
            for state, running, exit_code in [("running", True, 0), ("exited", False, 1), ("dead", False, 0), ("exited", False, 0)]:
                with self.subTest(state=state, exit_code=exit_code):
                    payload = {"state": {"Status": state, "Running": running, "ExitCode": exit_code}, "image": IMAGE,
                               "labels": {"com.docker.compose.project": "financial-platform-isolated", "com.docker.compose.service": "api"}}
                    adapter.command = lambda *args, **kwargs: json.dumps(payload)
                    if state == "exited" and exit_code == 0:
                        adapter.assert_no_unresolved_schema_migration()
                    else:
                        with self.assertRaises(DeploymentFailure):
                            adapter.assert_no_unresolved_schema_migration()

    def test_missing_container_remains_unknown_and_wrong_identity_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self.adapter(Path(temporary))
            adapter.record_schema_migration({"container_name": "financial-platform-isolated-schema-123456abcdef", "image_id": IMAGE, "phase": "starting"})
            def missing(*args, **kwargs):
                raise DeploymentFailure("synthetic missing handle")
            adapter.command = missing
            self.assertEqual(adapter.schema_status()["state"], "unknown")
            with self.assertRaises(DeploymentFailure):
                adapter.assert_no_unresolved_schema_migration()
            adapter.command = lambda *args, **kwargs: json.dumps({"state": {"Status": "exited", "Running": False, "ExitCode": 0}, "image": IMAGE, "labels": {"com.docker.compose.project": "dashboard", "com.docker.compose.service": "api"}})
            with self.assertRaisesRegex(DeploymentFailure, "identity mismatch"):
                adapter.schema_status()

    def test_successful_original_migration_is_reused_after_observation_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                def timeout(args, timeout=30):
                    raise subprocess.TimeoutExpired(args, timeout)
                adapter.command = timeout
                with self.assertRaises(subprocess.TimeoutExpired):
                    adapter.cutover(PLANS["backend-schema"], IMAGE)
                original_record = json.loads((adapter.directory / "schema-migration.json").read_text())
                calls = []
                def recovered(args, timeout=30):
                    calls.append(args)
                    if "inspect" in args:
                        self.assertEqual(args[-1], original_record["container_name"])
                        return json.dumps({"state": {"Status": "exited", "Running": False, "ExitCode": 0}, "image": IMAGE,
                            "labels": {"com.docker.compose.project": "financial-platform-isolated", "com.docker.compose.service": "api"}})
                    self.assertIn("up", args)
                    return ""
                adapter.command = recovered
                adapter.cutover(PLANS["backend-schema"], IMAGE)
                self.assertFalse(any("run" in call for call in calls))
                self.assertEqual(len(calls), 3)
                self.assertEqual((root / "compose.yaml").read_text(), adapter.schema_release.compose_text)
                saved = json.loads((adapter.directory / "schema-migration.json").read_text())
                self.assertEqual(saved["container_name"], original_record["container_name"])
                self.assertEqual(saved["phase"], "completed")
                adapter.verify_schema_target.assert_called_once()

    def test_running_original_migration_cannot_be_reexecuted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                adapter.record_schema_migration({"container_name": "financial-platform-isolated-schema-123456abcdef", "image_id": IMAGE,
                    "phase": "observation_required"})
                calls = []
                def running(args, timeout=30):
                    calls.append(args)
                    self.assertIn("inspect", args)
                    return json.dumps({"state": {"Status": "running", "Running": True, "ExitCode": 0}, "image": IMAGE,
                        "labels": {"com.docker.compose.project": "financial-platform-isolated", "com.docker.compose.service": "api"}})
                adapter.command = running
                with self.assertRaises(DeploymentFailure):
                    adapter.cutover(PLANS["backend-schema"], IMAGE)
                self.assertEqual(len(calls), 1)
                self.assertEqual((root / "compose.yaml").read_text(), ORIGINAL)

    def test_recovery_checks_current_revision_and_preserves_unrelated_services(self):
        for published in (False, True):
            with self.subTest(published=published), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with patch.object(platform_adapter, "ROOT", root):
                    adapter = self.adapter(root)
                    plan = adapter.schema_release
                    record = {"container_name": "financial-platform-isolated-schema-123456abcdef", "image_id": IMAGE,
                        "expected_revision": plan.expected_revision, "target_revision": plan.target_revision,
                        "original_sha256": plan.original_sha256,
                        "target_sha256": hashlib.sha256(plan.compose_text.encode()).hexdigest(), "rollback_image": IMAGE, "phase": "observation_required"}
                    adapter.record_schema_migration(record)
                    if published:
                        (root / "compose.yaml").write_text(plan.compose_text)
                    adapter.mode = lambda: "full"
                    adapter.verify_mode = lambda mode: self.assertEqual(mode, "full")
                    adapter.inspect = lambda: {"/financial-platform-isolated-next-1": {"Id": "protected", "State": {"StartedAt": "before"}}, "/financial-platform-isolated-worker-agent-1": {"Id": "agent", "Image": IMAGE, "RestartCount": 0, "State": {"StartedAt": "before", "Running": True}}}
                    calls = []
                    live_revision = plan.target_revision
                    def command(args, timeout=30):
                        calls.append(args)
                        if args[:3] == ["docker", "image", "inspect"]:
                            return IMAGE
                        if args[:2] == ["docker", "inspect"]:
                            return json.dumps({"state": {"Status": "exited", "Running": False, "ExitCode": 0}, "image": IMAGE,
                                "labels": {"com.docker.compose.project": "financial-platform-isolated", "com.docker.compose.service": "api"}})
                        if "psql" in args:
                            self.assertIn("PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=5000", args)
                            return live_revision
                        self.assertTrue("config" in args or "up" in args)
                        return ""
                    adapter.command = command
                    adapter.preflight_schema_recovery(IMAGE)
                    self.assertTrue(adapter.schema_recovery)
                    self.assertEqual(adapter.schema_rollback_plan.image_id, IMAGE)
                    self.assertEqual(adapter.protected, {"/financial-platform-isolated-next-1": ("protected", "before")})
                    adapter.cutover(PLANS["backend-schema"], IMAGE)
                    self.assertFalse(any("run" in call for call in calls))
                    live_revision = "unexpected_revision"
                    with self.assertRaisesRegex(DeploymentFailure, "database revision"):
                        adapter.preflight_schema_recovery(IMAGE)

    def test_schema_recovery_requires_maintenance_and_original_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                adapter.mode = lambda: "normal"
                adapter.command = lambda *args, **kwargs: self.fail("Normal mode recovery executed command")
                with self.assertRaisesRegex(DeploymentFailure, "full maintenance"):
                    adapter.preflight_schema_recovery(IMAGE)

    def test_new_migration_record_preserves_previous_execution_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self.adapter(Path(temporary))
            first = {"container_name": "financial-platform-isolated-schema-111111111111", "image_id": IMAGE, "phase": "completed"}
            second = {"container_name": "financial-platform-isolated-schema-222222222222", "image_id": IMAGE, "phase": "starting"}
            adapter.record_schema_migration(first)
            adapter.record_schema_migration(second)
            history = adapter.directory / "schema-history"
            self.assertEqual(history.stat().st_mode & 0o777, 0o700)
            for record in (first, second):
                path = history / (record["container_name"] + ".json")
                self.assertEqual(json.loads(path.read_text()), record)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((adapter.directory / "schema-migration.json").read_text()), second)
            with self.assertRaises(DeploymentFailure):
                adapter.record_schema_migration(dict(second, container_name="../unrelated"))

    def test_candidate_readback_is_readonly_and_requires_exact_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self.adapter(Path(temporary))
            calls = []
            def command(args, timeout=30):
                calls.append(args)
                return json.dumps({"revision": adapter.schema_release.target_revision})
            adapter.command = command
            PlatformAdapter.verify_schema_target(adapter)
            self.assertIn("PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=10000", calls[0])
            self.assertIn("--no-deps", calls[0])
            self.assertIn("check_runtime_database", calls[0][-1])
            self.assertNotIn("app.infrastructure.database.cli", calls[0])
            for response in ('{"revision":"f1a2b3c4d5e6"}', '{}', 'not-json'):
                adapter.command = lambda *args, **kwargs: response
                with self.assertRaises(DeploymentFailure):
                    PlatformAdapter.verify_schema_target(adapter)

    def test_failed_current_schema_readback_blocks_config_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                calls = []
                adapter.command = lambda args, **kwargs: calls.append(args) or ""
                adapter.verify_schema_target.side_effect = DeploymentFailure("synthetic incompatible schema")
                with self.assertRaisesRegex(DeploymentFailure, "incompatible schema"):
                    adapter.cutover(PLANS["backend-schema"], IMAGE)
                self.assertEqual((root / "compose.yaml").read_text(), ORIGINAL)
                self.assertEqual(len(calls), 1)
                self.assertIn("app.infrastructure.database.cli", calls[0])
                self.assertFalse(any("up" in args for args in calls))
                adapter.verify_schema_target.assert_called_once()

    def test_restored_database_after_success_never_reuses_unverified_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                plan = adapter.schema_release
                adapter.record_schema_migration({"container_name": "financial-platform-isolated-schema-123456abcdef",
                    "image_id": IMAGE, "expected_revision": plan.expected_revision, "target_revision": plan.target_revision,
                    "original_sha256": plan.original_sha256, "phase": "completed"})
                calls = []
                def command(args, timeout=30):
                    calls.append(args)
                    self.assertIn("inspect", args)
                    return json.dumps({"state": {"Status": "exited", "Running": False, "ExitCode": 0}, "image": IMAGE,
                        "labels": {"com.docker.compose.project": "financial-platform-isolated", "com.docker.compose.service": "api"}})
                adapter.command = command
                adapter.verify_schema_target.side_effect = DeploymentFailure("restored database is below target")
                with self.assertRaisesRegex(DeploymentFailure, "below target"):
                    adapter.cutover(PLANS["backend-schema"], IMAGE)
                adapter.verify_schema_target.assert_called_once()
                self.assertEqual(len(calls), 1)
                self.assertEqual((root / "compose.yaml").read_text(), ORIGINAL)

    def test_schema_quiesce_closes_ingress_before_draining_and_stopping(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self.adapter(Path(temporary))
            calls = []
            adapter.mode = lambda: "full"
            adapter.verify_mode = lambda mode: calls.append("verify-full")
            adapter.wait_idle = lambda: calls.append("idle")
            adapter.stop_schema_service_gracefully = lambda name, **kwargs: calls.append(name)
            adapter.active_counts = lambda: {"runs": 0}
            response = Mock()
            response.status = 503
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            with patch.object(platform_adapter.urllib.request, "urlopen", return_value=response):
                PlatformAdapter.quiesce_schema_services(adapter)
            self.assertEqual(calls, ["verify-full", "idle", "worker-task-discovery", "idle", "worker-standard", "worker-agent", "api"])
            response.status = 200
            calls.clear()
            with patch.object(platform_adapter.urllib.request, "urlopen", return_value=response):
                with self.assertRaisesRegex(DeploymentFailure, "ingress"):
                    PlatformAdapter.quiesce_schema_services(adapter)
            self.assertEqual(calls, ["verify-full"])

    def test_schema_service_stop_never_forces_or_accepts_observation_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self.adapter(Path(temporary))
            calls = []
            payload = {"id": "stable-id", "state": {"Running": True, "Status": "running", "ExitCode": 0},
                "labels": {"com.docker.compose.project": "financial-platform-isolated", "com.docker.compose.service": "worker-standard"}}
            def command(args, timeout=30):
                calls.append(args)
                if "inspect" in args:
                    return json.dumps(payload)
                self.assertEqual(args, ["docker", "stop", "--timeout", "-1", "financial-platform-isolated-worker-standard-1"])
                raise subprocess.TimeoutExpired(args, timeout)
            adapter.command = command
            with self.assertRaises(subprocess.TimeoutExpired):
                adapter.stop_schema_service_gracefully("worker-standard")
            self.assertEqual(len(calls), 2)
            with self.assertRaisesRegex(DeploymentFailure, "outside"):
                adapter.stop_schema_service_gracefully("postgres")

    def test_original_service_restore_requires_same_containers_and_unchanged_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                adapter.mode = lambda: "full"
                adapter.schema_container_ids = {name: "original-"+name for name in SCHEMA_SERVICES}
                adapter.schema_stop_requested = set(SCHEMA_SERVICES)
                containers = {"/financial-platform-isolated-"+name+"-1": {"Id": identity,
                    "State": {"Running": False, "Status": "exited", "ExitCode": 0}} for name, identity in adapter.schema_container_ids.items()}
                adapter.inspect = lambda: containers
                calls = []
                def command(args, timeout=30):
                    calls.append(args)
                    return adapter.schema_release.expected_revision if "psql" in args else ""
                adapter.command = command
                self.assertTrue(adapter.restore_before_schema_migration())
                self.assertEqual(calls[-1], ["docker", "start", *adapter.schema_container_ids.values()])
                calls.clear()
                adapter.schema_migration_attempted = True
                self.assertFalse(adapter.restore_before_schema_migration())
                self.assertEqual(calls, [])
                adapter.schema_migration_attempted = False
                containers["/financial-platform-isolated-api-1"]["State"]["Running"] = True
                with self.assertRaisesRegex(DeploymentFailure, "finished stopping"):
                    adapter.restore_before_schema_migration()
                self.assertFalse(any("start" in call for call in calls))

    def test_original_restore_refuses_changed_revision_without_starting_services(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                adapter.mode = lambda: "full"
                adapter.schema_container_ids = {name: "original-"+name for name in SCHEMA_SERVICES}
                adapter.schema_stop_requested = set(SCHEMA_SERVICES)
                calls = []
                adapter.command = lambda args, **kwargs: calls.append(args) or "f2a3b4c5d6e7"
                with self.assertRaisesRegex(DeploymentFailure, "changed database"):
                    adapter.restore_before_schema_migration()
                self.assertEqual(len(calls), 1)
                self.assertIn("psql", calls[0])

    def test_failed_schema_deploy_reopens_only_after_original_health_is_verified(self):
        adapter = Mock()
        adapter.mode.return_value = "normal"
        adapter.cutover.side_effect = DeploymentFailure("synthetic pre-migration failure")
        adapter.restore_before_schema_migration.return_value = True
        with self.assertRaisesRegex(DeploymentFailure, "pre-migration failure"):
            deploy(adapter, "backend-schema", IMAGE)
        events = [call[0] for call in adapter.mock_calls]
        self.assertLess(events.index("restore_before_schema_migration"), events.index("wait_healthy"))
        modes = [call.args[0] for call in adapter.set_mode.call_args_list]
        self.assertEqual(modes[-1], "normal")
        adapter.record.assert_any_call("restored-service", "backend-schema")

    def test_failed_original_health_keeps_full_maintenance(self):
        adapter = Mock()
        adapter.mode.return_value = "normal"
        adapter.cutover.side_effect = DeploymentFailure("synthetic cutover failure")
        adapter.restore_before_schema_migration.return_value = True
        adapter.wait_healthy.side_effect = DeploymentFailure("synthetic health failure")
        with self.assertRaisesRegex(DeploymentFailure, "health failure"):
            deploy(adapter, "backend-schema", IMAGE)
        modes = [call.args[0] for call in adapter.set_mode.call_args_list]
        self.assertNotIn("normal", modes)
        self.assertEqual(modes[-1], "full")
        adapter.record.assert_any_call("recovery-required", "backend-schema")

    def test_partial_drain_restores_only_the_original_service_stopped_by_this_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                adapter.mode = lambda: "full"
                adapter.schema_container_ids = {name: "original-"+name for name in SCHEMA_SERVICES}
                adapter.schema_stop_requested = {"worker-task-discovery"}
                containers = {"/financial-platform-isolated-"+name+"-1": {"Id": identity,
                    "State": {"Running": name != "worker-task-discovery", "Status": "exited" if name == "worker-task-discovery" else "running", "ExitCode": 0}}
                    for name, identity in adapter.schema_container_ids.items()}
                adapter.inspect = lambda: containers
                calls = []
                adapter.command = lambda args, **kwargs: calls.append(args) or adapter.schema_release.expected_revision
                self.assertTrue(adapter.restore_before_schema_migration())
                self.assertEqual(calls[-1], ["docker", "start", "original-worker-task-discovery"])
                self.assertEqual(len(calls), 2)
                containers["/financial-platform-isolated-worker-standard-1"]["State"] = {"Running": False, "Status": "exited", "ExitCode": 0}
                calls.clear()
                with self.assertRaisesRegex(DeploymentFailure, "outside this deployment"):
                    adapter.restore_before_schema_migration()
                self.assertEqual(len(calls), 1)

    def test_compatible_rollback_changes_only_images_without_migrating(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                rollback_image = "sha256:" + "b"*64
                adapter.schema_rollback_plan = SchemaRelease.prepare(ORIGINAL, rollback_image, *adapter.schema_revisions)
                adapter.schema_rollback_overlay = root / "rollback.json"
                adapter.schema_rollback_overlay.write_text(adapter.schema_rollback_plan.overlay_text())
                (root / "compose.yaml").write_text(adapter.schema_release.compose_text)
                adapter.schema_status = lambda: {"state": "exited", "running": False, "exit_code": 0}
                adapter.start_selected_services = Mock()
                adapter.command = Mock(side_effect=AssertionError("Rollback issued a migration or unplanned command"))
                self.assertTrue(adapter.rollback_after_schema_migration())
                adapter.quiesce_schema_services.assert_called_once_with(allow_failed_stopped=True)
                adapter.verify_schema_target.assert_called_once_with(adapter.schema_rollback_plan, adapter.schema_rollback_overlay)
                adapter.start_selected_services.assert_called_once_with(PLANS["backend-schema"])
                self.assertEqual((root / "compose.yaml").read_text(), adapter.schema_rollback_plan.compose_text)
                adapter.command.assert_not_called()

    def test_unknown_migration_never_stops_or_rolls_back_application(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self.adapter(Path(temporary))
            adapter.schema_rollback_plan = adapter.schema_release
            adapter.schema_rollback_overlay = adapter.schema_overlay
            for state in ({"state": "unknown"}, {"state": "running", "running": True, "exit_code": 0}, {"state": "exited", "running": False, "exit_code": 1}):
                adapter.schema_status = lambda: state
                with self.assertRaisesRegex(DeploymentFailure, "not confirmed successful"):
                    adapter.rollback_after_schema_migration()
            adapter.quiesce_schema_services.assert_not_called()
            adapter.verify_schema_target.assert_not_called()

    def test_incompatible_rollback_keeps_candidate_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                adapter.schema_rollback_plan = SchemaRelease.prepare(ORIGINAL, "sha256:"+"b"*64, *adapter.schema_revisions)
                adapter.schema_rollback_overlay = root / "rollback.json"
                adapter.schema_status = lambda: {"state": "exited", "running": False, "exit_code": 0}
                adapter.verify_schema_target.side_effect = DeploymentFailure("rollback schema mismatch")
                adapter.start_selected_services = Mock()
                with self.assertRaisesRegex(DeploymentFailure, "schema mismatch"):
                    adapter.rollback_after_schema_migration()
                self.assertEqual((root / "compose.yaml").read_text(), ORIGINAL)
                adapter.start_selected_services.assert_not_called()

    def test_healthy_containers_with_wrong_schema_image_cannot_reopen(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self.adapter(Path(temporary))
            adapter.expected_schema_image = IMAGE
            adapter.assert_no_unresolved_schema_migration = Mock()
            adapter.inspect = lambda: {"/financial-platform-isolated-"+name+"-1": {"Image": "sha256:"+"c"*64,
                "State": {"Running": True, "Health": {"Status": "healthy"}}} for name in SCHEMA_SERVICES}
            adapter.active_counts = Mock()
            with self.assertRaisesRegex(DeploymentFailure, "verified image"):
                adapter.healthy_sample()
            adapter.active_counts.assert_not_called()

    def test_confirmed_recovery_accepts_already_failed_stopped_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self.adapter(Path(temporary))
            payload = {"id": "failed-candidate", "state": {"Running": False, "Status": "exited", "ExitCode": 1},
                "labels": {"com.docker.compose.project": "financial-platform-isolated", "com.docker.compose.service": "api"}}
            calls = []
            adapter.command = lambda args, **kwargs: calls.append(args) or json.dumps(payload)
            with self.assertRaises(DeploymentFailure):
                adapter.stop_schema_service_gracefully("api")
            calls.clear()
            adapter.stop_schema_service_gracefully("api", allow_failed_stopped=True)
            self.assertEqual(len(calls), 2)
            self.assertTrue(all("inspect" in args for args in calls))

    def test_migration_record_retains_exact_rollback_image_and_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(platform_adapter, "ROOT", root):
                adapter = self.adapter(root)
                adapter.schema_rollback_plan = SchemaRelease.prepare(ORIGINAL, "sha256:"+"b"*64, *adapter.schema_revisions)
                adapter.command = lambda *args, **kwargs: ""
                adapter.cutover(PLANS["backend-schema"], IMAGE)
                record = json.loads((adapter.directory / "schema-migration.json").read_text())
                self.assertEqual(record["rollback_image"], adapter.schema_rollback_plan.image_id)
                self.assertEqual(record["rollback_sha256"], hashlib.sha256(adapter.schema_rollback_plan.compose_text.encode()).hexdigest())

    def test_agent_resumes_same_container_only_after_api_is_healthy(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self.adapter(Path(temporary))
            adapter.protected = {"/financial-platform-isolated-worker-agent-1": ("agent-original", "old")}
            containers = {
                "/financial-platform-isolated-api-1": {"State": {"Running": True, "Health": {"Status": "healthy"}}},
                "/financial-platform-isolated-worker-agent-1": {"Id": "agent-original", "Image": "agent-image", "RestartCount": 11,
                    "State": {"Running": False, "Status": "exited", "ExitCode": 0, "StartedAt": "old"}},
            }
            containers["/financial-platform-isolated-worker-agent-1"]["State"]["Running"] = True
            adapter.capture_schema_agent(containers)
            containers["/financial-platform-isolated-worker-agent-1"]["State"]["Running"] = False
            self.assertNotIn("/financial-platform-isolated-worker-agent-1", adapter.protected)
            adapter.schema_stop_requested.add("worker-agent")
            adapter.inspect = lambda: containers
            calls = []
            def start(args, timeout=30):
                calls.append(args)
                self.assertEqual(args, ["docker", "start", "agent-original"])
                agent = containers["/financial-platform-isolated-worker-agent-1"]
                agent["State"].update(Running=True, Status="running", StartedAt="resumed")
                agent["RestartCount"] = 0
                return "agent-original"
            adapter.command = start
            PlatformAdapter.resume_schema_agent(adapter)
            self.assertEqual(calls, [["docker", "start", "agent-original"]])
            self.assertEqual(adapter.schema_agent_identity["started_at"], "resumed")
            self.assertNotIn("worker-agent", adapter.schema_stop_requested)
            PlatformAdapter.resume_schema_agent(adapter)
            self.assertEqual(len(calls), 1)
            containers["/financial-platform-isolated-worker-agent-1"]["RestartCount"] = 1
            with self.assertRaisesRegex(DeploymentFailure, "restarted outside"):
                PlatformAdapter.resume_schema_agent(adapter)

    def test_agent_never_starts_before_api_health_or_after_identity_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            adapter = self.adapter(Path(temporary))
            adapter.schema_agent_identity = {"id": "original", "image": "original-image", "started_at": "old", "restarts": 0}
            adapter.schema_stop_requested.add("worker-agent")
            containers = {"/financial-platform-isolated-api-1": {"State": {"Running": True, "Health": {"Status": "starting"}}},
                "/financial-platform-isolated-worker-agent-1": {"Id": "replacement", "Image": "original-image", "State": {"Running": False}}}
            adapter.inspect = lambda: containers
            adapter.command = Mock()
            with self.assertRaisesRegex(DeploymentFailure, "API must be healthy"):
                PlatformAdapter.resume_schema_agent(adapter)
            containers["/financial-platform-isolated-api-1"]["State"]["Health"]["Status"] = "healthy"
            with self.assertRaisesRegex(DeploymentFailure, "identity changed"):
                PlatformAdapter.resume_schema_agent(adapter)
            adapter.command.assert_not_called()

    def test_new_adapter_recovers_persisted_coordinated_agent_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = self.adapter(Path(temporary))
            first.schema_agent_identity = {"id": "original-agent", "image": "agent-image", "started_at": "old", "restarts": 0}
            first.record_schema_agent_state("stop-requested")
            record_path = first.directory / "schema-agent-stop.json"
            self.assertEqual(record_path.stat().st_mode & 0o777, 0o600)
            recovered = PlatformAdapter.__new__(PlatformAdapter)
            recovered.directory = first.directory
            recovered.schema_container_ids = {}
            recovered.schema_stop_requested = set()
            recovered.protected = {}
            containers = {"/financial-platform-isolated-api-1": {"State": {"Running": True, "Health": {"Status": "healthy"}}},
                "/financial-platform-isolated-worker-agent-1": {"Id": "original-agent", "Image": "agent-image", "RestartCount": 0,
                    "State": {"Running": False, "Status": "exited", "ExitCode": 0, "StartedAt": "old"}}}
            recovered.capture_schema_agent(containers)
            self.assertIn("worker-agent", recovered.schema_stop_requested)
            recovered.inspect = lambda: containers
            calls = []
            def command(args, timeout=30):
                calls.append(args)
                containers["/financial-platform-isolated-worker-agent-1"]["State"].update(Running=True, Status="running", StartedAt="resumed")
                return ""
            recovered.command = command
            recovered.resume_schema_agent()
            self.assertEqual(calls, [["docker", "start", "original-agent"]])
            self.assertEqual(json.loads(record_path.read_text())["phase"], "resumed")
            containers["/financial-platform-isolated-worker-agent-1"]["State"].update(Running=False, Status="exited")
            with self.assertRaisesRegex(DeploymentFailure, "not owned"):
                recovered.capture_schema_agent(containers)


class FrontendReleaseTests(unittest.TestCase):
    def test_literal_frontend_image_is_pinned_without_other_changes(self):
        from frontend_release import FrontendRelease
        plan=FrontendRelease.prepare(ORIGINAL,IMAGE)
        before=yaml.safe_load(ORIGINAL)
        before["services"]["next"]["image"]=IMAGE
        self.assertEqual(yaml.safe_load(plan.compose_text),before)
        for bad in [ORIGINAL.replace("name: financial-platform-isolated","name: dashboard"),ORIGINAL.replace("image: unchanged-next","image: one\n    image: two")]:
            with self.assertRaises(DeploymentFailure):FrontendRelease.prepare(bad,IMAGE)

    def test_frontend_cutover_updates_effective_compose_before_recreate(self):
        from frontend_release import FrontendRelease
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/"compose.yaml").write_text(ORIGINAL)
            adapter=PlatformAdapter.__new__(PlatformAdapter)
            adapter.schema_revisions=None
            adapter.frontend_release=FrontendRelease.prepare(ORIGINAL,IMAGE)
            def start(plan):
                self.assertEqual(yaml.safe_load((root/"compose.yaml").read_text())["services"]["next"]["image"],IMAGE)
                self.assertEqual(plan.services,("next",))
            adapter.start_selected_services=Mock(side_effect=start)
            with patch.object(platform_adapter,"ROOT",root):
                adapter.cutover(PLANS["frontend"],IMAGE)
            adapter.start_selected_services.assert_called_once()
            self.assertEqual(adapter.expected_frontend_image,IMAGE)
            self.assertFalse((root/".env").exists())

    def test_frontend_drift_prevents_service_change(self):
        from frontend_release import FrontendRelease
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/"compose.yaml").write_text(ORIGINAL+"# changed\n")
            adapter=PlatformAdapter.__new__(PlatformAdapter)
            adapter.schema_revisions=None
            adapter.frontend_release=FrontendRelease.prepare(ORIGINAL,IMAGE)
            adapter.start_selected_services=Mock()
            with patch.object(platform_adapter,"ROOT",root),self.assertRaises(DeploymentFailure):
                adapter.cutover(PLANS["frontend"],IMAGE)
            adapter.start_selected_services.assert_not_called()

    def test_healthy_old_frontend_cannot_pass_new_image_readiness(self):
        adapter=PlatformAdapter.__new__(PlatformAdapter)
        adapter.assert_no_unresolved_schema_migration=Mock()
        adapter.verify_recorded_image_pair=Mock()
        adapter.inspect=Mock(return_value={'/financial-platform-isolated-next-1':{'Image':'sha256:old','State':{'Running':True}}})
        adapter.schema_agent_identity=None
        adapter.expected_schema_image=None
        adapter.expected_frontend_image=IMAGE
        with self.assertRaisesRegex(DeploymentFailure,"verified image"):
            adapter.healthy_sample()


    def test_frontend_failure_restores_only_original_image_before_reopening(self):
        from frontend_release import FrontendRelease
        old="sha256:"+"b"*64
        for failure in ("start", "health"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)
                (root/"compose.yaml").write_text(ORIGINAL)
                adapter=PlatformAdapter.__new__(PlatformAdapter)
                adapter.schema_revisions=None
                adapter.frontend_release=FrontendRelease.prepare(ORIGINAL,IMAGE)
                adapter.frontend_rollback_plan=FrontendRelease.prepare(ORIGINAL,old)
                adapter.frontend_observation_required=False
                adapter.protected={"/financial-platform-isolated-api-1":("api-original","started")}
                adapter.inspect=lambda:{"/financial-platform-isolated-api-1":{"Id":"api-original","State":{"Running":True,"StartedAt":"started"}}}
                state=["normal"]
                adapter.mode=lambda:state[0]
                adapter.set_mode=lambda mode:state.__setitem__(0,mode)
                adapter.verify_mode=Mock()
                adapter.preflight=Mock()
                adapter.backup=Mock()
                adapter.grace=Mock()
                adapter.record=Mock()
                def command(args,**kw):
                    if args[:2] == ["docker","inspect"]:
                        self.assertEqual(args[2:],["/financial-platform-isolated-api-1"])
                        return json.dumps([{"Name":args[2],"Id":"api-original","State":{"Running":True,"StartedAt":"started"}}])
                    return old
                adapter.command=command
                starts=[]
                def start(plan):
                    self.assertEqual(plan.services,("next",))
                    starts.append(adapter.expected_frontend_image)
                    if len(starts)==1 and failure=="start":raise DeploymentFailure("candidate start failed")
                def healthy(plan):
                    if adapter.expected_frontend_image==IMAGE:raise DeploymentFailure("candidate health failed")
                    self.assertEqual(adapter.expected_frontend_image,old)
                adapter.start_selected_services=start
                adapter.wait_healthy=healthy
                with patch.object(platform_adapter,"ROOT",root), self.assertRaisesRegex(DeploymentFailure,"candidate"):
                    deploy(adapter,"frontend",IMAGE)
                self.assertEqual(starts,[IMAGE,old])
                self.assertEqual(state[0],"normal")
                self.assertEqual(yaml.safe_load((root/"compose.yaml").read_text())["services"]["next"]["image"],old)
                adapter.record.assert_any_call("restored-service","frontend")

    def test_frontend_rollback_rejects_drift_and_unknown_operation(self):
        from frontend_release import FrontendRelease
        for unknown in (False,True):
            with tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)
                current=ORIGINAL if unknown else ORIGINAL+"# external change\n"
                (root/"compose.yaml").write_text(current)
                adapter=PlatformAdapter.__new__(PlatformAdapter)
                adapter.mode=lambda:"full"
                adapter.frontend_release=FrontendRelease.prepare(ORIGINAL,IMAGE)
                adapter.frontend_rollback_plan=FrontendRelease.prepare(ORIGINAL,"sha256:"+"b"*64)
                adapter.frontend_observation_required=unknown
                adapter.start_selected_services=Mock()
                with patch.object(platform_adapter,"ROOT",root),self.assertRaises(DeploymentFailure):
                    adapter.rollback_frontend()
                self.assertEqual((root/"compose.yaml").read_text(),current)
                adapter.start_selected_services.assert_not_called()
