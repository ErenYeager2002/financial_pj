import unittest
from scoped_tool_flow import publish, ScopeError

class Fake:
    def __init__(self, state="enabled", fail=None):
        self.state=state; self.fail=fail; self.events=[]; self.counts=iter([2,0]); self.other="enabled"
    def preflight(self): self.events.append("preflight")
    def prepare(self): self.events.append("prepare")
    def pause(self):
        if self.state != "enabled": raise ScopeError("already paused")
        self.state="draining"; self.events.append("pause")
    def wait_idle(self):
        for count in self.counts:
            self.events.append(("active",count))
            if not count: break
        if self.fail=="drain": raise ScopeError("timeout")
        self.state="disabled"
    def cutover(self):
        self.events.append("cutover")
        if self.fail=="cutover": raise ScopeError("switch failed")
    def verify(self):
        self.events.append("verify")
        if self.fail=="verify": raise ScopeError("hash mismatch")
    def persist(self): self.events.append("persist")
    def restore(self):
        self.events.append("restore")
        if self.fail=="restore": raise ScopeError("restore failed")
    def resume(self): self.state="enabled"; self.events.append("resume")
    def record(self,status): self.events.append(status)

class ScopedFlowTests(unittest.TestCase):
    def test_only_target_paused_and_existing_work_drained(self):
        a=Fake(); publish(a)
        self.assertEqual(a.state,"enabled"); self.assertEqual(a.other,"enabled")
        self.assertLess(a.events.index("prepare"),a.events.index("pause"))
        self.assertLess(a.events.index(("active",0)),a.events.index("cutover"))
        self.assertLess(a.events.index("verify"),a.events.index("resume"))
    def test_verify_failure_restores_before_reopening(self):
        a=Fake(fail="verify")
        with self.assertRaises(ScopeError): publish(a)
        self.assertLess(a.events.index("restore"),a.events.index("resume"))
    def test_drain_timeout_never_switches(self):
        a=Fake(fail="drain")
        with self.assertRaises(ScopeError): publish(a)
        self.assertNotIn("cutover",a.events); self.assertEqual(a.state,"enabled")
    def test_preexisting_disabled_tool_is_not_enabled(self):
        a=Fake(state="disabled")
        with self.assertRaises(ScopeError): publish(a)
        self.assertEqual(a.state,"disabled"); self.assertNotIn("resume",a.events)
    def test_partial_cutover_is_rolled_back(self):
        a=Fake(fail="cutover")
        with self.assertRaises(ScopeError): publish(a)
        self.assertIn("restore",a.events)

    def test_pause_commit_then_log_failure_still_restores(self):
        class CommittedPause(Fake):
            def pause(self):
                super().pause(); self.pause_owned=True
                raise ScopeError("journal write failed")
        a=CommittedPause()
        with self.assertRaises(ScopeError): publish(a)
        self.assertEqual(a.state,"enabled")
        self.assertNotIn("cutover",a.events)

    def test_restore_failure_keeps_tool_disabled(self):
        class BrokenRestore(Fake):
            def verify(self): raise ScopeError("verify failed")
            def restore(self): raise ScopeError("restore failed")
        a=BrokenRestore()
        with self.assertRaises(ScopeError): publish(a)
        self.assertEqual(a.state,"disabled")
        self.assertIn("needs_recovery",a.events)
        self.assertNotIn("resume",a.events)

    def test_persistence_failure_restores_before_resume(self):
        class BrokenPersist(Fake):
            def persist(self): raise ScopeError("concurrent config change")
        a=BrokenPersist()
        with self.assertRaises(ScopeError): publish(a)
        self.assertLess(a.events.index("restore"),a.events.index("resume"))

    def test_success_log_failure_does_not_undo_known_running_version(self):
        class BrokenSuccessLog(Fake):
            def record(self,status):
                if status=="succeeded": raise OSError("disk error")
                super().record(status)
        a=BrokenSuccessLog()
        with self.assertRaisesRegex(ScopeError,"已更新并恢复使用"): publish(a)
        self.assertEqual(a.state,"enabled")
        self.assertNotIn("restore",a.events)
        self.assertNotIn("pause_unconfirmed",a.events)

if __name__=="__main__": unittest.main()
