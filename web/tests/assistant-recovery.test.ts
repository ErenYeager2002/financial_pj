import test from 'node:test';
import assert from 'node:assert/strict';
import { watchAssistantTurn } from '../src/features/ai-chat/turn-recovery.ts';

test('return during generation refreshes history until final answer arrives without sending a new turn', async () => {
  let polls = 0;
  const seen: unknown[] = [];
  const calls: string[] = [];
  let finish!: () => void;
  const done = new Promise<void>(resolve => { finish = resolve; });
  const request = (async (url: string, options: RequestInit) => {
    calls.push(url);
    assert.equal(options.method, undefined);
    if (url.includes('/turn?')) return Response.json({ active: ++polls < 2 });
    return Response.json({ messages: polls < 2 ? [{ role: 'user', content: 'test' }] : [{ role: 'assistant', content: '完整回复' }] });
  }) as typeof fetch;
  const dispose = watchAssistantTurn('session', {
    update: (history, active) => { seen.push(history); if (!active) finish(); },
    error: message => assert.fail(message)
  }, request, 1);
  await done; dispose();
  assert.equal(polls, 2);
  assert.deepEqual(seen.at(-1), { messages: [{ role: 'assistant', content: '完整回复' }] });
  assert.equal(calls.length, 4);
});

test('leaving again ignores stale recovery responses and does not cancel the server turn', async () => {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  let updates = 0;
  const request = (async () => { await pending; return Response.json({ active: true, messages: [] }); }) as typeof fetch;
  const dispose = watchAssistantTurn('session', { update: () => { updates++; }, error: () => { updates++; } }, request, 1);
  dispose(); release();
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(updates, 0);
});
