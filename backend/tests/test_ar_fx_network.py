"""AR classification declared network is isolated from platform credentials."""
import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from app import ar_process_evidence as E
from app.registry import RuntimeSpec

class ArFxNetworkTests(unittest.TestCase):
    def test_classification_uses_only_declared_network(self):
        runtime=RuntimeSpec(network_access=True,network_targets=["https://www.boc.cn"])
        with patch.object(E,"load_workflow_manifest",return_value=SimpleNamespace(runtime=runtime)), patch.dict(os.environ,{
            "FINANCIAL_NETWORK_PROXY_URL":"http://egress-proxy:3128","FINANCIAL_ENV":"production","DATABASE_URL":"private-database"}):
            env=E.script_environment("classify_hexiao.py",[],SimpleNamespace())
            self.assertEqual(env["HTTPS_PROXY"],"http://egress-proxy:3128")
            self.assertEqual(env["FINANCIAL_NETWORK_TARGETS"],"https://www.boc.cn:443")
            self.assertNotIn("DATABASE_URL",env)
            cached=E.script_environment("run_read_cached.py",["--script","classify_hexiao.py","--"],SimpleNamespace())
            self.assertEqual(cached,env)
    def test_other_scripts_and_old_skill_do_not_gain_network(self):
        runtime=RuntimeSpec(network_access=True,network_targets=["http://192.168.10.167:18880"])
        with patch.object(E,"load_workflow_manifest",return_value=SimpleNamespace(runtime=runtime)), patch.dict(os.environ,{"FINANCIAL_NETWORK_POLICY_MODE":"internal"}):
            self.assertNotIn("HTTPS_PROXY",E.script_environment("classify_hexiao.py",[],SimpleNamespace()))
            self.assertNotIn("HTTPS_PROXY",E.script_environment("validate_plan.py",[],SimpleNamespace()))
            self.assertNotIn("HTTPS_PROXY",E.script_environment("run_read_cached.py",["--script","validate_plan.py"],SimpleNamespace()))

if __name__=="__main__":unittest.main()
