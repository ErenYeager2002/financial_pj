import assert from 'node:assert/strict';
import test from 'node:test';
import { ensurePiStorageScope, piStorageKey, readPiStorage, writePiStorage, removePiStorage } from '../src/features/pi-runtime/pi-storage.ts';

function storage() {
  const items = new Map<string, string>();
  return {
    get length() { return items.size; },
    key(index: number) { return [...items.keys()][index] ?? null; },
    getItem(key: string) { return items.get(key) ?? null; },
    setItem(key: string, value: string) { items.set(key, value); },
    removeItem(key: string) { items.delete(key); }
  };
}

test('migrates an authorized session pending receipt without changing its ID', () => {
  const cache = storage();
  cache.setItem('pi-delivery:session-a', 'request-a');
  assert.equal(readPiStorage('delivery', 'owner-a:team', 'session-a', cache), 'request-a');
  assert.equal(cache.getItem(piStorageKey('delivery', 'owner-a:team', 'session-a')), 'request-a');
  assert.equal(cache.getItem('pi-delivery:session-a'), null);
});

test('clears previous account drafts and receipts on account change', () => {
  const cache = storage();
  ensurePiStorageScope('owner-a:team', cache);
  cache.setItem(piStorageKey('delivery', 'owner-a:team', 'session-a'), 'request-a');
  cache.setItem(piStorageKey('attachments', 'owner-a:team', 'session-a'), 'private-draft');
  cache.setItem('pi-delivery:old-session', 'legacy-request');
  cache.setItem('unrelated', 'preserve');
  ensurePiStorageScope('owner-b:team', cache);
  assert.equal(cache.getItem(piStorageKey('delivery', 'owner-a:team', 'session-a')), null);
  assert.equal(cache.getItem(piStorageKey('attachments', 'owner-a:team', 'session-a')), null);
  assert.equal(cache.getItem('pi-delivery:old-session'), null);
  assert.equal(cache.getItem('unrelated'), 'preserve');
});

test('keeps same-account state while switching sessions', () => {
  const cache = storage();
  cache.setItem(piStorageKey('delivery', 'owner-a:team', 'session-a'), 'request-a');
  ensurePiStorageScope('owner-a:team', cache);
  ensurePiStorageScope('owner-a:team', cache);
  assert.equal(readPiStorage('delivery', 'owner-a:team', 'session-a', cache), 'request-a');
  assert.equal(readPiStorage('delivery', 'owner-a:team', 'session-b', cache), null);
});


test('late writes cannot restore previous-account drafts or receipt pointers', () => {
 const cache=storage();ensurePiStorageScope('owner-a:team',cache);ensurePiStorageScope('owner-b:team',cache);
 assert.equal(writePiStorage('delivery','owner-b:team','session-b','request-b',cache),true);
 for(const kind of ['delivery','attachments','attachment-send','text-draft'] as const){
  assert.equal(writePiStorage(kind,'owner-a:team','session-a','stale-private-value',cache),false);
  assert.equal(cache.getItem(piStorageKey(kind,'owner-a:team','session-a')),null);
 }
 assert.equal(cache.getItem('pi-v2:active-scope'),'owner-b:team');
 assert.equal(readPiStorage('delivery','owner-b:team','session-b',cache),'request-b');
});
test('late cleanup cannot reactivate the previous scope', () => {
 const cache=storage();ensurePiStorageScope('owner-b:team',cache);
 writePiStorage('delivery','owner-b:team','session-b','request-b',cache);
 assert.equal(removePiStorage('delivery','owner-a:team','session-a',cache),false);
 assert.equal(cache.getItem('pi-v2:active-scope'),'owner-b:team');
 assert.equal(readPiStorage('delivery','owner-b:team','session-b',cache),'request-b');
});
test('same-account callbacks can write and remove their own session state', () => {
 const cache=storage();ensurePiStorageScope('owner-a:team',cache);
 assert.equal(writePiStorage('delivery','owner-a:team','session-a','request-a',cache),true);
 assert.equal(writePiStorage('delivery','owner-a:team','session-b','request-b',cache),true);
 assert.equal(removePiStorage('delivery','owner-a:team','session-a',cache),true);
 assert.equal(readPiStorage('delivery','owner-a:team','session-a',cache),null);
 assert.equal(readPiStorage('delivery','owner-a:team','session-b',cache),'request-b');
});
test('absent ownership or storage failure cannot silently persist a receipt', () => {
 const cache=storage();
 assert.equal(writePiStorage('delivery','owner-a:team','session-a','request-a',cache),false);
 ensurePiStorageScope('owner-a:team',cache);
 cache.setItem=()=>{throw new Error('quota unavailable')};
 assert.throws(()=>writePiStorage('delivery','owner-a:team','session-a','request-a',cache),/quota unavailable/);
});


test('text drafts survive same-owner reload and remain isolated between sessions',()=>{
 const cache=storage();ensurePiStorageScope('owner-a:team',cache);
 writePiStorage('text-draft','owner-a:team','session-a','unsent text',cache);
 assert.equal(readPiStorage('text-draft','owner-a:team','session-a',cache),'unsent text');
 assert.equal(readPiStorage('text-draft','owner-a:team','session-b',cache),null);
 ensurePiStorageScope('owner-b:team',cache);
 assert.equal(cache.getItem(piStorageKey('text-draft','owner-a:team','session-a')),null);
});
test('dispatch removes only the submitted draft, retaining receipt uncertainty separately',()=>{
 const cache=storage();ensurePiStorageScope('owner-a:team',cache);
 writePiStorage('text-draft','owner-a:team','session-a','to send',cache);
 writePiStorage('delivery','owner-a:team','session-a','request-id',cache);
 assert.equal(removePiStorage('text-draft','owner-a:team','session-a',cache),true);
 assert.equal(readPiStorage('text-draft','owner-a:team','session-a',cache),null);
 assert.equal(readPiStorage('delivery','owner-a:team','session-a',cache),'request-id');
});
test('unscoped historical text is never imported as a current-user draft',()=>{
 const cache=storage();cache.setItem('pi-text-draft:session-a','unscoped');
 assert.equal(readPiStorage('text-draft','owner-a:team','session-a',cache),null);
});
