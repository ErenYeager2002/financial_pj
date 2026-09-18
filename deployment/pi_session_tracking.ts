import { mkdirSync, writeFileSync, renameSync } from 'node:fs';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';

// The same upstream event fires for terminal and RPC session changes, including
// empty sessions which Pi has not written to a JSONL history file yet.
export default function sessionTracking(pi: ExtensionAPI) {
  pi.on('session_start', async (_event, ctx) => {
    const platformSession = process.env.PI_PLATFORM_SESSION_ID;
    if (!platformSession || !/^[0-9a-f-]{36}$/i.test(platformSession)) return;
    const directory = join(process.env.HOME ?? '/home/agent', '.pi/agent/sessions/platform', platformSession);
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    const temporary = join(directory, `active-${randomUUID()}.tmp`);
    writeFileSync(temporary, JSON.stringify({
      id: ctx.sessionManager.getSessionId(), file: ctx.sessionManager.getSessionFile() ?? ''
    }), { mode: 0o600 });
    renameSync(temporary, join(directory, 'active.json'));
  });
}
