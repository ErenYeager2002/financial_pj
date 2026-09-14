type Entry = {
  id: string;
  active: boolean;
  stopped: boolean;
  abort?: () => void;
  finishedAt?: number;
  error?: string;
};
const state = globalThis as typeof globalThis & { __assistantTurnsV1?: Map<string, Entry> };
const entries = state.__assistantTurnsV1 ??= new Map<string, Entry>();
const key = (owner: string, session: string) => JSON.stringify([owner, session]);

export function beginTurn(owner: string, session: string): Entry | null {
  for (const [id, entry] of entries) {
    if (!entry.active && Date.now() - (entry.finishedAt ?? 0) > 300_000) entries.delete(id);
  }
  const id = key(owner, session);
  if (entries.get(id)?.active) return null;
  if (entries.size >= 200) {
    const finished = [...entries].find(([, entry]) => !entry.active);
    if (finished) entries.delete(finished[0]);
    else return null;
  }
  const entry: Entry = { id: crypto.randomUUID(), active: true, stopped: false };
  entries.set(id, entry);
  return entry;
}

export function attachTurn(entry: Entry, abort: () => void): void {
  entry.abort = abort;
  if (entry.stopped) abort();
}

export function finishTurn(entry: Entry, error = ''): void {
  entry.active = false;
  entry.abort = undefined;
  entry.finishedAt = Date.now();
  entry.error = error;
}

export function turnStatus(owner: string, session: string) {
  const entry = entries.get(key(owner, session));
  return { active: entry?.active ?? false, stopped: entry?.stopped ?? false, error: entry?.error ?? '' };
}

export function stopTurn(owner: string, session: string): void {
  const entry = entries.get(key(owner, session));
  if (!entry?.active) return;
  entry.stopped = true;
  entry.abort?.();
}
