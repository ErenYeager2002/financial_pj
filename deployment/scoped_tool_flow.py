"""Single-tool release sequence; deliberately has no global maintenance operation."""
class ScopeError(RuntimeError):
    pass


def publish(adapter):
    adapter.preflight()
    adapter.prepare()
    paused = False
    switching = False
    try:
        adapter.pause()
        paused = True
        adapter.wait_idle()
        switching = True
        adapter.cutover()
        adapter.verify()
        adapter.persist()
        adapter.resume()
        paused = False
    except BaseException:
        if paused or getattr(adapter, "pause_owned", False):
            try:
                if switching:
                    adapter.restore()
                adapter.resume()
            except BaseException:
                adapter.record("needs_recovery")
                raise ScopeError("恢复或状态核验失败，请按发布记录核实工具状态；全站维护状态未修改。") from None
        if getattr(adapter, "pause_requested", False) and not paused and not getattr(adapter, "pause_owned", False):
            adapter.record("pause_unconfirmed")
        else:
            adapter.record("failed_restored")
        raise
    # At this point the tool is verified, persisted and enabled. A journal error
    # must not relabel that known state as an unconfirmed pause or roll it back.
    try:
        adapter.record("succeeded")
    except Exception:
        raise ScopeError("工具已更新并恢复使用，但成功记录未保存；修复记录后才能再次发布。") from None
