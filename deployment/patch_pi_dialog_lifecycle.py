"""Pinned Pi 0.85.1 RPC instrumentation: report dialog cleanup, including abort.
No approval semantics change; consumers can discard dialogs already resolved upstream.
Fail the build if the expected upstream implementation changes.
"""
from pathlib import Path
p = Path('/opt/pi/node_modules/@earendil-works/pi-coding-agent/dist/modes/rpc/rpc-mode.js')
s = p.read_text()
old = '                pendingExtensionRequests.delete(id);\n            };'
assert s.count(old) == 1, 'Pi RPC dialog lifecycle changed; review the pinned patch'
s = s.replace(old, '                pendingExtensionRequests.delete(id);\n                output({ type: "platform_extension_ui_closed", id });\n            };')
p.write_text(s)

root = p.parents[2] / 'bundle'
needle = 'pendingExtensionRequests.delete(id)},onAbort='
matches = [f for f in root.rglob('*.js') if needle in f.read_text()]
assert len(matches) == 1, 'Pi bundled RPC lifecycle changed; review patch'
bundle = matches[0]
s = bundle.read_text()
assert s.count(needle) == 1
s = s.replace(needle, 'pendingExtensionRequests.delete(id),output({type:"platform_extension_ui_closed",id})},onAbort=')
bundle.write_text(s)
