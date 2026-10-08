import assert from 'node:assert/strict';
import test from 'node:test';

import { reducePiPoll } from '../src/features/pi-runtime/pi-event-reducer.ts';
import type { PiPoll } from '../src/features/pi-runtime/pi-protocol.ts';

function poll(sequences: number[], next: number, extra: Partial<PiPoll> = {}): PiPoll {
  return {
    running: true,
    instance_id: 'instance-a',
    generation: 1,
    events: sequences.map(sequence => ({ sequence, generation: 1, kind: 'rpc', event: {} })),
    next,
    ...extra
  };
}

test('accepts contiguous events once and keeps the cursor on a replay', () => {
  const first = reducePiPoll({ cursor: 0, instance: '', generation: undefined }, poll([1, 2], 2));
  assert.deepEqual(first.events.map(event => event.sequence), [1, 2]);
  const replay = reducePiPoll(first.cursor, poll([1, 2], 2));
  assert.deepEqual(replay.events, []);
  assert.equal(replay.cursor.cursor, 2);
});

test('does not apply partial history after a ring-buffer gap', () => {
  const result = reducePiPoll({ cursor: 2, instance: 'instance-a', generation: 1 },
    poll([6, 7], 7, { gap: true }));
  assert.equal(result.gap, true);
  assert.deepEqual(result.events, []);
  assert.equal(result.cursor.cursor, 7);
});

test('resets stale cursors when the instance or generation changes', () => {
  const previous = { cursor: 2, instance: 'instance-a', generation: 1 };
  assert.equal(reducePiPoll(previous, poll([1], 1, { instance_id: 'instance-b' })).reset, true);
  assert.equal(reducePiPoll(previous, poll([1], 1, { generation: 2 })).cursor.cursor, 0);
});

test('marks unreported discontinuity and duplicate sequence as a gap', () => {
  const previous = { cursor: 2, instance: 'instance-a', generation: 1 };
  for (const value of [poll([4], 4), poll([3, 3], 3), poll([], 3)]) {
    const result = reducePiPoll(previous, value);
    assert.equal(result.gap, true);
    assert.deepEqual(result.events, []);
  }
});
