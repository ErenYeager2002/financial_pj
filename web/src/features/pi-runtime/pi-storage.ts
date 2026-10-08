/** Browser-only drafts and receipt pointers, scoped to the authenticated owner. */

export type PiStorageKind = 'delivery' | 'attachments' | 'attachment-send' | 'text-draft';

type StoragePort = Pick<Storage, 'length' | 'key' | 'getItem' | 'setItem' | 'removeItem'>;

const activeScopeKey = 'pi-v2:active-scope';

function legacyKey(kind: PiStorageKind, sessionId: string): string {
  return `pi-${kind}:${sessionId}`;
}

export function piStorageKey(kind: PiStorageKind, scope: string, sessionId: string): string {
  return `pi-v2:${kind}:${scope}:${sessionId}`;
}

export function ensurePiStorageScope(scope: string, storage: StoragePort = sessionStorage): void {
  const previous = storage.getItem(activeScopeKey);
  if (previous && previous !== scope) {
    const keys: string[] = [];
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (key && (key.startsWith('pi-v2:') || key.startsWith('pi-delivery:') ||
        key.startsWith('pi-attachments:') || key.startsWith('pi-attachment-send:'))) keys.push(key);
    }
    for (const key of keys) storage.removeItem(key);
  }
  storage.setItem(activeScopeKey, scope);
}

export function readPiStorage(kind: PiStorageKind, scope: string, sessionId: string,
                              storage: StoragePort = sessionStorage): string | null {
  ensurePiStorageScope(scope, storage);
  const key = piStorageKey(kind, scope, sessionId);
  const scoped = storage.getItem(key);
  if (scoped !== null) return scoped;
  if (kind === 'text-draft') return null;
  const legacy = storage.getItem(legacyKey(kind, sessionId));
  if (legacy !== null) {
    storage.setItem(key, legacy);
    storage.removeItem(legacyKey(kind, sessionId));
  }
  return legacy;
}

/** An asynchronous callback must not reactivate an account that has been left. */
export function writePiStorage(kind: PiStorageKind, scope: string, sessionId: string, value: string,
                               storage: StoragePort = sessionStorage): boolean {
  if (storage.getItem(activeScopeKey) !== scope) return false;
  storage.setItem(piStorageKey(kind, scope, sessionId), value);
  return true;
}

export function removePiStorage(kind: PiStorageKind, scope: string, sessionId: string,
                                storage: StoragePort = sessionStorage): boolean {
  if (storage.getItem(activeScopeKey) !== scope) return false;
  storage.removeItem(piStorageKey(kind, scope, sessionId));
  return true;
}
