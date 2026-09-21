"""Paired API/Agent release contract; synthetic containers only."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml
import platform_adapter
from platform_adapter import PlatformAdapter, PROJECT
from schema_release import SchemaRelease
from maintenance_flow import DeploymentFailure
from test_schema_release import ORIGINAL, IMAGE

AGENT = "sha256:" + "b" * 64
OLD_AGENT = "sha256:" + "c" * 64
SOURCE = ORIGINAL.replace("  next:", "  worker-agent:\n    image: " + OLD_AGENT + "\n    command: node worker.js\n  next:")

class AgentReleaseTests(unittest.TestCase):
    def test_pair_changes_only_four_images(self):
        plan = SchemaRelease.prepare(SOURCE, IMAGE, "f4", "f4", agent_image_id=AGENT)
        before, after = yaml.safe_load(SOURCE), yaml.safe_load(plan.compose_text)
        for name in ("api", "worker-standard", "worker-task-discovery"):
            before["services"][name]["image"] = IMAGE
        before["services"]["worker-agent"]["image"] = AGENT
        self.assertEqual(before, after)
        self.assertEqual(plan.agent_image_id, AGENT)
        self.assertEqual(yaml.safe_load(plan.overlay_text()), {"services": {"api": {"image": IMAGE}}})

    def test_pair_requires_digest_and_explicit_agent_service(self):
        for source, image in ((SOURCE, "agent:latest"), (ORIGINAL, AGENT)):
            with self.subTest(image=image), self.assertRaises(DeploymentFailure):
                SchemaRelease.prepare(source, IMAGE, "f4", "f4", agent_image_id=image)

    def make_adapter(self, root):
        adapter = PlatformAdapter.__new__(PlatformAdapter)
        adapter.schema_agent_identity = {"id": "old-agent", "image": OLD_AGENT, "started_at": "old-time", "restarts": 0}
        adapter.schema_stop_requested = {"worker-agent"}
        adapter.expected_agent_image = AGENT
        adapter.expected_schema_image = IMAGE
        adapter.agent_switch_observation_required = False
        adapter.directory = root
        adapter.record_schema_agent_state = Mock()
        adapter.mode = lambda: "full"
        adapter.verify_mode = Mock()
        adapter.schema_release = SchemaRelease.prepare(SOURCE, IMAGE, "f4", "f4", agent_image_id=AGENT)
        (root / "compose.yaml").write_text(adapter.schema_release.compose_text)
        values = {
            "/" + PROJECT + "-api-1": {"Image": IMAGE, "State": {"Running": True, "Health": {"Status": "healthy"}}},
            "/" + PROJECT + "-worker-agent-1": {
                "Id": "old-agent", "Image": OLD_AGENT, "RestartCount": 0,
                "State": {"Running": False, "Status": "exited", "ExitCode": 0, "StartedAt": "old-time"},
                "Config": {"Labels": {"com.docker.compose.project": PROJECT, "com.docker.compose.service": "worker-agent"}},
            },
        }
        adapter.inspect = lambda: copy.deepcopy(values)
        calls = []
        def command(args, timeout=30):
            calls.append(args)
            if "up" in args:
                item = values["/" + PROJECT + "-worker-agent-1"]
                item.update(Id="new-agent", Image=AGENT)
                item["State"].update(Running=True, Status="running", StartedAt="new-time")
            return ""
        adapter.command = command
        return adapter, values, calls

    def test_new_agent_starts_only_after_healthy_api_and_updates_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(platform_adapter, "ROOT", root):
                adapter, values, calls = self.make_adapter(root)
                adapter.resume_schema_agent()
                self.assertEqual(adapter.schema_agent_identity["image"], AGENT)
                self.assertEqual(adapter.schema_agent_identity["id"], "new-agent")
                self.assertEqual(len(calls), 1)
                self.assertIn("--no-deps", calls[0])
                self.assertEqual(calls[0][-1], "worker-agent")
                self.assertNotIn("worker-agent", adapter.schema_stop_requested)

    def test_unhealthy_api_never_starts_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter, values, calls = self.make_adapter(Path(tmp))
            values["/" + PROJECT + "-api-1"]["State"]["Health"]["Status"] = "unhealthy"
            with self.assertRaises(DeploymentFailure):
                adapter.resume_schema_agent()
            self.assertEqual(calls, [])

    def test_running_old_agent_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter, values, calls = self.make_adapter(Path(tmp))
            values["/" + PROJECT + "-worker-agent-1"]["State"]["Running"] = True
            with self.assertRaises(DeploymentFailure):
                adapter.resume_schema_agent()
            self.assertEqual(calls, [])

    def test_switch_timeout_blocks_automatic_retry(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(platform_adapter, "ROOT", root):
                adapter, _, _ = self.make_adapter(root)
                adapter.command = Mock(side_effect=subprocess.TimeoutExpired("compose", 180))
                with self.assertRaises(subprocess.TimeoutExpired):
                    adapter.resume_schema_agent()
                self.assertTrue(adapter.agent_switch_observation_required)
                with self.assertRaises(DeploymentFailure):
                    adapter.resume_schema_agent()
                self.assertEqual(adapter.command.call_count, 1)

    def test_wrong_api_image_never_starts_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter, values, calls = self.make_adapter(Path(tmp))
            values["/" + PROJECT + "-api-1"]["Image"] = OLD_AGENT
            with self.assertRaisesRegex(DeploymentFailure, "API image"):
                adapter.resume_schema_agent()
            self.assertEqual(calls, [])

    def test_configuration_drift_never_replaces_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(platform_adapter, "ROOT", root):
                adapter, _, calls = self.make_adapter(root)
                (root / "compose.yaml").write_text(SOURCE + "# unrelated update\n")
                with self.assertRaisesRegex(DeploymentFailure, "configuration changed"):
                    adapter.resume_schema_agent()
                self.assertEqual(calls, [])

    def test_wrong_replacement_image_keeps_switch_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(platform_adapter, "ROOT", root):
                adapter, _, _ = self.make_adapter(root)
                adapter.command = Mock(return_value="")
                with self.assertRaisesRegex(DeploymentFailure, "identity"):
                    adapter.resume_schema_agent()
                self.assertTrue(adapter.agent_switch_observation_required)
                self.assertEqual(adapter.schema_agent_identity["id"], "old-agent")

    def test_pair_requires_both_images_and_local_availability(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter, _, _ = self.make_adapter(Path(tmp))
            adapter.schema_agent_image = AGENT
            adapter.schema_rollback_agent_image = None
            adapter.command = Mock(return_value=AGENT)
            with self.assertRaisesRegex(DeploymentFailure, "both"):
                adapter.validate_agent_images()
            adapter.command.assert_not_called()
            adapter.schema_rollback_agent_image = OLD_AGENT
            with self.assertRaisesRegex(DeploymentFailure, "unavailable"):
                adapter.validate_agent_images()
            adapter.command = lambda args: args[-1]
            adapter.validate_agent_images()

    def test_health_rejects_mixed_pair_and_unobserved_switch(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter, values, _ = self.make_adapter(root)
            rollback = "sha256:" + "d" * 64
            for service in ("worker-standard", "worker-task-discovery"):
                values["/" + PROJECT + "-" + service + "-1"] = {"Image": IMAGE}
            (root / "schema-migration.json").write_text(json.dumps({"image_id": IMAGE,
                "agent_image_id": AGENT, "rollback_image": rollback, "rollback_agent_image_id": OLD_AGENT}))
            with self.assertRaisesRegex(DeploymentFailure, "pair"):
                adapter.verify_recorded_image_pair()
            values["/" + PROJECT + "-worker-agent-1"]["Image"] = AGENT
            adapter.verify_recorded_image_pair()
            (root / "schema-agent-stop.json").write_text(json.dumps({"phase": "switch-requested"}))
            with self.assertRaisesRegex(DeploymentFailure, "explicit schema recovery"):
                adapter.verify_recorded_image_pair()
            (root / "schema-agent-stop.json").write_text(json.dumps({"phase": "resumed"}))
            for service in ("api", "worker-standard", "worker-task-discovery"):
                values["/" + PROJECT + "-" + service + "-1"]["Image"] = rollback
            values["/" + PROJECT + "-worker-agent-1"]["Image"] = OLD_AGENT
            adapter.verify_recorded_image_pair()

    def test_rollback_restores_matching_backend_and_agent_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(platform_adapter, "ROOT", root):
                adapter, _, _ = self.make_adapter(root)
                rollback = "sha256:" + "d" * 64
                adapter.schema_rollback_plan = SchemaRelease.prepare(SOURCE, rollback, "f4", "f4", agent_image_id=OLD_AGENT)
                adapter.schema_rollback_overlay = root / "rollback.json"
                adapter.schema_status = lambda: {"state": "exited", "running": False, "exit_code": 0}
                adapter.quiesce_schema_services = Mock()
                adapter.verify_schema_target = Mock()
                adapter.start_selected_services = Mock()
                adapter.rollback_after_schema_migration()
                self.assertEqual(adapter.expected_schema_image, rollback)
                self.assertEqual(adapter.expected_agent_image, OLD_AGENT)
                restored = yaml.safe_load((root / "compose.yaml").read_text())["services"]
                self.assertEqual(restored["api"]["image"], rollback)
                self.assertEqual(restored["worker-agent"]["image"], OLD_AGENT)
                adapter.start_selected_services.assert_called_once()

    def test_new_process_rejects_unobserved_switch_outside_explicit_recovery(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter, values, _ = self.make_adapter(root)
            adapter.schema_recovery = False
            values["/" + PROJECT + "-worker-agent-1"]["State"].update(Running=True, Status="running")
            (root / "schema-agent-stop.json").write_text(json.dumps({"phase": "switch-requested", "id": "old-id", "target_image": AGENT}))
            with self.assertRaisesRegex(DeploymentFailure, "explicit observed"):
                adapter.capture_schema_agent(values)

    def test_explicit_recovery_observes_same_running_replacement_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter, values, _ = self.make_adapter(Path(tmp))
            adapter.schema_rollback_plan = SchemaRelease.prepare(SOURCE, OLD_AGENT, "f4", "f4", agent_image_id=OLD_AGENT)
            item = values["/" + PROJECT + "-worker-agent-1"]
            item.update(Id="new-agent", Image=AGENT)
            item["State"].update(Running=True, Status="running")
            record = {"id": "old-agent", "target_image": AGENT}
            with patch.object(platform_adapter.time, "sleep"):
                adapter.observe_schema_agent_switch(values, record)
                changed = copy.deepcopy(values)
                changed["/" + PROJECT + "-worker-agent-1"]["RestartCount"] = 1
                adapter.inspect = lambda: changed
                with self.assertRaisesRegex(DeploymentFailure, "stable"):
                    adapter.observe_schema_agent_switch(values, record)

    def test_failed_owned_agent_can_stop_for_rollback_but_drift_cannot(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            adapter, _, _ = self.make_adapter(Path(tmp))
            payload = {"id": "old-agent", "state": {"Running": False, "Status": "exited", "ExitCode": 1},
                "labels": {"com.docker.compose.project": PROJECT, "com.docker.compose.service": "worker-agent"}}
            adapter.command = Mock(side_effect=lambda *args, **kwargs: json.dumps(payload))
            adapter.stop_schema_service_gracefully("worker-agent", allow_failed_stopped=True)
            self.assertTrue(adapter.schema_agent_failed_stopped)
            self.assertTrue(all("inspect" in call.args[0] for call in adapter.command.call_args_list))
            payload["id"] = "unrelated-agent"
            with self.assertRaisesRegex(DeploymentFailure, "identity changed"):
                adapter.stop_schema_service_gracefully("worker-agent", allow_failed_stopped=True)

    def test_confirmed_failed_agent_is_replaced_with_rollback_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(platform_adapter, "ROOT", root):
                adapter, values, calls = self.make_adapter(root)
                values["/" + PROJECT + "-worker-agent-1"]["State"]["ExitCode"] = 1
                adapter.schema_agent_failed_stopped = True
                adapter.resume_schema_agent()
                self.assertEqual(adapter.schema_agent_identity["image"], AGENT)
                self.assertEqual(calls[0][-1], "worker-agent")

    def test_recovery_observation_rechecks_api_and_agent_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter, values, _ = self.make_adapter(Path(tmp))
            adapter.schema_rollback_plan = SchemaRelease.prepare(SOURCE, OLD_AGENT, "f4", "f4", agent_image_id=OLD_AGENT)
            item = values["/" + PROJECT + "-worker-agent-1"]
            item.update(Id="new-agent", Image=AGENT)
            item["State"].update(Running=True, Status="running")
            for service in ("api", "worker-agent"):
                changed = copy.deepcopy(values)
                changed["/" + PROJECT + "-" + service + "-1"]["State"]["Health"] = {"Status": "unhealthy"}
                adapter.inspect = lambda: changed
                with patch.object(platform_adapter.time, "sleep"), self.assertRaisesRegex(DeploymentFailure, "stable"):
                    adapter.observe_schema_agent_switch(values, {"id": "old-agent", "target_image": AGENT})

    def test_new_recovery_process_accepts_only_recorded_failed_paired_agent(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter, values, _ = self.make_adapter(root)
            adapter.schema_recovery = True
            adapter.schema_container_ids = {}
            adapter.protected = {}
            adapter.schema_rollback_plan = SchemaRelease.prepare(SOURCE, OLD_AGENT, "f4", "f4", agent_image_id=OLD_AGENT)
            item = values["/" + PROJECT + "-worker-agent-1"]
            item.update(Id="new-agent", Image=AGENT)
            item["State"].update(Running=False, Status="exited", ExitCode=1)
            state_path = root / "schema-agent-stop.json"
            state_path.write_text(json.dumps({"id": "new-agent", "image": AGENT, "phase": "resumed"}))
            adapter.capture_schema_agent(values)
            self.assertTrue(adapter.schema_agent_failed_stopped)
            self.assertEqual(adapter.schema_agent_identity["id"], "new-agent")
            item["Id"] = "independent-agent"
            with self.assertRaisesRegex(DeploymentFailure, "not owned"):
                adapter.capture_schema_agent(values)

if __name__ == "__main__":
    unittest.main()
