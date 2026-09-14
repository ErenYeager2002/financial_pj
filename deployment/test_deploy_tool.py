import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from deploy_tool import SYNC, ToolDeployment, ScopeError, tree

class FileSwitchTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("SCOPED_ISOLATED_TEST")!="1": raise RuntimeError("isolated container required")
        self.stage=Path("/app/skills/.scoped-fixture")
        self.target=Path("/app/skills/scoped-fixture")
        self.stage.mkdir(); self.target.mkdir()
    def tearDown(self):
        import shutil
        shutil.rmtree(self.stage); shutil.rmtree(self.target)
    def sync(self):
        return subprocess.run([sys.executable,"-c",SYNC,str(self.stage),str(self.target)],capture_output=True)
    def test_changed_removed_added_files_and_unchanged_dependency(self):
        (self.target/"unchanged.py").write_text("value=1")
        (self.target/"changed.py").write_text("old=1")
        (self.target/"removed.py").write_text("old=1")
        before=(self.target/"unchanged.py").stat().st_mtime_ns
        (self.stage/"unchanged.py").write_text("value=1")
        (self.stage/"changed.py").write_text("new=1")
        (self.stage/"added.py").write_text("new=2")
        self.assertEqual(self.sync().returncode,0)
        self.assertEqual(tree(self.target),tree(self.stage))
        self.assertEqual(before,(self.target/"unchanged.py").stat().st_mtime_ns)
    def test_symlink_is_rejected_before_any_write(self):
        (self.target/"keep.py").write_text("keep=1")
        (self.stage/"escape").symlink_to("/tmp")
        self.assertNotEqual(self.sync().returncode,0)
        self.assertEqual((self.target/"keep.py").read_text(),"keep=1")

class DiscoveryScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.a=ToolDeployment.__new__(ToolDeployment)
        self.a.skill_id="ar-hexiao-daily";self.a.content=Path(self.temp.name)
        scripts=self.a.content/"vendor/scripts";scripts.mkdir(parents=True)
        (scripts/"fetch_zhiyun.py").write_text("import json\n")
        (scripts/"flow_monthly.py").write_text("value=1\n")
        self.a.old_tree=tree(self.a.content);self.a.new_tree=tree(self.a.content)
    def tearDown(self): self.temp.cleanup()
    def test_business_script_changes_are_allowed(self):
        self.a.validate_discovery_dependencies({"vendor/scripts/flow_monthly.py"})
    def test_discovery_import_changes_are_rejected(self):
        with self.assertRaises(ScopeError): self.a.validate_discovery_dependencies({"vendor/scripts/fetch_zhiyun.py"})
    def test_new_file_cannot_shadow_probe_import(self):
        (self.a.content/"vendor/scripts/json.py").write_text("value=2")
        self.a.new_tree=tree(self.a.content)
        with self.assertRaises(ScopeError): self.a.validate_discovery_dependencies({"vendor/scripts/json.py"})

class ControlConnectionTests(unittest.TestCase):
    def test_lost_connection_clears_guard_before_recovery(self):
        import io
        from unittest.mock import Mock, patch
        a=ToolDeployment.__new__(ToolDeployment)
        a.token="test";a.skill_id="env-doctor";a.generation=2;a.record_dir=None;a.guarded=True
        broken=Mock();broken.stdin=io.StringIO();broken.stdout=io.StringIO("")
        a.control=broken
        a.start_control=Mock()
        selector=Mock();selector.__enter__=Mock(return_value=selector);selector.__exit__=Mock(return_value=False)
        selector.select.return_value=[True]
        with patch("deploy_tool.selectors.DefaultSelector",return_value=selector):
            with self.assertRaises(ScopeError): a.operation("release_guard")
        self.assertFalse(a.guarded)
        broken.kill.assert_called_once()
        a.start_control.assert_called_once()

if __name__=="__main__": unittest.main()
