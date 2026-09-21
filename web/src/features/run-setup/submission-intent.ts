import { sha256 } from '@noble/hashes/sha256';

type IntentStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
type Intent = { fingerprint: string; key: string };
const prefix = 'financial-submission-intent:v1:';
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function ordered(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(ordered);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).sort(([a],[b]) => a < b ? -1 : a > b ? 1 : 0)
      .map(([key,item]) => [key,ordered(item)]));
  }
  return value;
}

export function submissionFingerprint(input: unknown): string {
  // Match JSON wire semantics; this digest detects edits, not authorization.
  const text = JSON.stringify(ordered(JSON.parse(JSON.stringify(input))));
  return Array.from(sha256(new TextEncoder().encode(text)), byte => byte.toString(16).padStart(2,'0')).join('');
}

function storage(): IntentStorage {
  try { return window.sessionStorage; } catch { throw new Error('浏览器无法保存提交标识，请允许网站存储后再提交。'); }
}

function read(saved: string | null): Intent | null {
  if (saved === null) return null;
  try {
    const value = JSON.parse(saved) as Partial<Intent>;
    if (typeof value.fingerprint === 'string' && /^[0-9a-f]{64}$/.test(value.fingerprint) &&
        typeof value.key === 'string' && uuid.test(value.key)) return {fingerprint:value.fingerprint,key:value.key};
  } catch { /* Do not silently replace an unreadable possibly-submitted intent. */ }
  throw new Error('提交记录无法读取，请先到任务中心核对本次任务。');
}

export function submissionKey(scope: string, input: unknown, newKey: () => string, store: IntentStorage = storage()): string {
  const fingerprint = submissionFingerprint(input);
  const previous = read(store.getItem(prefix + scope));
  if (previous?.fingerprint === fingerprint) return previous.key;
  const key = newKey();
  if (!uuid.test(key)) throw new Error('提交标识生成失败。');
  // Persist before the request. No parameter text, file names or credentials.
  store.setItem(prefix + scope, JSON.stringify({fingerprint,key}));
  return key;
}

export function completeSubmission(scope: string, key: string, store?: IntentStorage): void {
  try {
    const target = store ?? storage();
    const current = read(target.getItem(prefix + scope));
    if (current?.key === key) target.removeItem(prefix + scope);
  } catch { /* A confirmed successful task must not be reported as failed due to cleanup. */ }
}
